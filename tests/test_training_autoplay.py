"""Actual autoplay decisions, async grading and separation from player accuracy."""
import copy
from pathlib import Path
import random
import sys
import time
import unittest
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_app import PokerApp
from poker_engine import Session
from poker_ui import PokerUI
from poker_training import TrainingState,DetailedTable,AutoGradeQueue,autoplay_stats
from poker_cabinet_strategy import freeze_round
from poker_games import GAMES


class Clock:
    now=0.
    def __call__(self):return self.now


class AutoplayTrainingTests(unittest.TestCase):
    def app(self,game='ddb10'):
        clock=Clock();ui=PokerUI(Session(game_id=game,rng=random.Random(8841)),cabinet=True,clock=clock)
        app=PokerApp(play=ui,training_state=TrainingState(clock=clock),training_mode=True)
        ui.menu=None;self.addCleanup(app.close);return app,clock

    def report(self,app):
        app.play.session.deal();deadline=time.monotonic()+10
        while app.trainer.report is None and time.monotonic()<deadline:
            app.trainer.update(app.play._clock());time.sleep(.001)
        self.assertIsNotNone(app.trainer.report);return app.trainer.report

    @staticmethod
    def choose(app,mask):app.play.session.held=[bool(mask&(1<<i)) for i in range(5)]

    def test_automatic_good_and_bad_holds_are_graded_from_actual_mask(self):
        for correct in (True,False):
            app,_=self.app();report=self.report(app)
            mask=report['mask'] if correct else min(report['holds'],key=lambda row:row['value'])['mask']
            self.choose(app,mask);app.play.autoplay=True;result=app.play.session.draw()
            stats=app.trainer.state.totals('ddb10')
            self.assertEqual((stats['auto_decisions'],stats['auto_checked']),(1,1))
            self.assertEqual((stats['auto_correct'],stats['auto_errors']),(int(correct),int(not correct)))
            self.assertAlmostEqual(stats['auto_ev_lost'],0 if correct else report['value']-report['holds'][mask]['value'])
            self.assertEqual((stats['decisions'],stats['assisted']),(0,1))
            self.assertEqual((stats['auto_wagered'],stats['auto_returned'],stats['auto_hands']),(100,result['total_win'],10))

    def test_manual_error_then_auto_correction_records_each_decision_separately(self):
        app,_=self.app();report=self.report(app)
        self.choose(app,min(report['holds'],key=lambda row:row['value'])['mask']);app.play._play()
        self.assertIsNotNone(app.trainer.attempt)
        app.play.autoplay=True;self.choose(app,report['mask']);app.play.session.draw()
        stats=app.trainer.state.totals('ddb10')
        self.assertEqual((stats['decisions'],stats['errors'],stats['corrected']),(1,1,1))
        self.assertEqual((stats['auto_checked'],stats['auto_correct'],stats['auto_errors']),(1,1,0))

    def test_real_M_medium_and_fast_loops_record_two_cycles_without_pausing(self):
        for speed in (0,1,2):
            with self.subTest(speed=speed):self.run_auto('ddb10',speed,2)

    def test_all_twelve_games_record_actual_fast_autoplay(self):
        for game in GAMES:
            with self.subTest(game=game.id):self.run_auto(game.id,2,1)

    def run_auto(self,game,speed,rounds):
        app,clock=self.app(game);ui=app.play
        ui.autoplay=True;ui.autoplay_speed=speed
        ui._auto_stage='manual-deal' if speed==0 else 'deal';ui._auto_due=0.
        deadline=time.monotonic()+15;last_manual=None
        while ui.session.rounds<rounds and time.monotonic()<deadline:
            if speed==0:
                key=(ui.session.rounds,ui.session.phase)
                if key!=last_manual:
                    app.handle('DOWN');last_manual=key
            clock.now+=.06;app.update(clock());time.sleep(.001)
            self.assertTrue(ui.autoplay,ui.notice)
        self.assertEqual(ui.session.rounds,rounds)
        ui.pause_autoplay()
        deadline=time.monotonic()+10
        while app.trainer.state.totals(game)['auto_checked']<rounds and time.monotonic()<deadline:
            app.trainer.update(clock());time.sleep(.001)
        stats=app.trainer.state.totals(game)
        self.assertEqual((stats['auto_decisions'],stats['auto_checked'],stats['auto_correct']),(rounds,rounds,rounds))
        self.assertEqual((stats['auto_errors'],stats['auto_ev_lost'],stats['decisions']),(0,0,0))
        self.assertEqual(stats['auto_wagered'],10*ui.session.game.hands*rounds)
        self.assertEqual(stats['auto_hands'],ui.session.game.hands*rounds)
        self.assertEqual(stats['auto_returned']-stats['auto_wagered'],ui.session.credits-10000)
        return app,clock

    def test_late_grading_uses_original_session_and_does_not_mutate_the_game(self):
        app,_=self.app();report=self.report(app);s=app.play.session.snapshot()
        state=app.trainer.state
        state.record(s,report['mask'],None,100,12,assisted=True,autoplay=True)
        original=state.current;state.begin('ddb10')
        class Advisor:
            polls=0
            def request(self,snapshot):return 1
            def poll(self,token):
                self.polls+=1
                return None if self.polls==1 else report
            def close(self):pass
        queue=AutoGradeQueue(state,Advisor);self.addCleanup(queue.close)
        before=app.play.session.snapshot();rng=app.play.session._rng.getstate()
        self.assertTrue(queue.submit(s,report['mask'],original['id']))
        self.assertFalse(queue.update());self.assertEqual(original['stats']['auto_checked'],0)
        self.assertTrue(queue.update());self.assertEqual(original['stats']['auto_checked'],1)
        self.assertEqual(state.current['stats']['auto_checked'],0)
        self.assertEqual(state.totals('ddb10')['auto_checked'],1)
        self.assertFalse(queue.update());self.assertEqual(state.totals('ddb10')['auto_checked'],1)
        self.assertEqual(app.play.session.snapshot(),before);self.assertEqual(app.play.session._rng.getstate(),rng)

    def test_failed_or_overflowed_checks_remain_unchecked(self):
        app,_=self.app();report=self.report(app);s=app.play.session.snapshot();state=app.trainer.state
        state.record(s,0,None,100,0,assisted=True,autoplay=True)
        class Bad:
            def request(self,snapshot):return 1
            def poll(self,token):return {'error':'unavailable'}
            def close(self):pass
        queue=AutoGradeQueue(state,Bad,limit=1);self.addCleanup(queue.close)
        self.assertTrue(queue.submit(s,0,state.current['id']))
        self.assertFalse(queue.submit(s,0,state.current['id']))
        queue.update();stats=autoplay_stats(state.totals('ddb10'))
        self.assertEqual((stats['decisions'],stats['_auto_total'],stats['correct']),(0,1,0))

    def test_real_deferred_worker_finishes_after_changing_to_a_different_game(self):
        app,clock=self.app();report=self.report(app)
        self.choose(app,report['mask']);app.play.autoplay=True
        app.trainer.cancel_analysis()  # The original fast draw beats the live report.
        app.play.session.draw()
        self.assertEqual(app.trainer.state.totals('ddb10')['auto_checked'],0)
        self.assertEqual(len(app.trainer.auto_grades.jobs),1)
        app.play.pause_autoplay()
        app.play.session=Session(game_id='joker5',rng=random.Random(9));app.trainer.bind()
        app.play.session.deal();before=app.play.session.snapshot()
        deadline=time.monotonic()+10
        while app.trainer.state.totals('ddb10')['auto_checked']<1 and time.monotonic()<deadline:
            app.trainer.update(clock());time.sleep(.001)
        old=app.trainer.state.totals('ddb10');new=app.trainer.state.totals('joker5')
        self.assertEqual((old['auto_checked'],old['auto_correct']),(1,1))
        self.assertEqual(new['auto_checked'],0)
        self.assertEqual(app.play.session.snapshot(),before)

    def test_legacy_saved_history_restores_with_zero_autoplay_counters(self):
        state=TrainingState();state.begin('ddb10');state.current['stats']['decisions']=3
        raw=copy.deepcopy(state.data)
        for session in raw['sessions']:
            session['stats']={k:v for k,v in session['stats'].items() if not k.startswith('auto_')}
        restored=TrainingState(SimpleNamespace(data=raw))
        self.assertEqual(restored.data['sessions'][0]['stats']['decisions'],3)
        self.assertEqual(restored.data['sessions'][0]['stats']['auto_decisions'],0)

    def test_stats_open_on_autoplay_view_after_auto_round_and_show_coverage(self):
        app,_=self.run_auto('ddb10',0,1)
        app.trainer.open();app.trainer.index=3;app.handle('CENTER')
        self.assertEqual(app.trainer.stats_scope,2)
        label,stats=app.trainer.stats_views()[2]
        self.assertEqual(label,'SESSION AUTOPLAY')
        self.assertEqual((stats['decisions'],stats['_auto_total']),(1,1))
        self.assertEqual(app.render().size,(320,240))


if __name__=='__main__':unittest.main()
