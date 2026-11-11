"""Explicit synchronous input injection for simulated-clock integration tests.

Production always uses SampledInput. These tests deliberately advance logical
time themselves, so a real worker thread would not model their GPIO timelines.
Real concurrent capture and shutdown are exercised by test_input_latency.py.
"""
import launcher


class SynchronousInput:
    def __init__(self, hardware, *, clock):
        self.hardware, self.clock = hardware, clock
        self.router = launcher.InputRouter()
        self.running = False

    def __enter__(self):
        self.running = True
        return self

    def __exit__(self, *args):
        self.running = False

    def reset(self):
        self.router.reset()

    @property
    def pressed_mask(self):
        buttons = self.router.buttons
        return buttons.stable if buttons.armed else 0

    @property
    def gesture_pending(self):
        gate = self.router.gate
        return (gate.hold_started is not None or gate.latched or
                self.router.suppress_until_neutral)

    def read(self):
        entered, events = self.read_timed()
        return entered, tuple(action for _, action in events)

    def read_timed(self):
        try:
            now = self.clock()
            entered, actions = self.router.update(now, self.hardware.read_mask())
            return entered, tuple((now, action) for action in actions)
        except Exception:
            self.reset()
            raise
