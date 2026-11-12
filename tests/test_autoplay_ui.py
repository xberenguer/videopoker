"""Deterministic held-peek and human-paced autoplay controller checks."""
import copy
import random
import sys
import unittest
from pathlib import Path
from PIL import ImageChops

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
        self.requests, self.answers, self.polls = [], {}, []
        self.cancels = self.closes = 0
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
        ui.autoplay_speed = 1
        # Most controller tests isolate timing from animation presentation;
        # the real-profile test below restores all production animation values.
        ui.AUTO_PROFILES = tuple(dict(profile, animation=0) for profile in PokerUI.AUTO_PROFILES)
        return ui, clock, advisor

    def tick(self, ui, clock, seconds=0):
        clock.advance(seconds)
        return ui.update(clock())

    def press_up(self, ui, captured_at=None):
        ui.set_pressed_mask(1)
        return ui.handle('UP') if captured_at is None else ui.handle_sampled('UP', captured_at)

    def release_up(self, ui):
        return ui.set_pressed_mask(0)

    def tap_up(self, ui, captured_at=None):
        self.press_up(ui, captured_at)
        self.release_up(ui)

    def start_auto(self, ui, clock):
        desired_speed = ui.autoplay_speed
        self.tap_up(ui)
        self.assertFalse(ui.autoplay)
        clock.advance(.1)
        self.tap_up(ui)
        self.assertFalse(ui.autoplay)
        clock.advance(.1)
        self.tap_up(ui)
        self.assertTrue(ui.autoplay)
        self.assertTrue(ui.manual_autoplay)
        # Continuous-controller fixtures explicitly choose their profile after
        # the production activation gesture, which always starts in M.
        for _ in range(desired_speed):
            self.double_up(ui, clock)
            clock.advance(ui.UP_CLICK_GAP_SECONDS+ui.UP_TAP_COMMIT_GRACE_SECONDS+.01)
            ui._commit_auto_up()

    def double_up(self, ui, clock):
        self.tap_up(ui)
        clock.advance(.1)
        self.tap_up(ui)

    def finish_up_sequence(self, ui, clock):
        return self.tick(ui, clock, ui.UP_CLICK_GAP_SECONDS+ui.UP_TAP_COMMIT_GRACE_SECONDS+.01)

    def answer(self, ui, clock, advisor, mask):
        advisor.answers[ui._advisor_token] = {'mask': mask, 'expected_value': 1.25}
        self.tick(ui, clock)

    def normal_frame(self, ui):
        state = dict(ui._visual if ui._visual is not None else ui.session.snapshot())
        state.update(_button_focus=ui.button_focus,
                     _speed=ui.autoplay_display_speed if ui.autoplay else ui.speed,
                     _badge_frame=ui._badge_frame)
        return ui.renderer.render(state, ui.selected_card, ui.selected_hand, ui.menu)

    def finish_selections(self, ui, clock):
        self.tick(ui, clock, ui.AUTO_CONSIDER_SECONDS+.01)
        self.assertEqual(ui._auto_stage, 'select')
        for _ in range(5): self.tick(ui, clock, ui.AUTO_SELECT_SECONDS+.01)
        self.assertEqual(ui._auto_stage, 'draw')

    def test_held_up_requests_visible_detached_hand_without_holding_or_spending(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); before = ui.session.snapshot()
        self.press_up(ui)
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
        for _ in range(12): self.tick(ui, clock, .5)
        self.assertEqual(len(advisor.requests), 1)
        self.assertEqual(ui.session.snapshot(), before)
        self.assertTrue(ui.hint_visible)
        self.assertFalse(ui.autoplay)

    def test_red_peek_is_solid_only_on_recommended_cards_and_clears_on_release(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); ui.handle('CENTER')
        self.press_up(ui); self.answer(ui, clock, advisor, 0b10101)
        self.tick(ui, clock, ui.HINT_HOLD_SECONDS+.001)
        red = (255, 32, 32)
        for elapsed in (0, .28, .5, 1.7, 4.0):
            self.tick(ui, clock, elapsed)
            frame = ui.render(); normal = self.normal_frame(ui)
            self.assertTrue(ui.hint_visible)
            for index in range(5):
                x = (103+87*index)//2-1
                self.assertEqual(frame.getpixel((x, 150)) == red, bool(0b10101 & (1 << index)))
            self.assertEqual(frame.crop((57, 184, 87, 202)).tobytes(), normal.crop((57, 184, 87, 202)).tobytes())
            # No instructions, analyzing banner, AUTO text or footer overlay.
            self.assertEqual(frame.crop((0, 197, 320, 240)).tobytes(), normal.crop((0, 197, 320, 240)).tobytes())
        last_edge = ui._last_up
        self.assertTrue(self.release_up(ui))
        self.assertFalse(ui.hint_visible)
        self.assertEqual(ui._last_up, last_edge)
        self.assertEqual(ui.render().tobytes(), self.normal_frame(ui).tobytes())
        self.assertEqual(advisor.cancels, 1)

    def test_pending_and_draw_five_hint_flashes_actual_draw_button_only(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); before=ui.session.snapshot(); self.press_up(ui)
        self.assertEqual(ui.render().tobytes(), self.normal_frame(ui).tobytes())
        self.answer(ui, clock, advisor, 0)
        self.tick(ui, clock, ui.HINT_HOLD_SECONDS+.001)
        self.assertTrue(ui.hint_visible)
        for frame in range(8):
            if frame:self.tick(ui,clock,ui.HINT_DRAW_FLASH_SECONDS/2)
            image=ui.render();normal=self.normal_frame(ui)
            box=ImageChops.difference(image,normal).getbbox()
            if frame%2==0:
                self.assertIsNotNone(box)
                self.assertGreaterEqual(box[0],275);self.assertGreaterEqual(box[1],218)
                self.assertLessEqual(box[2],319);self.assertLessEqual(box[3],234)
                changed=sum(a!=b for a,b in zip(image.crop((275,218,319,234)).getdata(),
                                               normal.crop((275,218,319,234)).getdata()))
                self.assertGreater(changed,250) # Whole button face, not its outline.
                # Dark lettering is retained rather than covered with a fill.
                self.assertTrue(all(p==q for p,q in zip(image.crop((280,221,314,230)).getdata(),
                    normal.crop((280,221,314,230)).getdata()) if max(q)<50))
            else:self.assertIsNone(box)
            self.assertEqual(ui.session.snapshot(),before);self.assertIsNone(ui.notice)
        self.release_up(ui)
        self.assertFalse(ui.hint_visible)
        self.assertEqual(ui.render().tobytes(),self.normal_frame(ui).tobytes())

    def test_draw_hint_flash_restarts_only_for_a_new_continuous_hold(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN');self.press_up(ui);self.answer(ui,clock,advisor,0)
        self.tick(ui,clock,ui.HINT_HOLD_SECONDS+.01)
        first=ui._draw_hint_started
        self.tick(ui,clock,2);self.assertEqual(ui._draw_hint_started,first)
        self.release_up(ui);self.tick(ui,clock,.5)
        self.press_up(ui);self.answer(ui,clock,advisor,0)
        self.assertIsNone(ui._draw_hint_started)
        self.tick(ui,clock,ui.HINT_HOLD_SECONDS+.01)
        self.assertGreater(ui._draw_hint_started,first)
        self.assertFalse(ui.autoplay)

    def test_quick_double_and_triple_with_draw_five_advice_show_no_red_draw(self):
        for count in (2,3):
            ui,clock,advisor=self.make_ui();ui.handle('DOWN')
            for _ in range(count):
                self.press_up(ui)
                if ui._advisor_token is not None:self.answer(ui,clock,advisor,0)
                self.tick(ui,clock,.08)
                self.assertFalse(ui.hint_visible)
                self.assertEqual(ui.render().crop((275,218,319,233)).tobytes(),
                                 self.normal_frame(ui).crop((275,218,319,233)).tobytes())
                self.release_up(ui);self.tick(ui,clock,.08)

    def test_released_pending_answer_is_cached_without_showing_or_applying_it(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.press_up(ui)
        token = ui._advisor_token
        before = ui.session.snapshot()
        self.assertFalse(self.release_up(ui))  # No visible hint yet.
        advisor.answers[token] = {'mask': 31}
        self.tick(ui, clock, 5)
        self.assertIn(token, advisor.polls)
        self.assertEqual(ui._advice['mask'], 31)
        self.assertEqual(ui.session.snapshot(), before)
        self.assertFalse(ui.hint_visible)
        self.assertEqual(ui.render().tobytes(), self.normal_frame(ui).tobytes())

    def test_hint_waits_for_continuous_hold_then_clears_on_release(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.press_up(ui)
        self.answer(ui, clock, advisor, 7)
        self.tick(ui, clock, ui.HINT_HOLD_SECONDS-.001)
        self.assertFalse(ui.hint_visible)
        self.assertEqual(ui.render().tobytes(), self.normal_frame(ui).tobytes())
        self.assertTrue(self.tick(ui, clock, .002))
        self.assertTrue(ui.hint_visible)
        self.release_up(ui)
        self.assertFalse(ui.hint_visible)
        self.assertEqual(ui.render().tobytes(), self.normal_frame(ui).tobytes())

    def test_fast_double_and_triple_never_render_red_even_with_ready_advice(self):
        for count in (2,3):
            ui, clock, advisor = self.make_ui()
            ui.handle('DOWN')
            for _ in range(count):
                self.press_up(ui)
                if ui._advisor_token is not None:
                    self.answer(ui, clock, advisor, 7)
                self.tick(ui, clock, .08)
                self.assertFalse(ui.hint_visible)
                self.assertEqual(ui.render().crop((0,0,320,200)).tobytes(),
                                 self.normal_frame(ui).crop((0,0,320,200)).tobytes())
                self.release_up(ui)
                self.tick(ui, clock, .08)
            self.finish_up_sequence(ui, clock)
            if count==2 and ui._advisor_token is not None:
                self.answer(ui, clock, advisor, 7)
            self.assertEqual(ui.autoplay, count==3)
            self.assertFalse(ui.hint_visible)
            if count==2:self.assertEqual(ui.session.held,[True,True,True,False,False])

    def test_each_new_press_restarts_hint_delay_using_sampled_hold_time(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.press_up(ui)
        self.answer(ui, clock, advisor, 7)
        self.tick(ui, clock, .25);self.release_up(ui)
        self.tick(ui, clock, .5)
        ui.set_pressed_mask_sampled(1, clock()-.1)
        ui.handle_sampled('UP', clock()-.1)
        self.answer(ui, clock, advisor, 7)
        self.tick(ui, clock, .19)
        self.assertFalse(ui.hint_visible)
        self.tick(ui, clock, .02)
        self.assertTrue(ui.hint_visible)

    def test_queued_up_already_released_before_dispatch_cannot_show_late_hint(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); before = ui.session.snapshot()
        requests = len(advisor.requests)
        ui.set_pressed_mask(0)
        ui.handle_sampled('UP', clock()-.2)
        self.tick(ui, clock)
        self.assertEqual(len(advisor.requests), requests)
        self.assertFalse(ui.hint_visible)
        self.assertEqual(ui.session.snapshot(), before)
        self.assertEqual(ui.render().tobytes(), self.normal_frame(ui).tobytes())

    def test_ready_and_result_up_are_silent_until_three_clicks_start_auto(self):
        for phase in ('ready', 'result'):
            with self.subTest(phase=phase):
                ui, clock, advisor = self.make_ui()
                if phase == 'result': ui.handle('DOWN'); ui.handle('DOWN')
                before = ui.session.snapshot()
                requests = len(advisor.requests)
                self.tap_up(ui)
                self.assertEqual(ui.session.snapshot(), before)
                self.assertIsNone(ui.notice)
                self.assertEqual(len(advisor.requests), requests)
                self.assertEqual(ui.render().tobytes(), self.normal_frame(ui).tobytes())
                clock.advance(.2); self.tap_up(ui)
                self.assertFalse(ui.autoplay)
                clock.advance(.2); self.tap_up(ui)
                self.assertTrue(ui.autoplay)
                self.assertFalse(ui.hint_visible)

    def test_autoplay_paces_each_selection_then_draw_and_results_without_extra_debits(self):
        ui, clock, advisor = self.make_ui()
        self.start_auto(ui, clock); self.tick(ui, clock)
        dealt_at = clock(); before = ui.session.snapshot()
        self.answer(ui, clock, advisor, 0b01010)
        self.assertEqual(ui._auto_stage, 'consider')
        self.tick(ui, clock, ui.AUTO_CONSIDER_SECONDS-.01)
        self.assertEqual(ui.session.held, [False]*5)
        self.tick(ui, clock, .02)
        self.assertEqual((ui._auto_stage, ui.selected_card), ('select', 0))
        self.assertEqual(ui.session.held, [False]*5)
        expected = [False]*5
        for index in range(5):
            self.tick(ui, clock, ui.AUTO_SELECT_SECONDS-.01)
            self.assertEqual(ui.session.held, expected)
            self.tick(ui, clock, .02)
            expected[index] = bool(0b01010 & (1 << index))
            self.assertEqual(ui.session.held, expected)
            self.assertEqual(ui.selected_card, min(4, index+1))
            self.assertEqual(ui.session.credits, before['credits'])
        self.assertEqual(ui._auto_stage, 'draw')
        self.tick(ui, clock, ui.AUTO_HOLD_SECONDS-.01)
        self.assertEqual(ui.session.phase, 'hold')
        self.tick(ui, clock, .02)
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
        self.assertEqual(ui.session.active_multipliers, result['multipliers'])
        self.assertEqual(ui.session.rounds, 1)
        self.assertGreaterEqual(clock()-dealt_at, 6.03)
        self.assertLess(clock()-dealt_at, 6.3)
        self.assertEqual(len(advisor.requests), 2)

    def test_autoplay_uses_normal_yellow_and_only_adds_a_small_footer_a(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.start_auto(ui, clock)
        # Keep UP physically held while auto runs: still no red or labels.
        ui.set_pressed_mask(1)
        self.answer(ui, clock, advisor, 0b10101)
        for seconds in (0, 2, 4.01, .41, .41, .41, .41, .41, .51, 0):
            self.tick(ui, clock, seconds)
            self.assertTrue(ui.autoplay)
            self.assertFalse(ui.hint_visible)
            frame, normal = ui.render(), self.normal_frame(ui)
            difference = ImageChops.difference(frame, normal)
            bounds = difference.getbbox()
            self.assertIsNotNone(bounds)
            self.assertGreaterEqual(bounds[0], 246)
            self.assertGreaterEqual(bounds[1], 205)
            self.assertLessEqual(bounds[2], 262)
            self.assertLessEqual(bounds[3], 217)
            self.assertIn((255, 255, 0), set(frame.crop((246, 205, 262, 217)).getdata()))
            frame.paste(normal.crop((246, 205, 262, 217)), (246, 205))
            self.assertEqual(frame.tobytes(), normal.tobytes())
        self.assertEqual(ui.session.phase, 'result')
        self.assertEqual(ui.session.held, [True, False, True, False, True])

    def test_slow_frame_advances_only_one_card_and_never_catches_up_in_a_burst(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.start_auto(ui, clock)
        self.answer(ui, clock, advisor, 31)
        self.tick(ui, clock, 6.01)
        self.tick(ui, clock, 10)
        self.assertEqual(ui.session.held, [True, False, False, False, False])
        self.assertEqual(ui.selected_card, 1)
        self.tick(ui, clock)
        self.assertEqual(ui.session.held, [True, False, False, False, False])

    def test_autoplay_replaces_existing_holds_one_position_at_a_time(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); ui.handle('CENTER'); self.start_auto(ui, clock)
        self.answer(ui, clock, advisor, 0b10010)
        self.finish_selections(ui, clock)
        self.assertEqual(ui.session.held, [False, True, False, False, True])

    def test_every_other_button_stops_auto_without_performing_an_extra_game_action(self):
        for action in ('LEFT', 'RIGHT', 'CENTER', 'KEY1', 'KEY2', 'KEY3', 'DOWN'):
            with self.subTest(action=action):
                ui, clock, advisor = self.make_ui()
                ui.handle('DOWN'); self.start_auto(ui, clock)
                token = ui._advisor_token; cancels = advisor.cancels
                advisor.answers[token] = {'mask': 31}
                snapshot = ui.session.snapshot()
                selection = ui.selected_card
                ui.handle(action)
                self.assertFalse(ui.autoplay)
                self.assertIsNone(ui._advice)
                self.assertIsNone(ui._advisor_token)
                self.assertEqual(advisor.cancels, cancels+1)
                self.assertEqual(ui.session.snapshot(), snapshot)
                self.assertEqual(ui.selected_card, selection)
                self.assertIsNone(ui.button_focus)
                self.assertIsNone(ui.menu)
                self.tick(ui, clock, 30)
                self.assertEqual(ui.session.snapshot(), snapshot)
                self.assertNotIn(token, advisor.polls)
                self.assertFalse(ui.hint_visible)
                self.assertEqual(ui.render().tobytes(), self.normal_frame(ui).tobytes())

    def test_double_tap_changes_speed_and_triple_stops_without_double_prefix(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.tap_up(ui)
        clock.advance(.36); self.tap_up(ui)
        self.assertFalse(ui.autoplay)
        clock.advance(.1); self.tap_up(ui)
        self.assertFalse(ui.autoplay)
        clock.advance(.1); self.tap_up(ui)
        self.assertTrue(ui.autoplay)
        before = ui.session.snapshot()
        self.double_up(ui, clock)
        self.assertEqual(ui.autoplay_speed,0)
        self.finish_up_sequence(ui, clock)
        self.assertTrue(ui.autoplay)
        self.assertEqual(ui.autoplay_speed,1)
        for _ in range(3):
            clock.advance(.1); self.tap_up(ui)
        self.assertFalse(ui.autoplay)
        self.assertEqual(ui.autoplay_speed,1)
        self.assertEqual(ui.session.snapshot(),before)
        self.start_auto(ui,clock)
        self.assertEqual(ui.autoplay_speed,1)

    def test_menu_and_bottom_focus_up_down_never_start_peek_or_auto(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('KEY3')
        for action in ('UP', 'DOWN', 'UP', 'UP'): ui.handle(action)
        ui.button_focus = 0; ui.handle('KEY2')
        self.assertEqual(ui.menu['page'], 'paytable')
        ui.set_pressed_mask(1)
        for action in ('UP', 'UP', 'DOWN'): ui.handle(action)
        self.tick(ui, clock)
        self.assertEqual(ui.menu['bet'], 2)
        self.assertFalse(ui.autoplay)
        self.assertFalse(ui.hint_visible)
        self.assertEqual(advisor.requests, [])
        self.assertEqual(ui.session.credits, 10000)

    def test_changed_board_and_wrong_token_cannot_apply_stale_advice(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.start_auto(ui, clock)
        token = ui._advisor_token
        advisor.answers[token] = {'mask': 31, 'token': token+1}
        self.tick(ui, clock)
        self.assertIsNone(ui._advice)
        self.assertEqual(ui._advisor_token, token)
        ui.session.initial[0] = (ui.session.initial[0]+1) % 52
        advisor.answers[token] = {'mask': 31, 'token': token}
        before = ui.session.snapshot(); self.tick(ui, clock)
        self.assertFalse(ui.autoplay)
        self.assertIsNone(ui._advisor_token)
        self.assertEqual(ui.session.snapshot(), before)

    def test_strategy_failures_are_silent_and_do_not_retry_each_held_frame(self):
        answers = ({'error': 'unsupported'}, {'mask': -1}, {'mask': 32},
                   {'mask': True}, {'mask': 1.0}, {}, [], 'bad')
        for auto in (False, True):
            for answer in answers:
                with self.subTest(auto=auto, answer=answer):
                    ui, clock, advisor = self.make_ui()
                    ui.handle('DOWN')
                    if auto: self.start_auto(ui, clock)
                    else: self.press_up(ui)
                    before = ui.session.snapshot()
                    advisor.answers[ui._advisor_token] = answer
                    self.tick(ui, clock)
                    requests = len(advisor.requests)
                    for _ in range(5): self.tick(ui, clock, 1)
                    self.assertEqual(len(advisor.requests), requests)
                    self.assertEqual(ui.session.snapshot(), before)
                    self.assertFalse(ui.autoplay)
                    self.assertIsNone(ui.notice)
                    self.assertEqual(ui.render().tobytes(), self.normal_frame(ui).tobytes())
        for stage in ('request', 'poll'):
            ui, clock, advisor = self.make_ui(); ui.handle('DOWN')
            setattr(advisor, stage+'_error', RuntimeError('unsupported'))
            before = ui.session.snapshot(); self.press_up(ui); self.tick(ui, clock)
            self.assertEqual(ui.session.snapshot(), before)
            self.assertIsNone(ui.notice)
            self.assertFalse(ui.hint_visible)

    def test_insufficient_credits_pause_auto_without_refilling_or_an_extra_deal(self):
        ui, clock, advisor = self.make_ui(credits=20)
        self.start_auto(ui, clock); self.tick(ui, clock)
        self.assertFalse(ui.autoplay)
        self.assertTrue(ui._credit_notice)
        self.assertEqual(ui.session.phase, 'ready')
        self.assertEqual(ui.session.credits, 20)
        self.tick(ui, clock, 30)
        self.assertEqual(ui.session.credits, 20)
        ui.handle('KEY2')
        self.assertEqual(ui.session.credits, 10020)
        self.assertEqual(ui.session.phase, 'ready')
        self.assertFalse(ui.autoplay)

    def test_entropy_failure_pauses_auto_with_a_manual_retry(self):
        class Blocked:
            def sample(self, population, count): raise RandomNotReady('wait')
        ui, clock, advisor = self.make_ui(rng=Blocked()); before = ui.session.snapshot()
        self.start_auto(ui, clock); self.tick(ui, clock)
        self.assertFalse(ui.autoplay)
        self.assertEqual(ui.session.snapshot(), before)
        self.assertTrue(ui._entropy_notice)
        self.assertEqual(advisor.requests, [])

    def test_consideration_and_result_timers_start_after_full_animation(self):
        ui, clock, advisor = self.make_ui(); ui.speed = 0
        ui.AUTO_PROFILES = PokerUI.AUTO_PROFILES
        self.start_auto(ui, clock); self.tick(ui, clock)
        self.assertIsNotNone(ui._animation)
        self.answer(ui, clock, advisor, 31)
        self.assertIsNone(ui._auto_due)
        self.tick(ui, clock, .66)
        self.assertIsNone(ui._animation)
        due = ui._auto_due
        self.assertEqual(due, clock()+3.2)
        self.tick(ui, clock, 3.19)
        self.assertEqual(ui.session.held, [False]*5)
        self.tick(ui, clock, .02)
        for _ in range(5): self.tick(ui, clock, .66)
        self.tick(ui, clock, 2.01)
        result = ui.session.snapshot()
        self.assertEqual(result['phase'], 'result')
        self.assertIsNotNone(ui._animation)
        self.tick(ui, clock, .2)
        self.assertEqual(ui._auto_stage, 'result-animation')
        self.tick(ui, clock, 2)
        self.assertEqual(ui.session.snapshot(), result)
        self.assertEqual(ui._auto_due, clock()+1.35)
        self.tick(ui, clock, 1.34)
        self.assertEqual(ui.session.snapshot(), result)
        self.tick(ui, clock, .02)
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, result['credits']-result['total_bet'])

    def test_pause_and_close_cleanup_preserve_fail_closed_shutdown(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.start_auto(ui, clock)
        before = ui.session.snapshot(); cancels = advisor.cancels
        self.assertTrue(ui.pause_autoplay()); self.assertFalse(ui.pause_autoplay())
        self.assertEqual(advisor.cancels, cancels+1)
        advisor.close_error = RuntimeError('worker did not stop')
        with self.assertRaisesRegex(RuntimeError, 'worker did not stop'): ui.close()
        self.assertFalse(ui._closed)
        advisor.close_error = None
        ui.close(); ui.close()
        self.assertEqual(advisor.closes, 2)
        self.assertFalse(ui.handle('DOWN'))
        self.assertFalse(ui.update(clock()))
        self.assertFalse(ui.set_pressed_mask(1))
        self.assertEqual(ui.session.snapshot(), before)

    def test_three_separate_sampled_taps_drained_together_cannot_start_auto(self):
        ui, clock, advisor = self.make_ui(); ui.handle('DOWN')
        requests = len(advisor.requests)
        ui.set_pressed_mask(0)
        for captured in (clock()-1.2, clock()-.6, clock()):
            ui.handle_sampled('UP', captured)
        self.assertFalse(ui.autoplay)
        self.assertEqual(len(advisor.requests), requests)
        self.assertFalse(ui.hint_visible)

    def test_real_triple_survives_released_levels_and_delayed_dispatch(self):
        ui, clock, advisor = self.make_ui(); ui.handle('DOWN')
        captured = clock()-.05
        ui.set_pressed_mask(0)
        ui.handle_sampled('UP', captured)
        clock.advance(.65)
        ui.handle_sampled('UP', captured+.20)
        self.assertFalse(ui.autoplay)
        clock.advance(.65)
        ui.handle_sampled('UP', captured+.40)
        self.assertTrue(ui.autoplay)
        self.assertFalse(ui.hint_visible)
        self.assertIsNone(ui._captured_input_at)

    def test_stop_click_before_overdue_draw_only_stops_then_next_down_draws(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.start_auto(ui, clock)
        self.answer(ui, clock, advisor, 0b10101)
        self.finish_selections(ui, clock)
        before = ui.session.snapshot()
        clock.advance(10)
        ui.handle('DOWN'); self.tick(ui, clock)
        self.assertFalse(ui.autoplay)
        self.assertEqual(ui.session.snapshot(), before)
        ui.handle('DOWN')
        self.assertEqual(ui.session.phase, 'result')
        self.assertEqual(ui.session.rounds, before['rounds']+1)

    def test_up_short_tap_keeps_autoplay_without_a_hint_or_an_extra_game_action(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.start_auto(ui, clock)
        requests = len(advisor.requests)
        before = ui.session.snapshot()
        self.press_up(ui); self.tick(ui, clock, .2)
        self.release_up(ui)
        self.assertTrue(ui.autoplay)
        self.assertEqual(ui.autoplay_speed,1)
        self.assertEqual(ui.session.snapshot(),before)
        self.assertFalse(ui.hint_visible)
        self.assertEqual(len(advisor.requests), requests)

    def test_double_taps_cycle_speeds_and_a_single_hold_never_changes_speed(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); self.start_auto(ui, clock)
        for previous, expected in ((1,2),(2,0),(0,1)):
            before=ui.session.snapshot()
            self.double_up(ui,clock)
            self.tick(ui,clock,.34)
            self.assertEqual(ui.autoplay_speed,previous)
            self.assertEqual(ui.session.snapshot(),before)
            self.tick(ui,clock,.04)
            self.assertEqual(ui.autoplay_speed,expected)
            self.assertTrue(ui.autoplay)
            self.press_up(ui)
            for delay in (.64,1.11,10,120):
                self.tick(ui,clock,delay)
                self.assertEqual(ui.autoplay_speed,expected)
                self.assertTrue(ui.autoplay)
                self.assertFalse(ui.hint_visible)
            self.release_up(ui)

    def test_sampled_double_and_triple_taps_survive_delayed_dispatch_without_a_false_speed_change(self):
        for clicks in (2,3):
            with self.subTest(clicks=clicks):
                ui,clock,advisor=self.make_ui()
                ui.handle('DOWN');self.start_auto(ui,clock)
                before=ui.session.snapshot();captured=clock()
                clock.advance(1.0)
                for index in range(clicks):
                    at=captured+.1*index
                    ui.set_pressed_mask_sampled(1,at)
                    ui.handle_sampled('UP',at)
                    ui.set_pressed_mask_sampled(0,at+.02)
                    self.assertEqual(ui.autoplay_speed,1)
                self.tick(ui,clock)
                self.assertEqual(ui.autoplay,clicks==2)
                self.assertEqual(ui.autoplay_speed,2 if clicks==2 else 1)
                self.assertEqual(ui.session.snapshot(),before)
                self.assertFalse(ui.hint_visible)

    def test_speed_change_preserves_the_remaining_phase_fraction_and_does_not_catch_up(self):
        ui,clock,advisor=self.make_ui()
        self.start_auto(ui,clock);self.tick(ui,clock)
        self.answer(ui,clock,advisor,31);self.tick(ui,clock,1.6)
        before=ui.session.snapshot()
        self.double_up(ui,clock);self.tick(ui,clock,10)
        self.assertEqual(ui.autoplay_speed,2)
        self.assertAlmostEqual(ui._auto_due-clock(),.8)
        self.tick(ui,clock,.79)
        self.assertEqual(ui.session.snapshot(),before)
        self.tick(ui,clock,.02)
        self.assertEqual(ui._auto_stage,'select')
        self.assertEqual(ui.session.held,[False]*5)

    def test_other_buttons_stop_auto_and_cancel_a_pending_double_tap(self):
        for action in ('DOWN','CENTER','KEY1','KEY2','KEY3','LEFT','RIGHT'):
            with self.subTest(action=action):
                ui,clock,advisor=self.make_ui()
                ui.handle('DOWN');self.start_auto(ui,clock)
                before=ui.session.snapshot()
                self.double_up(ui,clock);self.tick(ui,clock,.1)
                ui.handle(action)
                self.assertFalse(ui.autoplay)
                self.assertEqual(ui.autoplay_speed,1)
                self.tick(ui,clock,20)
                self.assertEqual(ui.session.snapshot(),before)
                self.assertFalse(ui.hint_visible)

    def test_double_tap_retimes_an_in_progress_animation_without_jumping_cards(self):
        ui,clock,advisor=self.make_ui();ui.AUTO_PROFILES=PokerUI.AUTO_PROFILES
        self.start_auto(ui,clock);self.tick(ui,clock);self.tick(ui,clock,.2)
        before=ui.session.snapshot()
        progress=(clock()-ui._animation['started'])/ui._animation['interval']
        self.double_up(ui,clock);self.finish_up_sequence(ui,clock)
        self.assertEqual(ui.autoplay_speed,2)
        self.assertAlmostEqual(ui._animation['interval'],.04)
        self.assertAlmostEqual((clock()-ui._animation['started'])/ui._animation['interval'],progress)
        self.assertEqual(ui.session.snapshot(),before)
        self.assertTrue(ui.autoplay)

    def test_manual_double_tap_sets_exact_best_holds_without_drawing_or_spending(self):
        ui,clock,advisor=self.make_ui()
        ui.handle('DOWN');ui.handle('CENTER');ui.handle('RIGHT');ui.handle('CENTER')
        before=ui.session.snapshot()
        self.double_up(ui,clock)
        advisor.answers[ui._advisor_token]={'mask':0b10100}
        self.tick(ui,clock,.2)
        self.assertEqual(ui.session.snapshot(),before)
        self.finish_up_sequence(ui,clock)
        after=ui.session.snapshot()
        self.assertEqual(after['held'],[False,False,True,False,True])
        after['held']=before['held']
        self.assertEqual(after,before)
        self.assertFalse(ui.autoplay)
        self.assertFalse(ui.hint_visible)
        self.assertIsNone(ui._manual_hold_key)

    def test_manual_double_tap_waits_for_advice_and_draw_five_clears_all_holds(self):
        ui,clock,advisor=self.make_ui()
        ui.handle('DOWN');ui.handle('CENTER');before=ui.session.snapshot()
        self.double_up(ui,clock);token=ui._advisor_token
        self.finish_up_sequence(ui,clock)
        self.assertEqual(ui.session.snapshot(),before)
        self.assertIsNotNone(ui._manual_hold_key)
        advisor.answers[token]={'mask':0}
        self.tick(ui,clock)
        self.assertEqual(ui.session.held,[False]*5)
        self.assertEqual(ui.session.phase,'hold')
        self.assertEqual(ui.session.credits,before['credits'])
        self.assertFalse(ui.autoplay)

    def test_manual_triple_tap_starts_auto_without_applying_its_double_tap_prefix(self):
        ui,clock,advisor=self.make_ui()
        ui.handle('DOWN');before=ui.session.snapshot()
        self.double_up(ui,clock)
        advisor.answers[ui._advisor_token]={'mask':31}
        self.tick(ui,clock,.1)
        self.assertEqual(ui.session.snapshot(),before)
        self.tap_up(ui)
        self.assertTrue(ui.autoplay)
        self.assertEqual(ui.session.snapshot(),before)
        self.assertIsNone(ui._manual_hold_key)

    def test_manual_input_cancels_a_pending_automatic_hold_and_ignores_a_late_answer(self):
        ui,clock,advisor=self.make_ui()
        ui.handle('DOWN');self.double_up(ui,clock);token=ui._advisor_token
        self.finish_up_sequence(ui,clock)
        ui.handle('RIGHT');before=ui.session.snapshot()
        advisor.answers[token]={'mask':31}
        self.tick(ui,clock,10)
        self.assertEqual(ui.session.snapshot(),before)
        self.assertIsNone(ui._manual_hold_key)
        self.assertNotIn(token,advisor.polls[advisor.polls.index(token)+1:])
        self.assertFalse(ui.autoplay)

    def test_manual_double_tap_during_a_deal_waits_for_full_card_reveal(self):
        ui,clock,advisor=self.make_ui();ui.speed=0
        ui.handle('DOWN');before=ui.session.snapshot()
        self.double_up(ui,clock);self.finish_up_sequence(ui,clock)
        self.assertIsNotNone(ui._animation)
        self.assertEqual(ui.session.snapshot(),before)
        self.tick(ui,clock,.3)
        self.assertIsNone(ui._animation)
        advisor.answers[ui._advisor_token]={'mask':0b01010}
        self.tick(ui,clock)
        self.assertEqual(ui.session.held,[False,True,False,True,False])
        self.assertEqual(ui.session.phase,'hold')
        self.assertEqual(ui.session.credits,before['credits'])

    def test_both_continuous_production_profiles_keep_card_steps_and_paced_results(self):
        for index, expected_round in ((1,6.875),(2,3.67)):
            with self.subTest(speed=index):
                ui, clock, advisor = self.make_ui()
                ui.AUTO_PROFILES = PokerUI.AUTO_PROFILES
                ui.autoplay_speed = index
                self.start_auto(ui, clock)
                started = clock(); dealt_at = None; timings = []; old_holds = [False]*5
                for _ in range(2000):
                    if ui._advisor_token is not None:
                        advisor.answers[ui._advisor_token] = {'mask':31}
                    self.tick(ui, clock, .01)
                    state = ui.session.snapshot()
                    if dealt_at is None and state['phase']=='hold': dealt_at = clock()
                    if state['phase']=='hold' and state['rounds']==0:
                        self.assertLessEqual(sum(a!=b for a,b in zip(old_holds,state['held'])),1)
                        if old_holds != state['held']: timings.append(clock())
                        old_holds = state['held']
                    if state['phase']=='hold' and state['rounds']==1: break
                self.assertIsNotNone(dealt_at)
                self.assertEqual(len(timings),5)
                self.assertGreaterEqual(clock()-dealt_at,expected_round-.02)
                self.assertLess(clock()-dealt_at,expected_round+.2)
                self.assertTrue(ui.autoplay)

    def test_small_a_does_not_cover_cards_speaker_bets_credits_or_buttons(self):
        class House:
            def sample(self, population, count):
                self.asserted_count = count
                return [0, 13, 26, 1, 14]
        ui, clock, advisor = self.make_ui(rng=House())
        ui.session.multipliers = [12]*10
        ui.handle('DOWN')
        for index in range(5): ui.session.toggle_hold(index)
        ui.handle('DOWN')
        self.assertEqual(ui.session.multipliers, [12]*10)
        self.start_auto(ui, clock)
        icon_pixels = []
        left_icons = []
        for speed in (0,1,2):
            ui.autoplay_speed = speed
            frame, normal = ui.render(), self.normal_frame(ui)
            for box in ((0, 0, 320, 197), (227, 199, 247, 219),
                        (181, 210, 215, 219), (262, 197, 320, 219),
                        (0, 218, 320, 240)):
                self.assertEqual(frame.crop(box).tobytes(), normal.crop(box).tobytes(), box)
            icon_pixels.append(list(frame.crop((256,207,262,214)).getdata()).count((255,255,0)))
            left_icons.append(frame.crop((256,208,259,212)).tobytes())
            if speed:
                self.assertGreater(frame.getpixel((257,209))[0],128)
                self.assertGreater(frame.getpixel((257,210))[0],128)
                self.assertNotIn((255,255,0),list(frame.crop((256,207,262,208)).getdata()))
                self.assertNotIn((255,255,0),list(frame.crop((256,212,262,214)).getdata()))
            if speed==1:
                self.assertNotIn((255,255,0),list(frame.crop((259,208,262,212)).getdata()))
        self.assertGreater(icon_pixels[0],0)
        self.assertGreater(icon_pixels[1],0)
        self.assertGreater(icon_pixels[2],icon_pixels[1])
        self.assertEqual(left_icons[1],left_icons[2])
        ui.pause_autoplay()
        self.assertEqual(ui.render().tobytes(),self.normal_frame(ui).tobytes())

    def test_invalid_sampled_times_or_masks_cannot_enable_auto(self):
        ui, clock, advisor = self.make_ui()
        for invalid in (None, True, '100', float('nan'), float('inf')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                ui.handle_sampled('UP', invalid)
        for invalid in (None, True, '1', -1, 256):
            with self.subTest(mask=invalid), self.assertRaises(ValueError): ui.set_pressed_mask(invalid)
        self.assertFalse(ui.autoplay)


if __name__ == '__main__': unittest.main()
