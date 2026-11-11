"""Read-only draw advice, computed off the display/input thread.

Every completion comes from the remaining 47 cards, excluding ALL five dealt
cards. A small exhaustive subset histogram supplies exact category counts for
all 32 holds by inclusion/exclusion. Feature advice also includes the solved
continuation value of the next ten multipliers. No RNG, session object, seed,
GPIO, network, or persistent game state is accessed by this module.
"""
from collections import OrderedDict
import hashlib
import json
import math
from pathlib import Path
import struct
import threading
import time

from poker_engine import CATEGORIES, MULTIPLIERS, PAYOUTS, evaluate_hand


class StrategyError(ValueError):
    """Advice cannot be safely supplied for this snapshot or data set."""


class _Cancelled(Exception):
    pass


_CHOOSE = tuple(tuple(math.comb(n, k) if n >= k else 0 for k in range(6))
                for n in range(53))
_SECTIONS = ((64, 1, 4), (120, 52, 4), (3032, 1326, 2),
             (40160, 22100, 2), (658960, 270725, 1))
_SIZE = 4449110
_MULTS = (1, 2, 3, 4, 8, 10, 12)
_PAY = tuple(PAYOUTS[c] for c in CATEGORIES)
_MULT = tuple(MULTIPLIERS[c] for c in CATEGORIES)
_INDEX = {name: i for i, name in enumerate(CATEGORIES)}


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise _Cancelled()


def _round(snapshot):
    """Take only public current-round fields; ignore live next-bet settings."""
    if not isinstance(snapshot, dict) or snapshot.get('phase') != 'hold':
        raise StrategyError('Deal a hand before asking for advice')
    hand = snapshot.get('initial')
    if (not isinstance(hand, (list, tuple)) or len(hand) != 5
            or any(type(c) is not int or not 0 <= c < 52 for c in hand)
            or len(set(hand)) != 5):
        raise StrategyError('Invalid dealt hand')
    feature = snapshot.get('round_feature')
    base = snapshot.get('round_base_bet')
    hands = snapshot.get('round_num_hands')
    mults = snapshot.get('active_multipliers')
    if (type(feature) is not bool or type(base) is not int or not 1 <= base <= 5
            or type(hands) is not int or not 1 <= hands <= 10
            or not isinstance(mults, (list, tuple)) or len(mults) != 10
            or any(type(m) is not int or m not in _MULTS for m in mults)):
        raise StrategyError('Invalid round settings')
    if feature and (hands != 10 or base != 5):
        raise StrategyError('Feature advice requires 10 hands at max bet')
    return tuple(hand), feature, base, hands, sum(mults[:hands])


class StrategyTable:
    """Bounded, versioned data; never executes content from a strategy file."""
    def __init__(self, directory=None):
        directory = Path(directory) if directory is not None else Path(__file__).with_name('strategy')
        metadata_path = directory / 'strategy.json'
        table_path = directory / 'subset_counts.dat'
        if (metadata_path.is_symlink() or table_path.is_symlink()
                or not metadata_path.is_file() or not table_path.is_file()
                or metadata_path.stat().st_size > 100000
                or table_path.stat().st_size != _SIZE):
            raise StrategyError('Strategy data is missing or invalid')
        try:
            metadata = json.loads(metadata_path.read_text())
            raw = table_path.read_bytes()
        except (OSError, ValueError) as error:
            raise StrategyError('Cannot read strategy data') from error
        if (not isinstance(metadata, dict) or metadata.get('schema') != 1
                or metadata.get('category_order') != list(CATEGORIES)
                or metadata.get('payouts') != list(_PAY)
                or metadata.get('multiplier_order') != list(_MULT)
                or metadata.get('table_sha256') != hashlib.sha256(raw).hexdigest()
                or struct.unpack_from('<8s6I4Q', raw) !=
                (b'UXSUB01\0', 1, 64, 14, 52, 4, 0, 64, 4449046, 0, 0)):
            raise StrategyError('Strategy table does not match this game')
        bias = metadata.get('bias', {})
        if not isinstance(bias, dict):
            raise StrategyError('Invalid strategy continuation metadata')
        states, values = bias.get('states'), bias.get('values')
        reachable = {0}
        for _ in range(10):
            reachable = {s + m for s in reachable for m in _MULTS}
        if (bias.get('num_hands') != 10 or states != sorted(reachable)
                or not isinstance(values, list) or len(values) != len(states)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
                or type(bias.get('bellman_span')) not in (int, float)
                or not math.isfinite(bias['bellman_span'])
                or not 0 <= bias['bellman_span'] <= 0.000001):
            raise StrategyError('Strategy continuation values are not certified')
        self.raw = raw
        self.bias = dict(zip(states, values))
        self.certificate = bias['bellman_span']
        self.metadata = metadata

    def counts(self, hand, cancel=None):
        """Exact 14-category histogram for each original-card hold mask."""
        rows = []
        for mask in range(32):
            _check_cancel(cancel)
            cards = sorted(hand[i] for i in range(5) if mask & (1 << i))
            k = len(cards)
            if k == 5:
                row = [0] * 14
                row[_INDEX[evaluate_hand(cards)]] = 1
            else:
                offset, _, width = _SECTIONS[k]
                rank = sum(_CHOOSE[c][i + 1] for i, c in enumerate(cards))
                row = list(struct.unpack_from('<14' + {1: 'B', 2: 'H', 4: 'I'}[width],
                                              self.raw, offset + rank * 14 * width))
            rows.append(row)
        # Superset Möbius transform removes every dealt card not held.
        for bit in range(5):
            _check_cancel(cancel)
            for mask in range(32):
                if not mask & (1 << bit):
                    included = rows[mask | (1 << bit)]
                    rows[mask] = [a - b for a, b in zip(rows[mask], included)]
        for mask, row in enumerate(rows):
            if min(row) < 0 or sum(row) != _CHOOSE[47][5 - bin(mask).count('1')]:
                raise StrategyError('Strategy completion counts failed validation')
        return rows

    def advise(self, frozen, cancel=None):
        hand, feature, base, hands, multiplier_sum = frozen
        counts = self.counts(hand, cancel)
        pays = list(_PAY)
        if base < 5:
            pays[0] = 250
        immediate, probabilities = [], []
        for mask, row in enumerate(counts):
            denominator = sum(row)
            immediate.append(base * multiplier_sum * sum(n * p for n, p in zip(row, pays)) / denominator)
            q = dict.fromkeys(_MULTS, 0.0)
            for count, multiplier in zip(row, _MULT):
                q[multiplier] += count / denominator
            probabilities.append(tuple((m, p) for m, p in q.items() if p))
        scores = list(immediate)
        evaluated = 32
        if feature:
            if multiplier_sum not in self.bias:
                raise StrategyError('Invalid current multiplier total')
            # Rigorous pruning: linearize bias, bound only the residual.
            slope = (self.bias[120] - self.bias[10]) / 110
            residual = {s: v - slope * s for s, v in self.bias.items()}
            low, high = min(residual.values()), max(residual.values())
            linear = [immediate[i] + slope * 10 * sum(m*p for m, p in probabilities[i])
                      for i in range(32)]
            best_lower = max(linear) + low
            scores = [-math.inf] * 32
            evaluated = 0
            for mask in range(32):
                _check_cancel(cancel)
                if linear[mask] + high < best_lower - 1e-9:
                    continue
                distribution = {0: 1.0}
                for _ in range(10):
                    _check_cancel(cancel)
                    following = {}
                    for current, probability in distribution.items():
                        for multiplier, p in probabilities[mask]:
                            dest = current + multiplier
                            following[dest] = following.get(dest, 0.0) + probability * p
                    distribution = following
                    # Input sampling and display updates retain their own threads.
                    time.sleep(0)
                scores[mask] = immediate[mask] + sum(p * self.bias[s] for s, p in distribution.items())
                best_lower = max(best_lower, scores[mask])
                evaluated += 1
        _check_cancel(cancel)
        # Deterministic tie break; it cannot inspect future draws.
        best = max(scores)
        ties = [i for i, score in enumerate(scores) if best - score <= 1e-9]
        mask = max(ties, key=lambda i: (bin(i).count('1'), -i))
        return {'mask': mask, 'expected_current_win': immediate[mask],
                'value': scores[mask], 'feature': feature,
                'continuation_bellman_span': self.certificate if feature else 0.0,
                'evaluated_holds': evaluated}


class StrategyAdvisor:
    """One cancellable worker and a bounded cache; request/poll never solve."""
    def __init__(self, directory=None, table_factory=StrategyTable):
        self._directory, self._table_factory = directory, table_factory
        self._condition = threading.Condition()
        self._cancel = threading.Event()
        self._token = 0
        self._pending = None
        self._result = None
        self._closed = False
        self._cache = OrderedDict()
        self._thread = threading.Thread(target=self._run, name='poker-advisor', daemon=True)
        self._thread.start()

    def request(self, snapshot):
        frozen = _round(snapshot)
        with self._condition:
            if self._closed:
                raise StrategyError('Advisor is closed')
            self._cancel.set()
            self._cancel = threading.Event()
            self._token += 1
            self._result = None
            self._pending = self._token, frozen, self._cancel
            self._condition.notify()
            return self._token

    def poll(self, token):
        with self._condition:
            if self._closed or token != self._token:
                return None
            return dict(self._result) if self._result is not None else None

    def cancel(self):
        with self._condition:
            self._cancel.set()
            self._token += 1
            self._pending = self._result = None

    def close(self):
        with self._condition:
            self._closed = True
            self._cancel.set()
            self._pending = self._result = None
            self._condition.notify()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            raise StrategyError('Advisor did not stop; signer remains closed')
        self._cache.clear()

    def _run(self):
        table = None
        while True:
            with self._condition:
                while self._pending is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                token, frozen, cancel = self._pending
                self._pending = None
            try:
                _check_cancel(cancel)
                if frozen in self._cache:
                    result = self._cache.pop(frozen)
                else:
                    if table is None:
                        table = self._table_factory(self._directory)
                    _check_cancel(cancel)
                    result = table.advise(frozen, cancel)
                _check_cancel(cancel)
                self._cache[frozen] = result
                while len(self._cache) > 16:
                    self._cache.popitem(last=False)
            except _Cancelled:
                continue
            except Exception:
                result = {'error': 'Advice unavailable; use manual play'}
            with self._condition:
                if not self._closed and token == self._token and not cancel.is_set():
                    self._result = result
