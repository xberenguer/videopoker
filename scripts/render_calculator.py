#!/usr/bin/env python3
"""Capture real 320x240 calculator screens against a frozen runtime inventory."""
import hashlib
import json
from pathlib import Path
import sys
import time

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_app import PokerApp
from poker_games import GAMES


def runtime_hashes():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'payload/opt/dino').glob('*.py'))}


def main():
    folder=ROOT/'validation/screenshots-v052';folder.mkdir(exist_ok=False)
    before=runtime_hashes();app=PokerApp();screens=[];demo=[]
    def save(name):
        image=app.render();assert image.mode=='RGB' and image.size==(320,240)
        path=folder/(name+'.png');image.save(path)
        expanded=folder/(name+'-4x.png');image.resize((1280,960),Image.Resampling.NEAREST).save(expanded)
        screens.append({'name':name,'width':320,'height':240,'file':path.name,
                        'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                        'expanded_file':expanded.name,'expanded_sha256':hashlib.sha256(expanded.read_bytes()).hexdigest(),
                        'calculator':app.calculator_active,'page':app.calculator.page if app.calculator_active else 'play',
                        'game_id':app.calculator.game_id if app.calculator_active else app.play.session.game.id,
                        'cards':list(app.calculator.cards) if app.calculator_active else [],
                        'multipliers':list(app.calculator.multipliers) if app.calculator_active else [],
                        'mask':app.calculator.result['mask'] if app.calculator_active and app.calculator.result else None})
        demo.append(image.copy())
    def solve():
        c=app.calculator;assert c.calculate();deadline=time.monotonic()+5
        while c._token is not None and time.monotonic()<deadline:c.update(time.monotonic());time.sleep(.001)
        assert c.result is not None,c.status
    try:
        save('play-menu');app.toggle_calculator();save('calculator-menu')
        c=app.calculator;c.select_game('ddb10');save('calculator-empty')
        c.start_picker(0);c.picker_card=35;save('calculator-picker');c.page='editor'
        for i,card in enumerate((35,14,24,48,34)):c.set_card(i,card)
        save('calculator-entry');c.set_multiplier(4,3);c.set_multiplier(6,2)
        c.page='multipliers';c.multiplier_focus=4;save('calculator-multipliers');c.page='editor'
        solve();assert c.result['mask']==9;save('calculator-result')
        c.page='pays';save('calculator-paytable');c.page='editor'
        c.focus=9;c.handle('CENTER')
        for i,card in enumerate((9,24,14,23,4)):c.set_card(i,card)
        for i in range(10):c.set_multiplier(i,1)
        solve();assert c.result['mask']==14;save('calculator-continued-low')
        for i in range(10):c.set_multiplier(i,12)
        solve();assert c.result['mask']==10;save('calculator-continued-high')
        for i in range(10):c.set_multiplier(i,1)
        c.set_continued(False);solve();assert c.result['mask']==10;save('calculator-current-hand')
        for game in GAMES:
            c.select_game(game.id)
            hand=(52,12,25,38,0) if game.deck_size==53 else (12,25,38,11,24)
            for i,card in enumerate(hand):c.set_card(i,card)
            for i in range(game.hands):c.set_multiplier(i,game.possible_multipliers[(i+2)%len(game.possible_multipliers)])
            solve();save('calculator-'+game.id+'-result')
        for i,card in enumerate((1,16,31,44,12)):c.set_card(i,card)
        # The UI's no-hold/all-hold states are also captured with real solver
        # answers, rather than fabricated mask injection.
        c.select_game('ddb10')
        c.focus=9;c.handle('CENTER')
        for i,card in enumerate((12,11,10,9,8)):c.set_card(i,card)
        solve();assert c.result['mask']==31;save('calculator-hold-all')
        app.toggle_calculator();save('play-returned')
        palette=[im.convert('P',palette=Image.Palette.ADAPTIVE,colors=128) for im in demo[:8]]
        palette[0].save(folder/'gameplay-demo.gif',save_all=True,append_images=palette[1:],duration=1600,loop=0)
    finally:app.close()
    assert before==runtime_hashes(),'Runtime changed during capture'
    record={'version':'0.5.2','scope':'actual software renderer; no physical-device claim',
            'payload_sha256':before,'asset_manifest_sha256':hashlib.sha256((ROOT/'payload/opt/dino/assets/videopoker/manifest.json').read_bytes()).hexdigest(),
            'screens':screens,'demo_file':'gameplay-demo.gif','demo_sha256':hashlib.sha256((folder/'gameplay-demo.gif').read_bytes()).hexdigest()}
    (folder/'capture-record.json').write_text(json.dumps(record,indent=2)+'\n')
    docs=ROOT/'docs/screenshots'
    for name in ('calculator-menu','calculator-picker','calculator-multipliers','calculator-result','calculator-paytable','calculator-current-hand','calculator-joker5-result','calculator-dwb10-result'):
        (docs/(name+'.png')).write_bytes((folder/(name+'-4x.png')).read_bytes())
    print(json.dumps({'screens':len(screens),'folder':str(folder)}))


if __name__=='__main__':main()
