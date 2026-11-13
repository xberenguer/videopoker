"""Unmarked normal mode and the live trainer's nonmodal decision boundaries."""
import copy
from pathlib import Path
import random
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_app import PokerApp
from poker_ui import PokerUI
from poker_engine import Session
from poker_games import GAMES
from poker_training import TrainingState
from poker_training_hud import LAYOUTS


class Clock:
    now=0.
    def __call__(self):return self.now


class HiddenTrainerTests(unittest.TestCase):
    def app(self,game='ddb10',training=False,state=None):
        clock=Clock()
        play=PokerUI(Session(game_id=game,rng=random.Random(8841)),cabinet=True,clock=clock)
        app=PokerApp(play=play,training_state=state or TrainingState(clock=clock),training_mode=training)
        self.addCleanup(app.close)
        return app,clock

    def wait(self,app):
        until=time.monotonic()+8
        while app.trainer._token is not None and time.monotonic()<until:
            app.trainer.update(app.play._clock());time.sleep(.001)
        self.assertIsNotNone(app.trainer.report)

    def test_normal_pixels_and_deals_ignore_saved_training_settings_in_all_twelve_games(self):
        for game in GAMES:
            with self.subTest(game=game.id):
                state=TrainingState()
                state.settings(game.id).update(mode='coach',practice='errors',difficulty='close',dynamic=True)
                app,clock=self.app(game.id,state=state)
                control=PokerUI(Session(game_id=game.id,rng=random.Random(8841)),cabinet=True,clock=clock)
                self.addCleanup(control.close)
                saved=copy.deepcopy(state.data)
                self.assertFalse(app.training_mode)
                self.assertEqual(app.render().tobytes(),control.render().tobytes())
                app.play.menu=control.menu=None
                for phase in ('ready','hold','result'):
                    if phase=='hold':app.play.session.deal();control.session.deal()
                    elif phase=='result':app.play.session.draw();control.session.draw()
                    app.update(clock())
                    self.assertEqual(app.play.session.snapshot(),control.session.snapshot())
                    self.assertEqual(app.render().tobytes(),control.render().tobytes())
                self.assertEqual(state.data,saved)
                self.assertIsNone(app.trainer.advisor)

    def test_regular_top_selects_game_and_long_bottom_does_not_expose_trainer(self):
        app,clock=self.app()
        app.handle('KEY1')
        self.assertIsNone(app.play.menu)
        self.assertFalse(app.training_mode)
        app.set_pressed_mask_sampled(128,0);clock.now=1.2;app.update(clock())
        self.assertFalse(app.trainer.active)
        self.assertEqual(app.render().tobytes(),app.play.render().tobytes())

    def test_hidden_chord_enters_live_game_and_exits_without_changing_hand_or_credits(self):
        app,_=self.app()
        app.play.menu['index']=9
        app.toggle_hidden_mode()
        self.assertTrue(app.training_mode)
        self.assertIsNone(app.trainer.page)
        self.assertIsNone(app.play.menu)
        self.assertEqual(app.play.session.game.id,'ddb10')
        self.assertEqual(app.trainer.settings['mode'],'test')
        app.play.session.deal();self.wait(app)
        snapshot=app.play.session.snapshot();rng=app.play.session._rng.getstate()
        app.toggle_hidden_mode()
        self.assertFalse(app.training_mode)
        self.assertEqual(app.play.session.snapshot(),snapshot)
        self.assertEqual(app.play.session._rng.getstate(),rng)
        self.assertEqual(app.render().tobytes(),app.play.render().tobytes())

    def test_top_cycles_live_panels_without_leaving_the_cards(self):
        app,_=self.app(training=True);app.play.menu=None
        app.play.session.deal();self.wait(app)
        snap=app.play.session.snapshot()
        for expected in (1,2,0):
            app.handle('KEY1')
            self.assertEqual(app.training_hud.tab,expected)
            self.assertIsNone(app.trainer.page)
            self.assertEqual(app.play.session.snapshot(),snap)
            self.assertEqual(app.render().size,(320,240))

    def test_inline_warning_stays_on_live_board_then_second_down_accepts_same_hold(self):
        app,_=self.app(training=True);app.play.menu=None
        app.play.session.deal();self.wait(app)
        bad=min(app.trainer.report['holds'],key=lambda row:row['value'])['mask']
        app.play.session.held=[bool(bad&(1<<i)) for i in range(5)]
        app.play._play()
        self.assertIsNotNone(app.trainer.inline_warning)
        self.assertIsNone(app.trainer.page)
        self.assertEqual(app.play.session.phase,'hold')
        frame=app.render()
        self.assertEqual(frame.crop((0,199,256,240)).tobytes(),app.play.render().crop((0,199,256,240)).tobytes())
        app.play._play()
        self.assertEqual(app.play.session.phase,'result')
        self.assertEqual(app.trainer.state.totals('ddb10')['errors'],1)

    def test_pending_analysis_does_not_open_a_full_screen_page_and_hold_edit_cancels_draw(self):
        app,_=self.app(training=True);app.play.menu=None
        app.play.session.deal();app.play._play()
        self.assertTrue(app.trainer.inline_waiting)
        self.assertIsNone(app.trainer.page)
        app.handle('RIGHT')
        self.assertFalse(app.trainer.pending_draw)
        self.wait(app)
        self.assertEqual(app.play.session.phase,'hold')

    def test_every_live_layout_preserves_original_card_sizes_and_footer(self):
        for game_id in ('ddb3','job5','ddb10'):
            with self.subTest(game=game_id):
                app,_=self.app(game_id,True);app.play.menu=None
                app.trainer.settings['mode']='coach'
                app.play.session.active_multipliers=[12]*app.play.session.game.hands
                frame=app.render()
                self.assertEqual(frame.size,(320,240))
                self.assertEqual(frame.crop((0,199,320,240)).tobytes(),app.play.render().crop((0,199,320,240)).tobytes())
                main=LAYOUTS[app.play.session.game.hands][0]
                self.assertEqual(main[2:],(433,120))
                self.assertEqual(len(LAYOUTS[app.play.session.game.hands]),app.play.session.game.hands)

    def test_test_hides_best_hold_until_submission_and_coach_reveals_it(self):
        app,_=self.app(training=True);app.play.menu=None
        app.play.session.deal();self.wait(app)
        calls=[];r=app.training_hud.renderer(app.play)
        label=r.fitted_label
        def capture(image,box,value,*args,**kwargs):
            if box[0]==260:calls.append(str(value))
            return label(image,box,value,*args,**kwargs)
        r.fitted_label=capture
        app.render()
        self.assertIn('LOSS --',calls)
        calls.clear();app.trainer.settings['mode']='coach';app.render()
        self.assertNotIn('LOSS --',calls)
        self.assertTrue(any(value.startswith('LOSS ') for value in calls))

    def test_calculator_is_inside_hidden_options_and_chord_returns_to_live_trainer(self):
        app,_=self.app(training=True);app.trainer.open();app.trainer.index=5
        app.handle('CENTER')
        self.assertTrue(app.calculator_active)
        app.toggle_hidden_mode()
        self.assertFalse(app.calculator_active)
        self.assertTrue(app.training_mode)
        self.assertFalse(app.trainer.active)
        app.toggle_hidden_mode();self.assertFalse(app.training_mode)

    def test_failed_analysis_stays_inline_and_retries_only_after_another_draw(self):
        class FailedAdvisor:
            requests=0
            def request(self,snapshot):self.requests+=1;return self.requests
            def poll(self,token):return {'error':'fixture unavailable'}
            def cancel(self):pass
            def close(self):pass
        app,_=self.app(training=True);app.play.menu=None
        advisor=FailedAdvisor();app.trainer.advisor=advisor
        app.play.session.deal();app.play._play();app.trainer.update(0)
        self.assertTrue(app.trainer.analysis_failed)
        self.assertFalse(app.trainer.pending_draw)
        self.assertIsNone(app.trainer.page)
        self.assertIsNone(app.trainer.report)
        count=advisor.requests
        for _ in range(3):app.trainer.update(0)
        self.assertEqual(advisor.requests,count)
        app.play._play();self.assertEqual(advisor.requests,count+1)
        self.assertEqual(app.play.session.phase,'hold')
        self.assertEqual(app.trainer.state.totals('ddb10')['decisions'],0)


if __name__=='__main__':unittest.main()
