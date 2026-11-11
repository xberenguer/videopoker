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
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ui_sha = hashlib.sha256((ROOT/'payload/opt/dino/poker_ui.py').read_bytes()).hexdigest()
    engine_sha = hashlib.sha256((ROOT/'payload/opt/dino/poker_engine.py').read_bytes()).hexdigest()
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
                        'speed': ui.speed, 'animation_active': ui._animation is not None})

    save('ready')
    ui.handle('KEY2'); ui.handle('CENTER')
    ui.handle('RIGHT'); ui.handle('RIGHT'); ui.handle('CENTER')
    save('hold')
    ui.handle('KEY2'); save('result')
    ui.handle('KEY2'); ui.handle('CENTER'); ui.handle('KEY2')
    save('multiplier-result')
    ui.handle('CENTER'); save('inspect')
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
    clean.speed = 2; clean.handle('KEY2')
    clean.menu = {'page': 'controls', 'index': 0}
    ui = clean; save('hold-help-1')
    ui.handle('KEY2'); save('hold-help-2'); ui = original
    poor = PokerUI(Session(credits=20, rng=random.Random(250)), font_dir=args.font_dir)
    poor.speed = 2; poor.handle('KEY2')
    original = ui; ui = poor; save('insufficient-credits'); ui = original
    class BlockedSampler:
        def sample(self, population, count):
            raise RandomNotReady('not ready')
    waiting = PokerUI(Session(rng=BlockedSampler()), font_dir=args.font_dir)
    waiting.handle('KEY2')
    ui = waiting; save('shuffle-wait'); ui = original

    clock = Clock()
    animated = PokerUI(Session(rng=random.Random(250)), font_dir=args.font_dir, clock=clock)
    animated.speed = 0
    frames = []
    for _ in range(3): frames.append(animated.render())
    animated.handle('KEY2')
    for _ in range(10):
        clock.value += 0.1; animated.update(clock.value); frames.append(animated.render())
    animated.handle('CENTER'); animated.handle('RIGHT'); animated.handle('RIGHT'); animated.handle('CENTER')
    for _ in range(5): frames.append(animated.render())
    animated.handle('KEY2')
    for _ in range(15):
        clock.value += 0.1; animated.update(clock.value); frames.append(animated.render())
    for _ in range(8): frames.append(animated.render())
    palette = getattr(Image, 'Palette', Image).ADAPTIVE
    frames = [frame.convert('P', palette=palette, colors=128) for frame in frames]
    frames[0].save(args.output/'gameplay-demo.gif', save_all=True, append_images=frames[1:],
                   duration=100, loop=0, optimize=True)
    if ui_sha != hashlib.sha256((ROOT/'payload/opt/dino/poker_ui.py').read_bytes()).hexdigest() or engine_sha != hashlib.sha256((ROOT/'payload/opt/dino/poker_engine.py').read_bytes()).hexdigest():
        raise RuntimeError('Source changed during capture; regenerate against frozen source')
    if manifest_sha != hashlib.sha256((asset_dir/'manifest.json').read_bytes()).hexdigest() or artwork_hashes() != declared_hashes:
        raise RuntimeError('Artwork changed during capture; regenerate against frozen assets')
    (args.output/'capture-record.json').write_text(json.dumps({
        'version': '0.3.2',
        'scope': 'deterministic actual application renders; no physical-device claim',
        'artwork': 'private local publicly served reference bitmaps and rasterized installed Arial glyphs',
        'ui_sha256': ui_sha,
        'engine_sha256': engine_sha,
        'asset_manifest_sha256': manifest_sha,
        'asset_sha256': declared_hashes,
        'payload_sha256': {'poker_ui.py': ui_sha, 'poker_engine.py': engine_sha},
        'demo_file': 'gameplay-demo.gif',
        'demo_sha256': hashlib.sha256((args.output/'gameplay-demo.gif').read_bytes()).hexdigest(),
        'screens': screens, 'demo_frames': len(frames),
    }, indent=2)+'\n')
    print(json.dumps({'output': str(args.output), 'screens': len(screens), 'demo_frames': len(frames)}))


if __name__ == '__main__': main()
