#!/usr/bin/env python3
"""Exhaustively compare the production evaluator with an independent oracle.

Checks all C(52,5)=2,598,960 hands and exact combinatorial category counts.
This is NOT a draw-strategy/RTP analysis, RNG certification or device test.
"""
import argparse
from collections import Counter
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "payload/opt/dino"))
from poker_engine import CATEGORIES, MULTIPLIERS, PAYOUTS, evaluate_hand

EXPECTED_COUNTS = {
    "royal_flush": 4,
    "straight_flush": 36,
    "four_aces_kicker": 12,
    "four_234_kicker": 36,
    "four_aces": 36,
    "four_234": 108,
    "four_5k": 432,
    "full_house": 3744,
    "flush": 5108,
    "straight": 10200,
    "three_kind": 54912,
    "two_pair": 123552,
    "high_pair": 337920,
    "nothing": 2062860,
}
STRAIGHT_MASKS = frozenset([0b11111 << shift for shift in range(9)] + [0b1000000001111])
ROYAL_MASK = 0b11111 << 8


def reference_category(cards):
    # Independent array/bitset classifier. The exhaustive iterator guarantees
    # valid identities, so it deliberately does not reuse production validation.
    frequency = [0] * 13
    suits = [0] * 4
    rank_bits = 0
    for card in cards:
        rank = card % 13
        frequency[rank] += 1
        rank_bits |= 1 << rank
        suits[card // 13] += 1
    same_suit = 5 in suits
    is_straight = rank_bits in STRAIGHT_MASKS
    if same_suit and is_straight:
        return "royal_flush" if rank_bits == ROYAL_MASK else "straight_flush"
    for rank, count in enumerate(frequency):
        if count == 4:
            kicker = frequency.index(1)
            if rank == 12:
                return "four_aces_kicker" if kicker < 3 else "four_aces"
            if rank < 3:
                return "four_234_kicker" if kicker < 3 or kicker == 12 else "four_234"
            return "four_5k"
    if 3 in frequency:
        return "full_house" if 2 in frequency else "three_kind"
    if same_suit:
        return "flush"
    if is_straight:
        return "straight"
    pairs = frequency.count(2)
    if pairs == 2:
        return "two_pair"
    if pairs == 1 and frequency.index(2) >= 9:
        return "high_pair"
    return "nothing"


def validate():
    started = time.monotonic()
    counts = Counter()
    for cards in combinations(range(52), 5):
        actual = evaluate_hand(cards)
        expected = reference_category(cards)
        if actual != expected:
            raise AssertionError({"cards": cards, "actual": actual, "expected": expected})
        counts[actual] += 1
    if dict(counts) != EXPECTED_COUNTS:
        raise AssertionError({"counts": counts, "expected": EXPECTED_COUNTS})
    return {
        "schema": 1,
        "status": "PASS",
        "game": "Independent 10-hand 9/6 Double Double Bonus with next-hand multipliers",
        "engine_sha256": hashlib.sha256((ROOT / "payload/opt/dino/poker_engine.py").read_bytes()).hexdigest(),
        "hands_compared": sum(counts.values()),
        "independent_evaluator_mismatches": 0,
        "category_counts": {category: counts[category] for category in CATEGORIES},
        "base_bet_credits_per_hand": 5,
        "bonus_bet_credits_per_hand": 5,
        "payout_per_base_credit": PAYOUTS,
        "ten_hand_next_multiplier": MULTIPLIERS,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "scope": "Exhaustive five-card classification and combinatorial counts; unit tests separately cover multi-hand state transitions",
        "rtp_or_optimal_strategy_verified": False,
        "physical_hardware_tested": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = validate()
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
