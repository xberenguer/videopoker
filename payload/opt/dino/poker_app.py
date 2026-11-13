"""Unmarked poker machine, with a hold/release gate into the live trainer."""
from poker_ui import PokerUI
from poker_calculator import CardCalculator
from poker_training import TrainingState
from poker_training_store import TrainingStore
from poker_training_ui import TrainingController
from poker_training_hud import TrainingHUD
from poker_settings import DeviceSettings


class PokerApp:
    def __init__(self,play=None,calculator=None,training_state=None,training_advisor=None,training_mode=False,**kwargs):
        self.play=play if play is not None else PokerUI(**kwargs)
        self.calculator=calculator if calculator is not None else CardCalculator(renderer=self.play.renderer)
        self.calculator_active=False
        self.training_mode=bool(training_mode)  # Never restored from saved settings.
        self._closed=False
        self._pressed=0
        self._long_started=self._long_kind=self._consume_release=None
        state=training_state if training_state is not None else TrainingState(TrainingStore.hardware(),self.play._clock)
        self.trainer=TrainingController(self,state,training_advisor)
        self.training_hud=TrainingHUD()
        self.settings=DeviceSettings(self,state)
        self.play.profile_resolver=self.settings.resolve
        self.calculator.profile_resolver=self.settings.resolve

    @property
    def display_brightness(self):return self.settings.prefs['brightness']

    @property
    def active(self):
        if self.trainer.active and (self.training_mode or self.calculator_active):return self.trainer
        return self.calculator if self.calculator_active else self.play

    def _reset_controls(self):
        self._long_started=self._long_kind=self._consume_release=None
        self.play.pause_autoplay()
        self.play.set_pressed_mask(0)
        self.play.on_input_reset()

    def toggle_hidden_mode(self):
        """Right TOP+BOTTOM toggles the live sidebar at two seconds."""
        if hasattr(self,'settings'):self.settings.page=None
        self._reset_controls()
        self.trainer.dismiss()
        if self.calculator_active:
            self.calculator.cancel()
            self.calculator_active=False
            self.training_mode=True
            self.trainer.cancel_analysis()
            return True
        self.training_mode=not self.training_mode
        self.trainer.cancel_analysis()
        self.trainer.attempt=self.trainer.approved=None
        self.trainer.inline_warning=None
        self.trainer.inline_waiting=False
        self.trainer.revealed_key=None
        if self.training_mode:
            if self.play.menu and self.play.menu.get('page')=='cabinet':
                self.play._menu_action('CENTER')
                self.trainer.bind()
            if self.trainer.settings['mode']=='off':self.trainer.settings['mode']='test'
            self.trainer.assisted=self.play.session.phase=='hold'
            self.trainer.state.save()
            if self.play.session.phase=='hold':self.trainer.ensure_analysis()
        else:
            self.trainer.state.save()
            self.trainer.state.current=None
        return True

    def toggle_calculator(self):
        """Calculator is a utility inside the hidden workspace."""
        self.trainer.dismiss()
        self.trainer.cancel_analysis()
        self._reset_controls()
        if self.calculator_active:
            self.calculator.cancel()
            self.calculator_active=False
        else:
            if self.play.session.phase=='hold':self.trainer.assisted=True
            self.calculator.open(self.play.session.game.id)
            self.calculator_active=True
        return True

    def pause_autoplay(self):return self.play.pause_autoplay()

    def on_input_reset(self):
        self._long_started=self._long_kind=self._consume_release=None
        self.trainer.pending_draw=self.trainer.inline_waiting=False
        if self.calculator_active:
            if self.calculator._token is not None:
                self.calculator.cancel()
                self.calculator.status='Input reset. Top button: calculate again.'
            return True
        return self.play.on_input_reset()

    def set_pressed_mask(self,mask,captured_at=None):
        now=self.play._clock() if captured_at is None else captured_at
        self._pressed=mask
        if self.settings.active:return False
        kind=None
        if not self.trainer.active:
            if self.calculator_active and mask==32:kind='calculator_ev'
            elif self.training_mode and not self.calculator_active:
                if mask==128:kind='options'
                elif mask==32:kind='details'
        if kind!=self._long_kind:
            if self._long_kind and self._long_started is not None and now-self._long_started>=1.0:
                self._activate_long(self._long_kind)
            self._long_kind=kind
            self._long_started=now if kind else None
        if self.trainer.active and (self.training_mode or self.calculator_active):return False
        return False if self.calculator_active else self.play.set_pressed_mask(mask,captured_at)

    def set_pressed_mask_sampled(self,mask,captured_at):return self.set_pressed_mask(mask,captured_at)

    def _activate_long(self,kind):
        self._long_started=None
        self._consume_release='KEY3' if kind=='options' else 'KEY1'
        if kind=='calculator_ev':self.trainer.open_ev('calculator')
        elif kind=='options':self.trainer.open()
        elif self.play.session.phase=='result':
            self.play.pause_autoplay()
            self.play.menu={'page':'inspect','index':self.play.selected_hand}
        else:self.trainer.open_ev()

    def _route(self,action,captured_at=None):
        action=str(action).upper()
        self.trainer.bind()
        if self.settings.active:
            self.settings.handle(action)
            return
        if (not self.calculator_active and not self.trainer.active and self.play.menu
                and self.play.menu.get('page')=='cabinet' and action=='KEY3'):
            self.settings.open()
            return
        if (not self.calculator_active and not self.trainer.active and self.play.menu
                and self.play.menu.get('page')=='cabinet' and self.play.menu.get('return') and action=='KEY1'):
            self.play.menu=None;self.play.button_focus=None
            return
        if action==self._consume_release:
            self._consume_release=None
            return
        if self.trainer.active and (self.training_mode or self.calculator_active):
            self.trainer.handle(action)
            return
        if self.calculator_active:
            self.calculator.handle(action)
            if self.calculator.compare_ev_requested:
                self.calculator.compare_ev_requested=False
                self.trainer.open_ev('calculator')
            if self.calculator.exit_requested:self.toggle_calculator()
            return
        if self.training_mode:
            if action!='DOWN':self.trainer.pending_draw=self.trainer.inline_waiting=False
            if action=='KEY1' and not self.play.autoplay and self.play.menu is None and self.play.button_focus is None:
                self.training_hud.tab=(self.training_hud.tab+1)%3
                return
        if captured_at is None:self.play.handle(action)
        else:self.play.handle_sampled(action,captured_at)
        self.trainer.bind()

    def handle(self,action):return self._route(action)
    def handle_sampled(self,action,captured_at):return self._route(action,captured_at)

    def update(self,now):
        if self.settings.active:return False
        changed=False
        if self._long_kind and self._long_started is not None and now-self._long_started>=1.0:
            self._activate_long(self._long_kind)
            changed=True
        if not (self.trainer.active and (self.training_mode or self.calculator_active)):
            changed=(self.calculator if self.calculator_active else self.play).update(now) or changed
        if self.play._manual_hold_key is not None:self.trainer.assisted=True
        return self.trainer.update(now) or changed

    def render(self):
        if self.settings.active:return self.settings.render()
        if self.calculator_active:
            return self.trainer.render() if self.trainer.active else self.calculator.render()
        if not self.training_mode:
            image=self.play.render()
            if self.play.menu and self.play.menu.get('page')=='cabinet' and self.play.menu.get('return'):
                from PIL import ImageDraw
                self.play.renderer.center(ImageDraw.Draw(image),43,228,'TOP: BACK',7,(255,220,65))
            return image
        if self.trainer.active:return self.trainer.render()
        return self.training_hud.render(self.play,self.trainer)

    def on_frame_presented(self,now):
        if not self.calculator_active and not self.trainer.active:self.play.on_frame_presented(now)

    def close(self):
        if self._closed:return
        try:self.trainer.close()
        finally:
            try:self.play.close()
            finally:self.calculator.close()
        self._closed=True
