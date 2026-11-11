"""Offline ten-hand 9/6 Double Double Bonus with next-deal multipliers.

Original implementation; no vendor code, artwork, network, account, wallet or
storage access. Credits have no monetary value. This module uses a private OS
SystemRandom instance in production; injected samplers exist only for tests.
Cards are integers 0..51: rank = card % 13 + 2; suits are C, D, H, S.
"""

import os
import random
from poker_games import get_game
from poker_evaluate import evaluate_game_hand


NUM_HANDS = 10
BASE_BET = 5
BET_CHOICES = (1, 2, 3, 4, 5, 10)
STARTING_CREDITS = 10_000
PAYTABLE = "9/6 Double Double Bonus"
DECK = tuple(range(52))
CATEGORIES = (
    "royal_flush", "straight_flush", "four_aces_kicker", "four_234_kicker",
    "four_aces", "four_234", "four_5k", "full_house", "flush", "straight",
    "three_kind", "two_pair", "high_pair", "nothing",
)
# Per base credit. Royal flush uses the five-credit (max base bet) award.
PAYOUTS = dict(zip(CATEGORIES, (800, 50, 400, 160, 160, 80, 50, 9, 6, 4, 3, 1, 1, 0)))
# Classic ten-play schedule; different from the three/five-play schedules.
MULTIPLIERS = dict(zip(CATEGORIES, (4, 4, 4, 4, 4, 4, 3, 12, 10, 8, 4, 3, 2, 1)))
LABELS = dict(zip(CATEGORIES, (
    "Royal flush", "Straight flush", "4 aces + 2-4", "4 2-4 + A-4",
    "4 aces", "4 2-4", "4 5-K", "Full house", "Flush", "Straight",
    "3 of a kind", "Two pair", "Jacks or better", "No win",
)))


class RandomNotReady(ValueError):
    """The OS has not finished initializing its secure random generator."""


def _cards(cards, deck_size=52):
    """Validate card identity without accepting booleans as card integers."""
    try:
        result = tuple(cards)
    except TypeError as error:
        raise ValueError("A hand must contain five cards") from error
    if (len(result) != 5 or any(type(card) is not int or not 0 <= card < deck_size
                                for card in result) or len(set(result)) != 5):
        raise ValueError("A hand must contain five distinct cards from 0 through 51")
    return result


def evaluate_hand(cards):
    """Return the highest-paying non-wild 9/6 DDB category for five cards."""
    cards = _cards(cards)
    ranks = sorted(card % 13 + 2 for card in cards)
    flush = all(card // 13 == cards[0] // 13 for card in cards[1:])
    counts = {}
    for rank in ranks:
        counts[rank] = counts.get(rank, 0) + 1
    straight = len(counts) == 5 and (ranks[-1] - ranks[0] == 4 or ranks == [2, 3, 4, 5, 14])
    if flush and straight:
        return "royal_flush" if ranks[0] == 10 else "straight_flush"
    if 4 in counts.values():
        four = next(rank for rank, count in counts.items() if count == 4)
        kicker = next(rank for rank, count in counts.items() if count == 1)
        if four == 14:
            return "four_aces_kicker" if kicker in (2, 3, 4) else "four_aces"
        if four in (2, 3, 4):
            return "four_234_kicker" if kicker in (14, 2, 3, 4) else "four_234"
        return "four_5k"
    groups = sorted(counts.values(), reverse=True)
    if groups == [3, 2]:
        return "full_house"
    if flush:
        return "flush"
    if straight:
        return "straight"
    if groups[0] == 3:
        return "three_kind"
    if groups[:2] == [2, 2]:
        return "two_pair"
    if any(count == 2 and rank >= 11 for rank, count in counts.items()):
        return "high_pair"
    return "nothing"


def card_label(card):
    if type(card) is not int or not 0 <= card < 52:
        raise ValueError("Invalid card")
    rank = card % 13 + 2
    return ({11: "J", 12: "Q", 13: "K", 14: "A"}.get(rank, str(rank))
            + "CDHS"[card // 13])


def payout_for(category, base_bet=BASE_BET):
    """Base win before an existing multiplier, in play credits.

    The official pay screen shows royal250/500/750/1000/4000 for base
    wagers1/2/3/4/5. All other winning categories scale linearly.
    """
    if category not in PAYOUTS or type(base_bet) is not int or not 1 <= base_bet <= 5:
        raise ValueError("Invalid paytable category or base wager")
    per_coin = 250 if category == "royal_flush" and base_bet < 5 else PAYOUTS[category]
    return base_bet * per_coin


class Session:
    """Atomic deal/draw state machine for one RAM-only ten-hand session.

    ``multipliers`` always describes the NEXT deal. ``active_multipliers`` is
    frozen at the start of the current/last round for correct result rendering.
    Total per-hand wagers1..5 are ordinary draw poker;10 pays a five-credit
    base plus five-credit feature wager. Only10 earns future multipliers.
    """

    def __init__(self, credits=STARTING_CREDITS, rng=None, game_id="ddb10", cabinet_defaults=False):
        if type(credits) is not int or credits < 0:
            raise ValueError("Starting credits must be a non-negative integer")
        self.game = get_game(game_id)
        self.deck = tuple(range(self.game.deck_size))
        self._cabinet_defaults = bool(cabinet_defaults)
        self._starting_credits = credits
        self._rng = random.SystemRandom() if rng is None else rng
        self.reset()

    @property
    def max_hands(self):
        return self.game.hands

    @property
    def paytable(self):
        categories=self.game.categories
        return str(self.game.pays[categories.index('full_house')])+'/'+str(self.game.pays[categories.index('flush')])+' '+self.game.title

    @property
    def base_bet(self):
        return 5 if self.bet_per_hand == 10 else self.bet_per_hand

    @property
    def feature(self):
        return self.bet_per_hand == 10

    @property
    def total_bet(self):
        return self.num_hands * self.bet_per_hand

    def reset(self):
        """Start a new free-credit session; never write or restore SD state."""
        self.credits = self._starting_credits
        self.phase = "ready"
        self.bet_per_hand = 1 if self._cabinet_defaults else 10
        self.num_hands = 1 if self._cabinet_defaults else self.max_hands
        self.initial = []
        self.held = [False] * 5
        self.hands = []
        self.results = []
        self.multipliers = [1] * self.max_hands
        self.active_multipliers = [1] * self.max_hands
        self.round_feature = self.feature
        self.round_base_bet = self.base_bet
        self.round_bet_per_hand = self.bet_per_hand
        self.round_num_hands = self.num_hands
        self._reset_on_bet = False
        self.last_bet = 0
        self.total_win = 0
        self.rounds = 0
        return self.snapshot()

    def snapshot(self):
        """Return a detached, JSON-compatible view for renderers and tests."""
        return {
            "credits": self.credits, "phase": self.phase, "feature": self.feature,
            "base_bet": self.base_bet, "bet_per_hand": self.bet_per_hand,
            "bet_choices": list(BET_CHOICES), "total_bet": self.total_bet,
            "last_bet": self.last_bet, "total_win": self.total_win,
            "rounds": self.rounds, "num_hands": self.num_hands,
            "max_hands": self.max_hands, "paytable": self.paytable,
            "game_id":self.game.id, "game_title":self.game.title,
            "family":self.game.family, "deck_size":self.game.deck_size,
            "round_feature": self.round_feature,
            "round_base_bet": self.round_base_bet,
            "round_bet_per_hand": self.round_bet_per_hand,
            "round_num_hands": self.round_num_hands,
            "initial": list(self.initial), "held": list(self.held),
            "hands": [list(hand) for hand in self.hands],
            "results": [dict(result) for result in self.results],
            "multipliers": list(self.multipliers),
            "active_multipliers": list(self.active_multipliers),
        }

    def set_feature(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("Feature must be on or off")
        if self.phase == "hold":
            raise ValueError("Finish the current hand before changing the feature")
        return self.set_bet_per_hand(10 if enabled else min(5, self.bet_per_hand))

    def set_bet_per_hand(self, value):
        if type(value) is not int or value not in BET_CHOICES:
            raise ValueError("Bet per hand must be 1, 2, 3, 4, 5 or 10 credits")
        if self.phase == "hold":
            raise ValueError("Finish the current hand before changing the bet")
        self.bet_per_hand = value
        if value > 1:
            self.num_hands = self.max_hands
        self._clear_round_for_bet_change()
        return self.snapshot()

    def cycle_bet_per_hand(self):
        if self.phase == "hold":
            raise ValueError("Finish the current hand before changing the bet")
        # The observed reference resets all ten lines to one credit the first
        # time BET PER HAND is pressed after a completed round.
        if self._reset_on_bet:
            self.num_hands = self.max_hands
            return self.set_bet_per_hand(1)
        # Match the reference's all-lines affordability check, including the
        # partial-board case; its check caps at five before the5->10 transition.
        minimum_next_cost = self.max_hands * min(self.bet_per_hand + 1, BASE_BET)
        if self.credits < minimum_next_cost:
            self.num_hands = self.max_hands
            return self.set_bet_per_hand(1)
        # At one-credit partial boards, BET PER HAND activates one more line.
        if self.num_hands < self.max_hands:
            return self.set_num_hands(self.num_hands + 1)
        index = BET_CHOICES.index(self.bet_per_hand)
        return self.set_bet_per_hand(BET_CHOICES[(index + 1) % len(BET_CHOICES)])

    def _clear_round_for_bet_change(self, clear_bet_reset=True):
        self.phase = "ready"
        self.initial = []
        self.held = [False] * 5
        self.hands = []
        self.results = []
        self.total_win = 0
        if clear_bet_reset:
            self._reset_on_bet = False

    def set_num_hands(self, count):
        if type(count) is not int or not 1 <= count <= self.max_hands:
            raise ValueError("Choose from 1 through 10 active hands")
        if self.phase == "hold":
            raise ValueError("Finish the current hand before changing active hands")
        if self.bet_per_hand != 1:
            raise ValueError("Select hands is available only at 1 credit per hand")
        self.num_hands = count
        # SELECT HANDS does not clear the reference's post-round resetOnBet.
        self._clear_round_for_bet_change(clear_bet_reset=False)
        return self.snapshot()

    def cycle_num_hands(self):
        return self.set_num_hands(self.num_hands % self.max_hands + 1)

    set_active_hands = set_num_hands
    cycle_active_hands = cycle_num_hands

    def bet_max(self):
        """The official BET MAX button sets10 credits AND starts a game."""
        if self.phase == "hold":
            raise ValueError("Finish the current hand before changing the bet")
        if self.credits < 10*self.max_hands:
            # The reference chooses affordable ordinary coins, capped at five,
            # without starting a deal. Its tiny-balance fallback selects one
            # credit on every line even if that board is not yet affordable.
            affordable = max(1, min(5, self.credits // self.max_hands))
            self.num_hands = self.max_hands
            return self.set_bet_per_hand(affordable)
        old = (self.bet_per_hand, self.num_hands)
        self.bet_per_hand, self.num_hands = 10, self.max_hands
        try:
            return self.deal()
        except Exception:
            self.bet_per_hand, self.num_hands = old
            raise

    def add_credits(self, amount=STARTING_CREDITS):
        """Add free play credits without resetting cards or earned multipliers."""
        if type(amount) is not int or amount <= 0:
            raise ValueError("Added credits must be a positive integer")
        self.credits += amount
        return self.snapshot()

    def _sample(self, population, count):
        if isinstance(self._rng, random.SystemRandom) and hasattr(os, "getrandom"):
            # Linux's blocking urandom path must not freeze the display or the
            # signer gesture during early boot. Never substitute a weaker RNG.
            try:
                os.getrandom(1, os.GRND_NONBLOCK)
            except BlockingIOError as error:
                raise RandomNotReady("Shuffling is getting ready; try again") from error
        drawn = list(self._rng.sample(population, count))
        if (len(drawn) != count or len(set(drawn)) != count
                or any(type(card) is not int or card not in population for card in drawn)):
            raise ValueError("Random source returned an invalid draw")
        return drawn

    def deal(self):
        if self.phase not in ("ready", "result"):
            raise ValueError("Draw the current hand before dealing again")
        cost = self.total_bet
        if self.credits < cost:
            raise ValueError("Not enough credits; add free credits or lower the bet")
        # All failure-prone generation/validation precedes any state mutation.
        cards = self._sample(self.deck, 5)
        royal = evaluate_game_hand(cards,self.game) == "royal_flush"
        active = list(self.multipliers)
        if (len(active) != self.max_hands or any(type(value) is not int or value not in
                self.game.possible_multipliers for value in active)):
            raise ValueError("Invalid multiplier state")
        self.credits -= cost
        self.last_bet = cost
        self.initial = cards
        self.held = [royal] * 5
        self.hands = [list(cards) for _ in range(self.num_hands)]
        self.results = []
        self.active_multipliers = active
        # Classic Ultimate X consumes the pending board on the next deal.
        # Choosing fewer hands forfeits pending bonuses at inactive positions.
        self.multipliers = [1] * self.max_hands
        self.round_feature = self.feature
        self.round_base_bet = self.base_bet
        self.round_bet_per_hand = self.bet_per_hand
        self.round_num_hands = self.num_hands
        self.total_win = 0
        self.phase = "hold"
        if royal:
            # The documented game automatically holds and pays a dealt royal.
            return self.draw()
        return self.snapshot()

    def toggle_hold(self, index):
        if self.phase != "hold":
            raise ValueError("Cards can be held only after the deal")
        if type(index) is not int or not 0 <= index < 5:
            raise ValueError("Card position must be from 0 through 4")
        self.held[index] = not self.held[index]
        return self.snapshot()

    def draw(self):
        if self.phase != "hold":
            raise ValueError("Deal a hand before drawing")
        initial = _cards(self.initial,self.game.deck_size)
        if len(self.held) != 5 or any(type(held) is not bool for held in self.held):
            raise ValueError("Invalid hold state")
        remaining = tuple(card for card in self.deck if card not in initial)
        replacements = 5 - sum(self.held)
        hands, results = [], []
        following = list(self.multipliers)
        for position, multiplier in enumerate(self.active_multipliers[:self.round_num_hands]):
            # Each line samples separately from the SAME original 47 cards.
            # A discarded initial card cannot reappear on any line's draw.
            replacement = iter(self._sample(remaining, replacements)) if replacements else iter(())
            hand = [card if held else next(replacement) for card, held in zip(initial, self.held)]
            category = evaluate_game_hand(hand,self.game)
            base_payout = self.game.award(category, self.round_base_bet)
            next_multiplier = self.game.multiplier(category) if self.round_feature else 1
            hands.append(hand)
            results.append({"category": category, "base_payout": base_payout,
                            "payout": base_payout * multiplier, "multiplier": multiplier,
                            "next_multiplier": next_multiplier})
            following[position] = next_multiplier
        total = sum(result["payout"] for result in results)
        # A failing sampler/evaluator never leaves a partially settled board.
        self.hands = hands
        self.results = results
        self.multipliers = following
        self.total_win = total
        self.credits += total
        self.rounds += 1
        self.phase = "result"
        self._reset_on_bet = True
        return self.snapshot()


PokerSession = Session
