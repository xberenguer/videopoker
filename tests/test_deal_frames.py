"""Deal-frame equivalence, reduced render work and actual display timing."""
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_app import PokerApp
from poker_engine import Session
from poker_games import GAMES
from poker_ui import PokerUI
from poker_training import TrainingState
from poker_training_hud import TrainingHUD
from poker_calculator import CardCalculator
from poker_training_store import TrainingStore
import test_manual_autoplay as am_fixtures


class Clock:
    now=0.
    def __call__(self):return self.now


class DealFrameTests(unittest.TestCase):
    def ui(self,game='ddb10'):
        clock=Clock();ui=PokerUI(Session(game_id=game,rng=random.Random(8841)),cabinet=True,clock=clock)
        ui.menu=None;self.addCleanup(ui.close);return ui,clock

    def test_incremental_frames_match_full_renderer_in_every_game(self):
        for game in GAMES:
            with self.subTest(game=game.id):
                ui,_=self.ui(game.id);ui.session.deal();snapshot=ui.session.snapshot()
                if game.family=='joker':snapshot['initial']=[52,0,14,38,51]
                for count in (0,1,2,3,4,5,None,2,4,1,5):
                    snap=dict(snapshot)
                    if count is not None:snap['_deal_reveal']=count
                    snap['_badge_frame']=(count or 0)%3
                    actual=ui.renderer.render(snap,0,0)
                    oracle=ui.renderer.render_uncached(snap,0,0)
                    self.assertEqual(actual.tobytes(),oracle.tobytes(),(game.id,count))
                snapshot['held'][1]=True
                self.assertEqual(ui.renderer.render(snapshot).tobytes(),ui.renderer.render_uncached(snapshot).tobytes())

    def test_trainer_incremental_layers_match_fresh_full_layers(self):
        for game in ('ddb3','job5','ddb10','dw5','joker5'):
            with self.subTest(game=game):
                ui,_=self.ui(game);ui.session.deal();snapshot=ui.session.snapshot();hud=TrainingHUD()
                if game=='joker5':snapshot['initial']=[52,0,14,38,51]
                for count in (0,1,2,3,4,5,None,2,5):
                    snap=dict(snapshot)
                    if count is not None:snap['_deal_reveal']=count
                    actual=hud.board(snap,ui.renderer)
                    oracle=TrainingHUD().board(snap,ui.renderer)
                    self.assertEqual(actual.tobytes(),oracle.tobytes(),(game,count))

    def test_a_reveal_does_not_rescale_the_whole_screen(self):
        ui,_=self.ui();ui.session.deal();snapshot=ui.session.snapshot()
        snapshot['_deal_reveal']=1;ui.renderer.render(snapshot)
        sizes=[];resize=Image.Image.resize
        def observe(image,size,*args,**kwargs):
            sizes.append(size);return resize(image,size,*args,**kwargs)
        snapshot['_deal_reveal']=2
        with patch.object(Image.Image,'resize',observe):ui.renderer.render(snapshot)
        self.assertNotIn((320,240),sizes)
        self.assertLess(sum(w*h for w,h in sizes),320*240//4)

    def test_unchanged_trainer_sidebar_is_not_recomposed_for_each_card(self):
        ui,clock=self.ui();app=PokerApp(play=ui,training_state=TrainingState(clock=clock),training_mode=True)
        self.addCleanup(app.close);ui.session.deal()
        with patch.object(app.training_hud,'_draw_sidebar',wraps=app.training_hud._draw_sidebar) as draw:
            for stage in (1,2,3):
                ui._visual=dict(ui.session.snapshot(),_deal_reveal=stage);app.render()
            self.assertEqual(draw.call_count,1)
            ui.session.held[0]=True;ui._visual=None;app.render()
            self.assertEqual(draw.call_count,2)

    def test_first_card_holds_its_full_interval_after_the_LCD_presents_it(self):
        ui,clock=self.ui();ui.on_frame_presented(0)
        ui.handle('DOWN');clock.now=.25;ui.update(clock())
        self.assertEqual(ui._visual['_deal_reveal'],1)
        self.assertEqual(ui.session.credits,9900)
        ui.on_frame_presented(clock())
        clock.now+=.064;ui.update(clock());self.assertEqual(ui._visual['_deal_reveal'],1)
        clock.now+=.002;ui.update(clock());self.assertEqual(ui._visual['_deal_reveal'],2)
        ui.on_frame_presented(clock());self.assertAlmostEqual(ui._animation['started'],.25)

    def test_AM_keeps_its_instant_deal(self):
        ui,clock=self.ui();ui.on_frame_presented(0)
        ui.autoplay=True;ui.autoplay_speed=0;ui._auto_stage='manual-deal'
        ui.handle('DOWN')
        self.assertIsNone(ui._animation)
        self.assertEqual((ui.session.phase,ui.session.credits),('hold',9900))


class CalculatorInlineEVTests(unittest.TestCase):
    def test_ev_is_visible_on_editor_and_invalidated_when_inputs_change(self):
        c=CardCalculator();self.addCleanup(c.close);c.select_game('ddb10')
        for i,card in enumerate((12,4,40,46,5)):c.set_card(i,card)
        c.result={'game_id':'ddb10','mask':19,'value':123.456,'expected_current_win':100.0}
        labels=[];original=c.renderer.fitted_label
        def observe(image,box,label,*args,**kwargs):labels.append(str(label));return original(image,box,label,*args,**kwargs)
        with patch.object(c.renderer,'fitted_label',observe):frame=c.render()
        self.assertEqual(frame.size,(320,240))
        for text in ('EV 123.456 cr','NOW 100.000','NEXT 23.456'):self.assertIn(text,labels)
        self.assertEqual(c.ev_values(),(123.456,100.0,23.456000000000003))
        c.set_multiplier(0,12);self.assertIsNone(c.ev_values())

    def test_current_hand_only_shows_zero_future_and_nonfinite_data_is_hidden(self):
        c=CardCalculator();self.addCleanup(c.close)
        c.result={'value':42.5,'expected_current_win':42.5}
        self.assertEqual(c.ev_values(),(42.5,42.5,0.))
        c.result['value']=float('nan');self.assertIsNone(c.ev_values())

    def test_visible_compare_button_opens_full_calculator_rankings_without_a_previous_solve(self):
        import time
        app=PokerApp(training_state=TrainingState());self.addCleanup(app.close)
        app.toggle_calculator();c=app.calculator;c.select_game('ddb10')
        for i,card in enumerate((12,4,40,46,5)):c.set_card(i,card)
        c.focus=7;c.handle('RIGHT');self.assertEqual(c.focus,8)
        app.handle('KEY2');self.assertEqual(app.trainer.page,'ev')
        deadline=time.monotonic()+10
        while app.trainer.report is None and time.monotonic()<deadline:
            app.trainer.update(app.play._clock());time.sleep(.001)
        self.assertIsNotNone(app.trainer.report);self.assertEqual(len(app.trainer.report['holds']),32)
        self.assertIsNotNone(c.ev_values())
        app.handle('KEY3')
        self.assertTrue(app.calculator_active);self.assertFalse(app.trainer.active)
        self.assertEqual(c.page,'editor');self.assertIsNotNone(c.result)

    def test_compare_requires_five_cards_and_does_not_trigger_pays_or_clear(self):
        c=CardCalculator();self.addCleanup(c.close);c.select_game('ddb10');c.focus=8;c.handle('KEY2')
        self.assertFalse(c.compare_ev_requested);self.assertIn('five',c.status)
        c.handle('RIGHT');self.assertEqual(c.focus,9);c.handle('KEY2');self.assertEqual(c.page,'pays')
        c.handle('KEY3');c.handle('RIGHT');self.assertEqual(c.focus,10)


class AMPeekTests(unittest.TestCase):
    make_ui=am_fixtures.ManualAutoplayTests.make_ui
    tap=am_fixtures.ManualAutoplayTests.tap
    start=am_fixtures.ManualAutoplayTests.start
    answer=am_fixtures.ManualAutoplayTests.answer
    def test_held_up_peeks_in_AM_without_selecting_cards_drawing_or_changing_mode(self):
        ui,clock,advisor=self.make_ui();self.addCleanup(ui.close)
        self.start(ui,clock);ui.handle('DOWN');self.answer(ui,clock,advisor,0b10101)
        before=ui.session.snapshot()
        ui.set_pressed_mask(1);ui.handle('UP');clock.advance(.31)
        self.assertTrue(ui.update(clock()));self.assertTrue(ui.hint_visible)
        self.assertTrue(ui.manual_autoplay);self.assertEqual(ui.session.snapshot(),before)
        ui.render();ui.set_pressed_mask(0);self.assertFalse(ui.hint_visible)
        clock.advance(.2);ui.update(clock());self.assertTrue(ui.manual_autoplay)
        self.assertEqual(ui.session.snapshot(),before)

    def test_AM_double_and_triple_up_have_no_peek_and_keep_their_existing_actions(self):
        for clicks in (2,3):
            ui,clock,advisor=self.make_ui();self.addCleanup(ui.close)
            self.start(ui,clock);ui.handle('DOWN');self.answer(ui,clock,advisor,7)
            for _ in range(clicks):
                self.tap(ui,clock);ui.update(clock());self.assertFalse(ui.hint_visible)
            clock.advance(.4);ui.update(clock());self.assertFalse(ui.hint_visible)
            if clicks==2:self.assertTrue(ui.autoplay);self.assertEqual(ui.autoplay_speed,1)
            else:self.assertFalse(ui.autoplay)


class RAMOnlyTests(unittest.TestCase):
    def test_default_OFF_without_a_matching_journal_never_opens_or_writes_SD(self):
        with (patch('poker_training_store.hardware_journal',return_value=None),
              patch('poker_training_store.os.open',side_effect=AssertionError('SD open')),
              patch('poker_training_store.sys.platform','linux'),
              patch('poker_training_store.os.geteuid',return_value=0)):
            store=TrainingStore.hardware();state=TrainingState(store)
            self.assertIsNone(store.journal);self.assertIsNone(store._thread)
            state.settings('ddb10')['mode']='coach';state.begin('ddb10')
            state.totals('ddb10')['auto_correct']=7;state.save()
            self.assertEqual(store.status,'RAM only');store.close()
            fresh=TrainingState(TrainingStore.hardware())
            self.assertEqual(fresh.data['sessions'],[]);self.assertEqual(fresh.data['settings'],{})
            self.assertEqual(fresh.data['totals'],{});fresh.store.close()

    def test_cold_boot_selection_is_constant_and_does_not_restore_game_history(self):
        for _ in range(2):
            app=PokerApp();self.addCleanup(app.close)
            self.assertEqual(app.play.menu['index'],0)
            self.assertEqual(GAMES[app.play.menu['index']].id,'bp3')
            app.handle('KEY2')
            self.assertEqual(app.play.session.game.id,'bp3')
            self.assertEqual(app.trainer.state.data['sessions'],[])
            self.assertEqual(app.trainer.state.store.status,'RAM only')


if __name__=='__main__':unittest.main()
