"""Real UI/engine/runtime integration with a timed fake GPIO/SPI boundary.

No real GPIO, SD card, SeedSigner application, camera or signing is exercised.
Unlike the runtime unit tests, these scenarios use the actual PokerUI, Pillow
renderer and Session engine together. The signer callback records entry only.
"""
import importlib.util
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "payload/opt/dino"))
from poker_engine import Session
from poker_ui import PokerUI

SPEC = importlib.util.spec_from_file_location("poker_full_flow_launcher", ROOT / "payload/opt/dino/launcher.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
from input_harness import SynchronousInput

OBSERVATIONS = []


class SimulatedClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, duration):
        self.now += duration
        if self.now > 8:
            raise AssertionError("Explicit signer gesture did not finish")


class ObservedUI(PokerUI):
    def __init__(self, session, clock):
        super().__init__(session=session, clock=clock)
        self.actions = []

    def handle(self, action):
        self.actions.append(action)
        return super().handle(action)


class TraceHardware:
    def __init__(self, clock, ui, trace):
        self.clock, self.ui, self.trace = clock, ui, trace
        self.events = []
        self.frames = []

    def __enter__(self):
        self.events.append("hardware_open")
        return self

    def __exit__(self, *args):
        self.events.append("hardware_closed")

    def read_mask(self):
        for start, end, mask in self.trace:
            if start <= self.clock() < end:
                return mask
        return 0

    def present(self, frame):
        if frame.mode != "RGB" or frame.size != (320, 240):
            raise AssertionError("Renderer did not supply a native RGB320x240 frame")
        self.frames.append(self.ui.session.snapshot())

    def show_message(self, *args):
        raise AssertionError(("Unexpected recovery screen", args))


class FullFlowTests(unittest.TestCase):
    def test_gold_controls_select_three_one_credit_hands_before_play(self):
        clock = SimulatedClock()
        session = Session(rng=random.Random(73))
        ui = ObservedUI(session, clock)
        trace = (
            (.10, .20, launcher.KEY3),  # Gold control focus begins at SEE PAYS.
            (.40, .49, 1 << 3), (.60, .69, 1 << 3),
            (.80, .89, 1 << 3), (1.00, 1.09, 1 << 3),
            (1.20, 1.29, 1 << 4),       # BET PER HAND: 10 -> 1.
            (1.40, 1.49, 1 << 2),       # SELECT HANDS.
            (1.60, 1.69, 1 << 4),       # 10 -> 1 active line.
            (1.80, 1.89, 1 << 4),       # 1 -> 2.
            (2.00, 2.09, 1 << 4),       # 2 -> 3.
            (2.20, 2.30, launcher.KEY3), # Return from gold controls.
            (2.50, 2.59, 1 << 1),       # Down: deal three credits total.
            (3.10, 3.19, 1 << 1),       # Down: draw after deal animation.
            (4.00, 6.15, launcher.SIGNER_CHORD),
        )
        hardware = TraceHardware(clock, ui, trace)
        launcher.main(hardware_factory=lambda: hardware, ui_factory=lambda: ui,
                      clock=clock, sleep=clock.sleep, input_factory=SynchronousInput,
                      signer_runner=lambda argv: hardware.events.append("signer_started"))
        self.assertEqual(session.num_hands, 3)
        self.assertEqual(session.bet_per_hand, 1)
        self.assertEqual(session.total_bet, 3)
        self.assertEqual(session.phase, "result")
        self.assertEqual(session.rounds, 1)
        self.assertEqual(len(session.results), 3)
        self.assertEqual(session.credits, 10000-3+session.total_win)
        self.assertEqual(hardware.events, ["hardware_open", "hardware_closed", "signer_started"])
        self.assertIsNone(ui._animation)
        OBSERVATIONS.append({
            "scenario": "physical-buttons-gold-controls-select-three-one-credit-hands",
            "status": "PASS", "actions": ui.actions,
            "rgb_320x240_frames": len(hardware.frames),
            "active_hands": 3, "bet_per_hand": 1, "total_bet": 3,
            "settled_rounds": session.rounds, "ending_phase": session.phase,
            "credit_accounting_verified": True,
            "handoff_order": hardware.events,
        })

    def test_real_hold_draw_new_deal_and_signer_chord(self):
        clock = SimulatedClock()
        session = Session(rng=random.Random(10))
        ui = ObservedUI(session, clock)
        trace = (
            (.2, .4, 1 << 1),             # Down: deal once.
            (.6, .8, 1 << 4),             # Hold card 0 via center.
            (.9, 1.1, 1 << 3),            # Move right to card 1.
            (1.2, 1.4, launcher.KEY2),     # Hold card 1 via right middle.
            (2.0, 2.2, 1 << 1),           # Down: draw once.
            (2.8, 3.0, 1 << 4),           # Center: next round after win presentation.
            (3.3, 5.5, launcher.SIGNER_CHORD),
        )
        hardware = TraceHardware(clock, ui, trace)
        launcher.main(hardware_factory=lambda: hardware, ui_factory=lambda: ui,
                      clock=clock, sleep=clock.sleep, input_factory=SynchronousInput,
                      signer_runner=lambda argv: hardware.events.append("signer_started"))
        self.assertEqual(ui.actions, ["DOWN", "CENTER", "RIGHT", "KEY2", "DOWN", "CENTER"])
        self.assertEqual(hardware.events, ["hardware_open", "hardware_closed", "signer_started"])
        self.assertEqual(session.rounds, 1)
        self.assertEqual(session.phase, "hold")
        self.assertEqual(session.held, [False] * 5)
        self.assertIsNone(ui.menu)
        # Card/win animation and the 200ms idle badge create extra frames, but
        # not extra game actions/wagers or a runaway 100Hz full-screen repaint.
        self.assertLessEqual(len(hardware.frames), 100)
        completed = [state for state in hardware.frames if state["phase"] == "result"]
        self.assertGreaterEqual(len(completed), 1)
        result = completed[0]
        self.assertEqual(result["held"], [True, True, False, False, False])
        total_win = sum(item["payout"] for item in result["results"])
        self.assertEqual(result["credits"], 10_000 - 100 + total_win)
        self.assertEqual(session.credits, 10_000 - 200 + total_win)
        self.assertEqual(session.active_multipliers, result["multipliers"])
        for line in result["hands"]:
            self.assertEqual(line[:2], result["initial"][:2])
            self.assertTrue(set(line[2:]).isdisjoint(result["initial"]))
        self.assertGreaterEqual(clock(), 5.3)
        self.assertLess(clock(), 5.5)
        OBSERVATIONS.append({
            "scenario": "deal-hold0-right-hold1-draw-deal-signer",
            "status": "PASS", "actions": ui.actions,
            "rgb_320x240_frames": len(hardware.frames),
            "settled_rounds": session.rounds, "ending_phase": session.phase,
            "credit_accounting_verified": True,
            "earned_multipliers_used_on_next_deal": True,
            "reserved_chord_emitted_ordinary_actions": False,
            "handoff_simulated_seconds": round(clock(), 3),
            "handoff_order": hardware.events,
        })

    def test_held_deal_on_dealt_royal_does_not_start_another_round(self):
        class RoyalRandom:
            def __init__(self):
                self.calls = 0

            def sample(self, population, count):
                self.calls += 1
                if self.calls != 1 or count != 5:
                    raise AssertionError("A held Deal button started another hand")
                return [8, 9, 10, 11, 12]  # Club royal.

        clock, rng = SimulatedClock(), RoyalRandom()
        session = Session(rng=rng)
        ui = ObservedUI(session, clock)
        trace = ((.2, 1.8, 1 << 1), (2.0, 4.2, launcher.SIGNER_CHORD))
        hardware = TraceHardware(clock, ui, trace)
        launcher.main(hardware_factory=lambda: hardware, ui_factory=lambda: ui,
                      clock=clock, sleep=clock.sleep, input_factory=SynchronousInput,
                      signer_runner=lambda argv: hardware.events.append("signer_started"))
        self.assertEqual(ui.actions, ["DOWN"])
        self.assertEqual(rng.calls, 1)
        self.assertEqual(session.phase, "result")
        self.assertEqual(session.rounds, 1)
        self.assertEqual(session.total_win, 40_000)
        self.assertEqual(session.credits, 49_900)
        self.assertEqual(session.multipliers, [4] * 10)
        self.assertEqual(hardware.events, ["hardware_open", "hardware_closed", "signer_started"])
        # Reveal/count-up and idle badge frames cannot repeat the Deal action.
        self.assertLessEqual(len(hardware.frames), 60)
        OBSERVATIONS.append({
            "scenario": "held-deal-on-automatic-royal-then-signer",
            "status": "PASS", "actions": ui.actions,
            "rgb_320x240_frames": len(hardware.frames),
            "settled_rounds": session.rounds, "ending_phase": session.phase,
            "royal_payout_credits": session.total_win,
            "ending_credits": session.credits,
            "sampler_calls": rng.calls,
            "handoff_order": hardware.events,
        })


if __name__ == "__main__":
    unittest.main()
