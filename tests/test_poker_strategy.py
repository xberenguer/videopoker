"""Independent draw enumeration, continuation scoring and worker lifecycle.

Real-data tests require the packaged strategy files and never silently skip.
Synthetic-table tests separate the scoring/worker contract from generated data.
"""
import copy
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import random
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'payload/opt/dino'))
from poker_engine import CATEGORIES, MULTIPLIERS, PAYOUTS, Session, evaluate_hand
import poker_strategy as strategy

OBSERVATIONS = []


def snapshot(hand=(8, 9, 10, 11, 25), *, feature=True, base=5, hands=10):
    return {'phase': 'hold', 'initial': list(hand), 'round_feature': feature,
            'round_base_bet': base, 'round_num_hands': hands,
            'active_multipliers': [1] * 10}


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('Strategy worker did not produce its expected state')
        time.sleep(.001)


def row(**counts):
    return [counts.get(category, 0) for category in CATEGORIES]


def unpruned_feature_scores(table, hand, multiplier_sum):
    """Integer outcome multiplicities, with no production float/pruning path."""
    scores = []
    for counts in table.counts(hand):
        denominator = sum(counts)
        weights = {}
        for category, count in zip(CATEGORIES, counts):
            if count:
                multiplier = MULTIPLIERS[category]
                weights[multiplier] = weights.get(multiplier, 0) + count
        coefficients = {0: 1}
        for _ in range(10):
            result = {}
            for total, coefficient in coefficients.items():
                for multiplier, count in weights.items():
                    result[total+multiplier] = result.get(total+multiplier, 0) + coefficient*count
            coefficients = result
        future = sum(coefficient * table.bias[total] for total, coefficient in coefficients.items()) / denominator**10
        current = 5 * multiplier_sum * sum(count*PAYOUTS[c] for c, count in zip(CATEGORIES, counts)) / denominator
        scores.append(current + future)
    return scores


class SyntheticTable(strategy.StrategyTable):
    def __init__(self, rows, bias=None):
        self.rows = rows
        self.bias = bias if bias is not None else {s: 0 for s in range(10, 121)}
        self.certificate = 1e-8

    def counts(self, hand, cancel=None):
        strategy._check_cancel(cancel)
        return copy.deepcopy(self.rows)


class SnapshotTests(unittest.TestCase):
    def test_advice_uses_frozen_round_settings_and_detaches_mutable_input(self):
        state = snapshot(feature=False, base=1, hands=3)
        state.update(feature=True, base_bet=5, num_hands=10,
                     multipliers=[12] * 10, held=[True] * 5, credits=0)
        state['active_multipliers'] = [2, 3, 4] + [12] * 7
        before = copy.deepcopy(state)
        frozen = strategy._round(state)
        self.assertEqual(frozen, ((8, 9, 10, 11, 25), False, 1, 3, 9))
        self.assertEqual(state, before)
        state['initial'][0] = 51
        state['active_multipliers'][0] = 12
        self.assertEqual(frozen, ((8, 9, 10, 11, 25), False, 1, 3, 9))

    def test_actual_session_snapshot_and_rng_are_unchanged(self):
        rng = random.Random(250)
        game = Session(rng=rng)
        game.deal()
        before, rng_before = game.snapshot(), rng.getstate()
        strategy._round(before)
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(rng.getstate(), rng_before)

    def test_invalid_cards_phases_and_round_settings_are_rejected(self):
        cases = [None, [], {}, {'phase': 'result'}, {'phase': 'ready'}]
        changes = (
            ('initial', [0, 1, 2, 3]), ('initial', [0, 1, 2, 3, 3]),
            ('initial', [False, 1, 2, 3, 4]), ('initial', [0, 1, 2, 3, 52]),
            ('initial', [0, 1, 2, 3, -1]), ('initial', [0, 1, 2, 3, 4.0]),
            ('round_feature', 1), ('round_base_bet', True),
            ('round_base_bet', 0), ('round_base_bet', 6),
            ('round_num_hands', True), ('round_num_hands', 0),
            ('round_num_hands', 11), ('active_multipliers', [1] * 9),
            ('active_multipliers', [1] * 9 + [True]),
            ('active_multipliers', [1] * 9 + [5]),
            ('round_base_bet', 4), ('round_num_hands', 9),
        )
        for key, value in changes:
            state = snapshot()
            state[key] = value
            cases.append(state)
        for state in cases:
            with self.subTest(state=state):
                with self.assertRaises(strategy.StrategyError):
                    strategy._round(state)


class ScoreTests(unittest.TestCase):
    def test_ordinary_advice_uses_250_royal_below_max_and_800_at_max(self):
        rows = [row(nothing=1) for _ in range(32)]
        rows[1], rows[2] = row(royal_flush=1, nothing=99), row(three_kind=1)
        table = SyntheticTable(rows)
        low = table.advise(((8, 9, 10, 11, 25), False, 1, 3, 3))
        maximum = table.advise(((8, 9, 10, 11, 25), False, 5, 10, 10))
        self.assertEqual(low['mask'], 2)  # 3 beats a 2.5-credit royal attempt.
        self.assertEqual(low['expected_current_win'], 9)
        self.assertEqual(maximum['mask'], 1)  # 8 beats 3 per base credit.
        self.assertEqual(maximum['expected_current_win'], 400)
        self.assertEqual(maximum['value'], maximum['expected_current_win'])
        self.assertEqual(maximum['evaluated_holds'], 32)
        self.assertEqual(maximum['continuation_bellman_span'], 0)

    def test_feature_advice_can_trade_immediate_win_for_next_multipliers(self):
        rows = [row(nothing=1) for _ in range(32)]
        rows[1], rows[2] = row(four_5k=1), row(full_house=1)
        table = SyntheticTable(rows, {s: 30*s + 7 for s in range(10, 121)})
        answer = table.advise(((8, 9, 10, 11, 25), True, 5, 10, 10))
        self.assertEqual(answer['mask'], 2)
        self.assertEqual(answer['expected_current_win'], 450)
        self.assertEqual(answer['value'], 450 + 30*120 + 7)
        self.assertLess(answer['evaluated_holds'], 32)
        self.assertEqual(answer['continuation_bellman_span'], 1e-8)

    def test_nonlinear_continuation_uses_distribution_not_just_mean(self):
        rows = [row(nothing=1) for _ in range(32)]
        rows[5] = row(high_pair=1, nothing=1)
        table = SyntheticTable(rows, {s: 100*s*s for s in range(10, 121)})
        answer = table.advise(((8, 9, 10, 11, 25), True, 5, 10, 10))
        expected_bias = sum(math.comb(10, k) * table.bias[10+k] for k in range(11)) / 1024
        self.assertEqual(answer['mask'], 5)
        self.assertAlmostEqual(answer['value'], 25 + expected_bias)
        self.assertGreater(answer['value'], 25 + table.bias[15])

    def test_all_32_scores_match_independent_binomial_formula_under_pruning(self):
        rows, categories = [], []
        for mask in range(32):
            a, b = CATEGORIES[(mask*5+2) % 14], CATEGORIES[(mask*3+9) % 14]
            counts = dict.fromkeys(CATEGORIES, 0)
            counts[a] += 1
            counts[b] += 1
            rows.append(row(**counts))
            categories.append((a, b))
        bias = {s: (s % 7)**2*100 + s*11 for s in range(10, 121)}
        reference = []
        for a, b in categories:
            current = 5*24*(PAYOUTS[a] + PAYOUTS[b])/2
            future = sum(math.comb(10, k) * bias[k*MULTIPLIERS[a]+(10-k)*MULTIPLIERS[b]]
                         for k in range(11))/1024
            reference.append(current + future)
        best = max(reference)
        expected = max((m for m, value in enumerate(reference) if best-value <= 1e-9),
                       key=lambda m: (bin(m).count('1'), -m))
        answer = SyntheticTable(rows, bias).advise(((8, 9, 10, 11, 25), True, 5, 10, 24))
        self.assertEqual(answer['mask'], expected)
        self.assertAlmostEqual(answer['value'], best, places=8)

    def test_equal_values_prefer_more_held_cards_then_lower_mask(self):
        rows = [row(nothing=1) for _ in range(32)]
        for mask in (3, 5, 7, 11):
            rows[mask] = row(high_pair=1)
        answer = SyntheticTable(rows).advise(((8, 9, 10, 11, 25), False, 5, 10, 10))
        self.assertEqual(answer['mask'], 7)
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(strategy._Cancelled):
            SyntheticTable(rows).advise(((8, 9, 10, 11, 25), True, 5, 10, 10), cancelled)


class PackagedTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Missing or invalid production data is a test failure, never a skip.
        cls.table = strategy.StrategyTable()

    def test_all_hold_sizes_have_exact_remaining_47_card_denominators(self):
        for hand in ((12, 25, 38, 51, 0), (8, 9, 10, 11, 25), (9, 22, 10, 36, 50)):
            with self.subTest(hand=hand):
                rows = self.table.counts(hand)
                self.assertEqual(len(rows), 32)
                for mask, counts in enumerate(rows):
                    self.assertEqual(len(counts), 14)
                    self.assertTrue(all(type(n) is int and n >= 0 for n in counts))
                    self.assertEqual(sum(counts), math.comb(47, 5-bin(mask).count('1')))

    def test_every_three_four_and_five_card_hold_matches_direct_draw_enumeration(self):
        # Quads/kickers, blocked royal/flush cards, wheel and two-pair/full-house
        # boundaries are deliberately overrepresented instead of random deals.
        hands = ((12, 25, 38, 51, 0), (0, 13, 26, 39, 12),
                 (8, 9, 10, 11, 25), (12, 0, 1, 2, 16),
                 (9, 22, 10, 36, 50), (1, 14, 27, 8, 21))
        for hand in hands:
            rows = self.table.counts(hand)
            remaining = tuple(card for card in range(52) if card not in hand)
            for mask in range(32):
                if bin(mask).count('1') < 3:
                    continue
                held = tuple(hand[i] for i in range(5) if mask & (1 << i))
                expected = dict.fromkeys(CATEGORIES, 0)
                for drawn in combinations(remaining, 5-len(held)):
                    expected[evaluate_hand(held+drawn)] += 1
                with self.subTest(hand=hand, mask=mask):
                    self.assertEqual(rows[mask], [expected[c] for c in CATEGORIES])
        # The off-suit dealt ace must not be returned when drawing to four clubs.
        blocked = self.table.counts((8, 9, 10, 11, 25))[15]
        self.assertEqual(blocked[CATEGORIES.index('royal_flush')], 1)
        self.assertEqual(blocked[CATEGORIES.index('straight')], 5)

    def test_counts_and_best_mask_follow_card_order_and_suit_permutations(self):
        hand = (8, 9, 10, 11, 25)
        order, suits = (4, 1, 3, 0, 2), (3, 2, 0, 1)
        changed = tuple(suits[hand[i]//13]*13 + hand[i] % 13 for i in order)
        old, new = self.table.counts(hand), self.table.counts(changed)
        for mask in range(32):
            original_mask = sum(1 << order[i] for i in range(5) if mask & (1 << i))
            self.assertEqual(new[mask], old[original_mask])
        first = self.table.advise(strategy._round(snapshot(hand, feature=False)))
        second = self.table.advise(strategy._round(snapshot(changed, feature=False)))
        self.assertEqual(first['mask'], 15)
        self.assertEqual(second['mask'], 30)
        self.assertEqual(first['value'], second['value'])

    def test_feature_advice_matches_unpruned_integer_reference_for_real_data(self):
        observations = []
        for hand in ((8, 9, 10, 11, 25), (9, 22, 10, 36, 50)):
            for multiplier in (1, 8):
                state = snapshot(hand)
                state['active_multipliers'] = [multiplier] * 10
                began = time.monotonic()
                reference = unpruned_feature_scores(self.table, hand, 10*multiplier)
                reference_ms = (time.monotonic()-began)*1000
                began = time.monotonic()
                answer = self.table.advise(strategy._round(state))
                advice_ms = (time.monotonic()-began)*1000
                best = max(reference)
                expected = max((m for m, value in enumerate(reference) if best-value <= 1e-9),
                               key=lambda m: (bin(m).count('1'), -m))
                with self.subTest(hand=hand, current_multiplier=multiplier):
                    self.assertEqual(answer['mask'], expected)
                    self.assertAlmostEqual(answer['value'], best, places=7)
                observations.append({'hand': list(hand), 'current_multiplier': multiplier,
                                     'mask': answer['mask'], 'evaluated_holds': answer['evaluated_holds'],
                                     'host_unpruned_reference_ms': reference_ms,
                                     'host_production_advice_ms': advice_ms})
        OBSERVATIONS.append({'scenario': 'real-feature-advice-vs-unpruned-integer-convolution',
                             'status': 'PASS', 'cases': observations,
                             'scope': 'Host-only calculation timings; no physical Pi or latency claim'})


class DataValidationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name)
        raw = bytearray(4449110)
        struct.pack_into('<8s6I4Q', raw, 0, b'UXSUB01\0', 1, 64, 14, 52, 4, 0,
                         64, 4449046, 0, 0)
        self.raw = bytes(raw)
        states = {0}
        for _ in range(10):
            states = {s+m for s in states for m in (1, 2, 3, 4, 8, 10, 12)}
        self.metadata = {'schema': 1, 'category_order': list(CATEGORIES),
                         'payouts': [PAYOUTS[c] for c in CATEGORIES],
                         'multiplier_order': [MULTIPLIERS[c] for c in CATEGORIES],
                         'table_sha256': hashlib.sha256(self.raw).hexdigest(),
                         'bias': {'num_hands': 10, 'states': sorted(states),
                                  'values': [0] * len(states), 'bellman_span': 0}}
        self.write()

    def write(self):
        (self.directory/'subset_counts.dat').write_bytes(self.raw)
        (self.directory/'strategy.json').write_text(json.dumps(self.metadata))

    def test_valid_structural_fixture_loads_but_bad_histograms_fail_closed(self):
        table = strategy.StrategyTable(self.directory)
        with self.assertRaises(strategy.StrategyError):
            table.counts((8, 9, 10, 11, 25))

    def test_bad_hash_header_paytable_and_continuation_are_rejected(self):
        original = copy.deepcopy(self.metadata)
        changes = (
            lambda m: m.update(schema=2),
            lambda m: m.update(table_sha256='0'*64),
            lambda m: m['payouts'].__setitem__(0, 250),
            lambda m: m['category_order'].reverse(),
            lambda m: m['multiplier_order'].__setitem__(0, 12),
            lambda m: m['bias'].update(num_hands=3),
            lambda m: m['bias']['states'].pop(),
            lambda m: m['bias']['values'].pop(),
            lambda m: m['bias']['values'].__setitem__(0, float('nan')),
            lambda m: m['bias']['values'].__setitem__(0, float('inf')),
            lambda m: m['bias'].update(bellman_span=1e-5),
            lambda m: m['bias'].update(bellman_span=-1),
        )
        for change in changes:
            self.metadata = copy.deepcopy(original)
            change(self.metadata)
            self.write()
            with self.assertRaises(strategy.StrategyError):
                strategy.StrategyTable(self.directory)
        self.metadata = copy.deepcopy(original)
        self.raw = b'INVALID!' + self.raw[8:]
        self.metadata['table_sha256'] = hashlib.sha256(self.raw).hexdigest()
        self.write()
        with self.assertRaises(strategy.StrategyError):
            strategy.StrategyTable(self.directory)

    def test_missing_truncated_oversized_and_symlinked_data_are_rejected(self):
        table_file, metadata_file = self.directory/'subset_counts.dat', self.directory/'strategy.json'
        table_file.unlink()
        with self.assertRaises(strategy.StrategyError):
            strategy.StrategyTable(self.directory)
        self.write()
        table_file.write_bytes(self.raw[:-1])
        with self.assertRaises(strategy.StrategyError):
            strategy.StrategyTable(self.directory)
        self.write()
        metadata_file.write_text(' ' * 100001)
        with self.assertRaises(strategy.StrategyError):
            strategy.StrategyTable(self.directory)
        self.write()
        actual = self.directory/'other.dat'
        table_file.rename(actual)
        table_file.symlink_to(actual)
        with self.assertRaises(strategy.StrategyError):
            strategy.StrategyTable(self.directory)

    def test_malformed_json_root_and_bias_fail_with_strategy_error(self):
        metadata_file = self.directory/'strategy.json'
        for invalid in ([], None, 1, {'bias': []}, {'bias': None}):
            value = copy.deepcopy(self.metadata)
            if isinstance(invalid, dict):
                value.update(invalid)
            else:
                value = invalid
            metadata_file.write_text(json.dumps(value))
            with self.subTest(value=value):
                with self.assertRaises(strategy.StrategyError):
                    strategy.StrategyTable(self.directory)


class WorkerTests(unittest.TestCase):
    def make_advisor(self, factory):
        advisor = strategy.StrategyAdvisor(table_factory=factory)
        self.addCleanup(advisor.close)
        return advisor

    def answer(self, advisor, token):
        wait_for(lambda: advisor.poll(token) is not None)
        return advisor.poll(token)

    def test_request_and_poll_never_load_or_solve_on_the_calling_thread(self):
        loading, release, factory_returned, request_done = [threading.Event() for _ in range(4)]
        caller, worker = [], []
        class Table:
            def advise(self, frozen, cancel):
                worker.append(threading.get_ident())
                return {'mask': 15}
        def factory(directory):
            worker.append(threading.get_ident())
            loading.set()
            if not release.wait(3):
                raise AssertionError('Test did not release its table loader')
            factory_returned.set()
            return Table()
        advisor = self.make_advisor(factory)
        tokens = []
        def request():
            caller.append(threading.get_ident())
            tokens.append(advisor.request(snapshot()))
            request_done.set()
        client = threading.Thread(target=request)
        client.start()
        try:
            self.assertTrue(loading.wait(1))
            self.assertTrue(request_done.wait(1))
            self.assertFalse(factory_returned.is_set())
            self.assertIsNone(advisor.poll(tokens[0]))
        finally:
            release.set()
            client.join(2)
        self.assertEqual(self.answer(advisor, tokens[0]), {'mask': 15})
        self.assertTrue(all(thread != caller[0] for thread in worker))

    def test_new_request_and_cancel_discard_stale_results_and_cache_entries(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        class Table:
            def advise(self, frozen, cancel):
                calls.append(frozen)
                if len(calls) == 1:
                    entered.set()
                    release.wait(3)  # Deliberately ignore cancel, like a slow native call.
                return {'mask': frozen[0][0]}
        advisor = self.make_advisor(lambda directory: Table())
        old_state, new_state = snapshot(), snapshot((0, 1, 2, 3, 4))
        old = advisor.request(old_state)
        self.assertTrue(entered.wait(1))
        new = advisor.request(new_state)
        release.set()
        self.assertEqual(self.answer(advisor, new), {'mask': 0})
        self.assertIsNone(advisor.poll(old))
        again = advisor.request(old_state)
        self.assertEqual(self.answer(advisor, again), {'mask': 8})
        self.assertEqual(len(calls), 3)  # The cancelled first answer was not cached.
        advisor.cancel()
        self.assertIsNone(advisor.poll(again))

    def test_poll_is_detached_and_lru_cache_is_bounded_to_sixteen(self):
        calls = []
        class Table:
            def advise(self, frozen, cancel):
                calls.append(frozen)
                return {'mask': frozen[0][0]}
        advisor = self.make_advisor(lambda directory: Table())
        first_state = snapshot((0, 1, 2, 3, 4))
        token = advisor.request(first_state)
        value = self.answer(advisor, token)
        value['mask'] = 999
        self.assertEqual(advisor.poll(token), {'mask': 0})
        self.answer(advisor, advisor.request(first_state))
        self.assertEqual(len(calls), 1)
        for start in range(1, 17):
            self.answer(advisor, advisor.request(snapshot(tuple(range(start, start+5)))))
        self.answer(advisor, advisor.request(first_state))
        self.assertEqual(len(calls), 18)

    def test_worker_failures_leave_snapshot_unchanged_and_manual_play_available(self):
        calls = []
        class Table:
            def advise(self, frozen, cancel):
                calls.append(frozen)
                if len(calls) == 1:
                    raise OSError('corrupt table / solver unavailable')
                return {'mask': 15}
        advisor = self.make_advisor(lambda directory: Table())
        state = snapshot()
        before = copy.deepcopy(state)
        error = self.answer(advisor, advisor.request(state))
        self.assertEqual(error, {'error': 'Advice unavailable; use manual play'})
        self.assertEqual(state, before)
        self.assertEqual(self.answer(advisor, advisor.request(state)), {'mask': 15})

    def test_close_cancels_work_joins_and_rejects_future_requests(self):
        entered, cancelled = threading.Event(), threading.Event()
        class Table:
            def advise(self, frozen, cancel):
                entered.set()
                if cancel.wait(3):
                    cancelled.set()
                return {'mask': 15}
        advisor = self.make_advisor(lambda directory: Table())
        token = advisor.request(snapshot())
        self.assertTrue(entered.wait(1))
        advisor.close()
        self.assertTrue(cancelled.is_set())
        self.assertFalse(advisor._thread.is_alive())
        self.assertIsNone(advisor.poll(token))
        with self.assertRaises(strategy.StrategyError):
            advisor.request(snapshot())

    def test_uncooperative_worker_close_uses_bounded_join_and_fails_closed(self):
        entered, release = threading.Event(), threading.Event()
        class Table:
            def advise(self, frozen, cancel):
                entered.set()
                release.wait(3)
                return {'mask': 15}
        advisor = strategy.StrategyAdvisor(table_factory=lambda directory: Table())
        advisor.request(snapshot())
        self.assertTrue(entered.wait(1))
        try:
            # Assert the real shutdown contract without spending two seconds on
            # an intentionally uncooperative test worker or changing production.
            with mock.patch.object(advisor._thread, 'join') as join:
                with self.assertRaises(strategy.StrategyError):
                    advisor.close()
                join.assert_called_once_with(timeout=2.0)
            self.assertTrue(advisor._closed)
            with self.assertRaises(strategy.StrategyError):
                advisor.request(snapshot())
        finally:
            release.set()
            advisor.close()
        self.assertFalse(advisor._thread.is_alive())


if __name__ == '__main__':
    unittest.main()
