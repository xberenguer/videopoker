"""Reference pay screens, live cabinet switching and unpruned policy checks."""
from pathlib import Path
import random
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_games import GAMES,get_game
from poker_engine import Session
from poker_ui import PokerUI
from poker_cabinet_ui import GameBank,LAYOUTS
from poker_cabinet_strategy import GameStrategyTable,freeze_round
from test_autoplay_ui import Clock,Advisor

# Independent transcription, TOP TO BOTTOM on each captured reference pay
# screen. Per-coin max-credit awards, then next-hand multipliers. These are not
# derived from production constants or strategy metadata.
REFERENCE={
 'bp3':((800,50,80,40,25,7,5,4,3,2,1),(2,2,2,2,2,12,11,8,4,3,2)),
 'bpd3':((800,50,80,8,6,4,3,1,1),(2,2,2,12,11,7,4,3,2)),
 'ddb3':((800,50,400,160,160,80,50,9,6,4,3,1,1),(2,2,2,2,2,2,2,12,10,8,4,3,2)),
 'dw3':((800,200,25,15,9,4,4,3,2,1),(2,2,2,2,12,7,5,5,3,2)),
 'job5':((800,50,25,8,6,4,3,2,1),(2,2,3,12,11,7,4,3,2)),
 'db5':((800,50,160,80,50,9,6,4,3,1,1),(2,2,2,2,3,12,10,8,4,3,2)),
 'joker5':((800,200,100,50,15,7,5,3,2,1,1),(3,3,3,3,2,7,6,5,4,3,2)),
 'dw5':((800,200,25,15,9,4,4,3,2,1),(2,2,2,3,12,7,5,5,3,2)),
 'bp10':((800,50,80,40,25,7,5,4,3,2,1),(4,4,4,4,3,12,11,8,4,3,2)),
 'ddb10':((800,50,400,160,160,80,50,9,6,4,3,1,1),(4,4,4,4,4,4,3,12,10,8,4,3,2)),
 'tdb10':((800,800,400,160,80,50,50,9,6,4,2,1,1),(2,2,2,2,2,2,2,12,10,8,4,3,2)),
 'dwb10':((800,400,200,25,80,40,20,9,4,4,3,1,1),(4,4,4,4,4,4,4,12,7,6,4,3,2)),
}


class CabinetMathTests(unittest.TestCase):
    def test_reference_tile_order_awards_and_multiplier_rows(self):
        self.assertEqual([g.id for g in GAMES],list(REFERENCE))
        self.assertEqual([g.hands for g in GAMES],[3]*4+[5]*4+[10]*4)
        for game in GAMES:
            with self.subTest(game=game.id):
                awards,multipliers=REFERENCE[game.id]
                self.assertEqual(tuple(game.award(key,5)//5 for key in game.rows),awards)
                self.assertEqual(tuple(game.multiplier(key) for key in game.rows),multipliers)
                for coin in range(1,5):
                    for key,pay in zip(game.rows,awards):
                        expected=400 if game.id=='tdb10' and key in ('royal_flush','four_aces_kicker') else 250 if key=='royal_flush' else pay
                        self.assertEqual(game.award(key,coin),coin*expected)

    def test_all_twelve_games_settle_credits_and_next_multipliers_independently(self):
        class FixedFullHouse:
            def sample(self,population,count):
                return [12,25,38,11,24] if count==5 else []
        for game in GAMES:
            with self.subTest(game=game.id):
                session=Session(game_id=game.id,rng=FixedFullHouse())
                awards,mults=REFERENCE[game.id];row=game.rows.index('full_house')
                session.deal()
                for index in range(5):session.toggle_hold(index)
                session.draw()
                self.assertEqual(session.credits,10000-game.hands*10+game.hands*5*awards[row])
                self.assertEqual(session.multipliers,[mults[row]]*game.hands)
                self.assertTrue(all(result['category']=='full_house' for result in session.results))
                session.deal()
                self.assertEqual(session.active_multipliers,[mults[row]]*game.hands)

    def test_unpruned_all_32_hold_values_match_each_certified_policy(self):
        rng=random.Random(98553)
        for game in GAMES:
            table=GameStrategyTable(game.id)
            for feature in (False,True):
                session=Session(game_id=game.id,rng=rng)
                if not feature:session.set_bet_per_hand(3)
                session.deal()
                if session.phase!='hold':session.deal()
                choices=game.possible_multipliers
                session.active_multipliers=[choices[(i+2)%len(choices)] for i in range(game.hands)]
                snapshot=session.snapshot();frozen=freeze_round(snapshot)
                hand,_,base,_,scale=frozen[1:]
                histograms=table.counts(hand);expected=[]
                # Independent unpruned probability-polynomial calculation.
                # Production uses bounded pruning and sparse dictionaries.
                for row in histograms:
                    denominator=sum(row)
                    value=scale*sum(n*game.award(c,base) for n,c in zip(row,game.categories))/denominator
                    if feature:
                        q=[0.0]*(max(choices)+1)
                        for category,n in zip(game.categories,row):q[game.multiplier(category)]+=n/denominator
                        distribution=[1.0]
                        for _ in range(game.hands):
                            product=[0.0]*(len(distribution)+len(q)-1)
                            for i,p in enumerate(distribution):
                                if p:
                                    for j,weight in enumerate(q):
                                        if weight:product[i+j]+=p*weight
                            distribution=product
                        value+=sum(p*table.bias[total] for total,p in enumerate(distribution) if p)
                    expected.append(value)
                best=max(expected)
                mask=max((m for m,value in enumerate(expected) if best-value<=1e-9),key=lambda m:(m.bit_count(),-m))
                actual=table.advise(frozen[1:])
                with self.subTest(game=game.id,feature=feature):
                    self.assertEqual(actual['mask'],mask)
                    self.assertAlmostEqual(actual['value'],expected[mask],places=7)


class CabinetFlowTests(unittest.TestCase):
    def ui(self):
        clock=Clock();advisor=Advisor()
        ui=PokerUI(Session(game_id='bp3',cabinet_defaults=False,rng=random.Random(88)),
                   cabinet=True,clock=clock,advisor=advisor)
        return ui,clock,advisor

    def test_boot_is_reference_menu_and_every_tile_opens_its_real_game(self):
        ui,clock,advisor=self.ui()
        self.assertEqual(ui.menu,{'page':'cabinet','index':0,'return':False})
        for index,game in enumerate(GAMES):
            ui.menu={'page':'cabinet','index':index,'return':index>0};ui.handle('CENTER')
            self.assertEqual(ui.session.game.id,game.id);self.assertIsNone(ui.menu)
            self.assertEqual((ui.session.bet_per_hand,ui.session.num_hands),(10,game.hands))
            self.assertEqual(len(ui.session.multipliers),game.hands)
            self.assertEqual(ui.session.credits,10000)
            self.assertTrue(ui.session.feature)
            self.assertEqual(ui.session.phase,'ready')
            self.assertEqual(ui.session.total_bet,10*game.hands)
            self.assertEqual(ui.pay_preview_bet,10)
            frame=ui.render();self.assertEqual(frame.size,(320,240))
            self.assertEqual(len(ui.renderer.HANDS),game.hands)

    def test_menu_dpad_wraps_and_return_preserves_entire_current_game(self):
        ui,clock,advisor=self.ui()
        ui.handle('UP');self.assertEqual(ui.menu['index'],8)
        ui.handle('LEFT');self.assertEqual(ui.menu['index'],7)
        ui.handle('RIGHT');ui.handle('DOWN');self.assertEqual(ui.menu['index'],0)
        ui.handle('KEY3');self.assertIsNotNone(ui.menu)
        ui.handle('KEY2');ui.session.set_bet_per_hand(3)
        before=ui.session.snapshot();ui._button_action(1)
        self.assertEqual(ui.menu['page'],'cabinet');ui.handle('KEY3')
        self.assertEqual(ui.session.snapshot(),before)

    def test_gold_controls_cannot_reduce_a_cabinet_bet_or_active_hand_count(self):
        for index,game in enumerate(GAMES):
            ui,clock,advisor=self.ui();ui.menu['index']=index;ui.handle('CENTER')
            before=ui.session.snapshot()
            ui.handle('KEY3')
            for _ in range(3):ui.handle('RIGHT')
            self.assertEqual(ui.button_focus,3)
            ui.handle('CENTER');ui.handle('RIGHT');ui.handle('KEY2')
            self.assertEqual(ui.session.snapshot(),before)
            self.assertEqual((before['bet_per_hand'],before['num_hands']),(10,game.hands))
            ui.handle('KEY3');ui._button_action(0)
            self.assertEqual(ui.menu,{'page':'paytable','bet':10})
            self.assertEqual(ui.session.snapshot(),before)

    def test_lower_bet_engine_can_still_draw_every_active_hand(self):
        # Inactive upper cards were an intentional hand-count setting, not a
        # max-bet dependency. The cabinet now locks max; core math remains valid
        # at lower wagers for the independent paytable/strategy checks.
        for game in GAMES:
            session=Session(game_id=game.id,rng=random.Random(250))
            session.set_bet_per_hand(1)
            self.assertEqual(session.num_hands,game.hands)
            session.deal();session.draw()
            self.assertEqual(len(session.hands),game.hands)
            self.assertEqual(len(session.results),game.hands)
            self.assertTrue(all(len(set(hand))==5 for hand in session.hands))

    def test_switching_preserves_shared_credit_and_each_games_pending_x_only(self):
        ui,clock,advisor=self.ui();ui.handle('CENTER')
        ui.session.credits=9980;ui.session.multipliers=[1,3,1]
        ui.session.set_bet_per_hand(2)
        ui.menu={'page':'cabinet','index':1,'return':True};ui.handle('CENTER')
        self.assertEqual(ui.session.game.id,'bpd3');self.assertEqual(ui.session.multipliers,[1]*3)
        self.assertEqual(ui.session.credits,9980)
        ui.session.multipliers=[2,1,1]
        ui.menu={'page':'cabinet','index':0,'return':True};ui.handle('CENTER')
        self.assertEqual(ui.session.multipliers,[1,3,1]);self.assertEqual(ui.session.credits,9980)
        self.assertEqual((ui.session.bet_per_hand,ui.session.num_hands),(10,3))
        ui.session.deal()
        with self.assertRaises(ValueError):ui._cabinet_bank.select('dw3',ui.session)
        ui._button_action(1);self.assertIsNone(ui.menu)

    def test_hint_autohold_and_manual_autoplay_apply_each_games_advice(self):
        for index,game in enumerate(GAMES):
            ui,clock,advisor=self.ui();ui.menu['index']=index;ui.handle('CENTER')
            for _ in range(3):
                ui.set_pressed_mask(1);ui.handle('UP');ui.set_pressed_mask(0);clock.advance(.1)
            ui.handle('DOWN');self.assertTrue(ui.manual_autoplay)
            advisor.answers[ui._advisor_token]={'mask':0b10101};ui.update(clock())
            dealt=ui.session.snapshot();clock.advance(100);ui.update(clock())
            self.assertEqual(ui.session.snapshot(),dealt)
            ui.handle('DOWN');self.assertTrue(ui.manual_autoplay)
            self.assertEqual(ui.session.held,[True,False,True,False,True])
            self.assertEqual(ui.session.rounds,1)
            self.assertEqual(len(ui.session.results),game.hands)


if __name__=='__main__':unittest.main()
