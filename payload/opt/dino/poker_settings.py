"""General handheld settings, separate from optional training controls."""
from PIL import Image, ImageDraw
from poker_games import GAMES, PROFILE_GROUPS, get_game
from poker_engine import STARTING_CREDITS

BG=(5,7,30); GOLD=(255,220,65); WHITE=(235,239,250); MUTED=(155,168,193)


class DeviceSettings:
    def __init__(self, app, state):
        self.app, self.state = app, state
        self.page=None; self.index=0; self.message=''
        raw=state.data.get('device', {})
        brightness=raw.get('brightness', 100)
        speed=raw.get('animation_speed', 1)
        self.prefs={'brightness':brightness if type(brightness) is int and brightness in range(10,101,10) else 100,
                    'animation_speed':speed if type(speed) is int and speed in (0,1,2) else 1,
                    'profiles':{}}
        profiles=raw.get('profiles', {})
        for base, choices in PROFILE_GROUPS.items():
            if isinstance(profiles,dict) and profiles.get(base) in choices:
                self.prefs['profiles'][base]=profiles[base]
        self.app.play.speed=self.prefs['animation_speed']
        self.game_index=0; self.profile_index=0

    @property
    def active(self):return self.page is not None

    def resolve(self, game_id):
        game=get_game(game_id)
        if game.id!=game.cabinet_id:return game.id
        return self.prefs['profiles'].get(game.id,game.id)

    def save(self):
        self.state.data['device']=self.prefs
        self.state.save()

    def open(self):
        self.app._reset_controls()
        self.prefs['animation_speed']=self.app.play.speed
        self.page='main';self.index=0;self.message=''

    def close(self):
        self.page=None;self.app._reset_controls()

    def _select_profile_game(self, index):
        self.game_index=index%len(GAMES)
        choices=PROFILE_GROUPS[GAMES[self.game_index].id]
        current=self.resolve(GAMES[self.game_index].id)
        self.profile_index=choices.index(current)

    @property
    def profile_game(self):
        return get_game(PROFILE_GROUPS[GAMES[self.game_index].id][self.profile_index])

    def handle(self, action):
        if action=='KEY3':
            if self.page=='pays':self.page='profiles'
            elif self.page=='profiles':self.page='main';self.index=2
            else:self.close()
            return
        confirm=action in ('CENTER','KEY1','KEY2')
        delta=-1 if action in ('UP','LEFT') else 1
        if self.page=='pays':
            if confirm:self.page='profiles'
            return
        if action in ('UP','DOWN'):
            self.index=(self.index+delta)%(6 if self.page=='main' else 4)
            self.message='';return
        if not confirm and action not in ('LEFT','RIGHT'):return
        if self.page=='main':
            if self.index==0:
                self.prefs['brightness']=10+(self.prefs['brightness']-10+10*delta)%100
            elif self.index==1:
                self.app.play.speed=(self.app.play.speed+delta)%3
                self.prefs['animation_speed']=self.app.play.speed
            elif self.index==2:
                self.page='profiles';self.index=0
                self._select_profile_game(next(i for i,g in enumerate(GAMES) if g.id==self.app.play.session.game.cabinet_id))
                return
            elif self.index==3:
                self.save()
                self.state.store.set_persistent(not self.state.store.persistent)
                return
            elif self.index==4:
                if self.app.play.session.phase=='hold':self.message='Finish the current hand first.'
                else:
                    self.app.play.session.credits=STARTING_CREDITS
                    self.message='Play credits reset to 10,000.'
                return
            else:self.close();return
            self.save()
        elif self.page=='profiles':
            if self.index==0:self._select_profile_game(self.game_index+delta)
            elif self.index==1:
                choices=PROFILE_GROUPS[GAMES[self.game_index].id]
                self.profile_index=(self.profile_index+delta)%len(choices)
            elif self.index==2:self.page='pays'
            else:
                game=self.profile_game;play=self.app.play
                if game.cabinet_id==play.session.game.cabinet_id and play.session.phase=='hold':
                    self.message='Finish the current hand first.';return
                if self.resolve(game.cabinet_id)==game.id:
                    self.message='This preset is already selected.';return
                play._cancel_advice();self.app.trainer.cancel_analysis();play._finish_animation()
                self.app.calculator.cancel()
                self.prefs['profiles'][game.cabinet_id]=game.id
                self.save()
                if game.cabinet_id==play.session.game.cabinet_id:
                    play.session=play._cabinet_bank.select(game.id,play.session)
                    self.app.trainer.bind()
                self.message='Preset applied; strategy updated.'

    def render(self):
        image=Image.new('RGB',(320,240),BG);draw=ImageDraw.Draw(image);renderer=self.app.play.renderer
        def text(x,y,value,size=10,color=WHITE):renderer.text(draw,(x,y),str(value),size,color)
        def button(y,label,selected):
            draw.rounded_rectangle((10,y,310,y+22),radius=4,fill=(38,44,83) if selected else (19,24,59),
                                   outline=GOLD if selected else (49,61,98),width=2 if selected else 1)
            renderer.fitted_label(image,(16,y+3,304,y+19),label,11,GOLD if selected else WHITE,True)
        if self.page=='pays':
            source=renderer.render_paytable_source({'game_id':self.profile_game.id},{'bet':5})
            image=source.resize((320,240),Image.Resampling.LANCZOS)
            renderer.center(ImageDraw.Draw(image),160,228,'MIDDLE / BOTTOM: BACK',8,GOLD)
            return image
        text(10,5,'SETTINGS' if self.page=='main' else 'PAYTABLE PRESETS',13,GOLD)
        if self.page=='main':
            values=['Brightness    '+str(self.prefs['brightness'])+'%',
                    'Animations    '+('SLOW','NORMAL','INSTANT')[self.app.play.speed],
                    'Paytable presets', 'Persistent memory    '+('ON' if self.state.store.persistent else 'OFF'),
                    'Reset play credits', 'Return to cabinet']
            notes=[('Adjusts the LCD backlight.', '10% minimum keeps the menu visible.'),
                   ('Changes manual Deal / Draw reveals.', 'Autoplay pacing keeps its own modes.'),
                   ('Choose a game and verified paytable.', 'Payouts and strategy change together.'),
                   (('ON: options, errors and stats survive.', 'Hands, credits and autoplay reset.') if self.state.store.persistent else
                    ('OFF: session data stays in RAM.', 'Switching OFF clears the SD save.')),
                   ('Refills virtual credits to 10,000.', 'Finish a dealt hand before resetting.'),
                   ('Return to the cabinet selection.', 'Right TOP+BOTTOM, 2s: trainer sidebar.')][self.index]
            for i,label in enumerate(values):button(30+i*25,label,self.index==i)
            for i,line in enumerate(notes):text(12,184+i*11,line,8,MUTED)
            text(12,208,self.message or self.state.store.status,8,MUTED)
        else:
            game=self.profile_game
            full=game.pays[game.categories.index('full_house')];flush=game.pays[game.categories.index('flush')]
            labels=['Game: '+game.title+' / '+str(game.hands)+' hands',
                    'Preset: '+str(full)+'/'+str(flush)+(' - South Point photo' if game.id=='ddb10_75' else
                        ' - Original' if game.id==game.cabinet_id else ' - Alternate'),
                    'Review payouts and multipliers', 'Apply preset']
            for i,label in enumerate(labels):button(34+i*28,label,self.index==i)
            lines=('7/5 is verified from the supplied photo.', 'This is not a casino-wide preset.', 'Only listed, strategy-bound presets apply.')
            for i,line in enumerate(lines):text(12,160+i*12,line,8,MUTED)
            text(12,205,self.message or 'LEFT / RIGHT: change selected field',8,GOLD)
        draw.rectangle((0,220,319,239),fill=(8,11,36))
        renderer.center(draw,160,226,'D-PAD: MOVE / CHANGE   MIDDLE: SELECT   BOTTOM: BACK',7,MUTED)
        return image
