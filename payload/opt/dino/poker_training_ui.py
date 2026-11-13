"""Native 320x240 trainer, sharing the cabinet and its manual calculator."""
import copy
import json
import math
from pathlib import Path
import random
import time

from PIL import Image, ImageDraw
from poker_cabinet_ui import FOOTERS
from poker_cabinet_strategy import freeze_round
from poker_games import GAMES, get_game
from poker_evaluate import evaluate_game_hand
from poker_training import (TrainingAdvisor, TrainingState, TOLERANCE, snapshot_for_error,
                            empty_stats,autoplay_stats,AutoGradeQueue)
from poker_ui import GOLD, WHITE

BG = (5, 7, 30)
PANEL = (19, 24, 59)
MUTED = (155, 168, 193)
GREEN = (71, 238, 151)
RED = (255, 91, 108)


def hold_label(mask):
    return 'DRAW ALL FIVE' if mask == 0 else 'HOLD ' + ','.join(str(i+1) for i in range(5) if mask & (1 << i))


class TrainingController:
    def __init__(self, app, state=None, advisor=None, clock=None):
        self.app = app
        self.clock = clock if clock is not None else app.play._clock
        self.state = state if state is not None else TrainingState(clock=self.clock)
        self.advisor = advisor
        self.page = None
        self.index = 0
        self._bound = None
        self._token = self._key = self.report = None
        self.snapshot = None
        self.assisted = False
        self.pending_draw = False
        self.attempt = None
        self.approved = None
        self.replay = None
        self.last = None
        self.message = ''
        self.stats_scope = 0
        self.return_page = 'home'
        self.error_index = 0
        self.error_detail = None
        self.dirty = False
        self.drills = None
        self._practice_random = random.Random(0x56505452)  # Curated drills only; no new boot entropy wait.
        self._round_count = 0
        self._store_status = self.state.store.status
        self._forced_error = None
        self.detail_scroll = 0
        self.inline_warning=None
        self.inline_waiting=False
        self.revealed_key=None
        self.analysis_failed=False
        self.auto_grades=AutoGradeQueue(self.state)
        apply_hold=self.play._apply_manual_hold
        def assisted_hold():
            if self.play._manual_hold_key is not None:self.assisted=True
            return apply_hold()
        self.play._apply_manual_hold=assisted_hold
        self.bind()

    @property
    def play(self):
        return self.app.play

    @property
    def game(self):
        return self.play.session.game

    @property
    def settings(self):
        return self.state.settings(self.game.id)

    @property
    def active(self):
        return self.page is not None

    def open(self, page='home'):
        self.play.pause_autoplay()
        self.play.on_input_reset()
        self.play._clear_notice()
        self.page, self.index = page, 0
        self.dirty = True

    def dismiss(self):
        self.page = None
        self.pending_draw = False
        self.inline_waiting=False
        self.play._clear_notice()
        self.dirty = True

    def cancel_analysis(self):
        if self.advisor is not None:
            self.advisor.cancel()
        self._token = self._key = self.report = None
        self.snapshot = None
        self.analysis_failed=False

    def ensure_analysis(self, snapshot=None):
        snapshot = snapshot if snapshot is not None else self.play.session.snapshot()
        if snapshot['phase'] != 'hold':
            return
        key = freeze_round(snapshot)
        if self._key == key and (self.report is not None or self._token is not None or self.analysis_failed):
            return
        if self.advisor is None:
            self.advisor = TrainingAdvisor()
        self._token = self.advisor.request(snapshot)
        self._key = key
        self.snapshot = copy.deepcopy(snapshot)
        self.report = None
        self.analysis_failed=False

    def _practice(self):
        settings = self.settings
        errors = self.state.errors(self.game.id)
        if self._forced_error is not None:
            return snapshot_for_error(self._forced_error),self._forced_error
        if settings['practice'] == 'errors' or (settings['dynamic'] and self._round_count % 5 == 4 and errors):
            if not errors:
                self.message = 'No unlearned errors for this game.'
                self.open('message')
                raise ValueError(self.message)
            error = errors[self._round_count % len(errors)]
            return snapshot_for_error(error), error
        if settings['difficulty'] != 'all':
            if self.drills is None:
                path = Path(__file__).with_name('training_drills.json')
                self.drills = json.loads(path.read_text())
            bank = self.drills.get(self.game.id, {}).get(settings['difficulty'], [])
            if not bank:
                self.message = 'No matching practice hands.'
                self.open('message')
                raise ValueError(self.message)
            drill = self._practice_random.choice(bank)
            return snapshot_for_error(drill), None
        return None, None

    def bind(self):
        session = self.play.session
        if session is self._bound:
            return
        self.cancel_analysis()
        self._bound = session
        if self.app.training_mode and session.game.id not in self.state.data['settings']:
            self.state.settings(session.game.id)['mode']='test'
        if self.last and self.last['snapshot']['game_id']!=session.game.id:self.last=None
        self._forced_error=None
        self.attempt = self.approved = self.replay = None
        self.assisted = False
        original_deal, original_draw = session.deal, session.draw

        def deal():
            if not self.app.training_mode or self.settings['mode'] == 'off':
                return original_deal()
            # Reject invalid/underfunded deals before changing a practice board.
            if session.phase not in ('ready', 'result') or session.credits < session.total_bet:
                return original_deal()
            if self.state.current is None or self.state.current['game_id']!=session.game.id:
                self.state.begin(session.game.id)
            practice, replay = self._practice()
            old_multipliers, sample = list(session.multipliers), session._sample
            if practice is not None:
                freeze_round(practice)
                session.multipliers = list(practice['active_multipliers'])
                wanted = tuple(practice['initial'])
                def practice_sample(population, count):
                    if len(population) == session.game.deck_size and count == 5:
                        return list(wanted)
                    return sample(population, count)
                session._sample = practice_sample
            try:
                result = original_deal()
            except Exception:
                session.multipliers = old_multipliers
                raise
            finally:
                session._sample = sample
            self.attempt = self.approved = None
            self.inline_warning=self.revealed_key=None
            self.inline_waiting=False
            self.replay = replay
            self._forced_error = None
            self.assisted = self.settings['mode'] == 'coach' or self.play.autoplay
            self._round_count += 1
            self.cancel_analysis()
            if session.phase == 'hold':
                self.ensure_analysis(session.snapshot())
            return session.snapshot()

        def draw():
            snapshot = session.snapshot()
            if snapshot['phase'] != 'hold' or not self.app.training_mode or self.settings['mode'] == 'off':
                return original_draw()
            mask = sum(1 << i for i, held in enumerate(snapshot['held']) if held)
            automatic=bool(self.play.autoplay)
            key = freeze_round(snapshot)
            auto_royal = all(snapshot['held']) and evaluate_game_hand(snapshot['initial'], session.game) == 'royal_flush' and self._key != key
            assisted = self.assisted or self.play.autoplay or self.settings['mode'] == 'coach' or auto_royal
            # Assistance after a submitted error cannot erase that first attempt.
            if self.attempt is not None:assisted=False
            if not assisted:
                if self.analysis_failed:self.cancel_analysis()
                self.ensure_analysis(snapshot)
                if self.report is None:
                    self.pending_draw = True
                    self.inline_waiting=True
                    self.dirty=True
                    raise ValueError('Preparing training analysis')
                self.revealed_key=key
                chosen = self.report['holds'][mask]
                wrong = self.report['value']-chosen['value'] > TOLERANCE
                if wrong and self.settings['warn'] and self.approved != (key, mask):
                    if self.inline_warning==(key,mask):self.approved=(key,mask)
                    else:
                        if self.attempt is None:self.attempt=(copy.deepcopy(snapshot),mask)
                        self.inline_warning=(key,mask)
                        self.dirty=True
                        raise ValueError('Review the selected hold')
            report = self.report if self._key == key else None
            self.inline_warning=None
            self.inline_waiting=False
            result = original_draw()  # Failed RNG leaves the attempt unrecorded.
            attempted_snapshot, attempted_mask = self.attempt if self.attempt else (snapshot, mask)
            grade = self.state.record(attempted_snapshot, attempted_mask, report,
                snapshot['last_bet'], result['total_win'], assisted=assisted,
                corrected=self.attempt is not None and attempted_mask != mask, replay=self.replay,
                autoplay=automatic,auto_mask=mask)
            if automatic and report is None:
                self.auto_grades.submit(snapshot,mask,self.state.current['id'])
            self.last = {'snapshot': attempted_snapshot, 'mask': attempted_mask, 'report': report,
                         'grade': grade,'autoplay':automatic}
            self.attempt = self.approved = self.replay = None
            self.pending_draw = False
            self.dirty = True
            return result

        session.deal, session.draw = deal, draw

    def update(self, now):
        self.bind()
        changed, self.dirty = self.dirty, False
        if self._store_status!=self.state.store.status:
            self._store_status=self.state.store.status
            changed=True
        snapshot = self.play.session.snapshot() if self.app.training_mode and self.settings['mode']!='off' and not self.app.calculator_active else None
        if snapshot is not None and snapshot['phase'] == 'hold':
            self.ensure_analysis(snapshot)
            if self.play.hint_visible or self.play.autoplay:
                self.assisted = True
        if self._token is not None:
            answer = self.advisor.poll(self._token)
            if answer is not None:
                self._token = None
                expected_game=self.snapshot['game_id'] if self.snapshot else self.game.id
                if (answer.get('error') or answer.get('game_id') != expected_game
                        or answer.get('round_key') != self._key or len(answer.get('holds', [])) != 32):
                    self.message = 'Analysis unavailable. Retry or play ungraded.'
                    self.analysis_failed=True
                    if self.pending_draw:
                        self.inline_waiting=False
                        self.pending_draw = False
                        self.play._clear_notice()
                    self.report = None
                else:
                    self.report = answer
                    if self.app.calculator_active and self.return_page=='calculator':
                        calculator=self.app.calculator
                        if None not in calculator.cards and freeze_round(calculator.snapshot())==answer['round_key']:
                            calculator.cancel();calculator.result=dict(answer)
                            calculator.status=calculator.hold_text()
                    if self.inline_waiting and self.pending_draw:
                        self.page = None
                        self.pending_draw = False
                        self.inline_waiting=False
                        self.play._clear_notice()
                        self.play._play()
                changed = True
        return self.auto_grades.update() or changed

    def open_ev(self, source='game'):
        self.return_page = 'home'
        if source == 'calculator':
            calculator = self.app.calculator
            if None in calculator.cards:
                self.message = 'Enter all five cards in the calculator.'
                self.open('message')
                return
            self.ensure_analysis(calculator.snapshot())
            self.return_page = 'calculator'
        elif self.play.session.phase == 'hold':
            self.assisted = True
            self.ensure_analysis()
        elif self.last and self.last['report']:
            self.snapshot, self.report = self.last['snapshot'], self.last['report']
        else:
            self.message = 'Deal a hand to compare its 32 holds.'
            self.open('message')
            return
        self.open('ev')

    def _back(self):
        if self.page in ('home', 'waiting'):
            self.dismiss()
        elif self.page == 'ev_detail':
            self.page = 'ev'
        elif self.page == 'error_detail':
            self.page = 'errors'
        elif self.page == 'ev' and self.return_page == 'calculator':
            self.dismiss()
            self.return_page='home'
        elif self.page == 'clear_memory':
            self.page, self.index = 'settings', 7
        else:
            self.page, self.index = 'home', 0

    def handle(self, action):
        action = action.upper()
        if action == 'KEY3':
            self._back()
            return
        confirm = action in ('CENTER', 'KEY2', 'KEY1')
        delta = -1 if action in ('UP', 'LEFT') else 1 if action in ('DOWN', 'RIGHT') else 0
        if self.page == 'home':
            if delta:
                self.index = (self.index+delta) % 8
            elif confirm:
                if self.index == 0:
                    self.page, self.index = 'settings', 0
                elif self.index == 1:
                    if self.settings['mode']=='off':self.settings['mode']='test'
                    self.state.begin(self.game.id)
                    self.dismiss()
                elif self.index == 2:
                    self.page, self.index = 'errors', 0
                elif self.index == 3:
                    self.page, self.stats_scope = 'stats', (2 if self.last and self.last.get('autoplay') else 0)
                elif self.index == 4:
                    self.open_ev()
                elif self.index == 5:
                    self.app.toggle_calculator()
                elif self.index == 6:
                    self.page, self.index = 'help', 0
                else:
                    self.dismiss()
        elif self.page == 'settings':
            if action in ('UP', 'DOWN'):
                self.index = (self.index+delta) % 8
            elif confirm or action in ('LEFT', 'RIGHT'):
                if self.index == 6:
                    self.state.save()
                    self.state.store.set_persistent(not self.state.store.persistent)
                    return
                if self.index == 7:
                    if confirm:
                        self.page, self.index = 'clear_memory', 0
                    return
                key, choices = [('mode', ('off', 'test', 'coach')), ('warn', (False, True)),
                    ('record', (False, True)), ('dynamic', (False, True)),
                    ('practice', ('random', 'errors')), ('difficulty', ('all', 'close', 'clear'))][self.index]
                old = self.settings[key]
                self.settings[key] = choices[(choices.index(old)+(-1 if action == 'LEFT' else 1)) % len(choices)]
                self.state.save()
                if key == 'mode':
                    self.assisted = self.assisted or self.settings['mode']=='coach' or self.play.session.phase=='hold'
                    if self.settings['mode'] != 'off':
                        self.ensure_analysis()
        elif self.page == 'clear_memory':
            if delta:
                self.index = (self.index+delta) % 2
            elif confirm:
                if self.index == 0:
                    self.page, self.index = 'settings', 7
                else:
                    self.cancel_analysis()
                    self.auto_grades.close()
                    self.auto_grades = AutoGradeQueue(self.state)
                    if self.state.clear():
                        self.attempt = self.approved = self.replay = self.last = None
                        self.inline_warning = self.revealed_key = self._forced_error = None
                        self.pending_draw = self.inline_waiting = False
                        self.assisted = self.play.session.phase == 'hold'
                        self._round_count = 0
                        self.page, self.index = 'settings', 7
        elif self.page == 'warning':
            if delta:
                self.index = (self.index+delta) % 3
            elif confirm:
                if self.index == 0:
                    self.dismiss()
                else:
                    if self.index == 1:
                        self.play.session.held = [bool(self.report['mask'] & (1 << i)) for i in range(5)]
                    snapshot = self.play.session.snapshot()
                    mask = sum(1 << i for i, held in enumerate(snapshot['held']) if held)
                    self.approved = (freeze_round(snapshot), mask)
                    self.dismiss()
                    self.play._play()
        elif self.page == 'analysis_error':
            if delta:
                self.index = (self.index+delta) % 2
            elif confirm:
                if self.index == 0:
                    self.cancel_analysis()
                    self.ensure_analysis()
                    self.pending_draw = True
                    self.page = 'waiting'
                else:
                    self.assisted = True
                    self.dismiss()
                    self.play._play()
        elif self.page == 'errors':
            errors = self.state.errors(self.game.id, learned=True)
            if errors and delta:
                self.index = (self.index+delta) % len(errors)
            elif errors and confirm:
                if self.play.session.phase=='hold':self.assisted=True
                self.error_detail = errors[self.index]
                self.error_index = self.index
                self.page, self.index = 'error_detail', 0
        elif self.page == 'error_detail':
            if confirm:
                if self.play.session.phase == 'hold':
                    self.message = 'Finish the current hand before replaying.'
                    self.page = 'message'
                else:
                    self.settings['mode'] = 'test'
                    self.settings['practice'] = 'errors'
                    self.settings['difficulty'] = 'all'
                    self.error_detail['learned'] = False
                    self._forced_error = self.error_detail
                    self.state.save()
                    self.dismiss()
                    self.play._finish_animation()
                    self.play._play()
        elif self.page == 'stats':
            if delta or confirm:
                self.stats_scope = (self.stats_scope+(-1 if delta < 0 else 1)) % len(self.stats_views())
        elif self.page == 'ev':
            if self.report and delta:
                self.index = (self.index+delta) % 32
            elif self.report and confirm:
                self.page = 'ev_detail'
        elif self.page == 'ev_detail':
            if action in ('UP','DOWN'):
                self.detail_scroll=max(0,min(len(get_game(self.snapshot['game_id']).categories)-6,self.detail_scroll+delta))
            elif action in ('LEFT','RIGHT'):
                self.index = (self.index+delta) % 32
                self.detail_scroll=0
        elif self.page == 'help':
            if delta or confirm:
                self.index = (self.index+(-1 if delta < 0 else 1)) % 3
        elif self.page == 'message' and confirm:
            self.page, self.index = 'home', 0

    def text(self, image, xy, value, size=10, color=WHITE, bold=False):
        self.play.renderer.text(ImageDraw.Draw(image), xy, str(value), size, color, bold)

    def stats_views(self):
        current=self.state.current
        if current and current['game_id']!=self.game.id:current=None
        views=[('THIS SESSION',current['stats'] if current else empty_stats()),
               ('ALL SESSIONS',self.state.totals(self.game.id)),
               ('SESSION AUTOPLAY',autoplay_stats(current['stats'] if current else empty_stats())),
               ('ALL AUTOPLAY',autoplay_stats(self.state.totals(self.game.id)))]
        for session in reversed(self.state.data['sessions']):
            if session['game_id']==self.game.id and session is not current:
                views.append(('SESSION #'+str(session['id']),session['stats']))
                if session['stats']['auto_decisions']:
                    views.append(('SESSION #'+str(session['id'])+' AUTO',autoplay_stats(session['stats'])))
        return views

    def center(self, image, x, y, value, size=10, color=WHITE, bold=False):
        self.play.renderer.center(ImageDraw.Draw(image), x, y, str(value), size, color, bold)

    def button(self, image, box, value, selected=False, color=None):
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(box, radius=4, fill=(38, 44, 83) if selected else PANEL,
                               outline=color or (GOLD if selected else (49, 61, 98)), width=2 if selected else 1)
        self.play.renderer.fitted_label(image, (box[0]+6, box[1]+3, box[2]-6, box[3]-3), value, 11,
                                        GOLD if selected else WHITE, True)

    def cards(self, image, snapshot, mask=None, y=41):
        renderer = self.play.renderer
        renderer._game = get_game(snapshot['game_id'])
        for i, card in enumerate(snapshot['initial']):
            x = 16+59*i
            face = renderer.card(card, 52, 74)
            image.paste(face, (x, y), face)
            self.center(image, x+26, y-12, i+1, 8, MUTED)
            if mask is not None and mask & (1 << i):
                ImageDraw.Draw(image).rounded_rectangle((x-2, y-2, x+53, y+75), radius=3, outline=GOLD, width=2)

    def render(self):
        image = Image.new('RGB', (320, 240), BG)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 319, 29), fill=(9, 12, 42))
        title = {'home': 'TRAINING', 'settings': 'TRAINING OPTIONS', 'warning': 'CHECK YOUR HOLD',
                 'stats': 'SESSION STATS', 'errors': 'YOUR ERRORS', 'error_detail': 'REVIEW ERROR',
                 'ev': 'HOLD EV', 'ev_detail': 'EV DETAILS', 'waiting': 'ANALYZING HAND',
                 'analysis_error': 'ANALYSIS UNAVAILABLE', 'help': 'TRAINING GUIDE', 'message': 'TRAINING',
                 'clear_memory': 'CLEAR TRAINING DATA?'}[self.page]
        self.text(image, (10, 3), title, 13, GOLD, True)
        display_game=get_game(self.snapshot['game_id']) if self.page in ('ev','ev_detail') and self.snapshot else self.game
        full=display_game.pays[display_game.categories.index('full_house')]
        flush=display_game.pays[display_game.categories.index('flush')]
        self.text(image, (10, 19), FOOTERS[display_game.id]+'  '+str(full)+'/'+str(flush)+'  /  '+str(display_game.hands)+' hands', 8, MUTED)
        draw.rectangle((0, 218, 319, 239), fill=(8, 11, 36))
        self.center(image, 160, 225, 'D-PAD: MOVE   MIDDLE: SELECT   BOTTOM: BACK', 8, MUTED)
        if self.page == 'home':
            labels = ['Training: '+self.settings['mode'].upper(), 'New session',
                      'Your errors: '+str(len(self.state.errors(self.game.id))), 'Session stats',
                      'Compare hold EV', 'Card calculator', 'Training guide', 'Return to game']
            for i, label in enumerate(labels):
                self.button(image, (10, 34+i*21, 310, 53+i*21), label, self.index == i)
            self.text(image, (12, 205), self.state.store.status, 8, MUTED)
        elif self.page == 'settings':
            values = [('Training type', self.settings['mode'].upper()), ('Warn on error', self.settings['warn']),
                      ('Record errors', self.settings['record']), ('Mix errors: 1 in 5', self.settings['dynamic']),
                      ('Practice', self.settings['practice'].upper()), ('Difficulty', self.settings['difficulty'].upper()),
                      ('Persistent memory', self.state.store.persistent), ('Clear training data', 'SELECT')]
            start = min(max(0, self.index-4), len(values)-5)
            self.text(image, (278, 19), str(self.index+1)+'/8', 8, MUTED)
            for i, (label, value) in enumerate(values[start:start+5]):
                value = ('ON' if value else 'OFF') if type(value) is bool else value
                self.button(image, (10, 35+i*26, 310, 58+i*26), label+'    '+str(value), self.index == start+i)
            notes = [
                ('TEST hides advice until you decide.', 'COACH shows the best hold immediately.'),
                ('Warn before drawing an incorrect hold.', 'Fix it, or press DOWN again to continue.'),
                ('Keep incorrect decisions for review.', 'Assisted hands do not count as errors.'),
                ('Mix one unlearned error into every', 'five training rounds, when available.'),
                ('RANDOM deals normally; ERRORS replays', 'unlearned errors for this game.'),
                ('CLOSE / CLEAR use fixed 1x practice', 'boards. ALL uses ordinary hands.'),
                (('ON: saves options, errors and stats.', 'Restores them after power-off.', 'Hands, credits and autoplay reset.')
                 if self.state.store.persistent else
                 ('OFF: training stays in RAM only.', 'Power-off clears the current session.', 'Switching OFF clears the SD save.')),
                ('Clear options, errors and statistics.', 'Includes current RAM and saved history.', 'Keeps memory ON/OFF and the game hand.')][self.index]
            for i, line in enumerate(notes):
                self.text(image, (12, 173+i*11), line, 8, MUTED)
            self.text(image, (12, 208), self.state.store.status, 8, GREEN if self.state.store.persistent else MUTED)
        elif self.page == 'clear_memory':
            for i, line in enumerate(('Delete all training options,', 'recorded errors and statistics?', '',
                                      'This clears RAM and the SD save.', 'Memory ON/OFF stays unchanged.', 'Your current game hand stays intact.')):
                self.text(image, (14, 40+i*17), line, 10, WHITE)
            self.button(image, (14, 157, 151, 187), 'CANCEL', self.index == 0)
            self.button(image, (168, 157, 305, 187), 'CLEAR', self.index == 1)
            self.text(image, (14, 201), self.state.store.status, 8, MUTED)
        elif self.page == 'warning':
            snapshot = self.play.session.snapshot()
            self.cards(image, snapshot, self.report['mask'], y=43)
            mask = sum(1 << i for i, h in enumerate(snapshot['held']) if h)
            loss = max(0, self.report['value']-self.report['holds'][mask]['value'])
            self.text(image, (12, 123), 'BEST: '+hold_label(self.report['mask']), 11, GOLD, True)
            self.text(image, (12, 140), 'Your hold gives up %.4f credits EV' % loss, 9, RED)
            for i, text in enumerate(('TRY AGAIN', 'USE BEST + DRAW', 'DRAW ANYWAY')):
                x = 9+103*i
                self.button(image, (x, 166, x+98, 204), text, self.index == i)
        elif self.page == 'waiting':
            self.center(image, 160, 85, 'Comparing every hold...', 14, GOLD, True)
            self.center(image, 160, 111, 'Current pays + future multiplier value', 10, WHITE)
            self.center(image, 160, 142, 'Your Draw will continue when ready.', 10, MUTED)
            self.center(image, 160, 165, 'BOTTOM: CANCEL DRAW', 10, MUTED)
        elif self.page == 'analysis_error':
            self.center(image, 160, 75, 'No advice has been applied.', 12, WHITE)
            self.center(image, 160, 99, 'You can retry or play without grading.', 10, MUTED)
            for i, label in enumerate(('RETRY ANALYSIS', 'DRAW UNGRADED')):
                self.button(image, (20, 135+i*36, 300, 164+i*36), label, self.index == i)
        elif self.page == 'stats':
            views=self.stats_views();self.stats_scope%=len(views)
            label,stats=views[self.stats_scope]
            self.center(image, 160, 36, label, 10, GOLD, True)
            n = stats['decisions']
            accuracy = '%.2f%%' % (100*stats['correct']/n) if n else '--'
            rows = [('Hold accuracy', accuracy), ('Decisions / errors', '%s / %s' % (n, stats['errors'])),
                    ('EV lost', '%.4f credits' % stats['ev_lost']),
                    ('Wagered / returned', '%s / %s' % (stats['wagered'], stats['returned'])),
                    ('Actual net', '%+d credits' % (stats['returned']-stats['wagered'])),
                    ('Assisted / corrected', '%s / %s' % (stats['assisted'], stats['corrected'])),
                    ('Drawn hands / replays', '%s / %s' % (stats['hands'], stats['replayed'])),
                    ('Decision EV retained','%.3f%%' % (100*stats['played_ev']/stats['optimal_ev']) if stats['optimal_ev']>0 else '--')]
            if '_auto_total' in stats:
                rows[1]=('Checked / decisions','%s / %s'%(n,stats['_auto_total']))
                rows[5]=('Correct / errors','%s / %s'%(stats['correct'],stats['errors']))
                rows[6]=('Drawn hands',str(stats['hands']))
            for i, (left, right) in enumerate(rows):
                y = 55+i*18
                self.text(image, (12, y), left, 9, MUTED)
                self.play.renderer.right(draw, 307, y, right, 10, WHITE, True)
            self.center(image, 160, 203, 'LEFT / RIGHT: SESSION VIEW', 8, MUTED)
        elif self.page == 'errors':
            errors = self.state.errors(self.game.id, learned=True)
            if not errors:
                self.center(image, 160, 90, 'No recorded errors yet.', 13, GREEN, True)
                self.center(image, 160, 116, 'Test mode records missed decisions.', 10, MUTED)
            else:
                self.index %= len(errors)
                start = max(0, min(self.index-2, len(errors)-6))
                for row, index in enumerate(range(start, min(len(errors), start+6))):
                    error = errors[index]
                    self.button(image, (10, 39+row*27, 310, 63+row*27),
                        ('LEARNED ' if error.get('learned') else 'PRACTICE ')+str(index+1)+'    EV lost %.4f' % error['loss'], index == self.index)
                self.center(image, 160, 207, '%s of %s  /  MIDDLE: REVIEW' % (self.index+1, len(errors)), 8, MUTED)
        elif self.page == 'error_detail':
            error = self.error_detail
            self.cards(image, snapshot_for_error(error), error['best'], 44)
            self.text(image, (12, 126), 'YOUR: '+hold_label(error['chosen']), 10, RED, True)
            self.text(image, (12, 144), 'BEST: '+hold_label(error['best']), 10, GOLD, True)
            self.text(image, (12, 162), 'Multipliers: '+','.join(str(n) for n in error['multipliers']), 9, MUTED)
            self.button(image, (15, 184, 305, 211), 'REPLAY WITH ORIGINAL MULTIPLIERS', True)
        elif self.page in ('ev', 'ev_detail'):
            if self.report is None:
                self.center(image, 160, 102, 'Calculating all 32 holds...', 13, GOLD, True)
            else:
                selected_mask = self.report['ranking'][self.index]
                entry = self.report['holds'][selected_mask]
                if self.page == 'ev':
                    self.cards(image, self.snapshot, selected_mask, 39)
                    start = max(0, min(self.index-2, 24))
                    for row, index in enumerate(range(start, min(32, start+8))):
                        mask = self.report['ranking'][index]
                        value = self.report['holds'][mask]['value']
                        y = 122+row*11
                        if index == self.index:
                            draw.rectangle((8, y-1, 312, y+10), fill=(46, 51, 82))
                        self.text(image, (12, y), '%2d  %s' % (index+1, hold_label(mask)), 9, GOLD if mask in self.report['optimal_masks'] else WHITE)
                        self.play.renderer.right(draw, 306, y, '%.4f' % value, 9, GOLD if index == self.index else WHITE, True)
                else:
                    self.text(image, (12, 37), hold_label(selected_mask), 13, GOLD, True)
                    for i, (name, value) in enumerate((('Current board EV', entry['current']), ('Future multiplier value', entry['future']), ('Total decision EV', entry['value']))):
                        self.text(image, (12, 60+i*18), name, 10, MUTED)
                        self.play.renderer.right(draw, 307, 60+i*18, '%.5f' % value, 10, WHITE, True)
                    report_game=get_game(self.snapshot['game_id'])
                    categories = sorted(zip(report_game.categories, entry['probabilities']), key=lambda x: -x[1])
                    for i, (category, probability) in enumerate(categories[self.detail_scroll:self.detail_scroll+6]):
                        y=121+i*13
                        self.play.renderer.fitted_label(image,(12,y,177,y+12),report_game.label(category),9,WHITE)
                        self.play.renderer.right(draw, 245, y, '%.3f%%' % (probability*100), 9, MUTED)
                        contribution=probability*report_game.award(category,self.snapshot['round_base_bet'])*self.report['multiplier_sum']
                        self.play.renderer.right(draw,307,y,'%.3f'%contribution,9,GOLD)
                    self.center(image, 160, 205, 'UP/DOWN: OUTCOMES   LEFT/RIGHT: HOLD', 8, MUTED)
        elif self.page == 'help':
            pages = [
                ['TEST: decide first, then Draw to grade.', 'COACH: green borders show the best hold.', 'Red held-UP hints still work as before.', 'Hints, auto-holds and autoplay are assisted.', 'Assisted play does not improve test accuracy.'],
                ['EV measures the decision, not your luck.', 'A correct play can still lose this draw.', 'Current EV uses every active multiplier.', 'Future value includes earned multipliers.', 'Equal-value holds are accepted as correct.'],
                ['Hold right TOP + BOTTOM for two seconds.', 'Toggles live trainer before key release.', 'TOP: cycle live information panels.', 'Hold BOTTOM: options and calculator.', 'Errors replay original multiplier boards.', 'Close/Clear drills use fixed 1x boards.']]
            for i, line in enumerate(pages[self.index]):
                self.text(image, (12, 51+i*24), line, 10, WHITE)
            self.center(image, 160, 202, '%s / 3    LEFT / RIGHT: PAGE' % (self.index+1), 8, MUTED)
        else:
            words = self.message.split()
            lines = ['']
            for word in words:
                if len(lines[-1])+len(word) > 42:
                    lines.append('')
                lines[-1] += (' ' if lines[-1] else '')+word
            for i, line in enumerate(lines[:5]):
                self.center(image, 160, 78+i*20, line, 11, WHITE)
        return image

    def decorate(self, image):
        if not self.app.training_mode or self.settings['mode'] != 'coach' or self.report is None or self.play.session.phase != 'hold' or self.play.menu:
            return image
        if self.play.hint_visible or self.play._animation is not None:
            return image
        snapshot = self.play.session.snapshot()
        if self._key != freeze_round(snapshot):
            return image
        mask = self.report['mask']
        draw = ImageDraw.Draw(image)
        if mask == 0:
            draw.rounded_rectangle((276, 218, 318, 233), radius=3, outline=GREEN, width=2)
        else:
            base_x, base_y = self.play.renderer.base_box(snapshot)
            for i in range(5):
                if mask & (1 << i):
                    left = math.floor((base_x+87*i)/2)
                    right = math.ceil((base_x+87*i+83)/2)-1
                    center=round((base_x+87*i+41)/2)
                    held_box=(center-15,184,center+15,202) if snapshot['held'][i] else None
                    held_pixels=image.crop(held_box) if held_box else None
                    draw.rounded_rectangle((left-1, base_y//2-2, right+1, base_y//2+61), radius=2, outline=GREEN, width=2)
                    if held_pixels is not None:image.paste(held_pixels,held_box[:2])
        return image

    def close(self):
        self.auto_grades.close()
        if self.advisor:
            self.advisor.close()
        self.state.save()
        self.state.store.close()
