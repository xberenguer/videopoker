"""Exercise real poker/controller through production input routing, without GPIO."""
import random
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "payload/opt/dino"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
import launcher
from input_harness import SynchronousInput
try:
    from poker_engine import Session
    from poker_ui import PokerUI
except ImportError:
    PokerUI = None


class Clock:
    def __init__(self):
        self.now = 0.0
    def __call__(self):
        return self.now
    def sleep(self, duration):
        self.now += duration
        if self.now > 10:
            raise AssertionError("Runtime gesture was blocked")


@unittest.skipUnless(PokerUI, "Pillow UI dependency is required")
class RealControllerTests(unittest.TestCase):
    def run_trace(self, trace, ui_factory=None, session_factory=None):
        clock, events = Clock(), []
        game = Session(rng=random.Random(25)) if session_factory is None else session_factory()
        ui = PokerUI(session=game, clock=clock) if ui_factory is None else ui_factory(game, clock)
        class Hardware:
            def __enter__(self):
                events.append("open")
                return self
            def __exit__(self, *args):
                events.append("close")
            def read_mask(self):
                return trace(clock())
            def present(self, frame):
                if frame.size != (320, 240) or frame.mode != "RGB":
                    raise AssertionError("Wrong production frame format")
                events.append(("frame", clock()))
            def show_message(self, *args):
                raise AssertionError("Real UI entered unexpected recovery")
        def signer(argv):
            if events[-1] != "close":
                raise AssertionError("Signer started before GPIO/SPI release")
            events.append(("signer", clock()))
        launcher.main(hardware_factory=Hardware, ui_factory=lambda: ui,
                      clock=clock, sleep=clock.sleep, input_factory=SynchronousInput, signer_runner=signer)
        return game, ui, clock, events

    def test_production_entropy_wait_is_retryable_and_does_not_block_signer(self):
        initial = []
        def production_session():
            session = Session()
            initial.append(session.snapshot())
            return session
        def trace(t):
            if .10 <= t < .19 or .40 <= t < .49:
                return 1 << 1
            if .80 <= t < 2.95:
                return launcher.SIGNER_CHORD
            return 0
        with mock.patch("poker_engine.os.getrandom", side_effect=BlockingIOError(), create=True) as getrandom, \
                mock.patch("poker_engine.os.GRND_NONBLOCK", 1, create=True):
            game, ui, clock, events = self.run_trace(trace, session_factory=production_session)
        self.assertGreaterEqual(getrandom.call_count, 2)
        self.assertEqual(game.snapshot(), initial[0])
        self.assertEqual(game.credits, 10000)
        self.assertEqual(game.rounds, 0)
        self.assertFalse(ui._credit_notice)
        self.assertTrue(ui._entropy_notice)
        self.assertIsNotNone(ui.notice)
        self.assertIn("shuffling", ui.notice.lower())
        self.assertIsNone(ui._animation)
        self.assertGreaterEqual(clock(), 3.03)
        self.assertEqual(events[-2], "close")

    def test_animation_skip_and_held_deal_do_not_double_spend(self):
        def trace(t):
            if .10 <= t < .19 or .90 <= t < .99 or 1.10 <= t < 1.80:
                return 1 << 1
            if .60 <= t < .69:
                return 1 << 4
            if 2.0 <= t < 4.15:
                return launcher.SIGNER_CHORD
            return 0
        game, ui, clock, events = self.run_trace(trace)
        self.assertEqual(game.rounds, 1)
        self.assertEqual(game.phase, "result")
        self.assertEqual(game.credits, 10000 - 100 + game.total_win)
        self.assertIsNone(ui._animation)
        self.assertGreaterEqual(clock(), 4.23)
        self.assertGreaterEqual(sum(isinstance(event, tuple) and event[0] == "frame" for event in events), 8)

    def test_reserved_gesture_remains_responsive_during_long_animation(self):
        def long_animation(game, clock):
            ui = PokerUI(session=game, clock=clock)
            ui.SPEEDS = (2.0, 2.0, 0.0)
            return ui
        def trace(t):
            if .10 <= t < .19:
                return 1 << 1
            if .20 <= t < 2.35:
                return launcher.SIGNER_CHORD
            return 0
        game, ui, clock, events = self.run_trace(trace, long_animation)
        self.assertEqual(game.phase, "hold")
        self.assertEqual(game.rounds, 0)
        self.assertEqual(game.credits, 9900)
        self.assertIsNotNone(ui._animation)
        self.assertLess(clock(), 2.5)
        self.assertEqual(events[-2], "close")

    def test_paytable_menu_does_not_block_signer_gesture(self):
        def trace(t):
            if .10 <= t < .20:
                return launcher.KEY3
            if .40 <= t < .50:
                return 1 << 4
            if .80 <= t < 2.95:
                return launcher.SIGNER_CHORD
            return 0
        game, ui, clock, events = self.run_trace(trace)
        self.assertEqual(game.phase, "ready")
        self.assertEqual(game.credits, 10000)
        self.assertEqual(ui.menu["page"], "paytable")
        self.assertGreaterEqual(clock(), 3.03)

    def test_short_chord_in_game_does_not_toggle_hold_or_activate_gold_controls(self):
        def trace(t):
            if .10 <= t < .19:
                return 1 << 1
            if .60 <= t < 1.0 or 1.20 <= t < 3.35:
                return launcher.SIGNER_CHORD
            return 0
        game, ui, clock, events = self.run_trace(trace)
        self.assertEqual(game.phase, "hold")
        self.assertEqual(game.held, [False] * 5)
        self.assertIsNone(ui.menu)
        self.assertIsNone(ui.button_focus)
        self.assertEqual(game.credits, 9900)


if __name__ == "__main__":
    unittest.main()
