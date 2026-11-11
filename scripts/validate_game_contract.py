#!/usr/bin/env python3
"""Independent payout fixtures and exact draw-boundary checks.

The literal schedule below was transcribed from the selected official ten-play
9/6 DDB pay screen, rather than imported from the implementation's tables.
This validates mathematical rules and state transitions, not a vendor RNG or
optimal-strategy RTP, physical buttons, display, camera, or signing.
"""
import argparse
import hashlib
import json
from math import comb
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'payload/opt/dino'))
sys.path.insert(0, str(ROOT / 'scripts'))
from poker_engine import Session, evaluate_hand
from validate_math import reference_category

# category, fixed representative hand, ordinary per-coin pay, next-hand X.
# Royal's five-coin jackpot is checked independently below.
FIXTURES = (
    ('royal_flush', (8, 9, 10, 11, 12), 250, 4),
    ('straight_flush', (0, 1, 2, 3, 4), 50, 4),
    ('four_aces_kicker', (12, 25, 38, 51, 0), 400, 4),
    ('four_234_kicker', (0, 13, 26, 39, 12), 160, 4),
    ('four_aces', (12, 25, 38, 51, 4), 160, 4),
    ('four_234', (0, 13, 26, 39, 4), 80, 4),
    ('four_5k', (3, 16, 29, 42, 0), 50, 3),
    ('full_house', (0, 13, 26, 1, 14), 9, 12),
    ('flush', (0, 2, 4, 6, 9), 6, 10),
    ('straight', (0, 14, 28, 42, 4), 4, 8),
    ('three_kind', (0, 13, 26, 1, 3), 3, 4),
    ('two_pair', (0, 13, 1, 14, 3), 1, 3),
    ('high_pair', (9, 22, 0, 2, 4), 1, 2),
    ('nothing', (0, 14, 28, 44, 6), 0, 1),
)


class FixedOutcome:
    def __init__(self, outcome):
        self.outcome = list(outcome)
        self.initial = [c for c in range(52) if c not in outcome][:5]
        self.calls = 0

    def sample(self, population, count):
        self.calls += 1
        assert count == 5
        if self.calls == 1:
            assert tuple(population) == tuple(range(52))
            return self.initial
        assert set(population) == set(range(52)) - set(self.initial)
        return list(self.outcome)


class BoundarySampler:
    def __init__(self, mask):
        self.initial = [0, 14, 28, 44, 6]
        self.held = [bool(mask & (1 << i)) for i in range(5)]
        self.calls = 0
        self.rng = random.Random(20261110 + mask)

    def sample(self, population, count):
        self.calls += 1
        if self.calls == 1:
            assert tuple(population) == tuple(range(52)) and count == 5
            return list(self.initial)
        assert len(population) == len(set(population)) == 47
        assert set(population) == set(range(52)) - set(self.initial)
        assert count == 5 - sum(self.held)
        return self.rng.sample(population, count)


def validate():
    settlement_cases = settled_lines = 0
    for category, cards, per_coin, future_x in FIXTURES:
        assert reference_category(cards) == category == evaluate_hand(cards)
        for bet in (1, 2, 3, 4, 5, 10):
            for active in (range(1, 11) if bet == 1 else (10,)):
                for current_x in (1, 2, 3, 4, 8, 10, 12):
                    sampler = FixedOutcome(cards)
                    game = Session(credits=1_000_000, rng=sampler)
                    game.set_bet_per_hand(bet)
                    if bet == 1:
                        game.set_num_hands(active)
                    game.multipliers = [current_x] * 10
                    game.deal()
                    assert game.phase == 'hold'
                    game.draw()
                    base = 5 if bet == 10 else bet
                    pay = 4000 if category == 'royal_flush' and base == 5 else per_coin * base
                    expected = pay * current_x
                    assert len(game.hands) == len(game.results) == active
                    assert sampler.calls == 1 + active
                    for result in game.results:
                        assert result['category'] == category
                        assert result['payout'] == expected
                    assert game.total_win == expected * active
                    assert game.credits == 1_000_000 - bet * active + expected * active
                    assert game.multipliers == ([future_x] * 10 if bet == 10 else [1] * 10)
                    settlement_cases += 1
                    settled_lines += active

    draw_cases = 0
    for mask in range(32):
        for active in range(1, 11):
            sampler = BoundarySampler(mask)
            game = Session(rng=sampler)
            game.set_bet_per_hand(1)
            game.set_num_hands(active)
            game.deal()
            for i, held in enumerate(sampler.held):
                if held:
                    game.toggle_hold(i)
            game.draw()
            expected_calls = 1 if mask == 31 else 1 + active
            assert sampler.calls == expected_calls
            for hand in game.hands:
                assert len(hand) == len(set(hand)) == 5
                for i, card in enumerate(hand):
                    if sampler.held[i]:
                        assert card == sampler.initial[i]
                    else:
                        assert card not in sampler.initial
            draw_cases += 1

    # Separate OS-backed generator in production; deterministic tests cannot
    # accidentally replace the application's default source of randomness.
    assert isinstance(Session()._rng, random.SystemRandom)
    return {
        'schema': 1, 'status': 'PASS',
        'engine_sha256': hashlib.sha256((ROOT/'payload/opt/dino/poker_engine.py').read_bytes()).hexdigest(),
        'payout_and_multiplier_scenarios': settlement_cases,
        'individual_hand_settlements_checked': settled_lines,
        'independent_literal_paytable': True,
        'draw_boundary_scenarios': draw_cases,
        'hold_masks_checked': 32,
        'active_hand_counts_checked': list(range(1, 11)),
        'every_initial_card_excluded_from_all_replacement_decks': True,
        'draw_probability_contract': {
            'initial_unordered_hand': '1/' + str(comb(52, 5)),
            'replacement_unordered_hand_by_held_card_count': {
                str(held): '1/' + str(comb(47, 5-held)) for held in range(6)
            },
            'basis': 'OS-backed SystemRandom.sample; separate without-replacement sample from the same original remaining47-card population for each active line',
            'note': 'Hands share initial cards and holds; replacement draws are independent conditional on the initial deal',
        },
        'current_multiplier_claimed_at_all_coin_bets': True,
        'inactive_multipliers_forfeited_at_deal': True,
        'new_multipliers_earned_only_at_ten_credits_per_hand': True,
        'vendor_server_or_rng_verified': False,
        'optimal_strategy_rtp_verified': False,
        'physical_hardware_tested': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = json.dumps(validate(), indent=2) + '\n'
    if args.output:
        args.output.write_text(report)
    print(report, end='')


if __name__ == '__main__':
    main()
