#!/usr/bin/env python3
"""Create a deterministic corresponding-source archive from a strict allowlist."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.4.8'
PREFIX = 'seedsigner-poker-v' + VERSION


def main():
    sys.path.insert(0, str(ROOT/'scripts'))
    from build_poker_image import collect_payload
    from payload_assets import validate_asset_inventory
    records = collect_payload(ROOT/'payload')
    visual_assets = validate_asset_inventory({
        name: content for name, (mode, content) in records.items()
        if stat.S_ISREG(mode)})
    files = []
    for directory in ('payload', 'scripts', 'tests', 'native'):
        files.extend(p for p in (ROOT/directory).rglob('*')
                     if p.is_file() and not p.is_symlink()
                     and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo'))
    files.extend(ROOT/name for name in ('README.md','LICENSE','NOTICE'))
    files.extend(ROOT/name for name in ('CHANGELOG.md', 'requirements-dev.txt', '.gitignore')
                 if (ROOT/name).is_file())
    files.extend(path for path in (ROOT/'docs').rglob('*')
                 if path.is_file() and not path.is_symlink()
                 and path.suffix.lower() in ('.md', '.json', '.jpg', '.jpeg', '.png', '.svg'))
    files.extend(path for path in (ROOT/'validation/strategy-research').glob('*.md')
                 if path.is_file() and not path.is_symlink())
    files.extend(ROOT/'inputs'/name for name in (
        'seedsigner-pgp.asc', 'seedsigner.0.8.7.sha256.txt',
        'seedsigner.0.8.7.sha256.txt.sig'))
    files.extend((ROOT/'validation').glob('*.json'))
    capture_directory = ROOT/'validation/screenshots-v048'
    capture_path = capture_directory/'capture-record.json'
    capture = json.loads(capture_path.read_text())
    if capture.get('version') != VERSION:
        raise ValueError('Preview evidence belongs to a different release')
    if capture.get('asset_manifest_sha256') != visual_assets['manifest_sha256']:
        raise ValueError('Previews do not match the declared visual assets')
    for name in ('poker_ui.py', 'poker_engine.py'):
        current = hashlib.sha256((ROOT/'payload/opt/dino'/name).read_bytes()).hexdigest()
        if capture.get('payload_sha256', {}).get(name) != current:
            raise ValueError('Previews do not match current source: ' + name)
    files.append(capture_path)
    for screen in capture['screens']:
        name = screen['name']
        if (not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name)
                or (screen['width'], screen['height']) != (320, 240)):
            raise ValueError('Invalid native capture name or dimensions')
        path = capture_directory/(name + '.png')
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing native capture: ' + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != screen.get('sha256'):
            raise ValueError('Native capture checksum changed: ' + name)
        files.append(path)
    if capture.get('demo_file') != 'gameplay-demo.gif':
        raise ValueError('Unexpected gameplay preview filename')
    demo = capture_directory/'gameplay-demo.gif'
    if (not demo.is_file() or demo.is_symlink()
            or hashlib.sha256(demo.read_bytes()).hexdigest() != capture.get('demo_sha256')):
        raise ValueError('Gameplay preview is missing or changed')
    files.append(demo)
    arm = json.loads((ROOT/'validation/arm-runtime.json').read_text())
    if arm.get('status') != 'PASS' or arm.get('version') != VERSION:
        raise ValueError('Missing successful target-runtime evidence')
    for name, digest in arm['png_sha256'].items():
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.png', name):
            raise ValueError('Invalid target-runtime capture filename')
        path = ROOT/'validation/arm-probe-v0.4.8'/name
        if (not path.is_file() or path.is_symlink()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError('Target-runtime capture missing or changed: ' + name)
        files.append(path)
    files = sorted(set(files), key=lambda p:p.relative_to(ROOT).as_posix())
    hashes = {}
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w',format=tarfile.PAX_FORMAT) as archive:
        for path in files:
            name = path.relative_to(ROOT).as_posix()
            if path.suffix.lower() in ('.img','.gba','.gb','.gbc','.nes','.so','.bin'):
                raise ValueError('Unexpected binary/ROM in source package: '+name)
            body = path.read_bytes()
            hashes[name] = hashlib.sha256(body).hexdigest()
            entry = tarfile.TarInfo(PREFIX+'/'+name)
            entry.size,entry.mode,entry.mtime = len(body),0o644,1672531200
            entry.uid = entry.gid = 0
            entry.uname = entry.gname = ''
            archive.addfile(entry,io.BytesIO(body))
    compressed_stream = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed_stream,mode='wb',filename='',compresslevel=9,mtime=0) as stream:
        stream.write(raw.getvalue())
    compressed = compressed_stream.getvalue()
    output = ROOT/'outputs'/('seedsigner-poker-v'+VERSION+'-source.tar.gz')
    if output.exists():
        raise ValueError('Refusing to overwrite an existing release: ' + str(output))
    output.write_bytes(compressed)
    digest = hashlib.sha256(compressed).hexdigest()
    output.with_name(output.name+'.sha256').write_text(digest+'  '+output.name+'\n')
    manifest = {'schema':1,'version':VERSION,'archive':output.name,
                'sha256':digest,'file_count':len(hashes),'files_sha256':hashes,
                'game_roms_or_emulator_binaries_included':False,
                'license':'Original code GPL-2.0-or-later; stock components and third-party visual assets retain their own rights; see NOTICE',
                'visual_assets':visual_assets,
                'vendor_gameplay_javascript_included':False,
                'raw_font_outlines_included':False,
                'base_image_included':False}
    output.with_name(output.name + '.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'source_archive':str(output),'sha256':digest,'files':len(hashes)}))


if __name__ == '__main__': main()
