"""Deterministic controller tests: advice never consumes game randomness."""
import copy
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'payload/opt/dino'))
from poker_engine import RandomNotReady, Session
from poker_ui import PokerUI


class Clock:
    def __init__(self): self.value = 100.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds


class Advisor:
    def __init__(self):
        self.requests = []
        self.answers = {}
        self.polls = []
        self.cancels = 0
        self.closes = 0
        self.request_error = self.poll_error = self.close_error = None

    def request(self, snapshot):
        if self.request_error: raise self.request_error
        self.requests.append(copy.deepcopy(snapshot))
        return len(self.requests)

    def poll(self, token):
        self.polls.append(token)
        if self.poll_error: raise self.poll_error
        return self.answers.pop(token, None)

    def cancel(self): self.cancels += 1

    def close(self):
        self.closes += 1
        if self.close_error: raise self.close_error


class AutoplayUITests(unittest.TestCase):
    def make_ui(self, **session_args):
        clock, advisor = Clock(), Advisor()
        session_args.setdefault('rng', random.Random(250))
        ui = PokerUI(Session(**session_args), clock=clock, advisor=advisor)
        ui.speed = 2
        return ui, clock, advisor

    def tick(self, ui, clock, seconds=0):
        clock.advance(seconds)
        return ui.update(clock())

    def start_auto(self, ui, clock):
        ui.handle('UP')
        clock.advance(.1)
        ui.handle('UP')
        self.assertTrue(ui.autoplay)

    def answer(self, ui, clock, advisor, mask):
        advisor.answers[ui._advisor_token] = {'mask': mask, 'expected_value': 1.25}
        self.tick(ui, clock)

    def test_single_up_requests_visible_detached_hand_without_holding_or_spending(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN')
        before = ui.session.snapshot()
        ui.handle('UP')
        self.assertEqual(ui.session.snapshot(), before)
        self.assertEqual(len(advisor.requests), 1)
        request = advisor.requests[0]
        self.assertEqual(request['initial'], before['initial'])
        self.assertEqual(request['active_multipliers'], before['active_multipliers'])
        self.assertTrue(all(hand == before['initial'] for hand in request['hands']))
        self.assertEqual(request['results'], [])
        request['initial'][0] = -1
        self.assertEqual(ui.session.snapshot(), before)
        self.answer(ui, clock, advisor, 0b10100)
        self.assertEqual(ui.session.snapshot(), before)
        self.assertFalse(ui.autoplay)
        self.assertEqual(ui._advice['mask'], 0b10100)
        # A held button emits no further action: repeated frames do not request
        # another solve, debit a bet, or change the recommended mask.
        for _ in range(12): self.tick(ui, clock, .1)
        self.assertEqual(len(advisor.requests), 1)
        self.assertEqual(ui.session.snapshot(), before)

    def test_recommendation_flashes_bright_red_on_only_recommended_card_rings(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); ui.handle('CENTER'); ui.handle('UP')
        before = ui.render()
        self.answer(ui, clock, advisor, 0b10101)
        on = ui.render()
        red = (255, 32, 32)
        for index in range(5):
            x = (103+87*index)//2-1
            self.assertEqual(on.getpixel((x, 150)) == red, bool(0b10101 & (1 << index)))
        # HELD labels and the original source-rendered cards stay intact.
        self.assertEqual(on.crop((57, 184, 87, 202)).tobytes(), before.crop((57, 184, 87, 202)).tobytes())
        self.tick(ui, clock, ui.HINT_FLASH_SECONDS+.01)
        off = ui.render()
        self.assertFalse(ui._hint_flash)
        self.assertEqual(off.crop((0, 120, 270, 196)).tobytes(), before.crop((0, 120, 270, 196)).tobytes())
        self.tick(ui, clock, ui.HINT_FLASH_SECONDS)
        self.assertTrue(ui._hint_flash)

    def test_draw_five_advice_has_no_red_card_and_clear_status(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); ui.handle('UP')
        self.answer(ui, clock, advisor, 0)
        words = []
        original = ui.renderer.text
        def capture(draw, xy, text, *args, **kwargs):
            words.append(str(text))
            return original(draw, xy, text, *args, **kwargs)
        ui.renderer.text = capture
        frame = ui.render()
        self.assertIn('DRAW FIVE', words)
        self.assertNotIn((255, 32, 32), frame.crop((40, 130, 270, 196)).getdata())

    def test_ready_hint_never_bets_and_double_up_starts_one_deal(self):
        ui, clock, advisor = self.make_ui()
        before = ui.session.snapshot()
        ui.handle('UP')
        self.assertEqual(ui.session.snapshot(), before)
        self.assertTrue(ui._advice_notice)
        self.assertEqual(advisor.requests, [])
        clock.advance(.2); ui.handle('UP')
        self.assertTrue(ui.autoplay)
        self.assertIsNone(ui.notice)
        self.tick(ui, clock)
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, 9900)
        self.assertEqual(len(advisor.requests), 1)
        for _ in range(5): self.tick(ui, clock, .1)
        self.assertEqual(ui.session.credits, 9900)
        self.assertEqual(len(advisor.requests), 1)

    def test_autoplay_applies_exact_mask_then_draws_and_waits_before_next_bet(self):
        ui, clock, advisor = self.make_ui()
        self.start_auto(ui, clock)
        self.tick(ui, clock)
        before = ui.session.snapshot()
        self.answer(ui, clock, advisor, 0b01010)
        self.assertEqual(ui.session.held, [False]*5)
        self.tick(ui, clock, ui.AUTO_HINT_SECONDS-.01)
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.held, [False]*5)
        self.tick(ui, clock, .02)
        self.assertEqual(ui.session.held, [False, True, False, True, False])
        self.assertEqual(ui.session.credits, before['credits'])
        self.tick(ui, clock, ui.AUTO_HOLD_SECONDS+.01)
        result = ui.session.snapshot()
        self.assertEqual(result['phase'], 'result')
        self.assertEqual(result['rounds'], 1)
        self.assertEqual(result['credits'], before['credits']+result['total_win'])
        for hand in result['hands']:
            self.assertEqual((hand[1], hand[3]), (before['initial'][1], before['initial'][3]))
        self.tick(ui, clock)
        self.tick(ui, clock, ui.AUTO_RESULT_SECONDS-.01)
        self.assertEqual(ui.session.snapshot(), result)
        self.tick(ui, clock, .02)
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, result['credits']-result['total_bet'])
        self.assertEqual(ui.session.rounds, 1)
        self.assertEqual(ui.session.active_multipliers, result['multipliers'])
        self.assertEqual(len(advisor.requests), 2)

    def test_autoplay_replaces_existing_holds_instead_of_only_adding(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); ui.handle('CENTER')
        self.assertEqual(ui.session.held, [True, False, False, False, False])
        self.start_auto(ui, clock)
        self.answer(ui, clock, advisor, 0b10010)
        self.tick(ui, clock, ui.AUTO_HINT_SECONDS+.01)
        self.assertEqual(ui.session.held, [False, True, False, False, True])

    def test_other_manual_actions_cancel_auto_and_advice_before_their_normal_action(self):
        for action in ('LEFT', 'RIGHT', 'CENTER', 'KEY1', 'KEY2', 'KEY3', 'DOWN'):
            with self.subTest(action=action):
                ui, clock, advisor = self.make_ui()
                ui.handle('DOWN'); self.start_auto(ui, clock)
                token = ui._advisor_token
                advisor.answers[token] = {'mask': 31}
                ui.handle(action)
                self.assertFalse(ui.autoplay)
                self.assertIsNone(ui._advice)
                self.assertIsNone(ui._advisor_token)
                self.assertEqual(advisor.cancels, 1)
                snapshot = ui.session.snapshot()
                self.tick(ui, clock, 10)
                self.assertEqual(ui.session.snapshot(), snapshot)
                self.assertNotIn(token, advisor.polls)
                if action in ('CENTER', 'KEY1', 'KEY2'):
                    self.assertEqual(ui.session.held, [True, False, False, False, False])
                elif action == 'DOWN':
                    self.assertEqual(ui.session.phase, 'result')
                    self.assertEqual(ui.session.rounds, 1)
                elif action == 'KEY3':
                    self.assertEqual(ui.button_focus, 0)

    def test_double_up_turns_auto_off_and_slow_single_taps_do_not_enable_it(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); ui.handle('UP')
        clock.advance(.36); ui.handle('UP')
        self.assertFalse(ui.autoplay)
        self.assertEqual(len(advisor.requests), 1)
        clock.advance(.1); ui.handle('UP')
        self.assertTrue(ui.autoplay)
        clock.advance(.1); ui.handle('UP')
        self.assertTrue(ui.autoplay)
        clock.advance(.1); ui.handle('UP')
        self.assertFalse(ui.autoplay)
        self.assertIsNone(ui._advisor_token)
        self.assertIsNone(ui._advice)

    def test_menu_and_bottom_focus_up_down_never_request_advice_or_start_auto(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('KEY3')
        for action in ('UP', 'DOWN', 'UP', 'UP'): ui.handle(action)
        self.assertFalse(ui.autoplay)
        self.assertEqual(advisor.requests, [])
        ui.button_focus = 0
        ui.handle('KEY2')
        self.assertEqual(ui.menu['page'], 'paytable')
        for action in ('UP', 'UP', 'DOWN'): ui.handle(action)
        self.assertEqual(ui.menu['bet'], 2)
        self.assertFalse(ui.autoplay)
        self.assertEqual(advisor.requests, [])
        ui.handle('KEY2')
        self.assertEqual(ui.menu['page'], 'controls')
        ui.handle('DOWN'); ui.handle('UP')
        self.assertEqual(ui.menu['index'], 0)
        self.assertEqual(ui.session.credits, 10000)

    def test_changed_board_and_mismatched_token_cannot_apply_stale_advice(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.start_auto(ui, clock)
        token = ui._advisor_token
        advisor.answers[token] = {'mask': 31, 'token': token+1}
        self.tick(ui, clock)
        self.assertIsNone(ui._advice)
        self.assertEqual(ui._advisor_token, token)
        ui.session.initial[0] = (ui.session.initial[0]+1) % 52
        advisor.answers[token] = {'mask': 31, 'token': token}
        before = ui.session.snapshot()
        self.tick(ui, clock)
        self.assertFalse(ui.autoplay)
        self.assertIsNone(ui._advisor_token)
        self.assertEqual(ui.session.snapshot(), before)
        self.assertEqual(advisor.cancels, 1)

    def test_strategy_errors_and_malformed_answers_pause_without_game_mutation(self):
        answers = ({'error': 'unsupported'}, {'mask': -1}, {'mask': 32},
                   {'mask': True}, {'mask': 1.0}, {}, [], 'bad')
        for answer in answers:
            with self.subTest(answer=answer):
                ui, clock, advisor = self.make_ui()
                ui.handle('DOWN'); self.start_auto(ui, clock)
                before = ui.session.snapshot()
                advisor.answers[ui._advisor_token] = answer
                self.tick(ui, clock)
                self.assertEqual(ui.session.snapshot(), before)
                self.assertFalse(ui.autoplay)
                self.assertEqual(ui.notice, 'Best hold unavailable')
        for stage in ('request', 'poll'):
            with self.subTest(stage=stage):
                ui, clock, advisor = self.make_ui()
                ui.handle('DOWN')
                setattr(advisor, stage+'_error', RuntimeError('unsupported'))
                before = ui.session.snapshot()
                ui.handle('UP'); self.tick(ui, clock)
                self.assertEqual(ui.session.snapshot(), before)
                self.assertFalse(ui.autoplay)
                self.assertEqual(ui.notice, 'Best hold unavailable')

    def test_insufficient_credits_pause_auto_without_refill_or_extra_deal(self):
        ui, clock, advisor = self.make_ui(credits=20)
        self.start_auto(ui, clock); self.tick(ui, clock)
        self.assertFalse(ui.autoplay)
        self.assertTrue(ui._credit_notice)
        self.assertEqual(ui.session.phase, 'ready')
        self.assertEqual(ui.session.credits, 20)
        self.assertEqual(advisor.requests, [])
        self.tick(ui, clock, 20)
        self.assertEqual(ui.session.credits, 20)
        ui.handle('KEY2')
        self.assertEqual(ui.session.credits, 10020)
        self.assertEqual(ui.session.phase, 'ready')
        self.assertFalse(ui.autoplay)

    def test_entropy_failure_pauses_auto_and_leaves_retry_manual(self):
        class Blocked:
            def sample(self, population, count): raise RandomNotReady('wait')
        ui, clock, advisor = self.make_ui(rng=Blocked())
        before = ui.session.snapshot()
        self.start_auto(ui, clock); self.tick(ui, clock)
        self.assertFalse(ui.autoplay)
        self.assertEqual(ui.session.snapshot(), before)
        self.assertTrue(ui._entropy_notice)
        self.assertEqual(advisor.requests, [])

    def test_auto_animation_never_debits_or_draws_before_presentation_finishes(self):
        ui, clock, advisor = self.make_ui()
        ui.speed = 0
        self.start_auto(ui, clock); self.tick(ui, clock)
        self.assertIsNotNone(ui._animation)
        self.answer(ui, clock, advisor, 31)
        self.tick(ui, clock, ui.AUTO_HINT_SECONDS+.01)
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, 9900)
        self.assertEqual(ui.session.held, [False]*5)
        self.tick(ui, clock, .1)
        self.tick(ui, clock, ui.AUTO_HINT_SECONDS+.01)
        self.tick(ui, clock, ui.AUTO_HOLD_SECONDS+.01)
        self.assertEqual(ui.session.phase, 'result')
        self.assertIsNotNone(ui._animation)
        before = ui.session.snapshot()
        self.tick(ui, clock, .2)
        self.assertEqual(ui.session.snapshot(), before)
        # The result wait starts after the last result animation frame.
        self.tick(ui, clock, 2)
        self.assertEqual(ui.session.snapshot(), before)
        self.tick(ui, clock, ui.AUTO_RESULT_SECONDS-.01)
        self.assertEqual(ui.session.snapshot(), before)
        self.tick(ui, clock, .02)
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, before['credits']-before['total_bet'])

    def test_pause_hook_cancels_solver_and_close_is_idempotent(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.start_auto(ui, clock)
        before = ui.session.snapshot()
        self.assertTrue(ui.pause_autoplay())
        self.assertFalse(ui.pause_autoplay())
        self.assertEqual(advisor.cancels, 1)
        self.assertEqual(ui.session.snapshot(), before)
        ui.close(); ui.close()
        self.assertEqual(advisor.closes, 1)
        self.assertFalse(ui.handle('DOWN'))
        self.assertFalse(ui.update(clock()))
        self.assertEqual(ui.session.snapshot(), before)

    def test_advisor_shutdown_failure_propagates_for_launcher_fail_closed_guard(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.start_auto(ui, clock)
        advisor.close_error = RuntimeError('worker did not stop')
        with self.assertRaisesRegex(RuntimeError, 'worker did not stop'):
            ui.close()
        self.assertFalse(ui.autoplay)
        self.assertEqual(advisor.cancels, 1)
        self.assertFalse(ui._closed)
        advisor.close_error = None
        ui.close()
        self.assertTrue(ui._closed)
        self.assertEqual(advisor.closes, 2)

    def test_slow_separate_up_taps_drained_together_never_start_autoplay(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN')
        before = ui.session.snapshot()
        # Two 600 ms-separated captured edges arrive in one LCD-stalled batch.
        ui.handle_sampled('UP', clock()-0.70)
        ui.handle_sampled('UP', clock()-0.10)
        self.assertFalse(ui.autoplay)
        self.assertEqual(ui.session.snapshot(), before)
        self.assertEqual(len(advisor.requests), 1)

    def test_real_double_up_survives_separate_delayed_ui_dispatches(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN')
        captured = clock()-0.05
        ui.handle_sampled('UP', captured)
        clock.advance(.65)  # A slow redraw delays delivery of the second edge.
        ui.handle_sampled('UP', captured+.20)
        self.assertTrue(ui.autoplay)
        self.assertEqual(ui._captured_input_at, None)

    def test_invalid_sampled_time_cannot_toggle_autoplay(self):
        ui, clock, advisor = self.make_ui()
        for invalid in (None, True, '100', float('nan'), float('inf')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                ui.handle_sampled('UP', invalid)
        self.assertFalse(ui.autoplay)


if __name__ == '__main__': unittest.main()
