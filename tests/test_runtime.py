"""Runtime behavior tests without real GPIO, SPI or importing SeedSigner."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("poker_launcher", ROOT / "payload/opt/dino/launcher.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
sys.path.insert(0, str(ROOT / "payload/opt/dino"))
from input_harness import SynchronousInput


class Clock:
    def __init__(self):
        self.now = 0.0
    def __call__(self):
        return self.now
    def sleep(self, duration):
        self.now += duration
        if self.now > 12:
            raise AssertionError("Runtime did not finish its explicit gesture")


class FakeHardware:
    def __init__(self, clock, trace, events):
        self.clock, self.trace, self.events = clock, trace, events
    def __enter__(self):
        self.events.append("open")
        return self
    def __exit__(self, *args):
        self.events.append("close")
    def read_mask(self):
        result = self.trace(self.clock())
        if isinstance(result, BaseException):
            raise result
        return result
    def present(self, frame):
        self.events.append(("frame", frame))
    def show_message(self, message, detail):
        self.events.append(("message", message, detail))


class FakeUI:
    def __init__(self):
        self.actions = []
    def handle(self, action):
        self.actions.append(action)
    def update(self, now):
        return False
    def render(self):
        return "RGB320x240"


class GateTests(unittest.TestCase):
    def test_full_chord_and_every_key_release_are_required(self):
        gate = launcher.HoldReleaseGate()
        chord = launcher.SIGNER_CHORD
        self.assertFalse(gate.update(0, chord))
        self.assertFalse(gate.update(1.999, chord))
        self.assertFalse(gate.update(2.0, chord))
        self.assertTrue(gate.latched)
        self.assertFalse(gate.update(3.0, launcher.KEY2))
        self.assertFalse(gate.update(3.1, 0))
        self.assertFalse(gate.update(3.179, 0))
        self.assertTrue(gate.update(3.181, 0))

    def test_interrupted_hold_does_not_count_towards_next_hold(self):
        gate = launcher.HoldReleaseGate()
        chord = launcher.SIGNER_CHORD
        for now, mask in ((0, chord), (1.9, launcher.KEY1), (2.0, chord), (3.999, chord)):
            self.assertFalse(gate.update(now, mask))
        self.assertFalse(gate.latched)
        gate.update(4.0, chord)
        self.assertTrue(gate.latched)

    def test_clock_regression_cannot_complete_a_gate(self):
        gate = launcher.HoldReleaseGate()
        gate.update(100, launcher.SIGNER_CHORD)
        gate.update(102, launcher.SIGNER_CHORD)
        self.assertFalse(gate.update(1, 0))
        self.assertFalse(gate.latched)


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.router = launcher.InputRouter()
        self.router.update(0, 0)
        self.router.update(.081, 0)

    def test_held_deal_key_emits_only_one_edge(self):
        actions = []
        for now in (.1, .14, .2, .5, 1.0):
            unlock, events = self.router.update(now, 1 << 1)
            self.assertFalse(unlock)
            actions.extend(events)
        self.assertEqual(actions, ["DOWN"])

    def test_bounce_does_not_emit_a_deal(self):
        actions = []
        for now, mask in ((.1, 1 << 1), (.11, 0), (.12, 1 << 1), (.13, 0), (.2, 0)):
            actions.extend(self.router.update(now, mask)[1])
        self.assertEqual(actions, [])

    def test_outer_key_is_a_release_action(self):
        self.router.update(.1, launcher.KEY1)
        self.assertEqual(self.router.update(.14, launcher.KEY1)[1], ())
        self.router.update(.2, 0)
        self.assertEqual(self.router.update(.24, 0)[1], ("KEY1",))

    def test_short_chord_does_not_hold_a_card_or_open_menu(self):
        actions = []
        for now, mask in ((.1, launcher.KEY1), (.14, launcher.KEY1),
                          (.2, launcher.SIGNER_CHORD), (.24, launcher.SIGNER_CHORD),
                          (.7, 0), (.75, 0), (.9, 0)):
            unlock, events = self.router.update(now, mask)
            self.assertFalse(unlock)
            actions.extend(events)
        self.assertEqual(actions, [])

    def test_long_chord_suppresses_every_ordinary_action(self):
        actions = []
        trace = ((.1, launcher.KEY1), (.14, launcher.KEY1),
                 (.2, launcher.SIGNER_CHORD), (.24, launcher.SIGNER_CHORD),
                 (2.21, launcher.SIGNER_CHORD | launcher.KEY2),
                 (2.3, launcher.KEY2), (2.4, 0), (2.481, 0))
        for now, mask in trace:
            unlock, events = self.router.update(now, mask)
            actions.extend(events)
        self.assertTrue(unlock)
        self.assertEqual(actions, [])

    def test_held_key_at_boot_requires_release_before_any_action(self):
        router = launcher.InputRouter()
        for now in (0, .1, .5):
            self.assertEqual(router.update(now, launcher.KEY2), (False, ()))
        router.update(.6, 0)
        router.update(.69, 0)
        router.update(.8, launcher.KEY2)
        self.assertEqual(router.update(.84, launcher.KEY2)[1], ("KEY2",))

    def test_invalid_masks_are_rejected(self):
        for mask in (-1, 256, True, None, "0"):
            with self.assertRaises(ValueError):
                self.router.update(.1, mask)

    def test_twenty_ms_taps_register_once_for_every_button(self):
        for bit, action in enumerate(launcher.BUTTONS):
            with self.subTest(action=action):
                router = launcher.InputRouter()
                actions = []
                for tick in range(61):
                    now = tick * .005
                    mask = (1 << bit) if 20 <= tick < 24 else 0
                    actions.extend(router.update(now, mask)[1])
                self.assertEqual(actions, [action])

    def test_other_button_bounce_does_not_restart_a_stable_key_timer(self):
        actions = []
        for now, mask in ((.100, launcher.KEY2), (.105, launcher.KEY2 | 1),
                          (.110, launcher.KEY2), (.115, launcher.KEY2 | 1),
                          (.120, 0), (.125, 1), (.130, 0), (.145, 0)):
            actions.extend(self.router.update(now, mask)[1])
        self.assertEqual(actions, ['KEY2'])


class SampledStateTests(unittest.TestCase):
    def run_capture(self, trace):
        """Run the native capture loop with exact times, no scheduler or sleep."""
        clock, levels = Clock(), []
        remaining = list(trace)
        class Hardware:
            def read_mask(self):
                clock.now, value = remaining.pop(0)
                if isinstance(value, BaseException):
                    raise value
                return value
        service = launcher.SampledInput(Hardware(), clock=clock)
        service._stop = SimpleNamespace(is_set=lambda: not remaining,
                                        wait=lambda timeout: levels.append(service.pressed_mask))
        service._thread = SimpleNamespace(is_alive=lambda: True)
        service._sample()
        return service, levels

    def test_native_capture_reports_release_without_losing_queued_up_time(self):
        service, levels = self.run_capture(((0, 0), (.081, 0), (.100, 1),
                                           (.115, 1), (.130, 0), (.145, 0)))
        self.assertEqual(levels, [0, 0, 0, 1, 1, 0])
        self.assertEqual(service.pressed_mask, 0)
        self.assertEqual(service.read_timed(), (False, ((.115, "UP"),)))
        self.assertEqual(service.read(), (False, ()))
        self.assertEqual(service.stats['gap_resets'], 0)

    def test_native_capture_fault_and_startup_hold_expose_neutral_levels(self):
        service, levels = self.run_capture(((0, 1), (.081, 1), (.100, 0),
                                           (.181, 0), (.200, 1), (.215, 1),
                                           (.230, OSError("GPIO read failed"))))
        self.assertEqual(levels, [0, 0, 0, 0, 0, 1, 0])
        self.assertEqual(service.pressed_mask, 0)
        self.assertEqual(service.read_timed(), (False, ()))
        self.assertEqual(service.stats['read_errors'], 1)

    def test_native_event_stream_preserves_press_and_release_times_in_order(self):
        service, levels = self.run_capture(((0,0),(.081,0),(.100,1),
                                           (.115,1),(.130,0),(.145,0)))
        self.assertEqual(service.read_events(), (False, (
            (.115,'levels',1),(.115,'action','UP'),(.145,'levels',0))))
        self.assertEqual(service.read_timed(), (False, ()))

    def test_event_stream_fault_discards_actions_and_emits_explicit_neutral_reset(self):
        service, levels = self.run_capture(((0,0),(.081,0),(.100,1),
                                           (.115,1),(.130,OSError('GPIO'))))
        self.assertEqual(service.read_events(), (False, ((.130,'reset',0),)))
        self.assertEqual(service.read_events(), (False, ()))

    def test_synchronous_harness_uses_the_same_debounced_level_contract(self):
        clock, events = Clock(), []
        mask = [0]
        hardware = FakeHardware(clock, lambda t: mask[0], events)
        service = SynchronousInput(hardware, clock=clock)
        for now, value, expected in ((0, 0, 0), (.081, 0, 0),
                                     (.100, 1, 0), (.115, 1, 1),
                                     (.130, 0, 1), (.145, 0, 0)):
            clock.now, mask[0] = now, value
            service.read_timed()
            self.assertEqual(service.pressed_mask, expected)
        service.reset()
        self.assertEqual(service.pressed_mask, 0)


class RuntimeTests(unittest.TestCase):
    def test_sampled_level_events_reach_ui_in_captured_order_and_reset_pauses_auto(self):
        clock, events, captured = Clock(), [], []
        class EventInput:
            gesture_pending = False
            def __init__(self, hardware, *, clock): self.calls = 0
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def reset(self): pass
            def read_events(self):
                self.calls += 1
                if self.calls==1: return False, ()
                if self.calls==2:
                    return False, ((.002,'levels',1),(.002,'action','UP'),
                                   (.008,'levels',0),(.009,'reset',0))
                return True, ()
            def read_timed(self): raise AssertionError('Release timestamps discarded')
        class EventUI(FakeUI):
            def set_pressed_mask_sampled(self,mask,at): captured.append(('levels',mask,at))
            def handle_sampled(self,action,at): captured.append(('action',action,at))
            def pause_autoplay(self): captured.append(('pause',)); return True
        hardware = FakeHardware(clock,lambda t:0,events)
        launcher.run_poker_gate(lambda:hardware,EventUI,clock,clock.sleep,input_factory=EventInput)
        self.assertEqual(captured,[('levels',1,.002),('action','UP',.002),
                                   ('levels',0,.008),('pause',),('levels',0,.009)])

    def test_current_levels_are_forwarded_before_actions_and_empty_updates(self):
        clock, events = Clock(), []
        class LevelInput:
            running = False
            pressed_mask = 0
            def __init__(self, hardware, *, clock):
                self.calls = 0
            def __enter__(self):
                self.running = True
                return self
            def __exit__(self, *args):
                self.running = False
            def reset(self):
                pass
            def read_timed(self):
                self.calls += 1
                self.pressed_mask = 1 if self.calls == 2 else 0
                return (self.calls == 5, ((.005, "UP"),) if self.calls == 2 else ())
        class LevelUI(FakeUI):
            mask = None
            def set_pressed_mask(self, mask):
                events.append(("mask", mask, clock()))
                changed, self.mask = self.mask != mask, mask
                return changed
            def handle_sampled(self, action, at):
                events.append(("action", action, at, self.mask))
            def update(self, now):
                events.append(("update", now, self.mask))
                return False
            def render(self):
                return self.mask
        hardware = FakeHardware(clock, lambda t: 0, events)
        launcher.run_poker_gate(lambda: hardware, LevelUI, clock, clock.sleep,
                               input_factory=LevelInput)
        self.assertEqual([event[1] for event in events if isinstance(event, tuple) and event[0] == 'mask'],
                         [0, 1, 0, 0])
        self.assertEqual([event[1] for event in events if isinstance(event, tuple) and event[0] == 'frame'],
                         [0, 1, 0])  # Release alone schedules the clearing frame.
        self.assertIn(("action", "UP", .005, 1), events)
        self.assertLess(events.index(("mask", 0, .02)), events.index(("update", .02, 0)))

    def test_already_released_up_is_reported_before_its_queued_press_edge(self):
        clock, events = Clock(), []
        class ReleasedInput:
            running = False
            pressed_mask = 0
            def __init__(self, hardware, *, clock):
                self.calls = 0
            def __enter__(self):
                self.running = True
                return self
            def __exit__(self, *args):
                self.running = False
            def reset(self):
                pass
            def read_timed(self):
                self.calls += 1
                return (self.calls > 2, ((.002, "UP"),) if self.calls == 2 else ())
        class ReleasedUI(FakeUI):
            mask = None
            def set_pressed_mask(self, mask):
                self.mask = mask
                events.append(("mask", mask, clock()))
                return False
            def handle_sampled(self, action, at):
                events.append(("action", action, at, self.mask))
        hardware = FakeHardware(clock, lambda t: 0, events)
        launcher.run_poker_gate(lambda: hardware, ReleasedUI, clock, clock.sleep,
                               input_factory=ReleasedInput)
        action = ("action", "UP", .002, 0)
        self.assertIn(action, events)
        self.assertLess(events.index(("mask", 0, .01)), events.index(action))

    def test_runtime_preserves_captured_times_and_prefers_timed_input_dispatch(self):
        clock, events, captured = Clock(), [], []
        class TimedInput:
            running = False
            gesture_pending = False
            def __init__(self, hardware, *, clock):
                self.calls = 0
            def __enter__(self):
                self.running = True
                return self
            def __exit__(self, *args):
                self.running = False
            def reset(self):
                pass
            def read(self):
                raise AssertionError("Runtime ignored timestamp-capable input")
            def read_timed(self):
                self.calls += 1
                if self.calls == 1:
                    return False, ()
                if self.calls == 2:
                    return False, ((.002, "UP"), (.008, "DOWN"))
                return True, ()
        class TimedUI(FakeUI):
            def handle_sampled(self, action, at):
                captured.append((action, at, clock()))
        hardware = FakeHardware(clock, lambda t: 0, events)
        ui = TimedUI()
        launcher.run_poker_gate(lambda: hardware, lambda: ui, clock, clock.sleep,
                               input_factory=TimedInput)
        self.assertEqual(captured, [("UP", .002, .01), ("DOWN", .008, .01)])
        self.assertEqual(ui.actions, [])

    def test_legacy_input_receives_read_time_when_ui_accepts_sampled_events(self):
        clock, events, captured = Clock(), [], []
        class LegacyInput:
            running = False
            def __init__(self, hardware, *, clock):
                self.calls = 0
            def __enter__(self):
                self.running = True
                return self
            def __exit__(self, *args):
                self.running = False
            def reset(self):
                pass
            def read(self):
                self.calls += 1
                return ((True, ()) if self.calls > 2 else
                        (False, ("DOWN",) if self.calls == 2 else ()))
        class TimedUI(FakeUI):
            def handle_sampled(self, action, at):
                captured.append((action, at))
            def set_pressed_mask(self, mask):
                raise AssertionError("Legacy input has no current pressed state")
        hardware = FakeHardware(clock, lambda t: 0, events)
        launcher.run_poker_gate(lambda: hardware, TimedUI, clock, clock.sleep,
                               input_factory=LegacyInput)
        self.assertEqual(captured, [("DOWN", .01)])

    def test_pending_short_chord_pauses_autoplay_before_another_update(self):
        clock, events = Clock(), []
        class AutoUI(FakeUI):
            def __init__(self):
                super().__init__()
                self.playing, self.pauses = True, []
            def pause_autoplay(self):
                self.pauses.append(clock())
                changed = self.playing
                self.playing = False
                return changed
            def render(self):
                return self.playing
            def update(self, now):
                if .2 <= now < .6:
                    self.assert_paused()
                return False
            def assert_paused(self):
                if self.playing:
                    raise AssertionError("Autoplay updated during the reserved chord")
        ui = AutoUI()
        def trace(t):
            if .2 <= t < .6 or 1 <= t < 3.2:
                return launcher.SIGNER_CHORD
            return 0
        hardware = FakeHardware(clock, trace, events)
        launcher.run_poker_gate(lambda: hardware, lambda: ui, clock, clock.sleep,
                               input_factory=SynchronousInput)
        self.assertTrue(ui.pauses)
        self.assertGreaterEqual(ui.pauses[0], .2)
        self.assertLess(ui.pauses[0], .22)
        self.assertFalse(ui.playing)
        self.assertIn(('frame', True), events)
        self.assertIn(('frame', False), events)
        self.assertEqual(ui.actions, [])
        self.assertFalse(any(isinstance(event, tuple) and event[0] == "message" for event in events))

    def test_handoff_closes_hardware_before_starting_signer(self):
        clock, events, ui = Clock(), [], FakeUI()
        hardware = FakeHardware(clock, lambda t: launcher.SIGNER_CHORD if 1 <= t < 3.2 else 0, events)
        launcher.main(["test"], hardware_factory=lambda: hardware, ui_factory=lambda: ui,
                      clock=clock, sleep=clock.sleep, input_factory=SynchronousInput,
                      signer_runner=lambda argv: events.append(("signer", argv)))
        self.assertEqual(events[0], "open")
        self.assertEqual(events[-2:], ["close", ("signer", ["test"])])
        self.assertEqual(ui.actions, [])
        self.assertFalse(any(name.startswith("seedsigner") for name in sys.modules))

    def test_handoff_joins_input_and_closes_ui_before_hardware_and_signer(self):
        clock, events = Clock(), []
        class ClosingUI(FakeUI):
            def close(self):
                events.append("ui-close")
        class TracedInput(SynchronousInput):
            def __exit__(self, *args):
                super().__exit__(*args)
                events.append("input-stop")
        hardware = FakeHardware(clock, lambda t: launcher.SIGNER_CHORD if 1 <= t < 3.2 else 0, events)
        launcher.main(hardware_factory=lambda: hardware, ui_factory=ClosingUI,
                      clock=clock, sleep=clock.sleep, input_factory=TracedInput,
                      signer_runner=lambda argv: events.append("signer"))
        self.assertEqual(events[-4:], ["input-stop", "ui-close", "close", "signer"])
        self.assertEqual(events.count("ui-close"), 1)

    def test_failed_ui_close_aborts_signer_entry(self):
        clock, events = Clock(), []
        class UnclosedUI(FakeUI):
            def close(self):
                events.append("ui-close-failed")
                raise RuntimeError("advisor still running")
        hardware = FakeHardware(clock, lambda t: launcher.SIGNER_CHORD if 1 <= t < 3.2 else 0, events)
        with self.assertRaises(launcher.UIShutdownError):
            launcher.main(hardware_factory=lambda: hardware, ui_factory=UnclosedUI,
                          clock=clock, sleep=clock.sleep, input_factory=SynchronousInput,
                          signer_runner=lambda argv: events.append("signer"))
        self.assertEqual(events[-2:], ["ui-close-failed", "close"])
        self.assertNotIn("signer", events)

    def test_render_failure_with_failed_ui_close_cannot_recover_into_signer(self):
        clock, events = Clock(), []
        class BrokenUI(FakeUI):
            def render(self):
                raise RuntimeError("render failure")
            def close(self):
                events.append("ui-close-failed")
                raise RuntimeError("advisor still running")
        hardware = FakeHardware(clock, lambda t: 0, events)
        with self.assertRaises(launcher.UIShutdownError):
            launcher.main(hardware_factory=lambda: hardware, ui_factory=BrokenUI,
                          clock=clock, sleep=clock.sleep, input_factory=SynchronousInput,
                          signer_runner=lambda argv: events.append("signer"))
        self.assertEqual(events, ["open", "ui-close-failed", "close"])
        self.assertEqual(clock(), 0)

    def test_game_failure_offers_retry_and_does_not_automatically_open_signer(self):
        clock, events, attempts = Clock(), [], []
        def trace(t):
            if .2 <= t < .5:
                return 1 << 1
            return launcher.SIGNER_CHORD if 1 <= t < 3.2 else 0
        hardware = FakeHardware(clock, trace, events)
        def broken_ui():
            attempts.append(clock())
            raise RuntimeError("game import failed")
        launcher.main(hardware_factory=lambda: hardware, ui_factory=broken_ui,
                      clock=clock, sleep=clock.sleep, input_factory=SynchronousInput,
                      signer_runner=lambda argv: events.append("signer"))
        self.assertEqual(len(attempts), 2)
        self.assertGreaterEqual(clock(), 3.28)
        self.assertEqual(events[-2:], ["close", "signer"])
        self.assertTrue(any(isinstance(event, tuple) and event[0] == "message" for event in events))
        self.assertIn(("message", "Game unavailable", "Down button: retry"), events)

    def test_gpio_failure_interrupts_the_signer_hold(self):
        clock, events, ui = Clock(), [], FakeUI()
        def trace(t):
            if .1 <= t < 2.1 or 3 <= t < 5.2:
                return launcher.SIGNER_CHORD
            if 2.1 <= t < 2.2:
                return OSError("GPIO read failed")
            return 0
        hardware = FakeHardware(clock, trace, events)
        launcher.run_poker_gate(lambda: hardware, lambda: ui, clock, clock.sleep, input_factory=SynchronousInput)
        self.assertGreaterEqual(clock(), 5.28)
        self.assertEqual(events[-1], "close")

    def test_render_failure_remains_in_recovery_until_deliberate_exit(self):
        clock, events = Clock(), []
        class BrokenRender(FakeUI):
            def render(self):
                raise RuntimeError("render failure")
            def close(self):
                events.append("ui-close")
        hardware = FakeHardware(clock, lambda t: launcher.SIGNER_CHORD if 1 <= t < 3.2 else 0, events)
        launcher.run_poker_gate(lambda: hardware, BrokenRender, clock, clock.sleep, input_factory=SynchronousInput)
        self.assertEqual(events[-1], "close")
        self.assertGreaterEqual(clock(), 3.28)
        self.assertEqual(events.count("ui-close"), 1)
        self.assertLess(events.index("ui-close"), events.index("close"))

    def test_dead_input_worker_recovers_with_a_delay_and_never_opens_signer(self):
        clock, events, ui = Clock(), [], FakeUI()
        hardware = FakeHardware(clock, lambda t: launcher.SIGNER_CHORD if 1.2 <= t < 3.4 else 0, events)
        attempts = []
        class DeadInput:
            running = False
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                raise launcher.InputServiceError('worker unavailable')
        def factory(hw, *, clock):
            attempts.append(clock())
            return DeadInput() if len(attempts) == 1 else SynchronousInput(hw, clock=clock)
        launcher.main(hardware_factory=lambda: hardware, ui_factory=lambda: ui,
                      clock=clock, sleep=clock.sleep, input_factory=factory,
                      signer_runner=lambda argv: events.append('signer'))
        self.assertEqual(len(attempts), 2)
        self.assertGreaterEqual(attempts[1] - attempts[0], 1.0)
        self.assertEqual(events.count('close'), 2)
        self.assertEqual(events[-2:], ['close', 'signer'])
        self.assertEqual(ui.actions, [])

    def test_stuck_worker_aborts_without_gpio_cleanup_or_signer_entry(self):
        clock, events = Clock(), []
        hardware = FakeHardware(clock, lambda t: 0, events)
        class StuckInput:
            running = True
            def __init__(self, hardware, *, clock):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                raise launcher.InputShutdownError('worker still owns GPIO')
            def read(self):
                return True, ()
        with self.assertRaises(launcher.InputShutdownError):
            launcher.main(hardware_factory=lambda: hardware, ui_factory=FakeUI,
                          clock=clock, sleep=clock.sleep, input_factory=StuckInput,
                          signer_runner=lambda argv: events.append('signer'))
        self.assertEqual(events, ['open'])


if __name__ == "__main__":
    unittest.main()
