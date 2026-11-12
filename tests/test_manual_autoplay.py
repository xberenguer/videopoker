"""Production M/Medium/Fast controls and explicit Deal/Draw click boundaries."""
from pathlib import Path
import random
import sys
import unittest
from PIL import ImageChops

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_engine import Session
from poker_ui import PokerUI
from test_autoplay_ui import Clock,Advisor


class ManualAutoplayTests(unittest.TestCase):
    def make_ui(self,credits=10000):
        clock=Clock();advisor=Advisor()
        ui=PokerUI(Session(credits=credits,rng=random.Random(250)),clock=clock,advisor=advisor)
        return ui,clock,advisor

    def tap(self,ui,clock):
        ui.set_pressed_mask(1);ui.handle('UP');ui.set_pressed_mask(0);clock.advance(.1)

    def start(self,ui,clock):
        for _ in range(3):self.tap(ui,clock)
        ui.update(clock())
        self.assertTrue(ui.autoplay)

    def next_mode(self,ui,clock):
        for _ in range(2):self.tap(ui,clock)
        clock.advance(.38);ui.update(clock())

    def answer(self,ui,clock,advisor,mask):
        advisor.answers[ui._advisor_token]={'mask':mask}
        ui.update(clock())

    def test_default_is_manual_and_only_manual_medium_fast_exist(self):
        ui,clock,advisor=self.make_ui()
        self.assertEqual([p['name'] for p in ui.AUTO_PROFILES],['manual','medium','fast'])
        self.assertEqual(ui.autoplay_speed,0)
        for key in ('consider','select','draw','result','animation'):
            self.assertEqual(ui.AUTO_PROFILES[0][key],ui.AUTO_PROFILES[2][key])
        before=ui.session.snapshot();self.start(ui,clock)
        self.assertTrue(ui.manual_autoplay);self.assertEqual(ui._auto_stage,'manual-deal')
        clock.advance(1000);ui.update(clock())
        self.assertEqual(ui.session.snapshot(),before);self.assertEqual(advisor.requests,[])

    def test_each_round_waits_at_both_deal_and_draw_until_a_fresh_down(self):
        ui,clock,advisor=self.make_ui();self.start(ui,clock)
        for round_number in (1,2):
            previous=ui.session.snapshot();ui.handle('DOWN')
            self.assertTrue(ui.manual_autoplay);self.assertEqual(ui.session.phase,'hold')
            self.assertEqual(ui._auto_stage,'manual-draw');self.assertIsNone(ui._animation)
            self.assertEqual(ui.session.credits,previous['credits']-previous['total_bet'])
            self.assertEqual(ui.session.active_multipliers,previous['multipliers'])
            mask=7 if round_number==1 else 0
            self.answer(ui,clock,advisor,mask)
            dealt=ui.session.snapshot();self.assertEqual(dealt['held'],[False]*5)
            clock.advance(1000);ui.update(clock())
            self.assertEqual(ui.session.snapshot(),dealt)
            pressed_at=clock();ui.handle('DOWN')
            self.assertEqual(clock(),pressed_at)
            self.assertTrue(ui.manual_autoplay);self.assertIsNone(ui._animation)
            self.assertEqual(ui.session.phase,'result');self.assertEqual(ui.session.rounds,round_number)
            self.assertEqual(ui.session.held,[bool(mask&(1<<i)) for i in range(5)])
            self.assertEqual(ui._auto_stage,'manual-deal');self.assertIsNone(ui._auto_due)
            result=ui.session.snapshot();clock.advance(1000);ui.update(clock())
            self.assertEqual(ui.session.snapshot(),result)

    def test_cold_advice_queues_one_draw_and_never_an_extra_deal(self):
        ui,clock,advisor=self.make_ui();self.start(ui,clock);ui.handle('DOWN')
        before=ui.session.snapshot();token=ui._advisor_token
        for _ in range(4):ui.handle('DOWN')
        self.assertTrue(ui._manual_auto_draw_requested)
        self.assertEqual(ui.session.snapshot(),before);self.assertEqual(len(advisor.requests),1)
        advisor.answers[token]={'mask':0b10101};ui.update(clock())
        self.assertEqual(ui.session.phase,'result');self.assertEqual(ui.session.rounds,1)
        self.assertFalse(ui._manual_auto_draw_requested)
        self.assertEqual(ui.session.held,[True,False,True,False,True])
        result=ui.session.snapshot();clock.advance(1000);ui.update(clock())
        self.assertEqual(ui.session.snapshot(),result)

    def test_other_key_cancels_a_pending_draw_and_late_advice(self):
        for action in ('CENTER','KEY1','KEY2','KEY3','LEFT','RIGHT'):
            ui,clock,advisor=self.make_ui();self.start(ui,clock);ui.handle('DOWN');ui.handle('DOWN')
            token=ui._advisor_token;before=ui.session.snapshot()
            ui.handle(action)
            self.assertFalse(ui.autoplay);self.assertFalse(ui._manual_auto_draw_requested)
            advisor.answers[token]={'mask':31};clock.advance(1000);ui.update(clock())
            self.assertEqual(ui.session.snapshot(),before)

    def test_mode_cycle_is_manual_medium_fast_and_back_to_manual(self):
        ui,clock,advisor=self.make_ui();self.start(ui,clock)
        self.next_mode(ui,clock)
        self.assertEqual(ui.autoplay_speed,1);self.assertEqual(ui.session.phase,'hold')
        before=ui.session.snapshot();self.next_mode(ui,clock)
        self.assertEqual(ui.autoplay_speed,2);self.assertEqual(ui.session.snapshot(),before)
        self.next_mode(ui,clock)
        self.assertEqual(ui.autoplay_speed,0);self.assertTrue(ui.manual_autoplay)
        self.assertEqual(ui._auto_stage,'manual-draw');self.assertIsNone(ui._animation)
        self.assertEqual(ui.session.snapshot(),before)
        clock.advance(1000);ui.update(clock())
        self.assertEqual(ui.session.snapshot(),before)

    def test_triple_toggle_preserves_cards_and_returns_to_manual_draw_wait(self):
        ui,clock,advisor=self.make_ui();self.start(ui,clock);ui.handle('DOWN')
        before=ui.session.snapshot()
        for _ in range(3):self.tap(ui,clock)
        self.assertFalse(ui.autoplay)
        for _ in range(3):self.tap(ui,clock)
        ui.update(clock());self.assertTrue(ui.manual_autoplay)
        self.assertEqual(ui._auto_stage,'manual-draw')
        self.assertEqual(ui.session.snapshot(),before)

    def test_insufficient_credit_cannot_spend_or_refill_while_waiting(self):
        ui,clock,advisor=self.make_ui(20);self.start(ui,clock)
        clock.advance(1000);ui.update(clock())
        self.assertTrue(ui.manual_autoplay);self.assertEqual(ui.session.credits,20)
        ui.handle('DOWN');self.assertFalse(ui.autoplay)
        self.assertTrue(ui._credit_notice);self.assertEqual(ui.session.credits,20)

    def test_tiny_m_is_five_by_four_filled_pixels_and_changes_no_other_ui(self):
        ui,clock,advisor=self.make_ui();self.start(ui,clock)
        state=ui.session.snapshot();state.update(_speed=2,_button_focus=None,_badge_frame=ui._badge_frame)
        normal=ui.renderer.render(state);frame=ui.render()
        bounds=ImageChops.difference(frame,normal).getbbox()
        self.assertIsNotNone(bounds)
        self.assertGreaterEqual(bounds[0],246);self.assertGreaterEqual(bounds[1],205)
        self.assertLessEqual(bounds[2],262);self.assertLessEqual(bounds[3],217)
        for y,pattern in enumerate((0b10001,0b11011,0b10101,0b10001)):
            for x in range(5):
                self.assertEqual(frame.getpixel((256+x,208+y))==(255,255,0),bool(pattern&(1<<(4-x))))
        frame.paste(normal.crop((246,205,262,217)),(246,205))
        self.assertEqual(frame.tobytes(),normal.tobytes())

    def test_switching_to_manual_from_an_animation_stops_before_next_action(self):
        ui,clock,advisor=self.make_ui()
        self.start(ui,clock);self.next_mode(ui,clock);self.next_mode(ui,clock)
        self.assertIsNotNone(ui._animation)
        before=ui.session.snapshot();self.next_mode(ui,clock)
        self.assertTrue(ui.manual_autoplay);self.assertEqual(ui.autoplay_speed,0)
        self.assertEqual(ui.session.snapshot(),before);self.assertIsNone(ui._animation)
        self.assertEqual(ui._auto_stage,'manual-draw')


if __name__=='__main__':unittest.main()
