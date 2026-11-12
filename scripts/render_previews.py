#!/usr/bin/env python3
"""Capture actual deterministic renderer frames and a nonblocking game demo.

Private local reference bitmap artwork. These are actual software-rendered
screens, not photographs of physical hardware. All UI/engine/art hashes are
guarded across capture; no vendor game code is used.
"""
import argparse
import copy
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'payload/opt/dino'))
from poker_engine import Session, RandomNotReady
from poker_ui import PokerUI
from PIL import Image


class Clock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'validation/screenshots')
    parser.add_argument('--font-dir', type=Path,
                        default=ROOT.parent/'seedconsole-dualboot/build/signer/source/src/seedsigner/resources/fonts')
    parser.add_argument('--strategy-dir', type=Path, default=ROOT/'payload/opt/dino/strategy',
                        help='Certified strategy data used to verify deterministic advice captures')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ui_sha = hashlib.sha256((ROOT/'payload/opt/dino/poker_ui.py').read_bytes()).hexdigest()
    engine_sha = hashlib.sha256((ROOT/'payload/opt/dino/poker_engine.py').read_bytes()).hexdigest()
    strategy_sha = hashlib.sha256((ROOT/'payload/opt/dino/poker_strategy.py').read_bytes()).hexdigest()
    script_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    asset_dir = ROOT/'payload/opt/dino/assets/videopoker'
    manifest_bytes = (asset_dir/'manifest.json').read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    asset_manifest = json.loads(manifest_bytes)
    def artwork_hashes():
        return {item['path']: hashlib.sha256((asset_dir/item['path']).read_bytes()).hexdigest()
                for item in asset_manifest['assets']}
    declared_hashes = {item['path']: item['sha256'] for item in asset_manifest['assets']}
    if artwork_hashes() != declared_hashes:
        raise RuntimeError('Artwork differs from its declared manifest')
    capture_clock = Clock()
    ui = PokerUI(Session(rng=random.Random(250)), font_dir=args.font_dir, clock=capture_clock)
    ui.speed = 2  # Logic captures settle instantly; animation captured separately.
    screens = []
    nearest = getattr(Image, 'Resampling', Image).NEAREST

    def save(name):
        image = ui.render()
        native = args.output/(name+'.png')
        expanded = args.output/(name+'-4x.png')
        image.save(native)
        image.resize((1280, 960), nearest).save(expanded)
        screens.append({'name': name, 'width': 320, 'height': 240,
                        'file': native.name, 'sha256': hashlib.sha256(native.read_bytes()).hexdigest(),
                        'expanded_file': expanded.name, 'expanded_sha256': hashlib.sha256(expanded.read_bytes()).hexdigest(),
                        'phase': ui.session.phase, 'menu': copy.deepcopy(ui.menu),
                        'speed': ui.speed, 'animation_active': ui._animation is not None,
                        'autoplay': ui.autoplay, 'autoplay_stage': ui._auto_stage,
                        'autoplay_speed': ui.autoplay_speed,
                        'hint_mask': ui._advice['mask'] if ui._advice is not None else None,
                        'up_held': ui._up_held, 'hint_visible': ui.hint_visible})

    save('ready')
    ui.handle('DOWN'); ui.handle('CENTER')
    ui.handle('RIGHT'); ui.handle('RIGHT'); ui.handle('CENTER')
    save('hold')
    ui.handle('DOWN'); save('result')
    ui.handle('KEY2'); ui.handle('CENTER'); ui.handle('DOWN')
    save('multiplier-result')
    ui.handle('KEY1'); save('inspect')
    ui.handle('KEY3'); ui.handle('KEY3'); save('gold-controls')
    ui.handle('CENTER'); save('paytable')
    for _ in range(5): ui.handle('RIGHT')
    save('paytable-bonus')
    ui.handle('CENTER'); save('help-1')
    for index in range(2, 5):
        ui.handle('KEY2'); save('help-'+str(index))
    ui.handle('KEY3'); ui.handle('KEY3')
    ui.session.set_bet_per_hand(1); ui.session.set_num_hands(1)
    save('partial-hands')
    clean = PokerUI(Session(rng=random.Random(250)), font_dir=args.font_dir, clock=capture_clock)
    clean.session.set_bet_per_hand(1); clean.session.set_num_hands(1)
    original = ui; ui = clean; save('single-hand-ready'); ui = original
    clean.speed = 2; clean.handle('DOWN')
    clean.menu = {'page': 'controls', 'index': 0}
    ui = clean; save('hold-help-1')
    ui.handle('KEY2'); save('hold-help-2'); ui = original
    poor = PokerUI(Session(credits=20, rng=random.Random(250)), font_dir=args.font_dir)
    poor.speed = 2; poor.handle('DOWN')
    original = ui; ui = poor; save('insufficient-credits'); ui = original
    class BlockedSampler:
        def sample(self, population, count):
            raise RandomNotReady('not ready')
    waiting = PokerUI(Session(rng=BlockedSampler()), font_dir=args.font_dir)
    waiting.handle('DOWN')
    ui = waiting; save('shuffle-wait'); ui = original

    # The real exact-count solver verifies this hand before capturing. Its
    # answer is then injected only to make the capture clock deterministic;
    # production PokerUI still uses the cancellable background advisor.
    from poker_strategy import StrategyTable, _round
    class AcesSampler:
        def sample(self, population, count):
            return [12, 25, 38, 1, 2]  # Ac Ad Ah 3c 4c: hold the three aces.
    strategy_files = {name: hashlib.sha256((args.strategy_dir/name).read_bytes()).hexdigest()
                      for name in ('strategy.json', 'subset_counts.dat')}
    advice_session = Session(rng=AcesSampler())
    advice_session.deal()
    advice_snapshot = advice_session.snapshot()
    exact_advice = StrategyTable(args.strategy_dir).advise(_round(advice_snapshot))
    if exact_advice['mask'] != 7:
        raise RuntimeError('Certified capture hand no longer holds its three aces')
    class CaptureAdvisor:
        def request(self, snapshot):
            if _round(snapshot) != _round(advice_snapshot):
                raise RuntimeError('Capture advisor received a different visible hand')
            return 1
        def poll(self, token):
            return dict(exact_advice) if token == 1 else None
        def cancel(self): pass
        def close(self): pass
    advice_clock = Clock()
    advice_ui = PokerUI(advice_session, font_dir=args.font_dir, clock=advice_clock,
                       advisor=CaptureAdvisor())
    advice_ui.speed = 2
    advice_ui.autoplay_speed = 1
    ui = advice_ui
    ui.set_pressed_mask(1); ui.handle('UP'); ui.update(advice_clock())
    advice_clock.value += ui.HINT_HOLD_SECONDS
    ui.update(advice_clock())
    assert ui.hint_visible and ui._advice['mask'] == 7 and not ui.autoplay
    save('hint-on')
    ui.set_pressed_mask(0); ui.update(advice_clock())
    assert not ui.hint_visible and ui._advice['mask'] == exact_advice['mask']
    save('hint-off')
    ui.pause_autoplay()  # Separate the manual-hold and autoplay capture gestures.
    for _ in range(2):
        advice_clock.value += .1
        ui.set_pressed_mask(1);ui.handle('UP');ui.set_pressed_mask(0)
    advice_clock.value += ui.UP_CLICK_GAP_SECONDS+ui.UP_TAP_COMMIT_GRACE_SECONDS+.01
    ui.update(advice_clock())
    assert not ui.autoplay and ui.session.held==[True,True,True,False,False]
    save('manual-best-hold')
    for index,held in enumerate(ui.session.held):
        if held: ui.session.toggle_hold(index)
    ui.pause_autoplay()
    for _ in range(3):
        advice_clock.value += .1
        ui.set_pressed_mask(1);ui.handle('UP');ui.set_pressed_mask(0)
    for _ in range(2):
        advice_clock.value += .1
        ui.set_pressed_mask(1); ui.handle('UP'); ui.set_pressed_mask(0)
    advice_clock.value += ui.UP_CLICK_GAP_SECONDS+ui.UP_TAP_COMMIT_GRACE_SECONDS+.01
    ui._commit_auto_up()
    assert ui.autoplay_speed == 1
    ui.update(advice_clock())
    advice_clock.value += ui.AUTO_CONSIDER_SECONDS+.01
    ui.update(advice_clock())
    for _ in range(2):
        advice_clock.value += ui.AUTO_SELECT_SECONDS+.01
        ui.update(advice_clock())
    assert ui.autoplay and ui._auto_stage=='select' and not ui.hint_visible
    assert ui.selected_card==2 and ui.session.held==[True,True,False,False,False]
    save('autoplay')
    save('autoplay-medium')
    for suffix in ('fast','manual'):
        before_speed_change=ui.session.snapshot()
        for click in range(2):
            # Start the gesture before the next fast card-selection tick.
            advice_clock.value += .02 if click==0 else .1
            ui.set_pressed_mask(1);ui.handle('UP');ui.set_pressed_mask(0)
        advice_clock.value += ui.UP_CLICK_GAP_SECONDS+ui.UP_TAP_COMMIT_GRACE_SECONDS+.01
        ui.update(advice_clock())
        assert ui.autoplay and ui.session.snapshot()==before_speed_change
        save('autoplay-'+suffix)
    advice_capture = {
        'hand': advice_snapshot['initial'], 'mask': exact_advice['mask'],
        'active_multipliers': advice_snapshot['active_multipliers'],
        'basis': 'Actual certified StrategyTable result; injected only for deterministic capture timing',
        'answer': exact_advice,
        'data_sha256': strategy_files,
        'peek': 'Solid red borders only while UP is physically held; release has no overlay',
        'autoplay': 'Triple UP toggles autoplay on and off; each activation starts M. Single/held UP preserves an active mode. During autoplay double UP advances one speed; holding does not. Manual double UP sets exact best holds without drawing. A has no icon Slow, filled left triangle Medium, and adds right triangle Fast. M is first/default, followed by Medium and Fast. M waits at both Deal and Draw: DOWN deals, waits for study, then the next DOWN applies the best holds together and draws immediately. The M mark is 5x4 pixels. No added pacing or animation in M. Other buttons stop autoplay without another action.',
        'autoplay_profiles': list(PokerUI.AUTO_PROFILES),
    }
    ui.close()
    # A full actual M-mode cycle with an exact advisor, deterministic RNG and
    # an injected presentation clock. The delivered app still uses its worker.
    manual_clock=Clock();manual_table=StrategyTable(args.strategy_dir)
    class ManualCaptureAdvisor:
        def __init__(self):self.token=0;self.answers={}
        def request(self,snapshot):
            self.token+=1;self.answers[self.token]=manual_table.advise(_round(snapshot));return self.token
        def poll(self,token):return self.answers.pop(token,None)
        def cancel(self):self.answers.clear()
        def close(self):self.answers.clear()
    ui=PokerUI(Session(rng=random.Random(250)),font_dir=args.font_dir,clock=manual_clock,advisor=ManualCaptureAdvisor())
    for _ in range(3):
        manual_clock.value+=.1;ui.set_pressed_mask(1);ui.handle('UP');ui.set_pressed_mask(0)
    ui.update(manual_clock());assert ui.manual_autoplay and ui._auto_stage=='manual-deal'
    save('autoplay-manual-ready')
    ui.handle('DOWN');ui.update(manual_clock())
    assert ui._auto_stage=='manual-draw' and ui._advice is not None and ui.session.held==[False]*5
    manual_mask=ui._advice['mask'];save('autoplay-manual-think')
    ui.handle('DOWN');assert ui._auto_stage=='manual-deal' and ui.session.phase=='result'
    assert ui.session.held==[bool(manual_mask&(1<<i)) for i in range(5)]
    assert ui._animation is None;save('autoplay-manual-result')
    advice_capture['manual_autoplay']={'mode_order':['manual','medium','fast'],'default':'manual',
        'mask':manual_mask,'presses_per_round':2,'behavior':'DOWN Deal, wait to think; DOWN exact holds and immediate Draw; wait for next Deal',
        'marker_native_pixels':[5,4],'pacing_or_animation_delays':False}
    ui.close()
    class DrawFiveSampler:
        def sample(self,population,count): return [26,20,41,43,6]
    draw_game=Session(rng=DrawFiveSampler());draw_game.deal()
    draw_snapshot=draw_game.snapshot()
    draw_advice=StrategyTable(args.strategy_dir).advise(_round(draw_snapshot))
    assert draw_advice['mask']==0
    class DrawCaptureAdvisor:
        def request(self,snapshot):
            assert _round(snapshot)==_round(draw_snapshot)
            return 1
        def poll(self,token): return dict(draw_advice) if token==1 else None
        def cancel(self): pass
        def close(self): pass
    draw_clock=Clock()
    ui=PokerUI(draw_game,font_dir=args.font_dir,clock=draw_clock,advisor=DrawCaptureAdvisor())
    ui.speed=2;ui.set_pressed_mask(1);ui.handle('UP');ui.update(draw_clock())
    assert not ui.hint_visible
    draw_clock.value+=ui.HINT_HOLD_SECONDS+.001;ui.update(draw_clock())
    save('draw-hint')
    pulse_frames=[]
    for i in range(25):
        draw_clock.value=ui._draw_hint_started+i*ui.HINT_DRAW_FLASH_SECONDS/24
        ui.update(draw_clock());pulse_frames.append(ui.render())
    pulse_frames.extend([pulse_frames[-1]]*20)
    pulse_frames[0].save(args.output/'draw-hint-flash.gif',save_all=True,append_images=pulse_frames[1:],duration=40,loop=0)
    draw_clock.value=ui._draw_hint_started+ui.HINT_DRAW_FLASH_SECONDS/2;ui.update(draw_clock())
    save('draw-hint-normal')
    ui.set_pressed_mask(0);ui.update(draw_clock());save('draw-hint-off')
    assert not ui.hint_visible and draw_game.snapshot()==draw_snapshot
    advice_capture['draw_five']={'hand':draw_snapshot['initial'],'actual_advice':draw_advice,
        'appearance':'Only the real Draw button face flashes red at one cycle per second, while UP is held after the 0.30-second delay; exact dark label and bevel retained'}
    ui.close(); ui = original

    # Actual menu and all twelve engines/layouts, not fabricated device renders.
    from poker_games import GAMES
    cabinet_clock=Clock()
    cabinet_ui=PokerUI(Session(game_id='bp3',cabinet_defaults=False,rng=random.Random(600)),
                       cabinet=True,clock=cabinet_clock)
    ui=cabinet_ui;save('cabinet-menu')
    for game_index,game in enumerate(GAMES):
        ui.menu={'page':'cabinet','index':game_index,'return':game_index>0}
        save('cabinet-'+game.id+'-selected')
        ui.handle('CENTER');ui.speed=2
        save('cabinet-'+game.id+'-ready')
        ui._button_action(5);save('cabinet-'+game.id+'-hold')
        ui.handle('DOWN');save('cabinet-'+game.id+'-result')
        ui._button_action(0);save('cabinet-'+game.id+'-paytable')
    from poker_cabinet_strategy import CabinetStrategyTable,freeze_round
    class CabinetCaptureAdvisor:
        # The actual solver supplies the answer; only its delivery is made
        # synchronous for deterministic screenshots. Runtime stays async.
        def __init__(self):self.table=CabinetStrategyTable();self.answer=None;self.token=0
        def request(self,snapshot):
            self.answer=self.table.advise(freeze_round(snapshot));self.token+=1;return self.token
        def poll(self,token):return dict(self.answer) if token==self.token and self.answer is not None else None
        def cancel(self):self.answer=None
        def close(self):self.table=None;self.answer=None
    ui.menu={'page':'cabinet','index':9,'return':True};ui.handle('CENTER')
    ui._advisor=CabinetCaptureAdvisor()
    for _ in range(3):
        cabinet_clock.value+=.1
        ui.set_pressed_mask(1);ui.handle('UP');ui.set_pressed_mask(0)
    ui.update(cabinet_clock());save('cabinet-autoplay-manual-ready')
    ui.handle('DOWN');ui.update(cabinet_clock());save('cabinet-autoplay-manual-think')
    ui.handle('DOWN');save('cabinet-autoplay-manual-result')
    cabinet_ui.close();ui=original

    clock = Clock()
    animated = PokerUI(Session(rng=random.Random(250)), font_dir=args.font_dir, clock=clock)
    animated.speed = 0
    frames = []
    for _ in range(3): frames.append(animated.render())
    animated.handle('DOWN')
    for _ in range(10):
        clock.value += 0.1; animated.update(clock.value); frames.append(animated.render())
    animated.handle('CENTER'); animated.handle('RIGHT'); animated.handle('RIGHT'); animated.handle('CENTER')
    for _ in range(5): frames.append(animated.render())
    animated.handle('DOWN')
    for _ in range(15):
        clock.value += 0.1; animated.update(clock.value); frames.append(animated.render())
    for _ in range(8): frames.append(animated.render())
    palette = getattr(Image, 'Palette', Image).ADAPTIVE
    frames = [frame.convert('P', palette=palette, colors=128) for frame in frames]
    frames[0].save(args.output/'gameplay-demo.gif', save_all=True, append_images=frames[1:],
                   duration=100, loop=0, optimize=True)
    if ui_sha != hashlib.sha256((ROOT/'payload/opt/dino/poker_ui.py').read_bytes()).hexdigest() or engine_sha != hashlib.sha256((ROOT/'payload/opt/dino/poker_engine.py').read_bytes()).hexdigest():
        raise RuntimeError('Source changed during capture; regenerate against frozen source')
    if strategy_sha != hashlib.sha256((ROOT/'payload/opt/dino/poker_strategy.py').read_bytes()).hexdigest() or script_sha != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise RuntimeError('Advice/capture source changed during capture; regenerate')
    if any(digest != hashlib.sha256((args.strategy_dir/name).read_bytes()).hexdigest()
           for name, digest in strategy_files.items()):
        raise RuntimeError('Strategy data changed during capture; regenerate')
    if manifest_sha != hashlib.sha256((asset_dir/'manifest.json').read_bytes()).hexdigest() or artwork_hashes() != declared_hashes:
        raise RuntimeError('Artwork changed during capture; regenerate against frozen assets')
    (args.output/'capture-record.json').write_text(json.dumps({
        'version': '0.5.1',
        'scope': 'deterministic actual application renders; no physical-device claim',
        'artwork': 'private local publicly served reference bitmaps and rasterized installed Arial glyphs',
        'ui_sha256': ui_sha,
        'engine_sha256': engine_sha,
        'strategy_sha256': strategy_sha,
        'capture_script_sha256': script_sha,
        'advice_capture': advice_capture,
        'asset_manifest_sha256': manifest_sha,
        'asset_sha256': declared_hashes,
        'payload_sha256': {'poker_ui.py': ui_sha, 'poker_engine.py': engine_sha,
                           'poker_strategy.py': strategy_sha},
        'demo_file': 'gameplay-demo.gif',
        'demo_sha256': hashlib.sha256((args.output/'gameplay-demo.gif').read_bytes()).hexdigest(),
        'screens': screens, 'demo_frames': len(frames),
    }, indent=2)+'\n')
    print(json.dumps({'output': str(args.output), 'screens': len(screens), 'demo_frames': len(frames)}))


if __name__ == '__main__': main()
