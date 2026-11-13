"""Full 32-hold reports and bounded, outcome-independent training records."""
import copy
from collections import deque
import hashlib
import math
import random
import time

from poker_cabinet_strategy import GameStrategyTable, freeze_round, _check_cancel
from poker_games import get_game
from poker_strategy import StrategyAdvisor
from poker_training_store import TrainingStore, canonical

TOLERANCE = 1e-7
MAX_ERRORS = 160
MAX_SESSIONS = 48
DEFAULT_SETTINGS = {'mode': 'off', 'warn': True, 'record': True, 'dynamic': False,
                    'practice': 'random', 'difficulty': 'all'}


class DetailedTable:
    def __init__(self, directory=None):
        self.directory = directory
        self.table = None

    def advise(self, frozen, cancel=None):
        game_id, hand, feature, base, hands, multiplier_sum = frozen
        if self.table is None or self.table.game.id != game_id:
            self.table = GameStrategyTable(game_id, self.directory)
        table, game = self.table, self.table.game
        counts = table.counts(hand, cancel)
        reports = []
        for mask, row in enumerate(counts):
            _check_cancel(cancel)
            denominator = sum(row)
            chances = [n/denominator for n in row]
            current = multiplier_sum*sum(p*game.award(c, base) for c, p in zip(game.categories, chances))
            future = 0.0
            if feature:
                probabilities = {}
                for multiplier, p in zip(game.multipliers, chances):
                    if p:
                        probabilities[multiplier] = probabilities.get(multiplier, 0.0) + p
                distribution = {0: 1.0}
                for _ in range(hands):
                    _check_cancel(cancel)
                    following = {}
                    for total, p in distribution.items():
                        for multiplier, q in probabilities.items():
                            dest = total + multiplier
                            following[dest] = following.get(dest, 0.0) + p*q
                    distribution = following
                    time.sleep(0)
                future = sum(p*table.bias[s] for s, p in distribution.items())
            reports.append({'mask': mask, 'current': current, 'future': future,
                            'value': current+future, 'probabilities': chances})
        best = max(r['value'] for r in reports)
        equivalent = [r['mask'] for r in reports if best-r['value'] <= TOLERANCE]
        mask = max((r['mask'] for r in reports if best-r['value']<=1e-9),key=lambda m:(m.bit_count(),-m))
        ranked = sorted(reports, key=lambda r: (-r['value'], -r['mask'].bit_count(), r['mask']))
        return {'game_id': game_id, 'mask': mask, 'value': best,
                'round_key': frozen,
                'expected_current_win': reports[mask]['current'], 'holds': reports,
                'ranking': [r['mask'] for r in ranked], 'optimal_masks': equivalent,
                'feature': feature, 'multiplier_sum': multiplier_sum,
                'continuation_bellman_span': table.certificate if feature else 0.0,
                'future_baseline': 'All hands at 1x; relative continued-play value',
                'evaluated_holds': 32}


class TrainingAdvisor(StrategyAdvisor):
    _freeze_round = staticmethod(freeze_round)

    def __init__(self, directory=None):
        super().__init__(directory, DetailedTable)


def empty_stats():
    return {'decisions': 0, 'correct': 0, 'errors': 0, 'assisted': 0, 'corrected': 0,
            'ev_lost': 0.0, 'optimal_ev': 0.0, 'played_ev': 0.0,
            'wagered': 0, 'returned': 0, 'hands': 0, 'replayed': 0,
            'auto_decisions':0, 'auto_checked':0, 'auto_correct':0, 'auto_errors':0,
            'auto_ev_lost':0.0, 'auto_optimal_ev':0.0, 'auto_played_ev':0.0,
            'auto_wagered':0, 'auto_returned':0, 'auto_hands':0}


def autoplay_stats(stats):
    """A separate accuracy view; never credits machine decisions to the player."""
    view={key:stats.get('auto_'+key,0) for key in
          ('correct','errors','ev_lost','optimal_ev','played_ev','wagered','returned','hands')}
    view.update(decisions=stats.get('auto_checked',0),assisted=0,corrected=0,replayed=0,
                _auto_total=stats.get('auto_decisions',0))
    return view


class AutoGradeQueue:
    """Grade a late autoplay report without delaying or changing game draws.

    Missing/failed work remains explicitly unchecked, never an assumed correct
    decision. A bounded queue avoids accumulating RAM if the device falls behind.
    """
    def __init__(self,state,factory=TrainingAdvisor,limit=32):
        self.state,self.factory,self.limit=state,factory,limit
        self.jobs=deque();self.advisor=None;self.token=None

    def submit(self,snapshot,mask,session_id):
        if len(self.jobs)>=self.limit:return False
        self.jobs.append((copy.deepcopy(snapshot),mask,session_id))
        return True

    def update(self):
        if not self.jobs:return False
        snapshot,mask,session_id=self.jobs[0]
        try:
            if self.advisor is None:self.advisor=self.factory()
            if self.token is None:self.token=self.advisor.request(snapshot)
            report=self.advisor.poll(self.token)
            if report is None:return False
            self.state.grade_autoplay(snapshot,mask,report,session_id)
        except (ValueError,RuntimeError,OSError):
            # Coverage in the UI exposes failed/skipped checks.
            pass
        self.jobs.popleft();self.token=None
        return True

    def close(self):
        if self.advisor is not None:self.advisor.close()
        self.jobs.clear();self.token=None


def snapshot_for_error(error):
    game = get_game(error['game_id'])
    cards, multipliers = error['cards'], error['multipliers']
    snapshot = {'game_id': game.id, 'phase': 'hold', 'initial': list(cards),
                'round_feature': True, 'round_base_bet': 5,
                'round_num_hands': game.hands, 'active_multipliers': list(multipliers)}
    freeze_round(snapshot)
    return snapshot


class TrainingState:
    def __init__(self, store=None, clock=time.monotonic):
        self.store = store if store is not None else TrainingStore()
        self.clock = clock
        raw = self.store.data
        self.data = {'schema': 1, 'settings': {}, 'totals': {}, 'sessions': [], 'errors': [], 'next_session': 1, 'device': {}}
        self.current = None
        self._started = clock()
        if raw.get('schema') == 1:
            self._restore(raw)

    def _restore(self, raw):
        # A valid checksum is not permission to trust arbitrary JSON structures.
        if isinstance(raw.get('device'), dict):
            self.data['device'] = copy.deepcopy(raw['device'])
        for game_id, settings in raw.get('settings', {}).items() if isinstance(raw.get('settings'), dict) else []:
            try:
                get_game(game_id)
                self.data['settings'][game_id] = self._settings(settings)
            except (ValueError, TypeError):
                continue
        for game_id, stats in raw.get('totals', {}).items() if isinstance(raw.get('totals'), dict) else []:
            try:
                get_game(game_id)
                self.data['totals'][game_id] = self._stats(stats)
            except (ValueError, TypeError):
                continue
        sessions = raw.get('sessions', [])
        for session in sessions[-MAX_SESSIONS:] if isinstance(sessions, list) else []:
            try:
                value = {'id': int(session['id']), 'game_id': get_game(session['game_id']).id,
                         'stats': self._stats(session['stats']), 'seconds': max(0, int(session['seconds']))}
                if not 0 < value['id'] < 2**53:
                    raise ValueError('Invalid session')
                self.data['sessions'].append(value)
            except (KeyError, ValueError, TypeError, OverflowError):
                continue
        errors = raw.get('errors', [])
        for error in errors[-MAX_ERRORS:] if isinstance(errors, list) else []:
            try:
                snapshot_for_error(error)
                if (type(error['chosen']) is not int or not 0 <= error['chosen'] <= 31
                        or type(error['best']) is not int or not 0 <= error['best'] <= 31
                        or not isinstance(error['loss'], (int, float)) or not math.isfinite(error['loss'])
                        or error['loss'] <= 0):
                    raise ValueError('Invalid error')
                self.data['errors'].append({k: copy.deepcopy(error[k]) for k in
                    ('game_id', 'cards', 'multipliers', 'chosen', 'best', 'loss')}
                    | {'learned': bool(error.get('learned', False)), 'retries': max(0, min(100000, int(error.get('retries', 0))))})
            except (ValueError, TypeError, KeyError, OverflowError):
                continue
        latest = max((s['id'] for s in self.data['sessions']), default=0)
        self.data['next_session'] = latest + 1

    @staticmethod
    def _stats(value):
        if not isinstance(value, dict):
            raise ValueError('Invalid statistics')
        clean = empty_stats()
        for key in clean:
            n = value.get(key, 0)
            if type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1e15:
                raise ValueError('Invalid statistic')
            clean[key] = float(n) if key.removeprefix('auto_') in ('ev_lost','optimal_ev','played_ev') else int(n)
        return clean

    @staticmethod
    def _settings(value):
        if not isinstance(value, dict):
            raise ValueError('Invalid settings')
        result = dict(DEFAULT_SETTINGS)
        if value.get('mode') in ('off', 'test', 'coach'):
            result['mode'] = value['mode']
        for key in ('warn', 'record', 'dynamic'):
            if type(value.get(key)) is bool:
                result[key] = value[key]
        if value.get('practice') in ('random', 'errors'):
            result['practice'] = value['practice']
        if value.get('difficulty') in ('all', 'close', 'clear'):
            result['difficulty'] = value['difficulty']
        return result

    def settings(self, game_id):
        get_game(game_id)
        return self.data['settings'].setdefault(game_id, dict(DEFAULT_SETTINGS))

    def save(self):
        if self.current is not None:
            self.current['seconds'] = max(0, int(self.clock()-self._started))
        self.store.save(self.data)

    def clear(self):
        empty = {'schema': 1, 'settings': {}, 'totals': {}, 'sessions': [], 'errors': [], 'next_session': 1,
                 'device': copy.deepcopy(self.data.get('device', {}))}
        if not self.store.clear_training(empty):
            return False
        self.data = empty
        self.current = None
        self._started = self.clock()
        return True

    def begin(self, game_id):
        get_game(game_id)
        self.current = {'id': self.data['next_session'], 'game_id': game_id, 'stats': empty_stats(), 'seconds': 0}
        self.data['next_session'] += 1
        self.data['sessions'].append(self.current)
        self.data['sessions'] = self.data['sessions'][-MAX_SESSIONS:]
        self._started = self.clock()
        self.save()

    def totals(self, game_id):
        return self.data['totals'].setdefault(game_id, empty_stats())

    @staticmethod
    def fingerprint(snapshot):
        freeze_round(snapshot)
        return hashlib.sha256(canonical([snapshot['game_id'], snapshot['initial'], snapshot['active_multipliers']])).hexdigest()

    def errors(self, game_id, learned=False):
        return [e for e in self.data['errors'] if e['game_id'] == game_id and (learned or not e.get('learned'))]

    def grade_autoplay(self,snapshot,mask,report,session_id,save=True):
        if (type(mask) is not int or not 0<=mask<32 or not report or report.get('error')
                or report.get('round_key')!=freeze_round(snapshot)
                or report.get('game_id')!=snapshot['game_id'] or len(report.get('holds',[]))!=32):
            raise ValueError('Autoplay analysis does not match the played decision')
        chosen=report['holds'][mask]['value'];best=report['value']
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (chosen,best)):
            raise ValueError('Invalid autoplay EV')
        loss=max(0.,best-chosen);correct=loss<=TOLERANCE
        if correct:loss=0.
        targets=[self.totals(snapshot['game_id'])]
        targets.extend(s['stats'] for s in self.data['sessions']
                       if s['id']==session_id and s['game_id']==snapshot['game_id'])
        for stats in targets:
            stats['auto_checked']+=1;stats['auto_correct']+=int(correct)
            stats['auto_errors']+=int(not correct);stats['auto_ev_lost']+=loss
            stats['auto_optimal_ev']+=best;stats['auto_played_ev']+=chosen
        if save:self.save()

    def record(self, snapshot, chosen, report, wagered, returned, assisted=False, corrected=False, replay=None,
               autoplay=False,auto_mask=None):
        freeze_round(snapshot)
        if type(chosen) is not int or not 0 <= chosen < 32:
            raise ValueError('Invalid chosen hold')
        if report is not None and report['game_id'] != snapshot['game_id']:
            raise ValueError('Analysis belongs to another game')
        if report is not None and report.get('round_key') != freeze_round(snapshot):
            raise ValueError('Analysis belongs to another hand or multiplier board')
        game_id = snapshot['game_id']
        if self.current is None or self.current['game_id'] != game_id:
            self.begin(game_id)
        loss = max(0.0, report['value']-report['holds'][chosen]['value']) if report else 0.0
        correct = report is not None and loss <= TOLERANCE
        if correct:loss=0.0
        for stats in (self.totals(game_id), self.current['stats']):
            stats['wagered'] += wagered
            stats['returned'] += returned
            stats['hands'] += snapshot['round_num_hands']
            if autoplay:
                stats['auto_decisions']+=1;stats['auto_wagered']+=wagered
                stats['auto_returned']+=returned;stats['auto_hands']+=snapshot['round_num_hands']
            if assisted:
                stats['assisted'] += 1
            elif report is not None:
                stats['decisions'] += 1
                stats['correct'] += int(correct)
                stats['errors'] += int(not correct)
                stats['ev_lost'] += loss
                stats['optimal_ev'] += report['value']
                stats['played_ev'] += report['holds'][chosen]['value']
                stats['corrected'] += int(corrected)
            if replay is not None:
                stats['replayed'] += 1
        if not assisted and report is not None and not correct and self.settings(game_id)['record']:
            error = {'game_id': game_id, 'cards': list(snapshot['initial']),
                     'multipliers': list(snapshot['active_multipliers']), 'chosen': chosen,
                     'best': report['mask'], 'loss': loss, 'learned': False, 'retries': 0}
            fp = self.fingerprint(snapshot)
            existing = next((e for e in self.data['errors'] if self.fingerprint(snapshot_for_error(e)) == fp), None)
            if existing:
                retries=existing.get('retries',0)
                existing.update(error)
                existing['retries']=retries
            else:
                self.data['errors'].append(error)
                self.data['errors'] = self.data['errors'][-MAX_ERRORS:]
        if replay is not None and not assisted and report is not None:
            replay['retries'] = min(100000, int(replay.get('retries', 0))+1)
            replay['learned'] = correct
        if autoplay and report is not None:
            self.grade_autoplay(snapshot,chosen if auto_mask is None else auto_mask,report,self.current['id'],save=False)
        self.save()
        return {'correct': correct, 'loss': loss, 'assisted': bool(assisted)}
