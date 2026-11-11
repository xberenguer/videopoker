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

    def read(self):
        try:
            return self.router.update(self.clock(), self.hardware.read_mask())
        except Exception:
            self.reset()
            raise
