"""Manual entry, game/multiplier binding, cancellation and physical gate flow."""
import copy
import inspect
from pathlib import Path
import random
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_games import GAMES
from poker_ui import PokerUI
from poker_engine import Session
from poker_calculator import CardCalculator
from poker_app import PokerApp
from poker_cabinet_strategy import GameStrategyTable,freeze_round
import launcher
from input_harness import SynchronousInput


class PendingAdvisor:
    def __init__(self):self.token=0;self.answer=None;self.requested=None;self.closed=False
    def request(self,snapshot):self.token+=1;self.requested=copy.deepcopy(snapshot);return self.token
    def poll(self,token):return self.answer
    def cancel(self):self.token+=1
    def close(self):self.closed=True


class CalculatorTests(unittest.TestCase):
    def calc(self,game='ddb10',advisor=None):
        c=CardCalculator(advisor=advisor);self.addCleanup(c.close);c.select_game(game);return c

    @staticmethod
    def fill(c,cards=(9,24,14,23,4)):
        for i,card in enumerate(cards):c.set_card(i,card)

    def solve(self,c):
        self.assertTrue(c.calculate())
        deadline=time.monotonic()+5
        while c._token is not None and time.monotonic()<deadline:
            c.update(time.monotonic());time.sleep(.001)
        self.assertIsNotNone(c.result,c.status)
        return c.result

    def test_menu_opens_every_game_and_preserves_separate_entries(self):
        c=self.calc()
        for i,game in enumerate(GAMES):
            c.page='cabinet';c.menu_index=i;c.handle('CENTER')
            self.assertEqual(c.game_id,game.id);self.assertEqual(len(c.multipliers),game.hands)
            self.assertEqual(c.cards,[None]*5)
            c.set_card(0,i)
        for i,game in enumerate(GAMES):c.select_game(game.id);self.assertEqual(c.cards[0],i)

    def test_invalid_cards_duplicates_slots_and_game_specific_joker(self):
        c=self.calc();c.set_card(0,12)
        for bad in (-1,52,True,'12'):
            with self.subTest(card=bad),self.assertRaises(ValueError):c.set_card(1,bad)
        with self.assertRaises(ValueError):c.set_card(1,12)
        for slot in (-1,5,True):
            with self.assertRaises(ValueError):c.set_card(slot,0)
        c.select_game('joker5');c.set_card(0,52);self.assertEqual(c.cards[0],52)
        with self.assertRaises(ValueError):c.set_card(1,52)

    def test_multipliers_enforce_each_games_schedule_and_hand_count(self):
        c=self.calc()
        for game in GAMES:
            c.select_game(game.id)
            for i in range(game.hands):
                for value in game.possible_multipliers:c.set_multiplier(i,value)
            with self.assertRaises(ValueError):c.set_multiplier(game.hands,1)
            for bad in (0,13,True,'2'):
                with self.assertRaises(ValueError):c.set_multiplier(0,bad)
            invalid=next(i for i in range(1,13) if i not in game.possible_multipliers)
            with self.assertRaises(ValueError):c.set_multiplier(0,invalid)

    def test_missing_cards_never_request_advice(self):
        a=PendingAdvisor();c=self.calc(advisor=a)
        self.assertFalse(c.calculate());self.assertIsNone(a.requested)

    def test_each_card_slot_can_be_edited_and_cleared(self):
        c=self.calc();self.fill(c)
        for i in range(5):
            c.focus=i;c.handle('KEY2');self.assertEqual(c.page,'picker')
            c.handle('KEY1');self.assertIsNone(c.cards[i]);self.assertEqual(c.page,'editor')

    def test_duplicate_picker_selection_stays_open(self):
        c=self.calc();c.set_card(0,9);c.start_picker(1);c.picker_card=9;c.handle('CENTER')
        self.assertEqual(c.page,'picker');self.assertIsNone(c.cards[1]);self.assertIn('Already',c.status)

    def test_card_entry_flows_through_all_five_slots_using_buttons(self):
        c=self.calc();c.handle('CENTER');self.assertEqual(c.page,'picker')
        wanted=(9,24,14,23,4)
        for target in wanted:
            suit,rank=divmod(target,13)
            while c.picker_card//13!=suit:c.handle('DOWN')
            while c.picker_card%13!=rank:c.handle('RIGHT')
            c.handle('KEY2')
        self.assertEqual(c.cards,list(wanted));self.assertEqual(c.page,'editor')
        self.assertEqual(self.solve(c)['mask'],14)

    def test_joker_picker_navigation_and_selection(self):
        c=self.calc('joker5');c.start_picker(0)
        for _ in range(4):c.handle('DOWN')
        self.assertEqual(c.picker_card,52);c.handle('CENTER');self.assertEqual(c.cards[0],52)

    def test_bulk_multiplier_change_and_mixed_reset(self):
        c=self.calc();c.page='multipliers';c.multiplier_focus=10;c.handle('KEY1')
        self.assertEqual(c.multipliers,[12]*10)
        c.set_multiplier(0,2);c.handle('CENTER');self.assertEqual(c.multipliers,[1]*10)

    def test_every_multiplier_slot_is_reachable_by_dpad(self):
        c=self.calc()
        for game in GAMES:
            c.select_game(game.id);c.page='multipliers'
            reached=set();queue=[0]
            while queue:
                cursor=queue.pop()
                if cursor in reached:continue
                reached.add(cursor)
                for direction in ('UP','DOWN','LEFT','RIGHT'):
                    c.multiplier_focus=cursor;c.handle(direction)
                    if c.multiplier_focus not in reached:queue.append(c.multiplier_focus)
            self.assertEqual(reached,set(range(game.hands+1)),game.id)

    def test_editing_cards_multipliers_mode_or_game_invalidates_pending_advice(self):
        for edit in ('card','multiplier','mode','game'):
            with self.subTest(edit=edit):
                a=PendingAdvisor();c=self.calc(advisor=a);self.fill(c);c.calculate()
                a.answer={'mask':31,'game_id':'ddb10'}
                if edit=='card':c.set_card(0,8)
                elif edit=='multiplier':c.set_multiplier(0,12)
                elif edit=='mode':c.set_continued(False)
                else:c.select_game('job5')
                self.assertIsNone(c.result)
                if edit=='game':self.assertIsNone(c._token)
                else:
                    self.assertIsNotNone(c._token)
                    self.assertEqual(c._request_key,freeze_round(c.snapshot()))
                    self.assertEqual(a.requested,c.snapshot())
                a.answer=None
                self.assertFalse(c.update(time.monotonic()))

    def test_request_freezes_card_and_multiplier_inputs(self):
        a=PendingAdvisor();c=self.calc(advisor=a);self.fill(c);c.set_multiplier(3,8);c.set_continued(False);c.calculate()
        self.assertEqual(a.requested['initial'],[9,24,14,23,4])
        self.assertEqual(a.requested['active_multipliers'],[1,1,1,8,1,1,1,1,1,1])
        self.assertFalse(a.requested['round_feature']);self.assertEqual(a.requested['round_base_bet'],5)
        self.assertEqual(a.requested['round_num_hands'],10)

    def test_wrong_game_response_is_rejected(self):
        a=PendingAdvisor();c=self.calc(advisor=a);self.fill(c);c.calculate();a.answer={'mask':31,'game_id':'bp3'}
        self.assertTrue(c.update(0));self.assertIsNone(c.result)

    def test_literal_multiplier_and_continuation_cases_change_best_hold(self):
        c=self.calc();self.fill(c)
        self.assertEqual(self.solve(c)['mask'],14)
        for i in range(10):c.set_multiplier(i,12)
        self.assertEqual(self.solve(c)['mask'],10)
        for i in range(10):c.set_multiplier(i,1)
        c.set_continued(False);self.assertEqual(self.solve(c)['mask'],10)

    def test_all_twelve_games_and_both_modes_use_the_matching_solver(self):
        c=self.calc()
        for game in GAMES:
            c.select_game(game.id)
            cards=(52,12,25,38,0) if game.deck_size==53 else (12,25,38,11,24)
            self.fill(c,cards)
            for i in range(game.hands):c.set_multiplier(i,game.possible_multipliers[(i+2)%len(game.possible_multipliers)])
            for mode in (True,False):
                c.set_continued(mode)
                expected=GameStrategyTable(game.id).advise(freeze_round(c.snapshot())[1:])
                actual=self.solve(c)
                self.assertEqual((actual['game_id'],actual['mask']),(game.id,expected['mask']))
                self.assertAlmostEqual(actual['expected_current_win'],expected['expected_current_win'])

    def test_result_text_unambiguously_handles_no_cards_and_all_cards(self):
        c=self.calc();self.fill(c);c.result={'mask':0};self.assertEqual(c.hold_text(),'HOLD NONE - DRAW ALL FIVE')
        c.result={'mask':31};self.assertEqual(c.hold_text(),'HOLD ALL FIVE CARDS')

    def test_paytable_and_clear_controls(self):
        c=self.calc();self.fill(c);c.focus=7
        c.handle('RIGHT');c.handle('RIGHT');c.handle('CENTER');self.assertEqual(c.page,'pays')
        self.assertEqual(c.render().size,(320,240));c.handle('KEY3');self.assertEqual(c.page,'editor')
        c.focus=10;c.handle('KEY2');self.assertEqual(c.cards,[None]*5);self.assertIsNone(c.result)

    def test_every_screen_renders_for_every_game_including_joker_and_wild_cards(self):
        c=self.calc()
        for game in GAMES:
            c.select_game(game.id);self.fill(c,(52,0,13,26,39) if game.deck_size==53 else (0,13,26,39,12))
            for page in ('cabinet','editor','picker','multipliers','pays'):
                c.page=page
                self.assertEqual((c.render().mode,c.render().size),('RGB',(320,240)),(game.id,page))

    def test_close_joins_worker_and_is_idempotent(self):
        c=self.calc();self.fill(c);c.calculate();thread=c._advisor._thread;c.close();self.assertFalse(thread.is_alive());c.close()


class GateIntegrationTests(unittest.TestCase):
    def test_production_default_is_integrated_app_with_no_signer_callback(self):
        self.assertIsNone(inspect.signature(launcher.main).parameters['signer_runner'].default)
        app=launcher._default_ui()
        try:self.assertIsInstance(app,PokerApp)
        finally:app.close()

    def test_menu_back_returns_to_play_and_preserves_current_hand(self):
        play=PokerUI(Session(game_id='ddb10',rng=random.Random(88)),cabinet=True)
        play.menu=None;play.session.deal();before=play.session.snapshot()
        app=PokerApp(play=play)
        try:
            app.toggle_calculator();self.assertTrue(app.calculator_active);self.assertEqual(app.calculator.page,'cabinet')
            app.handle('KEY3');self.assertFalse(app.calculator_active)
            self.assertEqual(play.session.snapshot(),before)
        finally:app.close()

    def test_two_full_physical_chords_switch_in_and_back_without_exiting_gate(self):
        class StopProbe(BaseException):pass
        class Clock:
            now=0.
            def __call__(self):return self.now
            def sleep(self,amount):
                self.now+=amount
                if self.now>6:raise StopProbe()
        clock=Clock();events=[]
        class Hardware:
            def __enter__(self):events.append('open');return self
            def __exit__(self,*_):events.append('close')
            def read_mask(self):
                t=clock()
                return launcher.SIGNER_CHORD if .3<=t<2.5 or 3.0<=t<5.3 else 0
            def present(self,frame):self.assert_frame=frame.size
            def show_message(self,*args):raise AssertionError(args)
        class App(PokerApp):
            def toggle_hidden_mode(self):
                result=super().toggle_hidden_mode();events.append(('mode',self.training_mode));return result
        app=App(play=PokerUI(Session(rng=random.Random(77)),cabinet=True))
        with self.assertRaises(StopProbe):
            launcher.run_poker_gate(Hardware,lambda:app,clock,clock.sleep,input_factory=SynchronousInput)
        self.assertEqual([e for e in events if isinstance(e,tuple)],[('mode',True),('mode',False)])
        self.assertEqual(events.count('open'),1);self.assertEqual(events[-1],'close');self.assertTrue(app._closed)


if __name__=='__main__':unittest.main()
