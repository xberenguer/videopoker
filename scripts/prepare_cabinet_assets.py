#!/usr/bin/env python3
"""Add cabinet static public graphics and raster glyphs with provenance.

Menu basenames are listed in the public common script; Ultimate X uses the
modern directory. No authenticated game request or vendor executable is used.
Existing third-party rights notices continue to apply.
"""
import hashlib
import io
import json
from pathlib import Path
import sys
from PIL import Image
from prepare_reference_assets import glyph_atlases

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_games import GAMES
TILES=('TPBU','TPBDU','TPDDBU','TPDWU','FPJBU','FPDBU','FPJOKERU','FPDWU',
       'TenPBU','TenPDDBU','TenPTDBU','TenPDWBU')


def main():
    assets=ROOT/'payload/opt/dino/assets/videopoker'
    originals=ROOT/'validation/cabinet/reference/new-assets'
    originals.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((assets/'manifest.json').read_text())
    by_path={item['path']:item for item in manifest['assets']}
    bundle=json.loads((originals.parent/'bundle-final.json').read_text())
    cached={item['url']:Path(item['path']) for item in bundle['assets']}
    requests=[]
    for game,tile in zip(GAMES,TILES):
        requests.append(('shared_images/gamebuttons/modern/'+tile+'.png','cabinet/'+game.id+'.png','cabinet-tile'))
    for name in ('Joker','0w','13w','26w','39w'):
        requests.append(('shared_images/cards/'+name+'.png','cards/'+name+'.png','card-front'))
    requests.append(('games/UltimateX/images/gamebuttons/transparentGreenRectangle.png','cabinet/selection.png','cabinet-selection'))
    requests.append(('games/UltimateX/images/gui/ReturnToGame.png','cabinet/return.png','cabinet-return'))
    for number in (5,6,7,11):
        requests.append(('games/UltimateX/images/multipliers/'+str(number)+'x_2.gif','multipliers/'+str(number)+'x_2.png','multiplier'))
    acquired=[]
    for remote,local,role in requests:
        url='https://media.vidpok.com/'+remote+'?v=3'
        original=originals/Path(remote).name
        if original.exists():raw=original.read_bytes()
        elif url in cached and cached[url].is_file():
            raw=cached[url].read_bytes();original.write_bytes(raw)
        else:
            # The static host rejected a direct fetch (403). Do not retry or
            # change request identity. Use only the already captured visible
            # reference menu for missing artwork, with explicit provenance.
            source=originals.parent/'menu-return-bp3-focus.png'
            if local=='cabinet/bp3.png':source=originals.parent/'cabinet-menu.png'
            with Image.open(source) as opened:
                capture_format=opened.format.lower()
                if role=='cabinet-tile':
                    index=next(i for i,g in enumerate(GAMES) if local=='cabinet/'+g.id+'.png')
                    left,top=30+157*(index%4),74+100*(index//4)
                    box=tuple(round(v*1.3125) for v in (left,top,left+130,top+66))
                    image=opened.crop(box).resize((130,66),Image.Resampling.LANCZOS).convert('RGBA')
                elif role=='cabinet-return':
                    image=opened.crop((715,561,824,625)).resize((83,49),Image.Resampling.LANCZOS).convert('RGBA')
                else:raise ValueError('No acquired original or visible reference crop: '+local)
            target=assets/local;target.parent.mkdir(parents=True,exist_ok=True)
            image.save(target,format='PNG',optimize=True);body=target.read_bytes()
            item=dict(path=local,role=role,width=image.width,height=image.height,bytes=len(body),
                      sha256=hashlib.sha256(body).hexdigest(),
                      source_url='https://www.videopoker.com/play/?game=69',
                      source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                      source_format='visible-reference-screenshot-'+capture_format,mode='RGBA',
                      transform='Crop of visible reference menu, resampled from 840x630 to logical 640x480',
                      acquisition='visible-page-screenshot; static download unavailable')
            by_path[local]=item;acquired.append(item)
            continue
        with Image.open(io.BytesIO(raw)) as opened:
            source_format=opened.format.lower();image=opened.convert('RGBA')
        target=assets/local;target.parent.mkdir(parents=True,exist_ok=True)
        image.save(target,format='PNG',optimize=True)
        body=target.read_bytes()
        item=dict(path=local,role=role,width=image.width,height=image.height,bytes=len(body),
                  sha256=hashlib.sha256(body).hexdigest(),source_url=url,
                  source_sha256=hashlib.sha256(raw).hexdigest(),source_format=source_format,
                  mode='RGBA',transform='Lossless RGBA decode of source frame 0; PNG encoding; no pixel edits',
                  acquisition='public-static-media-over-TLS',source_frame_count=1)
        by_path[local]=item;acquired.append(item)
    sizes=sorted({round(170/len(game.rows),6) for game in GAMES}-{13.076923,17.0})
    labels=[text for game in GAMES for text in [game.title]+[game.label(key) for key in game.rows]]
    fonts,atlases=glyph_atlases(assets,extra_sizes=sizes,extra_labels=labels)
    for item in fonts:by_path[item['path']]=item
    manifest['assets']=sorted(by_path.values(),key=lambda item:item['path'])
    manifest['glyph_atlases']=atlases
    (assets/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (originals/'cabinet-acquisition.json').write_text(json.dumps(acquired,indent=2)+'\n')
    print(json.dumps(dict(added=len(acquired),asset_count=len(manifest['assets']),font_sizes=sizes)))


if __name__=='__main__':main()
