#!/usr/bin/env python3
"""Offline poker cabinet, trainer and manual card calculator.

The button gesture is an interface gate, not authentication or isolation.
The production entrypoint starts only Video Poker. Right TOP+BOTTOM held for two
seconds toggles the live trainer immediately; release is required before reuse.
"""
from collections import deque
import sys
import threading
import time

POLL_INTERVAL = 0.01
INPUT_INTERVAL = 0.005
BUTTONS = ("UP", "DOWN", "LEFT", "RIGHT", "CENTER", "KEY1", "KEY2", "KEY3")
KEY1, KEY2, KEY3 = 1 << 5, 1 << 6, 1 << 7
MENU_CHORD = KEY1 | KEY3
SIGNER_CHORD = MENU_CHORD  # Compatibility name for existing diagnostic tools.
RELEASE_BUTTONS = KEY1 | KEY3


class HoldReleaseGate:
    """Fire at two seconds; an explicit reset can require neutral rearming."""

    def __init__(self, hold_seconds=2.0, release_seconds=0.08):
        self.hold_seconds, self.release_seconds = hold_seconds, release_seconds
        self.reset()

    def reset(self):
        self.hold_started = None
        self.release_started = None
        self.latched = self.complete = False
        self.blocked = False
        self.previous = None

    def update(self, now, mask):
        if self.previous is not None and now < self.previous:
            self.reset()
        self.previous = now
        if self.blocked:
            if mask:
                self.release_started = None
            elif self.release_started is None:
                self.release_started = now
            elif now-self.release_started >= self.release_seconds:
                self.blocked = False
                self.release_started = None
            return False
        if self.complete:
            return True
        if not self.latched:
            if mask & SIGNER_CHORD != SIGNER_CHORD:
                self.hold_started = None
            elif self.hold_started is None:
                self.hold_started = now
            elif now - self.hold_started >= self.hold_seconds:
                self.latched = self.complete = True
        return self.complete


class DebouncedButtons:
    """Independent 12ms stable edges; startup/failure needs a neutral release."""

    def __init__(self, debounce_seconds=0.012, neutral_seconds=0.08):
        self.debounce_seconds, self.neutral_seconds = debounce_seconds, neutral_seconds
        self.reset()

    def reset(self):
        self.raw, self.stable = 0, 0
        self.raw_since = [None] * len(BUTTONS)
        self.neutral_since = None
        self.armed = False

    def update(self, now, mask):
        changed = mask ^ self.raw
        for bit in range(len(BUTTONS)):
            if self.raw_since[bit] is None or changed & (1 << bit):
                self.raw_since[bit] = now
        self.raw = mask
        if not self.armed:
            if mask:
                self.neutral_since = None
            elif self.neutral_since is None:
                self.neutral_since = now
            elif now - self.neutral_since >= self.neutral_seconds:
                self.armed = True
                self.stable = 0
            return 0, 0, self.stable
        previous = self.stable
        for bit, since in enumerate(self.raw_since):
            flag = 1 << bit
            if now - since >= self.debounce_seconds:
                self.stable = (self.stable | flag) if mask & flag else (self.stable & ~flag)
        return self.stable & ~previous, previous & ~self.stable, self.stable


class InputRouter:
    """Separate ordinary game edges from the reserved right TOP+BOTTOM chord.

    KEY1/KEY3 are actions on release, so forming the chord never changes a hold
    or opens a menu. An incomplete chord is cancelled without either action.
    """

    def __init__(self, debounce_seconds=0.012, neutral_seconds=0.08):
        self.gate = HoldReleaseGate()
        self.buttons = DebouncedButtons(debounce_seconds, neutral_seconds)
        self.pending = 0
        self.suppress_until_neutral = False
        self.previous = None

    def reset(self):
        self.gate.reset()
        self.buttons.reset()
        self.pending = 0
        self.suppress_until_neutral = False
        self.previous = None

    def update(self, now, mask):
        if not isinstance(mask, int) or isinstance(mask, bool) or not 0 <= mask <= 255:
            raise ValueError("Invalid GPIO button mask")
        if self.previous is not None and now < self.previous:
            self.reset()
        self.previous = now
        if self.gate.update(now, mask):
            return True, ()
        # The reserved chord is detected on raw input, not delayed by debounce.
        if mask & SIGNER_CHORD == SIGNER_CHORD or self.gate.latched:
            self.pending = 0
            self.suppress_until_neutral = True
        pressed, released, stable = self.buttons.update(now, mask)
        if self.suppress_until_neutral:
            if mask == 0 and stable == 0 and not self.gate.latched and not self.gate.blocked:
                self.suppress_until_neutral = False
            return False, ()
        self.pending |= pressed & RELEASE_BUTTONS
        actions = []
        for bit, action in enumerate(BUTTONS):
            flag = 1 << bit
            if flag & RELEASE_BUTTONS:
                if released & flag and self.pending & flag:
                    actions.append(action)
                    self.pending &= ~flag
            elif pressed & flag and not (mask & RELEASE_BUTTONS):
                actions.append(action)
        return False, tuple(actions)


class InputServiceError(RuntimeError):
    """Input sampling stopped; recover without entering the signer."""


class InputShutdownError(RuntimeError):
    """An input worker still owns GPIO; do not clean it up or enter the signer."""


class UIShutdownError(RuntimeError):
    """A game worker did not close; never continue into the signer."""


class SampledInput:
    """Sample GPIO independently of slow Pillow/SPI work on the UI thread.

    Only this worker reads GPIO and owns the router. The ordered bounded queue
    contains actions, never game state. Faults, stale queues and long sampling
    gaps discard pending actions and require a neutral release before rearming.
    """

    def __init__(self, hardware, *, clock=time.monotonic,
                 interval=INPUT_INTERVAL, debounce_seconds=0.012,
                 neutral_seconds=0.08, max_events=64, max_age_seconds=0.75,
                 max_sample_gap=0.10):
        if interval <= 0 or debounce_seconds <= 0 or neutral_seconds <= 0:
            raise ValueError("Input timings must be positive")
        if type(max_events) is not int or max_events < 1:
            raise ValueError("Input queue must have positive capacity")
        if max_age_seconds <= 0 or max_sample_gap <= interval:
            raise ValueError("Invalid input age or sampling gap")
        self.hardware, self.clock, self.interval = hardware, clock, interval
        self.max_events, self.max_age_seconds = max_events, max_age_seconds
        self.max_sample_gap = max_sample_gap
        self.router = InputRouter(debounce_seconds, neutral_seconds)
        self._queue = deque()
        self._events = deque()
        self._last_levels = 0
        self._lock, self._stop = threading.Lock(), threading.Event()
        self._thread = None
        self._entered = False
        self._last_sample = None
        self._stats = dict(samples=0, read_errors=0, queue_overflows=0,
                           stale_resets=0, gap_resets=0,
                           max_sample_gap_seconds=0.0)

    def _reset_locked(self):
        self.router.reset()
        self.router.gate.blocked = True
        self.router.suppress_until_neutral = True
        self._queue.clear()
        self._events.clear()
        self._events.append((self.clock(), 'reset', 0))
        self._last_levels = 0
        self._entered = False
        self._last_sample = None

    def reset(self):
        with self._lock:
            self._reset_locked()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def stats(self):
        with self._lock:
            return dict(self._stats)

    @property
    def pressed_mask(self):
        """Current debounced levels; startup and fault recovery are neutral."""
        with self._lock:
            buttons = self.router.buttons
            return buttons.stable if buttons.armed else 0

    @property
    def gesture_pending(self):
        """Expose chord suppression without allowing the UI to own its state."""
        with self._lock:
            gate = self.router.gate
            return (gate.hold_started is not None or gate.latched or
                    (self.router.suppress_until_neutral and not gate.blocked))

    def __enter__(self):
        if self._thread is not None:
            raise RuntimeError("Input service cannot be started twice")
        self._thread = threading.Thread(target=self._sample, name="poker-input", daemon=True)
        self._thread.start()
        return self

    def _sample(self):
        while not self._stop.is_set():
            began = self.clock()
            try:
                mask = self.hardware.read_mask()
                now = self.clock()
                with self._lock:
                    self._stats['samples'] += 1
                    if self._last_sample is not None:
                        gap = now - self._last_sample
                        self._stats['max_sample_gap_seconds'] = max(
                            gap, self._stats['max_sample_gap_seconds'])
                        if gap < 0 or gap > self.max_sample_gap:
                            self._stats['gap_resets'] += 1
                            self._reset_locked()
                    self._last_sample = now
                    entered, actions = self.router.update(now, mask)
                    buttons = self.router.buttons
                    levels = buttons.stable if buttons.armed else 0
                    events = []
                    if levels != self._last_levels:
                        events.append((now, 'levels', levels))
                        self._last_levels = levels
                    events.extend((now, 'action', action) for action in actions)
                    if entered:
                        self._entered = True
                        self._queue.clear()
                        self._events.clear()
                    elif events:
                        if (len(self._queue) + len(actions) > self.max_events
                                or len(self._events) + len(events) > 3*self.max_events):
                            self._stats['queue_overflows'] += 1
                            self._reset_locked()
                        else:
                            self._queue.extend((now, action) for action in actions)
                            self._events.extend(events)
            except Exception:
                with self._lock:
                    self._stats['read_errors'] += 1
                    self._reset_locked()
            # Event.wait also makes shutdown immediate rather than waiting for
            # the next poll, and does not hold the GIL during a render/SPI write.
            self._stop.wait(max(0.0, self.interval - (self.clock() - began)))

    def read(self):
        entered, events = self.read_timed()
        return entered, tuple(action for _, action in events)

    def read_timed(self):
        """Drain captured edges with their monotonic sampling timestamps."""
        with self._lock:
            if not self.running:
                raise InputServiceError("Input sampling is unavailable")
            if self._entered:
                return True, ()
            if self._queue and self.clock() - self._queue[0][0] > self.max_age_seconds:
                self._stats['stale_resets'] += 1
                self._reset_locked()
                return False, ()
            events = tuple(self._queue)
            self._queue.clear()
            self._events.clear()
            return False, events

    def read_events(self):
        """Drain ordered debounced levels and actions, including UP releases.

        Keeping captured releases makes tap-versus-hold independent of how
        long the UI took to draw. Legacy read/read_timed retain press-only APIs.
        """
        with self._lock:
            if not self.running:
                raise InputServiceError('Input sampling is unavailable')
            if self._entered:
                return True, ()
            if self._events and self.clock()-self._events[0][0] > self.max_age_seconds:
                self._stats['stale_resets'] += 1
                self._reset_locked()
            events = tuple(self._events)
            self._events.clear()
            self._queue.clear()
            return False, events

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            if self._thread.is_alive():
                raise InputShutdownError("Input worker did not release GPIO")
        self.reset()

    def __exit__(self, *args):
        self.close()


def _default_ui():
    from poker_app import PokerApp
    return PokerApp(width=320, height=240)


def _neutral_message(hardware):
    try:
        hardware.show_message("Game unavailable", "Down button: retry")
    except Exception:
        # A failed frame must not disable GPIO polling or reveal the signer.
        pass


def _close_ui(ui):
    close = getattr(ui, "close", None)
    if callable(close):
        try:
            close()
        except Exception as error:
            raise UIShutdownError("Game worker did not stop") from error


def run_game_gate(hardware_factory=None, ui_factory=_default_ui,
                  clock=time.monotonic, sleep=time.sleep, *, input_factory=SampledInput):
    """Return only after the explicit signer gesture, with hardware released."""
    if hardware_factory is None:
        from hardware import PlusHardware
        hardware_factory = PlusHardware
    # Hardware-construction failure cannot open a different application. Retry safely.
    while True:
        inputs, ui = None, None
        try:
            hardware_context = hardware_factory()
            hardware = hardware_context.__enter__()
        except Exception:
            sleep(1.0)
            continue
        try:
            with input_factory(hardware, clock=clock) as inputs:
                ui, dirty, retry = None, True, True
                while True:
                    now = clock()
                    try:
                        read_events = getattr(inputs, 'read_events', None)
                        read_timed = getattr(inputs, "read_timed", None)
                        if callable(read_events):
                            enter_signer, input_events = read_events()
                            timed_actions = tuple((at, value) for at, kind, value in input_events if kind == 'action')
                        elif callable(read_timed):
                            enter_signer, timed_actions = read_timed()
                        else:
                            enter_signer, actions = inputs.read()
                            captured_at = clock()
                            timed_actions = tuple((captured_at, action) for action in actions)
                        actions = tuple(action for _, action in timed_actions)
                    except InputServiceError:
                        raise
                    except Exception:
                        inputs.reset()
                        sleep(POLL_INTERVAL)
                        continue
                    if enter_signer:
                        toggle=getattr(ui,'toggle_hidden_mode',None)
                        if not callable(toggle):toggle=getattr(ui,'toggle_calculator',None)
                        if callable(toggle):
                            toggle()
                            inputs.reset()
                            brightness=getattr(hardware,'set_brightness',None)
                            if callable(brightness):brightness(getattr(ui,'display_brightness',100))
                            hardware.present(ui.render())
                            dirty=False
                            sleep(POLL_INTERVAL)
                            continue
                        return
                    if retry:
                        retry = False
                        try:
                            ui = ui_factory()
                            dirty = True
                        except Exception:
                            ui = None
                            _neutral_message(hardware)
                        # Never replay buttons pressed while the UI was being
                        # imported or rebuilt, before it became visible.
                        inputs.reset()
                        actions = ()
                        timed_actions = ()
                        input_events = ()
                    if ui is None:
                        retry = "DOWN" in actions
                    else:
                        try:
                            gesture_pending = getattr(inputs, "gesture_pending", False)
                            if gesture_pending:
                                pause = getattr(ui, "pause_autoplay", None)
                                if callable(pause):
                                    dirty = bool(pause()) or dirty
                            set_pressed_mask = getattr(ui, "set_pressed_mask", None)
                            handle_sampled = getattr(ui, "handle_sampled", None)
                            if callable(read_events):
                                sampled_levels = getattr(ui, 'set_pressed_mask_sampled', None)
                                for captured_at, kind, value in input_events:
                                    if kind in ('levels', 'reset'):
                                        if kind == 'reset':
                                            reset_ui = getattr(ui, 'on_input_reset', None)
                                            if not callable(reset_ui):
                                                reset_ui = getattr(ui, 'pause_autoplay', None)
                                            if callable(reset_ui):
                                                dirty = bool(reset_ui()) or dirty
                                        if callable(sampled_levels):
                                            dirty = bool(sampled_levels(value, captured_at)) or dirty
                                        elif callable(set_pressed_mask):
                                            dirty = bool(set_pressed_mask(value)) or dirty
                                    elif kind == 'action' and not gesture_pending:
                                        if callable(handle_sampled):
                                            handle_sampled(value, captured_at)
                                        else:
                                            ui.handle(value)
                                        dirty = True
                            else:
                                pressed_mask = getattr(inputs, "pressed_mask", None)
                                if pressed_mask is not None and callable(set_pressed_mask):
                                    dirty = bool(set_pressed_mask(pressed_mask)) or dirty
                                for captured_at, action in timed_actions:
                                    if gesture_pending:
                                        continue
                                    if callable(handle_sampled):
                                        handle_sampled(action, captured_at)
                                    else:
                                        ui.handle(action)
                                    dirty = True
                            dirty = bool(ui.update(now)) or dirty
                            if dirty:
                                brightness=getattr(hardware,'set_brightness',None)
                                if callable(brightness):brightness(getattr(ui,'display_brightness',100))
                                hardware.present(ui.render())
                                presented=getattr(ui,'on_frame_presented',None)
                                if callable(presented):presented(clock())
                                dirty = False
                        except Exception:
                            discarded_ui, ui = ui, None
                            _close_ui(discarded_ui)
                            discarded_ui = None
                            inputs.reset()
                            _neutral_message(hardware)
                    sleep(POLL_INTERVAL)
        except InputServiceError:
            _neutral_message(hardware)
            sleep(1.0)
        finally:
            try:
                # Solver threads must be cancelled/joined before releasing the
                # display or importing the signer. A failed close aborts entry.
                _close_ui(ui)
            finally:
                # A stuck native GPIO call must never race cleanup or signer setup.
                # Its bounded join raises above; fail closed with ownership retained.
                if inputs is None or not getattr(inputs, 'running', False):
                    hardware_context.__exit__(None, None, None)


def start_signer(argv=None):
    """Keep the upstream splash, settings behavior and restart entrypoint."""
    upstream_path = "/opt/src"
    if upstream_path not in sys.path:
        sys.path.insert(0, upstream_path)
    from hardware import configure_plus_display
    from seedsigner.models.settings import Settings, SettingsConstants
    from seedsigner.hardware.displays import st7789_mpy
    configure_plus_display(Settings.get_instance(), SettingsConstants, st7789_mpy)
    import main as upstream_main
    upstream_main.main(sys.argv[1:] if argv is None else argv)


# Descriptive public entrypoint for hardware probes and host integration tests.
run_poker_gate = run_game_gate


def main(argv=None, *, hardware_factory=None, ui_factory=_default_ui,
         clock=time.monotonic, sleep=time.sleep, signer_runner=None,
         input_factory=SampledInput):
    # An explicit injected callback is retained only for the existing harness.
    # There is no signer fallback in this build's normal boot path, even if a
    # UI cannot be initialized while the reserved gesture completes.
    while True:
        run_poker_gate(hardware_factory, ui_factory, clock, sleep, input_factory=input_factory)
        if signer_runner is not None:
            signer_runner(argv)
            return
        sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
