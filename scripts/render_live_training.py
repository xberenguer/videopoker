#!/usr/bin/env python3
"""Render real native game/trainer frames using documented deterministic fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import random
import sys
import time
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_app import PokerApp
from poker_ui import PokerUI
from poker_engine import Session
from poker_training import TrainingState


class Clock:
    now=0.
    def __call__(self):return self.now


def main():
    out=ROOT/'validation/live-training-v066';out.mkdir(exist_ok=True)
    files=[];apps=[]
    def fixture(s):
        sample=s._sample
        s._sample=lambda population,count: [12,4,40,46,5] if len(population)==52 and count==5 else sample(population,count)
    def app(game='ddb10',fixed=True):
        clock=Clock();s=Session(game_id=game,rng=random.Random(8841))
        if fixed:
            fixture(s)
        a=PokerApp(play=PokerUI(s,cabinet=True,clock=clock),training_state=TrainingState(clock=clock))
        apps.append(a);return a
    def wait(a):
        deadline=time.monotonic()+12
        while a.trainer._token is not None and time.monotonic()<deadline:
            a.trainer.update(a.play._clock());time.sleep(.001)
        assert a.trainer.report
    def save(a,name):
        a.play._finish_animation()
        image=a.render();assert image.size==(320,240)
        image.save(out/(name+'.png'))
        image.resize((960,720),Image.Resampling.NEAREST).save(out/(name+'-3x.png'))
        files.append({'name':name,'training_mode':a.training_mode,'game':a.play.session.game.id,
                      'phase':a.play.session.phase,'page':a.trainer.page,'panel':a.training_hud.tab,
                      'frame_sha256':hashlib.sha256((out/(name+'.png')).read_bytes()).hexdigest(),
                      'snapshot':a.play.session.snapshot()})
    try:
        a=app();save(a,'01-regular-menu')
        a.play.menu['index']=9
        a.handle('KEY1');fixture(a.play.session);save(a,'02-regular-ready')
        a.play.session.deal();save(a,'03-regular-game')
        a.toggle_hidden_mode();wait(a);save(a,'04-test-live')
        # First finish the hand entered mid-round (assisted), then start a test.
        a.play.session.draw();a.play.session.deal();wait(a)
        t=a.trainer;bad=min(t.report['holds'],key=lambda row:row['value'])['mask']
        a.play.session.held=[bool(bad&(1<<i)) for i in range(5)]
        a.play._play();assert t.inline_warning is not None
        save(a,'05-inline-error')
        a.play.session.held=[bool(t.report['mask']&(1<<i)) for i in range(5)]
        a.play._play();save(a,'06-result-feedback')
        t.settings['mode']='coach';a.play.session.deal();wait(a)
        a.play.session.held=[bool(t.report['mask']&(1<<i)) for i in range(5)]
        save(a,'07-coach-live')
        a.training_hud.tab=1;save(a,'08-live-ev')
        a.training_hud.tab=2;save(a,'09-live-stats')
        a.training_hud.tab=0
        a.play.session.active_multipliers=[12]*10;t.cancel_analysis();t.ensure_analysis();wait(a)
        save(a,'10-multiplier-aware')
        t.open();save(a,'11-hidden-options')
        t.page='errors';save(a,'12-error-history')
        t.page='settings';save(a,'13-training-settings')
        t.dismiss();a.toggle_calculator();save(a,'14-calculator')
        for game in ('ddb3','job5','dw5','joker5'):
            b=app(game,False);b.play.menu=None;b.toggle_hidden_mode()
            b.trainer.settings['mode']='coach';b.play.session.deal();wait(b)
            save(b,'15-'+game+'-live')
        for game in ('ddb3','dw5'):
            b=app(game,False);b.play.menu=None;b.play.session.deal();b.play.session.draw()
            save(b,'16-'+game+'-regular')
        # Native frames enlarged with nearest-neighbor only, no invented artwork.
        pair=Image.new('RGB',(1280,480))
        for i,name in enumerate(('03-regular-game','07-coach-live')):
            pair.paste(Image.open(out/(name+'.png')).resize((640,480),Image.Resampling.NEAREST),(640*i,0))
        pair.save(out/'regular-and-trainer.png')
        names=('04-test-live','05-inline-error','07-coach-live','08-live-ev','09-live-stats','14-calculator')
        gallery=Image.new('RGB',(1280,1512),(8,10,25));draw=ImageDraw.Draw(gallery)
        for i,name in enumerate(names):
            x=(i%2)*640;y=(i//2)*504
            draw.text((x+10,y+5),name[3:].replace('-',' ').upper(),fill=(255,220,85))
            gallery.paste(Image.open(out/(name+'.png')).resize((640,480),Image.Resampling.NEAREST),(x,y+24))
        gallery.save(out/'gallery.png')
        payload={p.relative_to(ROOT/'payload').as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted((ROOT/'payload').rglob('*')) if p.is_file()}
        (out/'manifest.json').write_text(json.dumps({'native_size':[320,240],'version':'0.6.6',
            'fixture':'Deterministic RNG plus A clubs,6 clubs,3 spades,9 spades,7 clubs DDB fixture; runtime-rendered, not physical photos',
            'payload_sha256':payload,'screens':files},indent=2)+'\n')
        print(json.dumps({'output':str(out),'native_frames':len(files)}))
    finally:
        for a in apps:a.close()


if __name__=='__main__':main()
