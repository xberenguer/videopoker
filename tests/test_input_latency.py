"""Real-clock GPIO sampling while the UI thread is blocked by render/SPI work.

The GPIO and LCD boundary is simulated; these checks establish concurrency and
event accounting rather than physical switch bounce or measured Pi latency.
"""
from pathlib import Path
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'payload/opt/dino'))
import launcher

OBSERVATIONS = []


def wait_until(predicate, timeout=1.0):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= end:
            raise AssertionError('Timed out waiting for input sample')
        time.sleep(.001)


class MaskHardware:
    def __init__(self):
        self.mask = 0
        self.lock = threading.Lock()
        self.read_threads = set()
        self.closed = False
        self.reads_after_close = 0

    def set(self, mask):
        with self.lock:
            self.mask = mask

    def read_mask(self):
        with self.lock:
            self.read_threads.add(threading.get_ident())
            self.reads_after_close += int(self.closed)
            value = self.mask
        if isinstance(value, BaseException):
            raise value
        return value


def armed(service):
    with service._lock:
        return service.router.buttons.armed


def pulse(hardware, mask, seconds):
    start = time.monotonic()
    hardware.set(mask)
    time.sleep(seconds)
    hardware.set(0)
    return {'mask': mask, 'started': start, 'ended': time.monotonic(),
            'requested_ms': seconds * 1000,
            'actual_ms': (time.monotonic() - start) * 1000}


class EndRun(BaseException):
    pass


class RuntimeTimeout(BaseException):
    pass


class SampledInputTests(unittest.TestCase):
    def test_up_tap_times_survive_coalescing_and_delayed_dispatch(self):
        # A long pair wholly inside a blocked present must remain two singles;
        # a genuine double across that present must remain a double. Gesture
        # timing uses captured GPIO edges, not when the UI finally drains them.
        for scenario, block_seconds, expected_double in (
                ('separate-taps-coalesced', .520, False),
                ('genuine-double-delayed', .450, True)):
            with self.subTest(scenario=scenario):
                hardware = MaskHardware()
                first_present, blocked = threading.Event(), threading.Event()
                services, samples, presses, blocks, producer_errors = [], [], [], [], []
                began = time.monotonic()

                class UI:
                    def __init__(self):
                        self.frames = 0
                        self.double = False
                    def handle(self, action):
                        # Models the old dispatch-time fallback, so this test
                        # fails if production stops forwarding sampled times.
                        self.handle_sampled(action, time.monotonic())
                    def handle_sampled(self, action, at):
                        samples.append((action, at, time.monotonic()))
                        if len(samples) == 2:
                            self.double = 0 <= at-samples[0][1] <= .350
                            raise EndRun()
                    def update(self, now):
                        if now-began > 3:
                            raise RuntimeTimeout('Timestamped UP taps were lost')
                        return (scenario == 'separate-taps-coalesced' and
                                self.frames == 1 and now-began > .120)
                    def render(self):
                        self.frames += 1
                        return self.frames
                ui = UI()
                class RuntimeHardware:
                    def __enter__(self):
                        return hardware
                    def __exit__(self, *args):
                        if services[0].running:
                            raise AssertionError('Input survived timestamp-test cleanup')
                        hardware.closed = True
                def present(frame):
                    first_present.set()
                    if frame == 2:
                        blocks.append(time.monotonic())
                        blocked.set()
                        time.sleep(block_seconds)
                        blocks.append(time.monotonic())
                hardware.present = present
                hardware.show_message = lambda *args: producer_errors.append(('unexpected-recovery', args))
                def factory(hw, *, clock):
                    service = launcher.SampledInput(hw, clock=clock)
                    services.append(service)
                    return service
                def producer():
                    try:
                        if not first_present.wait(1):
                            raise AssertionError('First timestamp-test frame missing')
                        wait_until(lambda: services and armed(services[0]))
                        if scenario == 'separate-taps-coalesced':
                            if not blocked.wait(1):
                                raise AssertionError('Timestamp test never blocked')
                            time.sleep(.020)
                            presses.append(pulse(hardware, 1, .035))
                            time.sleep(.375)
                            presses.append(pulse(hardware, 1, .035))
                        else:
                            presses.append(pulse(hardware, 1, .035))
                            if not blocked.wait(1):
                                raise AssertionError('First UP did not trigger blocked present')
                            time.sleep(.080)
                            presses.append(pulse(hardware, 1, .035))
                    except BaseException as error:
                        producer_errors.append(repr(error))
                actor = threading.Thread(target=producer)
                actor.start()
                try:
                    with self.assertRaises(EndRun):
                        launcher.main(hardware_factory=RuntimeHardware, ui_factory=lambda: ui,
                                      input_factory=factory,
                                      signer_runner=lambda argv: producer_errors.append('unexpected-signer'))
                finally:
                    actor.join(2)
                self.assertEqual(producer_errors, [])
                self.assertFalse(actor.is_alive())
                self.assertEqual([action for action, _, _ in samples], ['UP', 'UP'])
                self.assertEqual(ui.double, expected_double)
                for (_, at, _), press in zip(samples, presses):
                    self.assertGreaterEqual(at, press['started'])
                    self.assertLessEqual(at, press['ended'])
                captured_gap = samples[1][1]-samples[0][1]
                dispatch_gap = samples[1][2]-samples[0][2]
                if expected_double:
                    self.assertLessEqual(captured_gap, .350)
                    self.assertGreater(dispatch_gap, .350)
                else:
                    self.assertGreater(captured_gap, .350)
                    self.assertLess(dispatch_gap, .100)
                    self.assertTrue(all(blocks[0] <= at <= blocks[1] for _, at, _ in samples))
                self.assertEqual(services[0].stats['gap_resets'], 0)
                self.assertFalse(services[0].running)
                self.assertEqual(hardware.reads_after_close, 0)
                OBSERVATIONS.append({'scenario': scenario, 'status': 'PASS',
                                     'captured_up_gap_ms': captured_gap*1000,
                                     'dispatch_up_gap_ms': dispatch_gap*1000,
                                     'double_tap': ui.double, 'stats': services[0].stats})

    def test_quick_taps_survive_blocked_render_and_spi_in_the_real_runtime(self):
        # Both presses begin and end while the *same production UI thread* is
        # blocked. A synchronous poller cannot observe either physical pulse.
        for stage, blocking_seconds, buttons in (
                ('render', .150, ((1 << 3, .035),)),
                ('present', .250, ((1 << 3, .035), (1 << 1, .050)))):
            with self.subTest(stage=stage):
                hardware = MaskHardware()
                blocked = threading.Event()
                events, services, presses, block_times = [], [], [], []
                ui_thread = threading.get_ident()
                began = time.monotonic()

                def block():
                    block_times.append(time.monotonic())
                    blocked.set()
                    time.sleep(blocking_seconds)
                    block_times.append(time.monotonic())

                class UI:
                    def __init__(self):
                        self.actions, self.frames = [], 0
                    def handle(self, action):
                        if threading.get_ident() != ui_thread:
                            raise AssertionError('Sampler touched game state')
                        self.actions.append(action)
                        if len(self.actions) == len(buttons):
                            raise EndRun()
                    def update(self, now):
                        if time.monotonic() - began > 3:
                            raise RuntimeTimeout('Quick taps were lost')
                        return self.frames == 1 and time.monotonic() - began > .12
                    def render(self):
                        self.frames += 1
                        if self.frames == 2 and stage == 'render':
                            block()
                        return self.frames

                ui = UI()
                class RuntimeHardware:
                    def __enter__(self):
                        events.append('hardware-open')
                        return hardware
                    def __exit__(self, *args):
                        events.append('hardware-close')
                        if services[0].running:
                            raise AssertionError('GPIO cleaned up before sampler joined')
                        hardware.closed = True
                def present(frame):
                    if frame == 2 and stage == 'present':
                        block()
                hardware.present = present
                hardware.show_message = lambda *args: events.append('unexpected-recovery')
                def factory(hw, *, clock):
                    service = launcher.SampledInput(hw, clock=clock)
                    services.append(service)
                    return service
                def producer():
                    if not blocked.wait(2):
                        return
                    time.sleep(.020)
                    for mask, seconds in buttons:
                        presses.append(pulse(hardware, mask, seconds))
                        time.sleep(.030)
                actor = threading.Thread(target=producer)
                actor.start()
                try:
                    with self.assertRaises(EndRun):
                        launcher.main(hardware_factory=RuntimeHardware,
                                      ui_factory=lambda: ui, input_factory=factory,
                                      signer_runner=lambda argv: events.append('unexpected-signer'))
                finally:
                    actor.join(2)
                expected = ['RIGHT'] + (['DOWN'] if len(buttons) == 2 else [])
                self.assertEqual(ui.actions, expected)
                self.assertEqual(events, ['hardware-open', 'hardware-close'])
                self.assertFalse(actor.is_alive())
                self.assertFalse(services[0].running)
                self.assertEqual(hardware.reads_after_close, 0)
                self.assertNotIn(ui_thread, hardware.read_threads)
                self.assertEqual(len(presses), len(buttons))
                for press in presses:
                    self.assertGreaterEqual(press['started'], block_times[0])
                    self.assertLess(press['ended'], block_times[1])
                OBSERVATIONS.append({
                    'scenario': 'quick-taps-during-blocked-' + stage,
                    'status': 'PASS', 'requested_block_ms': blocking_seconds * 1000,
                    'actual_block_ms': (block_times[1] - block_times[0]) * 1000,
                    'presses': presses, 'actions': ui.actions,
                    'all_presses_wholly_inside_block': True,
                    'game_state_only_on_ui_thread': True,
                    'sampler_stopped_before_gpio_cleanup': True,
                    'stats': services[0].stats,
                })

    def test_held_deal_does_not_repeat_and_queue_preserves_action_order(self):
        hardware = MaskHardware()
        with launcher.SampledInput(hardware) as service:
            wait_until(lambda: armed(service))
            press = pulse(hardware, 1 << 1, .180)
            time.sleep(.025)
            pulse(hardware, 1 << 2, .040)
            time.sleep(.025)
            pulse(hardware, 1 << 3, .040)
            time.sleep(.025)
            self.assertEqual(service.read(), (False, ('DOWN', 'LEFT', 'RIGHT')))
            self.assertEqual(service.read(), (False, ()))
            OBSERVATIONS.append({'scenario': 'held-deal-and-ordered-input', 'status': 'PASS',
                                 'held_deal_actual_ms': press['actual_ms'],
                                 'actions': ['DOWN', 'LEFT', 'RIGHT'], 'deal_count': 1,
                                 'stats': service.stats})

    def test_short_reserved_chord_is_visible_before_latching_without_action_leaks(self):
        hardware = MaskHardware()
        with launcher.SampledInput(hardware) as service:
            wait_until(lambda: armed(service))
            self.assertFalse(service.gesture_pending)
            hardware.set(launcher.SIGNER_CHORD)
            wait_until(lambda: service.gesture_pending)
            with service._lock:
                self.assertIsNotNone(service.router.gate.hold_started)
                self.assertFalse(service.router.gate.latched)
            self.assertEqual(service.read(), (False, ()))
            hardware.set(0)
            wait_until(lambda: not service.gesture_pending)
            self.assertEqual(service.read(), (False, ()))

    def test_gpio_error_discards_pending_events_and_requires_neutral_release(self):
        hardware = MaskHardware()
        with launcher.SampledInput(hardware) as service:
            wait_until(lambda: armed(service))
            pulse(hardware, launcher.KEY2, .040)
            hardware.set(OSError('simulated GPIO failure'))
            wait_until(lambda: service.stats['read_errors'] > 0)
            hardware.set(launcher.KEY2)
            time.sleep(.060)
            self.assertEqual(service.read(), (False, ()))
            hardware.set(0)
            wait_until(lambda: armed(service))
            pulse(hardware, launcher.KEY2, .040)
            self.assertEqual(service.read(), (False, ('KEY2',)))
            OBSERVATIONS.append({'scenario': 'gpio-error-clears-pending-input', 'status': 'PASS',
                                 'neutral_release_required': True, 'stats': service.stats})

    def test_queue_overflow_clears_all_pending_input_and_rearms_at_neutral(self):
        hardware = MaskHardware()
        with launcher.SampledInput(hardware, max_events=1) as service:
            wait_until(lambda: armed(service))
            pulse(hardware, launcher.KEY2, .040)
            time.sleep(.025)
            hardware.set(1 << 3)
            wait_until(lambda: service.stats['queue_overflows'] == 1)
            self.assertEqual(service.read(), (False, ()))
            hardware.set(0)
            wait_until(lambda: armed(service))
            pulse(hardware, 1 << 4, .040)
            self.assertEqual(service.read(), (False, ('CENTER',)))
            OBSERVATIONS.append({'scenario': 'queue-overflow-fails-closed', 'status': 'PASS',
                                 'stats': service.stats})

    def test_stale_actions_are_discarded_instead_of_replayed(self):
        hardware = MaskHardware()
        with launcher.SampledInput(hardware, max_age_seconds=.040) as service:
            wait_until(lambda: armed(service))
            pulse(hardware, launcher.KEY2, .040)
            time.sleep(.050)
            self.assertEqual(service.read(), (False, ()))
            self.assertEqual(service.stats['stale_resets'], 1)
            self.assertFalse(armed(service))

    def test_stopped_worker_is_reported_instead_of_silently_ignoring_input(self):
        hardware = MaskHardware()
        with launcher.SampledInput(hardware) as service:
            service._stop.set()
            service._thread.join(timeout=1)
            with self.assertRaises(launcher.InputServiceError):
                service.read()

    def test_bounded_shutdown_does_not_release_gpio_while_worker_is_blocked(self):
        hardware = MaskHardware()
        entered, release = threading.Event(), threading.Event()
        original_read = hardware.read_mask
        def blocked_read():
            entered.set()
            release.wait(3)
            return original_read()
        hardware.read_mask = blocked_read
        service = launcher.SampledInput(hardware).__enter__()
        self.assertTrue(entered.wait(1))
        began = time.monotonic()
        try:
            with self.assertRaises(launcher.InputShutdownError):
                service.close()
            self.assertLess(time.monotonic() - began, 1.5)
            self.assertTrue(service.running)
        finally:
            release.set()
            service.close()
        self.assertFalse(service.running)

    def test_real_clock_signer_chord_suppresses_actions_and_joins_before_handoff(self):
        hardware = MaskHardware()
        services, events = [], []
        first_present = threading.Event()
        producer_done, producer_stop = threading.Event(), threading.Event()
        producer_errors, requested_masks, observed_masks = [], [], []
        trace_lock = threading.Lock()
        stimulus = {}
        began = time.monotonic()
        original_read = hardware.read_mask

        def traced_read():
            mask = original_read()
            with trace_lock:
                if not observed_masks or observed_masks[-1]['mask'] != mask:
                    observed_masks.append({'seconds': time.monotonic() - began, 'mask': mask})
            return mask
        hardware.read_mask = traced_read

        def router_state():
            if not services:
                return None
            service = services[0]
            with service._lock:
                gate = service.router.gate
                return {'armed': service.router.buttons.armed,
                        'raw': service.router.buttons.raw,
                        'stable': service.router.buttons.stable,
                        'pending': service.router.pending,
                        'hold_started': gate.hold_started,
                        'release_started': gate.release_started,
                        'latched': gate.latched, 'complete': gate.complete,
                        'entered': service._entered}

        def diagnostics():
            with trace_lock:
                requested, observed = list(requested_masks), list(observed_masks)
            return {'elapsed_seconds': time.monotonic() - began,
                    'first_present': first_present.is_set(),
                    'producer_done': producer_done.is_set(),
                    'producer_errors': list(producer_errors),
                    'sampler_running': services[0].running if services else False,
                    'sampler_stats': services[0].stats if services else None,
                    'router': router_state(), 'stimulus': dict(stimulus),
                    'requested_masks': requested, 'observed_masks': observed,
                    'events': list(events)}

        def wait_for(predicate, label, timeout=2.0):
            deadline = time.monotonic() + timeout
            while not predicate():
                if producer_stop.is_set():
                    raise AssertionError('Input producer cancelled')
                if time.monotonic() >= deadline:
                    raise AssertionError(label + ': ' + repr(diagnostics()))
                time.sleep(.001)

        def set_mask(mask):
            with trace_lock:
                requested_masks.append({'seconds': time.monotonic() - began, 'mask': mask})
            hardware.set(mask)

        class UI:
            def handle(self, action):
                events.append(('unexpected-action', action))
            def update(self, now):
                if producer_errors or time.monotonic() - began > 10:
                    raise RuntimeTimeout('Signer chord did not complete: ' + repr(diagnostics()))
                return False
            def render(self):
                return None
        class Hardware:
            def __enter__(self):
                events.append('hardware-open')
                return hardware
            def __exit__(self, *args):
                if services[0].running:
                    raise AssertionError('Sampler survived GPIO cleanup')
                hardware.closed = True
                events.append('hardware-close')
        hardware.present = lambda frame: first_present.set()
        hardware.show_message = lambda *args: events.append('unexpected-recovery')
        def factory(hw, *, clock):
            service = launcher.SampledInput(hw, clock=clock)
            services.append(service)
            return service
        def producer():
            try:
                # The production gate resets input after importing/building its
                # UI. Start the gesture only after that reset and its neutral
                # rearm, rather than racing startup with a fixed .15s sleep.
                wait_for(first_present.is_set, 'First game frame never appeared')
                wait_for(lambda: services and armed(services[0]), 'Sampler did not arm after first frame')
                stimulus['ready_seconds'] = time.monotonic() - began
                initial_gap_resets = services[0].stats['gap_resets']
                set_mask(launcher.KEY1)
                wait_for(lambda: router_state()['pending'] & launcher.KEY1,
                         'First outer button was not sampled')
                set_mask(launcher.SIGNER_CHORD)
                wait_for(lambda: router_state()['hold_started'] is not None,
                         'Full chord was not sampled')
                observed_start = router_state()['hold_started']
                stimulus['sampled_hold_started_seconds'] = observed_start - began

                def latched_without_reset():
                    state = router_state()
                    if services[0].stats['gap_resets'] != initial_gap_resets:
                        raise AssertionError('Sampling gap reset the live chord: ' + repr(diagnostics()))
                    if state['hold_started'] != observed_start:
                        raise AssertionError('Observed chord was interrupted: ' + repr(diagnostics()))
                    return state['latched']
                wait_for(latched_without_reset, 'Real two-second hold did not latch', timeout=3.0)
                latched = router_state()
                stimulus['observed_hold_seconds'] = time.monotonic() - observed_start
                if stimulus['observed_hold_seconds'] < 2.0 or not latched['entered']:
                    raise AssertionError('Chord must fire at its real two-second hold: ' + repr(diagnostics()))
                if latched['raw'] & launcher.MENU_CHORD != launcher.MENU_CHORD:
                    raise AssertionError('Entry waited for release instead of the held chord')
            except BaseException as error:
                producer_errors.append(type(error).__name__ + ': ' + str(error))
                hardware.set(0)
            finally:
                producer_done.set()
        actor = threading.Thread(target=producer)
        actor.start()
        try:
            launcher.main(hardware_factory=Hardware, ui_factory=UI, input_factory=factory,
                          signer_runner=lambda argv: events.append('signer'))
        finally:
            producer_stop.set()
            actor.join(3)
        self.assertFalse(actor.is_alive(), repr(diagnostics()))
        self.assertEqual(producer_errors, [], repr(diagnostics()))
        self.assertEqual(events, ['hardware-open', 'hardware-close', 'signer'])
        self.assertEqual(hardware.reads_after_close, 0)
        self.assertFalse(services[0].running)
        OBSERVATIONS.append({'scenario': 'production-chord-and-input-thread-handoff',
                             'status': 'PASS', 'ordinary_actions': 0,
                             'opens_while_chord_still_held': True,
                             'first_frame_and_neutral_rearm_before_stimulus': True,
                             'stimulus': stimulus,
                             'observed_mask_transitions': list(observed_masks),
                             'order': events, 'stats': services[0].stats})


if __name__ == '__main__':
    unittest.main()
