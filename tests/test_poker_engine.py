"""Rule fixtures and state-transition checks for the independent poker engine."""
import random
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "payload/opt/dino"))
import poker_engine
from poker_engine import (BASE_BET, BET_CHOICES, CATEGORIES, DECK, MULTIPLIERS, PAYOUTS,
                          RandomNotReady, Session, card_label, evaluate_hand, payout_for)


def hand(text):
    ranks = {str(rank): rank for rank in range(2, 11)}
    ranks.update(J=11, Q=12, K=13, A=14)
    return ["CDHS".index(card[-1]) * 13 + ranks[card[:-1]] - 2
            for card in text.split()]


class ScriptedRandom:
    def __init__(self, draws):
        self.draws = list(draws)
        self.calls = []

    def sample(self, population, count):
        self.calls.append((tuple(population), count))
        if not self.draws:
            raise RuntimeError("No scripted draw remaining")
        return self.draws.pop(0)


class EvaluatorTests(unittest.TestCase):
    def test_all_fourteen_categories_and_wheel(self):
        fixtures = {
            "10H JH QH KH AH": "royal_flush",
            "AC 2C 3C 4C 5C": "straight_flush",
            "AC AD AH AS 4S": "four_aces_kicker",
            "2C 2D 2H 2S AH": "four_234_kicker",
            "AC AD AH AS KS": "four_aces",
            "4C 4D 4H 4S 5H": "four_234",
            "KC KD KH KS 2H": "four_5k",
            "5C 5D 5H JC JD": "full_house",
            "2C 4C 7C 9C KC": "flush",
            "AC 2D 3H 4S 5C": "straight",
            "7C 8D 9H 10S JC": "straight",
            "8C 8D 8H 2S KC": "three_kind",
            "4C 4D 9H 9S KC": "two_pair",
            "JC JD 2H 4S 8C": "high_pair",
            "10C 10D 2H 4S 8C": "nothing",
            "AC 2D 5H 7S KC": "nothing",
            "QC KD AH 2S 3C": "nothing",
        }
        seen = set()
        for cards, expected in fixtures.items():
            with self.subTest(cards=cards):
                actual = evaluate_hand(hand(cards))
                self.assertEqual(actual, expected)
                seen.add(actual)
                self.assertEqual(evaluate_hand(reversed(hand(cards))), expected)
        self.assertEqual(seen, set(CATEGORIES))

    def test_every_quad_rank_and_kicker(self):
        for rank in range(2, 15):
            four = [suit * 13 + rank - 2 for suit in range(4)]
            for kicker_rank in range(2, 15):
                if kicker_rank == rank:
                    continue
                expected = ("four_aces_kicker" if kicker_rank <= 4 else "four_aces") if rank == 14 else (
                    ("four_234_kicker" if kicker_rank in (2, 3, 4, 14) else "four_234")
                    if rank <= 4 else "four_5k")
                self.assertEqual(evaluate_hand(four + [kicker_rank - 2]), expected)

    def test_invalid_cards(self):
        for invalid in (None, [], [0, 1, 2, 3], [0, 1, 2, 3, 4, 5],
                        [0, 0, 1, 2, 3], [-1, 1, 2, 3, 4],
                        [52, 1, 2, 3, 4], [True, 1, 2, 3, 4],
                        [0.0, 1, 2, 3, 4], "12345"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                evaluate_hand(invalid)

    def test_literal_payout_and_ten_hand_multiplier_fixture(self):
        # Independent literal fixture prevents accidentally selecting the 3/5-play table.
        self.assertEqual([PAYOUTS[key] for key in CATEGORIES],
                         [800, 50, 400, 160, 160, 80, 50, 9, 6, 4, 3, 1, 1, 0])
        self.assertEqual([MULTIPLIERS[key] for key in CATEGORIES],
                         [4, 4, 4, 4, 4, 4, 3, 12, 10, 8, 4, 3, 2, 1])
        self.assertEqual(BASE_BET, 5)

    def test_card_labels(self):
        self.assertEqual([card_label(card) for card in hand("2C 10D JH QS AS")],
                         ["2C", "10D", "JH", "QS", "AS"])
        for card in (-1, 52, True, "A"):
            with self.assertRaises(ValueError):
                card_label(card)

    def test_official_variable_coin_pay_screen(self):
        self.assertEqual([payout_for("royal_flush", bet) for bet in range(1, 6)],
                         [250, 500, 750, 1000, 4000])
        for category in CATEGORIES:
            if category == "royal_flush":
                continue
            for bet in range(1, 6):
                self.assertEqual(payout_for(category, bet), PAYOUTS[category] * bet)
        for bet in (0, 6, 10, True, 1.5):
            with self.assertRaises(ValueError):
                payout_for("royal_flush", bet)


class SessionTests(unittest.TestCase):
    def test_unready_os_random_does_not_call_blocking_sampler_or_change_deal(self):
        game = Session()
        before = game.snapshot()
        with mock.patch.object(poker_engine.os, "getrandom", side_effect=BlockingIOError, create=True) as ready:
            with mock.patch.object(poker_engine.os, "GRND_NONBLOCK", 1, create=True):
                with mock.patch.object(random.SystemRandom, "sample", autospec=True) as sample:
                    with self.assertRaisesRegex(RandomNotReady, "Shuffling is getting ready; try again"):
                        game.deal()
                    sample.assert_not_called()
            ready.assert_called_once_with(1, 1)
        self.assertEqual(game.snapshot(), before)

    def test_ready_os_random_uses_the_normal_system_random_sampler(self):
        game = Session()
        cards = hand("JC JD 2H 4S 8C")
        with mock.patch.object(poker_engine.os, "getrandom", return_value=b"x", create=True) as ready:
            with mock.patch.object(poker_engine.os, "GRND_NONBLOCK", 1, create=True):
                with mock.patch.object(random.SystemRandom, "sample", autospec=True, return_value=cards) as sample:
                    game.deal()
                    sample.assert_called_once_with(game._rng, DECK, 5)
            ready.assert_called_once_with(1, 1)
        self.assertEqual(game.phase, "hold")
        self.assertEqual(game.initial, cards)
        self.assertEqual(game.credits, 9900)

    def test_injected_test_sampler_does_not_check_os_readiness(self):
        game = Session(rng=random.Random(10))
        with mock.patch.object(poker_engine.os, "getrandom", side_effect=AssertionError("test RNG must not use OS"), create=True) as ready:
            game.deal()
            game.draw()
            ready.assert_not_called()
        self.assertEqual(game.phase, "result")

    def test_unready_os_random_preserves_a_pending_draw_and_holds(self):
        game = Session()
        cards = hand("JC JD 2H 4S 8C")
        with mock.patch.object(poker_engine.os, "getrandom", return_value=b"x", create=True):
            with mock.patch.object(poker_engine.os, "GRND_NONBLOCK", 1, create=True):
                with mock.patch.object(random.SystemRandom, "sample", autospec=True, return_value=cards):
                    game.deal()
        game.toggle_hold(0)
        game.toggle_hold(1)
        before = game.snapshot()
        with mock.patch.object(poker_engine.os, "getrandom", side_effect=BlockingIOError, create=True):
            with mock.patch.object(poker_engine.os, "GRND_NONBLOCK", 1, create=True):
                with mock.patch.object(random.SystemRandom, "sample", autospec=True) as sample:
                    with self.assertRaises(RandomNotReady):
                        game.draw()
                    sample.assert_not_called()
        self.assertEqual(game.snapshot(), before)

    def test_variable_bets_cycle_and_max_starts_a_hand(self):
        game = Session(rng=random.Random(10))
        self.assertEqual(game.bet_per_hand, 10)
        for expected in (1, 2, 3, 4, 5, 10):
            game.cycle_bet_per_hand()
            self.assertEqual(game.bet_per_hand, expected)
            self.assertEqual(game.total_bet, expected * 10)
            self.assertEqual(game.feature, expected == 10)
            self.assertEqual(game.base_bet, min(expected, 5))
        game.set_bet_per_hand(1)
        game.bet_max()
        self.assertEqual(game.phase, "hold")
        self.assertEqual(game.bet_per_hand, 10)
        self.assertEqual(game.credits, 9900)
        before = game.snapshot()
        for action in (lambda: game.set_bet_per_hand(2), game.cycle_bet_per_hand, game.bet_max):
            with self.assertRaises(ValueError):
                action()
            self.assertEqual(game.snapshot(), before)

    def test_lower_coin_dealt_royals_pay_reduced_schedule(self):
        royal = hand("10H JH QH KH AH")
        for bet, single_payout in ((1, 250), (2, 500), (3, 750), (4, 1000), (5, 4000), (10, 4000)):
            with self.subTest(bet=bet):
                game = Session(rng=ScriptedRandom([royal]))
                game.set_bet_per_hand(bet)
                game.deal()
                self.assertEqual(game.phase, "result")
                self.assertEqual(game.total_win, single_payout * 10)
                self.assertEqual(game.credits, 10000 - 10 * bet + single_payout * 10)
                self.assertEqual(game.multipliers, [4 if bet == 10 else 1] * 10)

    def test_add_free_credits_preserves_current_board_and_multipliers(self):
        game = Session(credits=100, rng=random.Random(10))
        game.deal()
        game.toggle_hold(0)
        before = game.snapshot()
        game.add_credits()
        after = game.snapshot()
        self.assertEqual(after.pop("credits"), before.pop("credits") + 10000)
        self.assertEqual(after, before)
        game.draw()
        before = game.snapshot()
        game.add_credits(500)
        after = game.snapshot()
        self.assertEqual(after.pop("credits"), before.pop("credits") + 500)
        self.assertEqual(after, before)
        for amount in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                game.add_credits(amount)

    def test_max_bet_with_insufficient_credits_configures_without_dealing(self):
        for credits, expected_bet in ((0, 1), (9, 1), (10, 1), (29, 2), (50, 5), (99, 5)):
            with self.subTest(credits=credits):
                game = Session(credits=credits, rng=ScriptedRandom([]))
                game.set_bet_per_hand(1)
                game.set_num_hands(3)
                game.bet_max()
                self.assertEqual(game.phase, "ready")
                self.assertEqual(game.num_hands, 10)
                self.assertEqual(game.bet_per_hand, expected_bet)
                self.assertEqual(game.credits, credits)

    def test_bet_per_hand_reference_affordability_and_five_to_ten_transition(self):
        game = Session(credits=40, rng=ScriptedRandom([]))
        game.set_bet_per_hand(4)
        game.cycle_bet_per_hand()
        self.assertEqual((game.num_hands, game.bet_per_hand), (10, 1))
        # The observed reference checks the five-credit base before allowing
        # the feature step to10, so configured total100 can exceed credits50.
        game = Session(credits=50, rng=ScriptedRandom([]))
        game.set_bet_per_hand(5)
        game.cycle_bet_per_hand()
        self.assertEqual(game.bet_per_hand, 10)
        self.assertEqual(game.credits, 50)
        with self.assertRaises(ValueError):
            game.deal()
        game = Session(credits=10, rng=ScriptedRandom([]))
        game.set_bet_per_hand(1)
        game.set_num_hands(3)
        game.cycle_bet_per_hand()
        self.assertEqual((game.num_hands, game.bet_per_hand), (10, 1))

    def test_selected_hands_only_at_one_credit_and_partial_bet_sequence(self):
        game = Session(rng=random.Random(10))
        with self.assertRaises(ValueError):
            game.set_num_hands(3)
        game.set_bet_per_hand(1)
        self.assertEqual(game.cycle_num_hands()["num_hands"], 1)
        for expected in range(2, 11):
            self.assertEqual(game.cycle_num_hands()["num_hands"], expected)
        game.set_num_hands(3)
        game.cycle_bet_per_hand()
        self.assertEqual((game.num_hands, game.bet_per_hand, game.total_bet), (4, 1, 4))
        game.set_bet_per_hand(2)
        self.assertEqual((game.num_hands, game.bet_per_hand), (10, 2))
        for count in (0, 11, True, 1.5):
            with self.assertRaises(ValueError):
                game.set_num_hands(count)

    def test_first_bet_per_hand_after_result_resets_to_all_ten_one_credit(self):
        cards = hand("JC JD 2H 4S 8C")
        game = Session(rng=ScriptedRandom([cards]))
        game.set_bet_per_hand(2)
        game.deal()
        for index in range(5):
            game.toggle_hold(index)
        game.draw()
        credits, pending = game.credits, list(game.multipliers)
        game.cycle_bet_per_hand()
        self.assertEqual((game.num_hands, game.bet_per_hand, game.phase), (10, 1, "ready"))
        self.assertEqual((game.credits, game.multipliers), (credits, pending))
        self.assertEqual(game.hands, [])
        self.assertEqual(game.results, [])
        game.cycle_bet_per_hand()
        self.assertEqual(game.bet_per_hand, 2)

    def test_select_hands_after_result_does_not_remove_first_bet_reset(self):
        cards = hand("JC JD 2H 4S 8C")
        game = Session(rng=ScriptedRandom([cards]))
        game.set_bet_per_hand(1)
        game.set_num_hands(3)
        game.deal()
        for index in range(5):
            game.toggle_hold(index)
        game.draw()
        game.cycle_num_hands()
        self.assertEqual(game.num_hands, 4)
        game.cycle_bet_per_hand()
        self.assertEqual((game.num_hands, game.bet_per_hand), (10, 1))

    def test_active_hands_draw_separately_and_inactive_multipliers_forfeit(self):
        initial = hand("JC JD 2H 4S 8C")
        sampler = ScriptedRandom([initial])
        game = Session(rng=sampler)
        game.set_bet_per_hand(1)
        game.set_num_hands(3)
        game.multipliers = [2, 3, 4, 8, 10, 12, 2, 3, 4, 8]
        game.deal()
        self.assertEqual(game.round_num_hands, 3)
        self.assertEqual(game.last_bet, 3)
        self.assertEqual(game.multipliers, [1] * 10)
        for index in range(5):
            game.toggle_hold(index)
        game.draw()
        self.assertEqual(len(game.hands), 3)
        self.assertEqual(len(game.results), 3)
        self.assertEqual(game.total_win, 2 + 3 + 4)
        self.assertEqual(game.credits, 10000 - 3 + 9)
        self.assertEqual(game.multipliers, [1] * 10)
        game.set_num_hands(10)
        self.assertEqual(game.multipliers, [1] * 10)

    def test_changing_bets_before_deal_preserves_pending_board(self):
        game = Session()
        pending = [2, 3, 4, 8, 10, 12, 2, 3, 4, 8]
        game.multipliers = list(pending)
        for bet in BET_CHOICES:
            game.set_bet_per_hand(bet)
            self.assertEqual(game.multipliers, pending)
        game.set_bet_per_hand(1)
        game.set_num_hands(1)
        self.assertEqual(game.multipliers, pending)
        game.set_num_hands(10)
        self.assertEqual(game.multipliers, pending)

    def test_default_wager_and_os_rng(self):
        game = Session()
        self.assertIsInstance(game._rng, random.SystemRandom)
        self.assertEqual(game.total_bet, 100)
        self.assertEqual(game.phase, "ready")
        game = Session(rng=random.Random(10))
        game.deal()
        self.assertEqual(game.credits, 9900)
        self.assertEqual(game.phase, "hold")
        game.draw()
        self.assertEqual(len(game.results), 10)
        self.assertEqual(game.credits, 9900 + sum(r["payout"] for r in game.results))

    def test_independent_remaining47_decks_and_hold_positions(self):
        initial = hand("JC JD 2H 4S 8C")
        draw = hand("QC KD AH 6S 7C")[:3]
        sampler = ScriptedRandom([initial] + [draw] * 10)
        game = Session(rng=sampler)
        game.deal()
        game.toggle_hold(0)
        game.toggle_hold(1)
        game.draw()
        self.assertEqual(len(sampler.calls), 11)
        expected = tuple(card for card in DECK if card not in initial)
        for population, count in sampler.calls[1:]:
            self.assertEqual(population, expected)
            self.assertEqual(len(population), 47)
            self.assertEqual(count, 3)
        self.assertEqual(game.hands, [initial[:2] + draw] * 10)
        self.assertEqual(game.total_win, 50)
        self.assertEqual(game.multipliers, [2] * 10)

    def test_all_holds_preserve_hand_and_use_current_not_new_multiplier(self):
        cards = hand("2C 2D 2H KC KD")
        sampler = ScriptedRandom([cards, cards])
        game = Session(rng=sampler)
        game.deal()
        for index in range(5):
            game.toggle_hold(index)
        game.draw()
        self.assertEqual(game.total_win, 450)
        self.assertEqual(game.multipliers, [12] * 10)
        self.assertEqual(game.results[0]["multiplier"], 1)
        self.assertEqual(game.results[0]["next_multiplier"], 12)
        game.deal()
        self.assertEqual(game.active_multipliers, [12] * 10)
        for index in range(5):
            game.toggle_hold(index)
        game.draw()
        self.assertEqual(game.total_win, 5400)
        self.assertEqual(len(sampler.calls), 2)

    def test_bonus_off_consumes_old_multipliers_but_creates_no_new_ones(self):
        cards = hand("JC JD 2H 4S 8C")
        game = Session(rng=ScriptedRandom([cards, cards, cards]))
        game.multipliers = [12, 10, 8, 4, 3, 2, 1, 1, 1, 1]
        game.set_feature(False)
        self.assertEqual(game.total_bet, 50)
        before = game.credits
        game.deal()
        for index in range(5):
            game.toggle_hold(index)
        game.draw()
        expected = 5 * sum([12, 10, 8, 4, 3, 2, 1, 1, 1, 1])
        self.assertEqual(game.total_win, expected)
        self.assertEqual(game.credits, before - 50 + expected)
        self.assertEqual(game.multipliers, [1] * 10)
        game.deal()
        self.assertEqual(game.active_multipliers, [1] * 10)

    def test_dealt_royal_automatically_settles_all_lines(self):
        royal = hand("10H JH QH KH AH")
        sampler = ScriptedRandom([royal])
        game = Session(rng=sampler)
        game.multipliers[3] = 12
        snap = game.deal()
        self.assertEqual(snap["phase"], "result")
        self.assertEqual(game.total_win, 4000 * 21)
        self.assertEqual(game.credits, 10000 - 100 + 84000)
        self.assertEqual(game.held, [True] * 5)
        self.assertEqual(game.multipliers, [4] * 10)
        self.assertEqual(len(sampler.calls), 1)

    def test_insufficient_funds_and_state_errors_do_not_mutate(self):
        game = Session(credits=50, rng=random.Random(10))
        before = game.snapshot()
        with self.assertRaises(ValueError):
            game.deal()
        self.assertEqual(game.snapshot(), before)
        game.set_feature(False)
        game.deal()
        self.assertEqual(game.credits, 0)
        before = game.snapshot()
        for action in (game.deal, lambda: game.set_feature(True),
                       lambda: game.toggle_hold(-1), lambda: game.toggle_hold(True)):
            with self.assertRaises(ValueError):
                action()
            self.assertEqual(game.snapshot(), before)
        game.draw()
        before = game.snapshot()
        with self.assertRaises(ValueError):
            game.draw()
        self.assertEqual(game.snapshot(), before)

    def test_invalid_sampler_and_draw_failure_are_atomic(self):
        bad = Session(rng=ScriptedRandom([[0, 0, 1, 2, 3]]))
        before = bad.snapshot()
        with self.assertRaises(ValueError):
            bad.deal()
        self.assertEqual(bad.snapshot(), before)
        initial = hand("JC JD 2H 4S 8C")
        final = hand("QC KD AH 6S 7C")
        sampler = ScriptedRandom([initial] + [final] * 9 + [[initial[0]] * 5])
        game = Session(rng=sampler)
        game.deal()
        before = game.snapshot()
        with self.assertRaises(ValueError):
            game.draw()
        self.assertEqual(game.snapshot(), before)

    def test_snapshot_is_detached_and_reset_starts_fresh(self):
        game = Session(credits=12345, rng=random.Random(10))
        game.deal()
        snap = game.snapshot()
        snap["hands"][0][0] = 999
        snap["held"][0] = True
        snap["multipliers"][0] = 99
        self.assertNotEqual(game.hands[0][0], 999)
        self.assertFalse(game.held[0])
        self.assertEqual(game.multipliers[0], 1)
        game.draw()
        game.reset()
        self.assertEqual(game.credits, 12345)
        self.assertEqual(game.phase, "ready")
        self.assertEqual(game.multipliers, [1] * 10)

    def test_many_seeded_rounds_preserve_deck_and_accounting_invariants(self):
        game = Session(credits=1_000_000, rng=random.Random(5678))
        for round_number in range(200):
            if round_number % 7 == 0:
                game.set_feature(not game.feature)
            before = game.credits
            cost = game.total_bet
            game.deal()
            if game.phase == "hold":
                for index in range(5):
                    if (round_number + index) % 3 == 0:
                        game.toggle_hold(index)
                initial = set(game.initial)
                game.draw()
                for drawn in game.hands:
                    self.assertEqual(len(set(drawn)), 5)
                    for index, held in enumerate(game.held):
                        if held:
                            self.assertEqual(drawn[index], game.initial[index])
                        else:
                            self.assertNotIn(drawn[index], initial)
            self.assertEqual(game.credits, before - cost + game.total_win)
            self.assertGreaterEqual(game.credits, 0)
            self.assertEqual(game.rounds, round_number + 1)

    def test_invalid_constructor_and_feature_inputs(self):
        for credit in (-1, 1.5, True, "100"):
            with self.assertRaises(ValueError):
                Session(credit)
        game = Session()
        for feature in (1, 0, None, "yes"):
            with self.assertRaises(ValueError):
                game.set_feature(feature)


if __name__ == "__main__":
    unittest.main()
