"""Opt-in SD memory, device controls, paytable binding and automatic entry."""
import copy
import hashlib
from pathlib import Path
import random
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_training_store import TrainingStore,Journal,OFFSET,HEADER_BYTES,SLOT_BYTES,initial_region,unpack_slot
from poker_training import TrainingState,DetailedTable
from poker_games import EXTRA_PROFILES,get_game
from poker_engine import Session
from poker_ui import PokerUI
from poker_app import PokerApp
from poker_calculator import CardCalculator
import launcher
from hardware import PlusHardware


class PersistenceTests(unittest.TestCase):
    def image(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'save.img'
        with (ROOT/'inputs/base-os-v0.8.7-pi0.img').open('rb') as stream:mbr=stream.read(512)
        with path.open('wb') as stream:
            stream.write(mbr);stream.seek(OFFSET);stream.write(initial_region(mbr))
        return path

    def store(self,path):
        store=TrainingStore(Journal(path),lambda:Journal(path));self.addCleanup(store.close)
        return store

    def test_fresh_default_and_legacy_history_do_not_opt_in_or_write(self):
        for legacy in (False,True):
            with self.subTest(legacy=legacy):
                path=self.image()
                if legacy:
                    j=Journal(path);j.write({'schema':1,'settings':{'ddb10':{'mode':'coach'}}});j.close()
                before=hashlib.sha256(path.read_bytes()).hexdigest()
                with patch('poker_training_store.hardware_journal',side_effect=lambda:Journal(path)):
                    store=TrainingStore.hardware();state=TrainingState(store)
                self.assertFalse(store.persistent);self.assertIsNone(store._thread)
                self.assertFalse(state.data['settings'])
                state.begin('ddb10');state.totals('ddb10')['correct']=3;state.save();store.close()
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_opt_in_restores_settings_stats_and_device_preferences(self):
        path=self.image();store=self.store(path);state=TrainingState(store)
        state.settings('ddb10')['mode']='coach';state.begin('ddb10')
        state.totals('ddb10')['correct']=7;state.data['device']={'brightness':40};state.save()
        self.assertTrue(store.set_persistent(True));store.close()
        reboot=self.store(path);loaded=TrainingState(reboot)
        self.assertTrue(reboot.persistent)
        self.assertEqual(loaded.settings('ddb10')['mode'],'coach')
        self.assertEqual(loaded.totals('ddb10')['correct'],7)
        self.assertEqual(loaded.data['device']['brightness'],40)
        app=PokerApp(training_state=loaded);self.addCleanup(app.close)
        self.assertFalse(app.training_mode);self.assertEqual(app.play.menu['index'],0)
        self.assertEqual(app.play.session.credits,10000);self.assertFalse(app.play.autoplay)

    def test_off_erases_both_copies_but_keeps_current_RAM_data(self):
        path=self.image();store=self.store(path);state=TrainingState(store)
        state.begin('ddb10');state.totals('ddb10')['correct']=11;state.save()
        self.assertTrue(store.set_persistent(True))
        state.totals('ddb10')['correct']=12;state.save()
        self.assertTrue(store.set_persistent(False))
        self.assertEqual(state.totals('ddb10')['correct'],12)
        with path.open('rb') as stream:
            stream.seek(OFFSET+HEADER_BYTES)
            for _ in range(2):
                payload=unpack_slot(stream.read(SLOT_BYTES))['payload']
                self.assertFalse(payload['persistent_memory']);self.assertEqual(payload['training'],{})
        state.totals('ddb10')['correct']=13;state.save();store.close()
        fresh=TrainingState(self.store(path));self.assertFalse(fresh.data['totals'])

    def test_interrupted_second_off_copy_still_prevents_old_history_restore(self):
        path=self.image();store=self.store(path);state=TrainingState(store)
        state.begin('ddb10');self.assertTrue(store.set_persistent(True))
        write=store.journal.write;calls=[]
        def interrupted(record):
            calls.append(record)
            if len(calls)==2:raise OSError('interrupted second slot')
            return write(record)
        with patch.object(store.journal,'write',side_effect=interrupted):
            self.assertFalse(store.set_persistent(False))
        self.assertFalse(store.persistent);store.close()
        fresh=self.store(path);self.assertFalse(fresh.persistent);self.assertEqual(fresh.data,{})

    def test_clear_removes_training_data_and_preserves_memory_mode_and_device_settings(self):
        path=self.image();store=self.store(path);state=TrainingState(store)
        state.begin('ddb10');state.data['device']={'brightness':30};state.save()
        self.assertTrue(store.set_persistent(True));self.assertTrue(state.clear())
        self.assertTrue(store.persistent);self.assertIsNone(state.current)
        self.assertEqual(state.data['device'],{'brightness':30})
        store.close();fresh=TrainingState(self.store(path))
        for key in ('settings','totals','sessions','errors'):self.assertFalse(fresh.data[key])
        self.assertEqual(fresh.data['device'],{'brightness':30})

    def test_missing_card_cannot_claim_persistence_is_enabled(self):
        store=TrainingStore(journal_factory=lambda:None);self.addCleanup(store.close)
        self.assertFalse(store.set_persistent(True));self.assertFalse(store.persistent)
        self.assertIn('failed',store.status)

    def test_pending_saves_are_coalesced_and_flush_keeps_latest_data(self):
        path=self.image()
        with patch.object(TrainingStore,'SAVE_INTERVAL',60):
            store=self.store(path);self.assertTrue(store.set_persistent(True))
            generation=store.journal.generation
            for i in range(50):store.save({'counter':i})
            self.assertEqual(store.journal.generation,generation)
            self.assertTrue(store.flush())
            self.assertEqual(store.journal.generation,generation+1)
            self.assertEqual(store.journal.payload['training'],{'counter':49})


class NewControlsTests(unittest.TestCase):
    def app(self):
        app=PokerApp(play=PokerUI(Session(rng=random.Random(3)),cabinet=True),training_state=TrainingState())
        self.addCleanup(app.close);return app

    def test_right_chord_toggles_live_sidebar_at_two_seconds_and_dpad_is_not_shortcut(self):
        gate=launcher.HoldReleaseGate()
        self.assertEqual(launcher.MENU_CHORD,160)
        dpad=launcher.HoldReleaseGate()
        self.assertFalse(dpad.update(0,3));self.assertFalse(dpad.update(3,3))
        self.assertFalse(gate.update(1,160));self.assertFalse(gate.update(2.999,160))
        self.assertTrue(gate.update(3,160))
        app=self.app();app.toggle_hidden_mode()
        self.assertTrue(app.training_mode);self.assertIsNone(app.trainer.page)
        self.assertEqual(app.render().size,(320,240))
        gate.reset();gate.blocked=True
        for now in (4,6,9):self.assertFalse(gate.update(now,160))
        self.assertFalse(gate.update(10,0));self.assertFalse(gate.update(10.081,0))
        self.assertFalse(gate.update(11,160));self.assertTrue(gate.update(13,160))
        app.toggle_hidden_mode();self.assertFalse(app.training_mode)

    def test_general_settings_are_accessible_and_apply_profile_to_game_and_calculator(self):
        app=self.app()
        for index in range(12):
            app.play.menu['index']=index
            self.assertEqual(app.render().tobytes(),app.play.render().tobytes())
        app.handle('KEY3');self.assertTrue(app.settings.active)
        self.assertEqual(app.render().size,(320,240))
        app.settings.handle('LEFT');self.assertEqual(app.display_brightness,90)
        app.settings.page='profiles';app.settings._select_profile_game(9)
        app.settings.profile_index=3;app.settings.index=3;app.settings.handle('CENTER')
        self.assertEqual(app.settings.resolve('ddb10'),'ddb10_75')
        app.settings.close();app.play.menu['index']=9;app.handle('KEY2')
        self.assertEqual(app.play.session.game.id,'ddb10_75')
        self.assertEqual(app.play.session.total_bet,100)
        app.calculator.select_game('ddb10');self.assertEqual(app.calculator.game_id,'ddb10_75')

    def test_lcd_brightness_controls_the_real_backlight_pin_and_stops_PWM(self):
        calls=[]
        pwm=SimpleNamespace(start=lambda value:calls.append(('start',value)),
                            ChangeDutyCycle=lambda value:calls.append(('duty',value)),stop=lambda:calls.append(('stop',)))
        owner=PlusHardware();owner.gpio=SimpleNamespace(PWM=lambda pin,hz:(calls.append(('PWM',pin,hz)) or pwm),
            output=lambda *args:None,cleanup=lambda *args:None)
        owner.display=SimpleNamespace(backlight=18,spi=SimpleNamespace(close=lambda:None))
        self.assertTrue(owner.set_brightness(40));owner.set_brightness(70);owner.close()
        self.assertEqual(calls,[('PWM',18,1000),('start',40),('duty',70),('stop',)])

    def test_all_alternate_profiles_have_bound_payouts_and_certified_full_EV(self):
        snapshot=Session(rng=random.Random(44)).snapshot()
        snapshot.update(phase='hold',initial=[12,4,40,46,5],round_feature=True,round_base_bet=5)
        table=DetailedTable()
        for game in EXTRA_PROFILES:
            with self.subTest(game=game.id):
                self.assertEqual(game.pays[:7]+game.pays[9:],get_game(game.cabinet_id).pays[:7]+get_game(game.cabinet_id).pays[9:])
                self.assertEqual(game.multipliers,get_game(game.cabinet_id).multipliers)
                snapshot.update(game_id=game.id,round_num_hands=game.hands,active_multipliers=[1]*game.hands)
                from poker_cabinet_strategy import freeze_round
                report=table.advise(freeze_round(snapshot))
                self.assertEqual(len(report['holds']),32)
                self.assertLess(report['continuation_bellman_span'],1e-6)
        g=get_game('ddb10_75')
        self.assertEqual(g.pays,(800,50,400,160,160,80,50,7,5,4,3,1,1,0))
        self.assertEqual(g.multipliers,(4,4,4,4,4,4,3,12,10,8,4,3,2,1))

    def test_fifth_card_automatically_requests_advice_and_edits_refresh_it(self):
        class Advisor:
            def __init__(self):self.calls=[]
            def request(self,snapshot):self.calls.append(copy.deepcopy(snapshot));return len(self.calls)
            def cancel(self):pass
            def poll(self,token):return None
            def close(self):pass
        advisor=Advisor();calc=CardCalculator(advisor=advisor);self.addCleanup(calc.close);calc.select_game('ddb10')
        for i,card in enumerate((12,4,40,46)):calc.set_card(i,card)
        self.assertEqual(advisor.calls,[])
        calc.set_card(4,5);self.assertEqual(len(advisor.calls),1)
        calc.set_multiplier(0,12);self.assertEqual(len(advisor.calls),2)
        calc.set_card(4,6);self.assertEqual(len(advisor.calls),3)
        calc.set_continued(False);self.assertEqual(len(advisor.calls),4)
        calc.set_card(4,None);self.assertIsNone(calc._token)


if __name__=='__main__':unittest.main()
