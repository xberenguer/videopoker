#!/usr/bin/env python3
"""Prepare a private, local runtime bitmap set from public reference assets.

No credentials, account APIs or game sessions are used. HTTP403 stops all further
fetches. Source GIFs remain in validation/reference; runtime images are PNG only.
This script does not grant redistribution rights to third-party artwork.
"""
import argparse
import concurrent.futures
import hashlib
import io
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
HOST = 'https://media.vidpok.com/'
GAME = 'games/UltimateX/images/'
SHARED = 'shared_images/'


def sha(data): return hashlib.sha256(data).hexdigest()


def targets():
    rows = []
    def add(remote, local, role): rows.append((remote, local, role))
    for number in range(52): add(SHARED+'cards/'+str(number)+'.png', 'cards/'+str(number)+'.png', 'card-front')
    for name in ('Back', 'Back_Disabled'):
        add(SHARED+'cards/'+name+'.png', 'cards/'+name+'.png', 'card-back')
    for name in ('uxgamebg', 'uxpaytablebg', 'uxbg'):
        add(GAME+'background/'+name+'.png', 'backgrounds/'+name+'.png', 'background')
    for name in ('SeePaysHelp', 'SeePaysHelpDim', 'MoreGames', 'MoreGamesDim', 'BetPerHand', 'BetPerHandDim',
                 'SelectHands', 'SelectHandsDim', 'BetMax', 'BetMaxDim', 'Deal', 'DealDim', 'Draw', 'DrawDim',
                 'Speed01', 'Speed02', 'Speed03', 'SpeedDim', 'hold', 'speaker_0', 'speaker_1', 'speaker_2', 'speaker_3'):
        add(GAME+'gui/'+name+'.png', 'gui/'+name+'.png', 'gui')
    for number in range(13): add(GAME+'activatesigns/active'+str(number)+'_2.gif', 'badges/active'+str(number)+'.png', 'active-badge-frame')
    for number in range(7): add(GAME+'activatesigns/toactivate'+str(number)+'_2.gif', 'badges/inactive'+str(number)+'.png', 'inactive-badge-frame')
    for number in (2, 3, 4, 8, 10, 12):
        for suffix in ('_2', '_trans_2'):
            add(GAME+'multipliers/'+str(number)+'x'+suffix+'.gif', 'multipliers/'+str(number)+'x'+suffix+'.png', 'multiplier')
        if number in (10, 12):
            add(GAME+'multipliers/'+str(number)+'x_full_2.gif', 'multipliers/'+str(number)+'x_full_2.png', 'multiplier')
    add(GAME+'multipliers/nexthand.png', 'multipliers/nexthand.png', 'multiplier-label')
    for number in range(1, 17): add(GAME+'winindicators/payline'+str(number)+'_2.gif', 'wins/payline'+str(number)+'.png', 'win-indicator')
    for name in ('helpscreen1', 'helpscreen2', 'helpscreen3', 'helpscreen4', 'helpdraw1', 'helpdraw2'):
        add(GAME+'helpscreens/'+name+'.png', 'help/'+name+'.png', 'help-screen')
    for name in ('help', 'betup', 'betdown', 'return'):
        add(GAME+'helpscreens/buttons/'+name+'.png', 'help/buttons/'+name+'.png', 'help-control')
    for name in ('next-page', 'prev-page', 'exit-help'):
        add(SHARED+'helpscreens/'+name+'.png', 'help/shared/'+name+'.png', 'help-control')
    return rows



def glyph_atlases(runtime, extra_sizes=(), extra_labels=()):
    """Rasterize installed Arial once; no TTF is copied into the runtime."""
    rows, atlases = [], {}
    sizes = list(range(5, 41)) + [13.076923] + list(extra_sizes)
    labels = ['Royal Flush', 'Straight Flush', '4 Aces w/2,3,4',
              '4 2s,3s,4s w/Ace,2,3,4', '4 Aces', '4 2s,3s,4s',
              '4 5s thru Ks', 'Full House', 'Flush', 'Straight', '3 of a Kind',
              '2 Pair', 'Jacks or Better', 'Double Dbl Bonus', 'Game Over',
              'Shuffling is getting ready', 'MIDDLE: RETRY', 'Cards and credits are unchanged.',
              'INACTIVE X LOST ON DEAL', 'BET', 'HELP', 'RETURN TO GAME']
    labels.extend(['4 Aces w/ 2,3,4', '4 2s,3s,4s w/ Ace 2,3,4'])
    labels += [label.upper() for label in labels]
    labels.extend(extra_labels)
    pairs = sorted({text[i:i+2] for text in labels for i in range(len(text)-1)})
    for style, name in [('regular', 'Arial.ttf'), ('bold', 'Arial Bold.ttf')]:
        source = Path('/System/Library/Fonts/Supplemental')/name
        source_bytes = source.read_bytes()
        sheet = Image.new('RGBA', (1024, 2048), (0, 0, 0, 0))
        x, y, row_height = 1, 1, 0
        font_sizes = {}
        for size in sizes:
            key = str(size)
            font = ImageFont.truetype(str(source), size)
            glyphs = {}
            for code in range(32, 127):
                char = chr(code)
                bbox = font.getbbox(char, anchor='ls')
                width, height = max(1, bbox[2]-bbox[0]), max(1, bbox[3]-bbox[1])
                if x+width+1 > sheet.width:
                    x, y, row_height = 1, y+row_height+2, 0
                if y+height+1 > sheet.height:
                    raise ValueError('Arial atlas exceeds bounded 1024x2048 sheet')
                glyph = Image.new('RGBA', (width, height), (0, 0, 0, 0))
                ImageDraw.Draw(glyph).text((-bbox[0], -bbox[1]), char, font=font,
                                          fill=(255, 255, 255, 255), anchor='ls')
                sheet.paste(glyph, (x, y))
                glyphs[char] = {'x': x, 'y': y, 'width': width, 'height': height,
                                'advance': float(font.getlength(char)),
                                'bearing_x': bbox[0], 'bearing_y': bbox[1]}
                x += width+2
                row_height = max(row_height, height)
            kerning = {}
            for pair in pairs:
                adjustment = float(font.getlength(pair)-font.getlength(pair[0])-font.getlength(pair[1]))
                if adjustment: kerning[pair] = adjustment
            font_sizes[key] = {'glyphs': glyphs, 'kerning': kerning}
        used_height = y+row_height+1
        sheet = sheet.crop((0, 0, 1024, used_height))
        target = runtime/'fonts'/('arial-'+style+'.png')
        target.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(target, format='PNG', optimize=True)
        content = target.read_bytes()
        relative = target.relative_to(runtime).as_posix()
        rows.append({'path': relative, 'role': 'glyph-atlas-'+style, 'width': sheet.width,
                     'height': sheet.height, 'bytes': len(content), 'sha256': sha(content),
                     'source_kind': 'installed_font', 'source_url': source.as_uri(),
                     'source_sha256': sha(source_bytes), 'source_format': 'ttf', 'mode': 'RGBA',
                     'transform': 'ASCII32..126 Arial glyph rasterization at declared sizes; no raw font included',
                     'rights': 'Installed proprietary Arial font; derived bitmap for this private local build only.'})
        atlases[style] = {'path': relative, 'sizes': font_sizes}
    return rows, atlases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-bundle', type=Path)
    args = parser.parse_args()
    bundle = json.loads(args.browser_bundle.read_text()) if args.browser_bundle else {'assets': []}
    cached = {urllib.parse.urlparse(x['url']).path.lstrip('/'): x for x in bundle['assets']}
    originals = ROOT/'validation/reference/assets-original'
    runtime = ROOT/'payload/opt/dino/assets/videopoker'
    originals.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()

    def fetch(row):
        remote, local, role = row
        source_path = originals/remote
        source_path.parent.mkdir(parents=True, exist_ok=True)
        url = HOST+remote+'?v=3'
        if remote in cached:
            item = cached[remote]
            data = Path(item['path']).read_bytes()
            url = item['url']
            acquisition = 'browser-observed-public-resource'
        elif source_path.exists():
            data = source_path.read_bytes()
            acquisition = 'verified-local-public-resource-cache'
        else:
            if stop.is_set(): return {'blocked': remote}
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(request, timeout=25) as response:
                    data = response.read(8*1024*1024+1)
                    if len(data) > 8*1024*1024: raise ValueError('Source image exceeds 8MiB')
            except urllib.error.HTTPError as error:
                if error.code == 403: stop.set()
                return {'error': remote, 'http_status': error.code}
            acquisition = 'public-static-url-declared-by-reference-game'
        image = Image.open(io.BytesIO(data))
        fmt = image.format
        if fmt not in ('PNG', 'GIF') or image.width > 2048 or image.height > 2048:
            raise ValueError('Unsupported or oversized public image '+remote)
        source_path.write_bytes(data)
        image.seek(0)
        rgba = image.convert('RGBA')
        target = runtime/local
        target.parent.mkdir(parents=True, exist_ok=True)
        rgba.save(target, format='PNG', optimize=True)
        content = target.read_bytes()
        return {'path': local, 'role': role, 'width': rgba.width, 'height': rgba.height,
                'bytes': len(content), 'sha256': sha(content), 'source_url': url,
                'source_sha256': sha(data), 'source_format': fmt.lower(), 'mode': 'RGBA',
                'transform': 'Lossless RGBA decode of source frame 0; PNG encoding; no pixel edits',
                'acquisition': acquisition, 'source_frame_count': getattr(image, 'n_frames', 1)}

    rows = targets()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, rows))
    errors = [r for r in results if 'error' in r or 'blocked' in r]
    if errors:
        print(json.dumps({'status': 'incomplete', 'errors': errors}, indent=2))
        raise SystemExit(1)
    font_rows, fonts = glyph_atlases(runtime)
    results.extend(font_rows)
    manifest = {'schema': 1,
                'glyph_atlases': fonts, 'scope': 'private local reference-art build; no redistribution license granted',
                'rights': 'Third-party artwork retains its original rights. See THIRD-PARTY-ASSETS.txt.',
                'assets': sorted(results, key=lambda r:r['path']),
                'sequences': {
                    'active': {'frames': ['badges/active'+str(n)+'.png' for n in range(13)], 'duration_ms': 200},
                    'inactive': {'frames': ['badges/inactive'+str(n)+'.png' for n in range(7)], 'duration_ms': 300}}}
    target = runtime/'manifest.json'
    target.write_text(json.dumps(manifest, separators=(',', ':'))+'\n')
    print(json.dumps({'status':'PASS', 'assets':len(results), 'runtime_bytes':sum(a['bytes'] for a in results),
                      'manifest':str(target),'manifest_sha256':sha(target.read_bytes())}))


if __name__ == '__main__': main()
