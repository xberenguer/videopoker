"""Cold-start M keeps its mode across safe input recovery and RNG waits."""
import random
import unittest
from unittest.mock import patch

from test_autoplay_ui import Clock, Advisor
from poker_engine import RandomNotReady, Session
from poker_ui import PokerUI
import launcher


class ManualBootTests(unittest.TestCase):
    def make_ui(self):
        clock, advisor = Clock(), Advisor()
        return PokerUI(Session(rng=random.Random(250)), clock=clock, advisor=advisor), clock, advisor

    def activate(self, ui, clock):
        for _ in range(3):
            ui.set_pressed_mask(1); ui.handle('UP'); ui.set_pressed_mask(0)
            clock.advance(.1)
        self.assertTrue(ui.manual_autoplay)
        self.assertEqual(ui.autoplay_speed, 0)

    def change_mode(self, ui, clock):
        for _ in range(2):
            ui.set_pressed_mask(1);ui.handle('UP');ui.set_pressed_mask(0);clock.advance(.1)
        clock.advance(ui.UP_CLICK_GAP_SECONDS+ui.UP_TAP_COMMIT_GRACE_SECONDS+.01)
        ui.update(clock())

    def test_first_double_up_uses_one_cold_request_across_both_releases(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); before = ui.session.snapshot()
        token = ui._advisor_token
        self.assertIsNotNone(token)  # Ready before the very first UP.
        for _ in range(2):
            ui.set_pressed_mask(1); ui.handle('UP'); ui.set_pressed_mask(0)
            clock.advance(.08); ui.update(clock())
            self.assertEqual(ui._advisor_token, token)
        clock.advance(.5); ui.update(clock())
        self.assertEqual(ui.session.snapshot(), before)
        self.assertIsNotNone(ui._manual_hold_key)
        advisor.answers[token] = {'mask':0b10101}; ui.update(clock())
        self.assertEqual(ui.session.held, [True,False,True,False,True])
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, before['credits'])
        self.assertEqual(len(advisor.requests), 1)
        self.assertFalse(ui.hint_visible)
        self.assertFalse(ui.autoplay)

    def test_first_held_hint_uses_prepared_answer_and_release_only_hides_it(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); before = ui.session.snapshot()
        token = ui._advisor_token
        advisor.answers[token] = {'mask':0b01010}
        ui.set_pressed_mask(1); ui.handle('UP')
        clock.advance(.8); ui.update(clock())
        self.assertTrue(ui.hint_visible)
        self.assertEqual(ui._advice['mask'], 0b01010)
        self.assertEqual(ui.session.snapshot(), before)
        self.assertTrue(ui.set_pressed_mask(0))
        self.assertFalse(ui.hint_visible)
        self.assertEqual(advisor.cancels, 0)
        clock.advance(.5); ui.update(clock())
        self.assertEqual(ui.session.snapshot(), before)

    def test_cold_read_only_advice_survives_input_reset_without_replaying_a_gesture(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); before = ui.session.snapshot(); token = ui._advisor_token
        ui.set_pressed_mask(1); ui.handle('UP'); ui.on_input_reset()
        ui.set_pressed_mask_sampled(0, clock())
        advisor.answers[token] = {'mask':7}
        clock.advance(1); ui.update(clock())
        self.assertEqual(ui.session.snapshot(), before)
        self.assertFalse(ui.hint_visible)
        self.assertEqual(advisor.cancels, 0)
        for _ in range(2):
            ui.set_pressed_mask(1); ui.handle('UP'); ui.set_pressed_mask(0)
            clock.advance(.08); ui.update(clock())
        clock.advance(.5); ui.update(clock())
        self.assertEqual(ui.session.held, [True,True,True,False,False])
        self.assertEqual(len(advisor.requests), 1)
        self.assertEqual(ui.session.credits, before['credits'])

    def test_release_of_a_long_second_tap_requests_redraw_while_double_is_pending(self):
        ui, clock, advisor = self.make_ui(); ui.speed = 2
        ui.handle('DOWN'); before = ui.session.snapshot()
        advisor.answers[ui._advisor_token] = {'mask':7}; ui.update(clock())
        ui.set_pressed_mask(1); ui.handle('UP'); ui.set_pressed_mask(0)
        clock.advance(.08)
        ui.set_pressed_mask(1); ui.handle('UP')
        clock.advance(ui.HINT_HOLD_SECONDS+.001); ui.update(clock())
        self.assertTrue(ui.hint_visible)
        self.assertTrue(ui._wants_manual_advice())
        self.assertEqual(ui.session.snapshot(), before)
        self.assertTrue(ui.set_pressed_mask(0))
        self.assertFalse(ui.hint_visible)
        self.assertEqual(ui.session.snapshot(), before)

    def test_late_preload_cannot_hold_or_draw_a_replaced_board(self):
        ui, clock, advisor = self.make_ui()
        ui.handle('DOWN'); token = ui._advisor_token
        ui.handle('DOWN'); ui.handle('DOWN'); ui.handle('DOWN')
        before = ui.session.snapshot()
        advisor.answers[token] = {'mask':31}
        clock.advance(10); ui.update(clock())
        self.assertEqual(ui.session.snapshot(), before)
        self.assertFalse(ui.hint_visible)
        self.assertFalse(ui.autoplay)

    def test_user_cold_boot_medium_single_up_and_sampling_reset_keep_autoplay(self):
        ui,clock,advisor=self.make_ui();self.activate(ui,clock)
        self.change_mode(ui,clock)
        self.assertEqual(ui.autoplay_speed,1);self.assertEqual(ui.session.phase,'hold')
        for speed in (1,2):
            self.assertEqual(ui.autoplay_speed,speed)
            before=ui.session.snapshot();token=ui._advisor_token
            ui.set_pressed_mask(1);ui.handle('UP')
            ui.on_input_reset();ui.set_pressed_mask_sampled(0,clock())
            self.assertTrue(ui.autoplay);self.assertEqual(ui.autoplay_speed,speed)
            self.assertEqual(ui.session.snapshot(),before)
            self.assertEqual(ui._advisor_token,token)
            self.change_mode(ui,clock)
        self.assertTrue(ui.manual_autoplay)
        advisor.answers[ui._advisor_token]={'mask':7};ui.update(clock())
        ui.handle('DOWN')
        self.assertTrue(ui.manual_autoplay);self.assertEqual(ui.session.phase,'result')
        ui.handle('DOWN')
        self.assertTrue(ui.manual_autoplay);self.assertEqual(ui.session.phase,'hold')

    def test_single_held_up_keeps_each_mode_and_triple_stops_without_changing_speed(self):
        for speed in (0,1,2):
            ui,clock,advisor=self.make_ui();self.activate(ui,clock)
            for _ in range(speed):self.change_mode(ui,clock)
            ui.set_pressed_mask(1);ui.handle('UP');clock.advance(2);ui.update(clock())
            ui.set_pressed_mask(0)
            self.assertTrue(ui.autoplay);self.assertEqual(ui.autoplay_speed,speed)
            self.assertFalse(ui.hint_visible)
            before=ui.session.snapshot()
            for index in range(3):
                ui.set_pressed_mask(1);ui.handle('UP');ui.set_pressed_mask(0);clock.advance(.1)
                self.assertEqual(ui.autoplay,index<2)
                self.assertEqual(ui.autoplay_speed,speed)
            self.assertEqual(ui.session.snapshot(),before)
            clock.advance(100);ui.update(clock())
            self.assertEqual(ui.session.snapshot(),before)
            self.activate(ui,clock)
            self.assertTrue(ui.manual_autoplay)

    def test_triple_off_cancels_queued_draw_and_late_advice(self):
        ui,clock,advisor=self.make_ui();self.activate(ui,clock)
        ui.handle('DOWN');ui.handle('DOWN')
        token=ui._advisor_token;before=ui.session.snapshot()
        self.assertTrue(ui._manual_auto_draw_requested)
        for _ in range(3):
            ui.set_pressed_mask(1);ui.handle('UP');ui.set_pressed_mask(0);clock.advance(.1)
        self.assertFalse(ui.autoplay);self.assertFalse(ui._manual_auto_draw_requested)
        advisor.answers[token]={'mask':31};clock.advance(100);ui.update(clock())
        self.assertEqual(ui.session.snapshot(),before)
        self.assertIsNone(ui._advisor_token)

    def test_continuous_sampling_reset_preserves_timer_solver_and_card_selection(self):
        ui,clock,advisor=self.make_ui();self.activate(ui,clock);self.change_mode(ui,clock)
        ui._finish_animation()
        advisor.answers[ui._advisor_token]={'mask':31};ui.update(clock())
        clock.advance(ui.AUTO_CONSIDER_SECONDS+.01);ui.update(clock())
        self.assertEqual(ui._auto_stage,'select')
        clock.advance(ui.AUTO_SELECT_SECONDS+.01);ui.update(clock())
        before=ui.session.snapshot();progress=(ui._auto_stage,ui._auto_due,ui._auto_index,ui._advice)
        ui.on_input_reset()
        self.assertTrue(ui.autoplay);self.assertEqual(ui.autoplay_speed,1)
        self.assertEqual(ui.session.snapshot(),before)
        self.assertEqual((ui._auto_stage,ui._auto_due,ui._auto_index,ui._advice),progress)

    def test_every_activation_starts_in_m_after_each_previous_mode_and_phase(self):
        for speed in (0, 1, 2):
            for phase in ('ready', 'hold', 'result'):
                with self.subTest(speed=speed, phase=phase):
                    ui, clock, _ = self.make_ui()
                    if phase != 'ready': ui.session.deal()
                    if phase == 'result': ui.session.draw()
                    ui.autoplay_speed = speed
                    before = ui.session.snapshot()
                    self.activate(ui, clock)
                    ui.update(clock())
                    self.assertEqual(ui.session.snapshot(), before)
                    self.assertEqual(ui._auto_stage, 'manual-draw' if phase == 'hold' else 'manual-deal')

    def test_first_deal_then_input_reset_stays_m_without_replaying_down(self):
        ui, clock, advisor = self.make_ui(); self.activate(ui, clock)
        self.assertEqual(ui.session.phase, 'ready')
        ui.handle('DOWN'); self.assertEqual(ui.session.phase, 'hold')
        token = ui._advisor_token; dealt = ui.session.snapshot()
        ui.on_input_reset(); ui.set_pressed_mask_sampled(0, clock())
        self.assertTrue(ui.manual_autoplay)
        advisor.answers[token] = {'mask':31}
        for _ in range(5): clock.advance(10); ui.update(clock())
        self.assertEqual(ui.session.snapshot(), dealt)
        self.assertNotEqual(ui._advisor_token, token)
        advisor.answers[ui._advisor_token] = {'mask':0}; ui.update(clock())
        ui.handle('DOWN')
        self.assertTrue(ui.manual_autoplay); self.assertEqual(ui.session.phase, 'result')
        self.assertEqual(ui.session.rounds, 1)

    def test_reset_cancels_queued_draw_and_requires_a_fresh_down(self):
        ui, clock, advisor = self.make_ui(); self.activate(ui, clock)
        ui.handle('DOWN'); ui.handle('DOWN'); token = ui._advisor_token
        self.assertTrue(ui._manual_auto_draw_requested)
        before = ui.session.snapshot(); ui.on_input_reset(); ui.update(clock())
        self.assertFalse(ui._manual_auto_draw_requested)
        advisor.answers[token] = {'mask':31}
        advisor.answers[ui._advisor_token] = {'mask':7}; ui.update(clock())
        self.assertEqual(ui.session.snapshot(), before)
        ui.handle('DOWN')
        self.assertTrue(ui.manual_autoplay); self.assertEqual(ui.session.rounds, 1)
        result = ui.session.snapshot(); ui.on_input_reset()
        clock.advance(100); ui.update(clock())
        self.assertEqual(ui.session.snapshot(), result); self.assertTrue(ui.manual_autoplay)

    def test_continuous_modes_survive_resets_but_signer_chord_pause_still_stops(self):
        for speed in (1, 2):
            ui, clock, _ = self.make_ui(); self.activate(ui, clock)
            ui.autoplay_speed = speed; ui.on_input_reset()
            self.assertTrue(ui.autoplay); self.assertEqual(ui.autoplay_speed,speed)
        ui, clock, _ = self.make_ui(); self.activate(ui, clock)
        ui.pause_autoplay(); ui.on_input_reset()
        self.assertFalse(ui.autoplay)

    def test_entropy_wait_retries_one_deal_and_keeps_m(self):
        ui, clock, _ = self.make_ui(); self.activate(ui, clock)
        before = ui.session.snapshot(); sample = ui.session._sample
        with patch.object(ui.session, '_sample', side_effect=RandomNotReady('wait')):
            ui.handle('DOWN')
            self.assertTrue(ui.manual_autoplay); self.assertEqual(ui._manual_retry_action, 'deal')
            for _ in range(4): ui.handle('DOWN')
            clock.advance(.2); ui.update(clock())
            self.assertEqual(ui.session.snapshot(), before)
        clock.advance(.2); ui.update(clock())
        self.assertTrue(ui.manual_autoplay); self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, before['credits']-before['total_bet'])
        self.assertIsNone(ui._manual_retry_action); self.assertIsNone(ui.notice)
        dealt = ui.session.snapshot(); clock.advance(100); ui.update(clock())
        self.assertEqual(ui.session.snapshot(), dealt)

    def test_entropy_wait_retries_one_draw_without_an_extra_deal(self):
        ui, clock, advisor = self.make_ui(); self.activate(ui, clock); ui.handle('DOWN')
        advisor.answers[ui._advisor_token] = {'mask':7}; ui.update(clock())
        credits = ui.session.credits
        with patch.object(ui.session, '_sample', side_effect=RandomNotReady('wait')):
            ui.handle('DOWN')
            self.assertTrue(ui.manual_autoplay); self.assertEqual(ui._manual_retry_action, 'draw')
            self.assertEqual(ui.session.rounds, 0); self.assertEqual(ui.session.credits, credits)
            for _ in range(4): ui.handle('DOWN')
        clock.advance(.2); ui.update(clock())
        self.assertTrue(ui.manual_autoplay); self.assertEqual(ui.session.rounds, 1)
        self.assertEqual(ui.session.held, [True,True,True,False,False])
        result = ui.session.snapshot(); clock.advance(100); ui.update(clock())
        self.assertEqual(ui.session.snapshot(), result)

    def test_cancel_or_input_reset_cannot_replay_a_waiting_random_operation(self):
        for cancel in ('LEFT', 'CENTER', 'reset'):
            ui, clock, _ = self.make_ui(); self.activate(ui, clock)
            with patch.object(ui.session, '_sample', side_effect=RandomNotReady('wait')):
                ui.handle('DOWN')
            before = ui.session.snapshot()
            if cancel == 'reset': ui.on_input_reset()
            else: ui.handle(cancel)
            clock.advance(100); ui.update(clock())
            self.assertIsNone(ui._manual_retry_action); self.assertIsNone(ui.notice)
            self.assertEqual(ui.session.snapshot(), before)
            self.assertEqual(ui.autoplay, cancel == 'reset')

    def test_launcher_dispatches_reset_to_m_handler_after_first_deal(self):
        ui, clock, advisor = self.make_ui()
        class ReadyAdvisor(Advisor):
            def poll(self, token): return {'mask':0}
        ui._advisor = ReadyAdvisor()
        frames = []
        schedule = [(100.2,'action','UP'),(100.32,'action','UP'),(100.44,'action','UP'),
                    (100.65,'action','DOWN'),(100.70,'reset',0),
                    (100.95,'action','DOWN'),(101.02,'reset',0),
                    (101.25,'action','DOWN')]
        class Inputs:
            gesture_pending = False
            def __init__(self,*args,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def reset(self): pass
            def read_events(self):
                events=[]
                while schedule and schedule[0][0] <= clock(): events.append(schedule.pop(0))
                return clock() >= 101.60, tuple(events)
        class Hardware:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def present(self,frame): frames.append((ui.session.snapshot(),ui.manual_autoplay))
            def show_message(self,*args): raise AssertionError(args)
        launcher.main(hardware_factory=Hardware,ui_factory=lambda:ui,clock=clock,
                      sleep=clock.advance,input_factory=Inputs,signer_runner=lambda argv:None)
        played = [(state,mode) for state,mode in frames if state['phase']!='ready']
        self.assertTrue(played); self.assertTrue(all(mode for state,mode in played))
        self.assertEqual(ui.session.rounds,1); self.assertEqual(ui.session.phase,'hold')
        self.assertTrue(any(state['phase']=='result' for state,mode in played))


if __name__ == '__main__': unittest.main()
