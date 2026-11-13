"""Training decisions, independent EV convolution, controls and power-loss saves."""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import time
import unittest
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_app import PokerApp
from poker_ui import PokerUI
from poker_engine import Session
from poker_games import GAMES
from poker_cabinet_strategy import GameStrategyTable,freeze_round
from poker_training import DetailedTable,TrainingState,TOLERANCE,snapshot_for_error,MAX_ERRORS
from poker_training_store import (Journal,TrainingStore,OFFSET,HEADER_BYTES,SLOT_BYTES,initial_region,pack_slot,unpack_slot)
from poker_training_store import hardware_journal


class Clock:
    def __init__(self):self.now=0.0
    def __call__(self):return self.now


class TrainingMathTests(unittest.TestCase):
    def test_every_value_for_all_games_matches_independent_dense_polynomial(self):
        rng=random.Random(41271)
        detailed=DetailedTable()
        for game in GAMES:
            table=GameStrategyTable(game.id)
            for feature in (False,True):
                s=Session(game_id=game.id,rng=rng);s.deal()
                if s.phase!='hold':s.deal()
                s.active_multipliers=[game.possible_multipliers[(i+2)%len(game.possible_multipliers)] for i in range(game.hands)]
                snapshot=s.snapshot();snapshot['round_feature']=feature
                actual=detailed.advise(freeze_round(snapshot));counts=table.counts(snapshot['initial'])
                for mask,row in enumerate(counts):
                    immediate=sum(snapshot['active_multipliers'])*sum(n*game.award(c,5) for c,n in zip(game.categories,row))/sum(row)
                    future=0.0
                    if feature:
                        q=[0.0]*(max(game.possible_multipliers)+1)
                        for category,n in zip(game.categories,row):q[game.multiplier(category)]+=n/sum(row)
                        poly=[1.0]
                        for _ in range(game.hands):
                            product=[0.0]*(len(poly)+len(q)-1)
                            for i,p in enumerate(poly):
                                for j,v in enumerate(q):
                                    if p and v:product[i+j]+=p*v
                            poly=product
                        future=sum(p*table.bias[total] for total,p in enumerate(poly) if p)
                    with self.subTest(game=game.id,feature=feature,mask=mask):
                        value=actual['holds'][mask]
                        self.assertAlmostEqual(value['current'],immediate,places=8)
                        self.assertAlmostEqual(value['future'],future,places=8)
                        self.assertAlmostEqual(value['value'],immediate+future,places=8)
                        self.assertAlmostEqual(sum(value['probabilities']),1,places=12)
                legacy=table.advise(freeze_round(snapshot)[1:])
                self.assertAlmostEqual(actual['value'],legacy['value'],places=7)
                self.assertEqual(actual['mask'],legacy['mask'])
                self.assertIn(legacy['mask'],actual['optimal_masks'])
                self.assertEqual(sorted(actual['ranking']),list(range(32)))

    def test_curated_difficulty_labels_and_holds_are_verified_for_every_game(self):
        drills=json.loads((ROOT/'payload/opt/dino/training_drills.json').read_text())
        table=DetailedTable()
        for game in GAMES:
            for level in ('close','clear'):
                self.assertGreaterEqual(len(drills[game.id][level]),8)
                for drill in drills[game.id][level]:
                    report=table.advise(freeze_round(snapshot_for_error(drill)))
                    worse=[r['value'] for r in report['holds'] if report['value']-r['value']>TOLERANCE]
                    gap=(report['value']-max(worse))/(10*game.hands)
                    self.assertIn(drill['best'],report['optimal_masks'])
                    self.assertAlmostEqual(gap,drill['gap_per_wager'],places=10)
                    if level=='close':self.assertTrue(0<gap<=.002)
                    else:self.assertGreaterEqual(gap,.02)


class JournalTests(unittest.TestCase):
    def test_device_discovery_validates_both_possible_mmc_indices(self):
        paths=[Path('/dev/mmcblk0'),Path('/dev/mmcblk1')]
        sentinel=object()
        with patch('poker_training_store.Path.glob',return_value=paths),patch('poker_training_store.Path.is_symlink',return_value=False),patch('poker_training_store.Path.is_block_device',return_value=True),patch('poker_training_store.Journal',side_effect=[ValueError('Not our image'),sentinel]) as constructor:
            self.assertIs(hardware_journal(),sentinel)
            self.assertEqual([call.args[0] for call in constructor.call_args_list],paths)

    def image(self,root):
        p=Path(root)/'journal.img'
        mbr=(ROOT/'inputs/seedsigner_os.0.8.7.pi0.img').read_bytes()[:512]
        with p.open('wb') as f:
            f.write(mbr);f.seek(OFFSET);f.write(initial_region(mbr))
        return p

    def test_saved_history_reopens_and_writes_only_reserved_data_slots(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.image(root)
            with p.open('rb') as f:before=hashlib.sha256(f.read(OFFSET+HEADER_BYTES)).hexdigest()
            journal=Journal(p);journal.write({'schema':1,'test':'first'});journal.write({'schema':1,'test':'second'});journal.close()
            reopened=Journal(p);self.assertEqual(reopened.payload['test'],'second');reopened.close()
            with p.open('rb') as f:self.assertEqual(hashlib.sha256(f.read(OFFSET+HEADER_BYTES)).hexdigest(),before)

    def test_interrupted_newest_slot_recovers_previous_complete_save(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.image(root);j=Journal(p);j.write({'value':'previous'});j.write({'value':'newest'})
            os.pwrite(j.fd,b'broken partial save'*100,OFFSET+HEADER_BYTES+j.slot*SLOT_BYTES)
            j.close();j=Journal(p)
            self.assertEqual(j.payload,{'value':'previous'});self.assertTrue(j.recovered)
            j.write({'value':'recovered'});j.close();j=Journal(p)
            self.assertEqual(j.payload['value'],'recovered');j.close()

    def test_wrong_mbr_or_header_and_both_corrupt_slots_are_never_overwritten(self):
        for where in ('mbr','header','both'):
            with self.subTest(where=where),tempfile.TemporaryDirectory() as root:
                p=self.image(root)
                with p.open('r+b') as f:
                    if where=='mbr':f.seek(0);f.write(b'bad')
                    elif where=='header':f.seek(OFFSET);f.write(b'bad')
                    else:
                        for i in range(2):f.seek(OFFSET+HEADER_BYTES+i*SLOT_BYTES);f.write(b'bad')
                before=hashlib.sha256(p.read_bytes()).digest()
                with self.assertRaises(ValueError):Journal(p)
                self.assertEqual(hashlib.sha256(p.read_bytes()).digest(),before)

    def test_oversized_or_nonfinite_records_are_rejected(self):
        for payload in ({'x':'a'*(SLOT_BYTES+1)},{'x':float('nan')}):
            with self.assertRaises(ValueError):pack_slot(1,payload)
        self.assertIsNone(unpack_slot(b'incomplete'))

    def test_background_save_flushes_and_restores_statistics(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.image(root);store=TrainingStore(Journal(p));state=TrainingState(store)
            self.assertTrue(store.set_persistent(True))
            state.settings('ddb10')['mode']='test';state.begin('ddb10')
            state.totals('ddb10')['correct']=7;state.save()
            self.assertTrue(store.flush());store.close()
            store=TrainingStore(Journal(p));state=TrainingState(store)
            self.assertEqual(state.settings('ddb10')['mode'],'test')
            self.assertEqual(state.totals('ddb10')['correct'],7)
            store.close()


class TrainerFlowTests(unittest.TestCase):
    def app(self,game='ddb10'):
        clock=Clock();play=PokerUI(Session(game_id=game,rng=random.Random(8841)),clock=clock,cabinet=True)
        app=PokerApp(play=play,training_state=TrainingState(clock=clock),training_mode=True)
        self.addCleanup(app.close);return app,clock

    def ready(self,app,mode='test'):
        app.play.menu=None;app.trainer.settings['mode']=mode
        app.play.session.deal();self.wait(app)
        self.assertEqual(app.play.session.phase,'hold')
        return app.trainer.report

    def wait(self,app):
        until=time.monotonic()+8
        while app.trainer._token is not None and time.monotonic()<until:
            app.trainer.update(app.play._clock());time.sleep(.001)
        self.assertIsNotNone(app.trainer.report)

    def choose(self,app,mask):app.play.session.held=[bool(mask&(1<<i)) for i in range(5)]

    def test_first_ddb_decision_is_graded_and_correct_play_can_lose(self):
        app,_=self.app();report=self.ready(app)
        self.choose(app,report['mask']);app.play._play()
        self.assertEqual(app.play.session.phase,'result')
        stats=app.trainer.state.totals('ddb10')
        self.assertEqual((stats['decisions'],stats['correct'],stats['errors']),(1,1,0))
        self.assertAlmostEqual(stats['ev_lost'],0);self.assertEqual(stats['hands'],10)

    def test_warning_does_not_spend_or_consume_rng_and_correction_is_recorded_once(self):
        app,_=self.app();report=self.ready(app);bad=min(report['holds'],key=lambda r:r['value'])['mask']
        self.choose(app,bad);before=app.play.session.snapshot();rng=app.play.session._rng.getstate()
        app.play._play()
        self.assertIsNone(app.trainer.page);self.assertIsNotNone(app.trainer.inline_warning)
        self.assertEqual(app.play.session.snapshot(),before)
        self.assertEqual(app.play.session._rng.getstate(),rng)
        self.assertEqual(app.trainer.state.totals('ddb10')['decisions'],0)
        self.choose(app,report['mask']);app.play._play()
        stats=app.trainer.state.totals('ddb10')
        self.assertEqual((stats['decisions'],stats['errors'],stats['corrected']),(1,1,1))
        self.assertEqual(len(app.trainer.state.errors('ddb10')),1)
        self.assertEqual(app.play.session.phase,'result')

    def test_draw_anyway_records_actual_chosen_hold_and_ev_loss(self):
        app,_=self.app();report=self.ready(app);bad=min(report['holds'],key=lambda r:r['value'])['mask']
        self.choose(app,bad);app.play._play();app.play._play()
        stats=app.trainer.state.totals('ddb10')
        self.assertAlmostEqual(stats['ev_lost'],report['value']-report['holds'][bad]['value'])
        self.assertEqual(app.trainer.state.errors('ddb10')[0]['chosen'],bad)
        self.assertEqual(stats['wagered'],100)

    def test_assisted_hands_do_not_inflate_accuracy_or_error_list(self):
        for reason in ('coach','hint','autoplay'):
            with self.subTest(reason=reason):
                app,_=self.app();self.ready(app,'coach' if reason=='coach' else 'test')
                if reason=='hint':app.trainer.assisted=True
                if reason=='autoplay':app.play.autoplay=True
                self.choose(app,0);app.play.session.draw()
                stats=app.trainer.state.totals('ddb10')
                self.assertEqual((stats['decisions'],stats['assisted']),(0,1))
                self.assertEqual(app.trainer.state.errors('ddb10'),[])

    def test_every_game_has_a_working_training_decision(self):
        for game in GAMES:
            with self.subTest(game=game.id):
                app,_=self.app(game.id);report=self.ready(app)
                self.choose(app,report['mask']);app.play._play()
                self.assertEqual(app.trainer.state.totals(game.id)['correct'],1)
                self.assertEqual(app.trainer.state.totals(game.id)['wagered'],10*game.hands)

    def test_trainer_long_bottom_opens_options_and_release_is_consumed(self):
        app,clock=self.app()
        app.set_pressed_mask_sampled(128,0);clock.now=1.1;app.update(clock())
        self.assertEqual(app.trainer.page,'home')
        app.set_pressed_mask_sampled(0,1.2);app.handle_sampled('KEY3',1.2)
        self.assertEqual(app.trainer.page,'home')
        app.handle('KEY3');self.assertFalse(app.trainer.active)
        app.set_pressed_mask_sampled(128,2);app.set_pressed_mask_sampled(160,2.2)
        clock.now=4.5;app.update(clock());self.assertFalse(app.trainer.active)
        app.toggle_calculator();self.assertTrue(app.calculator_active)

    def test_calculator_ev_uses_its_own_game_not_the_suspended_game(self):
        app,clock=self.app();app.toggle_calculator();c=app.calculator;c.select_game('joker5')
        for i,card in enumerate((52,9,24,14,4)):c.set_card(i,card)
        app.set_pressed_mask_sampled(32,0);clock.now=1.1;app.update(clock())
        self.assertEqual(app.trainer.page,'ev');self.wait(app)
        self.assertEqual(app.trainer.report['game_id'],'joker5')
        self.assertEqual(app.trainer.render().size,(320,240))
        app.set_pressed_mask_sampled(0,1.2);app.handle_sampled('KEY1',1.2)
        self.assertEqual(app.trainer.page,'ev')
        app.handle('KEY3');self.assertTrue(app.calculator_active)

    def test_error_replay_restores_cards_and_multiplier_vector(self):
        app,_=self.app();report=self.ready(app)
        snap=app.play.session.snapshot();snap['active_multipliers']=[2,3,4,8,10,12,1,2,3,4]
        report=DetailedTable().advise(freeze_round(snap))
        bad=min(report['holds'],key=lambda r:r['value'])['mask']
        app.trainer.state.record(snap,bad,report,100,0)
        error=app.trainer.state.errors('ddb10')[0]
        self.choose(app,report['mask']);app.play.session.draw()
        app.trainer._forced_error=error
        app.play.session.deal()
        self.assertEqual(app.play.session.initial,error['cards'])
        self.assertEqual(app.play.session.active_multipliers,error['multipliers'])
        self.wait(app);self.choose(app,app.trainer.report['mask']);app.play.session.draw()
        self.assertTrue(error['learned']);self.assertEqual(error['retries'],1)

    def test_close_and_clear_drills_use_valid_fixed_boards(self):
        for difficulty in ('close','clear'):
            app,_=self.app();app.trainer.settings.update(mode='test',difficulty=difficulty)
            app.play.session.deal();self.wait(app)
            self.assertEqual(app.play.session.active_multipliers,[1]*10)
            report=app.trainer.report
            worse=[r['value'] for r in report['holds'] if report['value']-r['value']>TOLERANCE]
            gap=(report['value']-max(worse))/100
            self.assertTrue(0<gap<=.002 if difficulty=='close' else gap>=.02)

    def test_every_training_page_renders_at_native_resolution(self):
        app,_=self.app();report=self.ready(app)
        snap=app.play.session.snapshot();bad=min(report['holds'],key=lambda r:r['value'])['mask']
        app.trainer.state.record(snap,bad,report,100,0)
        app.trainer.error_detail=app.trainer.state.errors('ddb10')[0]
        for page in ('home','settings','warning','stats','errors','error_detail','ev','ev_detail','waiting','analysis_error','help','message'):
            with self.subTest(page=page):
                app.trainer.page=page;app.trainer.index=0
                self.assertEqual(app.trainer.render().size,(320,240))

    def test_stale_analysis_for_another_multiplier_board_is_rejected(self):
        app,_=self.app();report=self.ready(app)
        snap=app.play.session.snapshot();snap['active_multipliers']=[12]*10
        with self.assertRaises(ValueError):app.trainer.state.record(snap,0,report,100,0)
        self.assertEqual(app.trainer.state.totals('ddb10')['decisions'],0)

    def test_draw_waits_for_first_analysis_without_requiring_a_second_press(self):
        app,_=self.app();app.play.menu=None;app.trainer.settings.update(mode='test',warn=False)
        app.play.session.deal();app.play._play()
        until=time.monotonic()+8
        while app.play.session.phase=='hold' and time.monotonic()<until:
            app.trainer.update(app.play._clock());time.sleep(.001)
        self.assertEqual(app.play.session.phase,'result')
        self.assertEqual(app.trainer.state.totals('ddb10')['decisions'],1)

    def test_equally_good_alternatives_are_not_marked_as_errors(self):
        app,_=self.app();report=self.ready(app)
        alt=next(i for i in range(32) if i!=report['mask'])
        report['holds'][alt]['value']=report['value']
        self.choose(app,alt);app.play._play()
        self.assertEqual(app.play.session.phase,'result')
        self.assertEqual(app.trainer.state.totals('ddb10')['correct'],1)

    def test_history_is_bounded_and_each_stored_error_retains_full_context(self):
        app,_=self.app();report=self.ready(app)
        state=app.trainer.state;rng=random.Random(99)
        for _ in range(MAX_ERRORS+20):
            snap=copy.deepcopy(app.play.session.snapshot());snap['initial']=rng.sample(range(52),5)
            fake=copy.deepcopy(report);fake['round_key']=freeze_round(snap)
            fake['value']=10;fake['holds'][0]['value']=0
            state.record(snap,0,fake,100,0)
        self.assertEqual(len(state.errors('ddb10')),MAX_ERRORS)
        self.assertLess(len(pack_slot(1,state.data)),SLOT_BYTES+1)
        for error in state.errors('ddb10'):self.assertEqual(len(snapshot_for_error(error)['active_multipliers']),10)

    def test_late_hint_cannot_erase_an_already_submitted_error(self):
        app,_=self.app();report=self.ready(app)
        bad=min(report['holds'],key=lambda r:r['value'])['mask'];self.choose(app,bad)
        app.play._play();self.assertIsNotNone(app.trainer.inline_warning)
        app.trainer.assisted=True
        self.choose(app,report['mask']);app.play._play()
        stats=app.trainer.state.totals('ddb10')
        self.assertEqual((stats['decisions'],stats['errors'],stats['assisted']),(1,1,0))

    def test_coach_to_test_mid_hand_remains_assisted(self):
        app,_=self.app();report=self.ready(app,'coach')
        app.trainer.page='settings';app.trainer.index=0;app.trainer.handle('LEFT')
        self.assertEqual(app.trainer.settings['mode'],'test')
        self.assertTrue(app.trainer.assisted)
        app.trainer.dismiss();self.choose(app,report['mask']);app.play.session.draw()
        self.assertEqual(app.trainer.state.totals('ddb10')['decisions'],0)

    def test_input_reset_cancels_a_queued_draw(self):
        app,_=self.app();app.play.menu=None;app.trainer.settings['mode']='test'
        app.play.session.deal();app.trainer.pending_draw=True;app.trainer.inline_waiting=True
        app.on_input_reset();self.wait(app)
        self.assertFalse(app.trainer.pending_draw);self.assertEqual(app.play.session.phase,'hold')

    def test_captured_long_release_survives_a_blocked_display_frame(self):
        app,clock=self.app()
        app.set_pressed_mask_sampled(128,1.0)
        # There was no UI update while the key was physically held.
        app.set_pressed_mask_sampled(0,2.2)
        app.handle_sampled('KEY3',2.2)
        self.assertEqual(app.trainer.page,'home')

    def test_input_reset_does_not_consume_a_future_unrelated_back_click(self):
        app,clock=self.app();app._consume_release='KEY3'
        app.on_input_reset();app.trainer.open();app.handle('KEY3')
        self.assertFalse(app.trainer.active)

    def test_calculator_assistance_during_a_test_hand_is_excluded_from_accuracy(self):
        app,_=self.app();report=self.ready(app)
        app.toggle_calculator();self.assertTrue(app.trainer.assisted)
        app.toggle_calculator();self.choose(app,report['mask']);app.play.session.draw()
        stats=app.trainer.state.totals('ddb10')
        self.assertEqual((stats['decisions'],stats['assisted']),(0,1))

    def test_reviewing_saved_answers_during_a_replay_counts_as_assistance(self):
        app,_=self.app();report=self.ready(app)
        bad=min(report['holds'],key=lambda r:r['value'])['mask']
        app.trainer.state.record(app.play.session.snapshot(),bad,report,100,0)
        app.trainer.page='errors';app.trainer.index=0;app.trainer.handle('CENTER')
        self.assertTrue(app.trainer.assisted)


if __name__=='__main__':unittest.main()
