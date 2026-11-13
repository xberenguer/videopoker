#!/usr/bin/env python3
"""Stage a verified Video Poker release for review; never contacts GitHub."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_poker_image import PROJECT_VERSION

REPOSITORY = 'https://github.com/xberenguer/videopoker'
PREFIX = 'videopoker-v' + PROJECT_VERSION


def digest(body):
    return hashlib.sha256(body).hexdigest()


def main():
    destination = ROOT.parent / ('videopoker-publish-v' + PROJECT_VERSION)
    if destination.exists():
        raise ValueError('Publication staging already exists; inspect it before replacing it')
    source = ROOT / 'outputs' / (PREFIX + '-source.tar.gz')
    expected_sha, expected_name = source.with_name(source.name + '.sha256').read_text().split()
    if expected_name != source.name or digest(source.read_bytes()) != expected_sha:
        raise ValueError('Source checksum mismatch')
    image_name = PREFIX + '-pi0-320x240.img'
    image_sha = digest((ROOT / 'outputs' / image_name).read_bytes())
    tag = 'v' + PROJECT_VERSION.replace('.', '')
    evidence = json.loads((ROOT / 'validation' / ('release-validation-' + tag + '.json')).read_text())
    if evidence['image_sha256'] != image_sha or evidence['github_published']:
        raise ValueError('Release evidence differs or already claims publication')
    release_url = REPOSITORY + '/releases/download/v' + PROJECT_VERSION + '/'
    description = 'Offline video poker cabinet, calculator and trainer for Raspberry Pi Zero handhelds.'
    host_checks=json.loads((ROOT/'validation/tests.json').read_text())['tests_run']
    notes = f'''# Video Poker v{PROJECT_VERSION}

Twelve video poker presets, an EV calculator and a hidden trainer for a Raspberry Pi Zero 1.3 handheld with a 320 × 240 ST7789 display.

- Boot highlights Triple Play Bonus Poker, the first cabinet tile. Every game keeps its maximum-bet default.
- Memory is OFF by default. Explicit ON saves training history and device preferences; live hands, credits and autoplay always start fresh. Both settings menus explain the choice.
- General Settings adds LCD brightness, animation speed, virtual-credit reset and verified paytable presets.
- Three/ten-hand DDB offer 9/6, 9/5, 8/5 and 7/5 with matching offline policies; ten-hand 7/5 matches the supplied South Point photo.
- Completing the fifth calculator card starts analysis automatically; complete-hand edits refresh it.
- Hold right-column TOP+BOTTOM for two seconds to toggle the live trainer sidebar before release. Release fully before reusing the chord.
- Removes the cabinet Settings footer text; its bottom-right shortcut still works.
- Includes a complete controls, menus, training, statistics, EV and storage guide plus Raspberry Pi Imager installation steps.
- Video Poker branding and generic image/source filenames throughout the public presentation.

Download `{image_name}` and its matching `.sha256`, verify the checksum, then flash the IMG with your image writer. The matching source archive and image manifest are attached.

Validation: {host_checks} host checks passed, plus stock ARM emulation of all twelve games, six alternate policies, trainer/autoplay, calculator, rendering and memory transitions on a disposable guest-RAM file. Physical cold boot, LCD brightness, display timing and buttons still require hardware testing. Virtual credits only.

Required upstream and third-party attribution remains in the legal notices. See [README]({REPOSITORY}#readme), [licenses and credits]({REPOSITORY}/blob/main/NOTICE) and the attached source.
'''
    with tempfile.TemporaryDirectory(prefix='videopoker-publish-', dir=ROOT.parent) as temporary:
        stage = Path(temporary)
        repo = stage / 'repo'
        assets = stage / 'release-assets'
        repo.mkdir(); assets.mkdir()
        bodies = {}
        with tarfile.open(source, 'r:gz') as archive:
            for member in archive.getmembers():
                relative = PurePosixPath(member.name)
                if (not member.isfile() or relative.parts[0] != PREFIX
                        or '..' in relative.parts or relative.is_absolute()):
                    raise ValueError('Unsafe source member: ' + member.name)
                name = relative.relative_to(PREFIX).as_posix()
                if name in bodies:
                    raise ValueError('Duplicate source member: ' + name)
                bodies[name] = archive.extractfile(member).read()
        inventory = json.loads(bodies['SOURCE-INVENTORY.json'])
        if inventory['production_image_sha256'] != image_sha:
            raise ValueError('Source belongs to another image')
        if {name: digest(body) for name, body in bodies.items() if name != 'SOURCE-INVENTORY.json'} != inventory['files_sha256']:
            raise ValueError('Source inventory differs')
        for name, body in bodies.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        readme = repo / 'README.md'
        text = readme.read_text()
        for name in (image_name, image_name + '.sha256', source.name):
            text = text.replace('](outputs/' + name + ')', '](' + release_url + name + ')')
            if '](' + release_url + name + ')' not in text:
                raise ValueError('Expected release download missing from README: ' + name)
        readme.write_text(text)
        staged_inventory = dict(inventory)
        staged_inventory['files_sha256'] = dict(inventory['files_sha256'])
        staged_inventory['files_sha256']['README.md'] = digest(readme.read_bytes())
        staged_inventory['README_download_links_adapted_for_publication'] = True
        (repo / 'SOURCE-INVENTORY.json').write_text(json.dumps(staged_inventory, indent=2) + '\n')
        # Staging adjusts only the README's local download URLs. The attached
        # source archive remains the exact corresponding source that was verified.
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', text):
            if '://' not in target and not target.startswith('#') and not (repo / target.split('#')[0]).is_file():
                raise ValueError('Broken README link: ' + target)
        asset_names = (image_name, image_name + '.sha256', image_name + '.manifest.json',
                       source.name, source.name + '.sha256')
        for name in asset_names:
            original = ROOT / 'outputs' / name
            target = assets / name
            if name.endswith('.manifest.json'):
                public = json.loads(original.read_text().replace(str(ROOT), '.'))
                public['image'] = image_name
                target.write_text(json.dumps(public, indent=2) + '\n')
            else:
                shutil.copyfile(original, target)
        for name in (image_name, source.name):
            checksum, filename = (assets / (name + '.sha256')).read_text().split()
            if filename != name or digest((assets / name).read_bytes()) != checksum:
                raise ValueError('Staged asset differs: ' + name)
        (stage / 'release-notes.md').write_text(notes)
        settings = {'repository': REPOSITORY, 'release_tag': 'v' + PROJECT_VERSION,
                    'release_title': 'Video Poker v' + PROJECT_VERSION,
                    'about_description': description, 'github_changed': False,
                    'publish_only_after_user_confirmation':True,
                    'publication_order':['Upload release assets and verify their direct download URLs',
                                         'Apply prepared repository files and About description',
                                         'Verify rendered README images, guide links and visible release']}
        (stage / 'publication.json').write_text(json.dumps(settings, indent=2) + '\n')
        surfaces = [repo / 'README.md', repo / 'CHANGELOG.md', stage / 'release-notes.md',
                    stage / 'publication.json'] + list((repo / 'docs').rglob('*.md'))
        for path in surfaces:
            if 'seedsigner' in path.read_text().casefold():
                raise ValueError('Old product branding in public surface: ' + str(path.relative_to(stage)))
        report = {'status': 'READY_FOR_CONFIRMATION', 'version': PROJECT_VERSION,
                  'production_image_sha256': image_sha, 'source_archive_sha256': expected_sha,
                  'source_archive_inventory_verified': True, 'README_local_links_verified': True,
                  'README_download_targets_have_staged_assets': True,
                  'public_surfaces_without_old_brand': [p.relative_to(stage).as_posix() for p in surfaces],
                  'required_legal_attribution_and_technical_upstream_dependencies_preserved': True,
                  'repository_history_or_old_releases_modified': False,
                  'repository_changes_from_source': 'README download URLs adapted; inventory updated for that README only',
                  'github_published': False, 'physical_device_written': False,
                  'files_sha256': {p.relative_to(stage).as_posix(): digest(p.read_bytes())
                                   for p in sorted(stage.rglob('*')) if p.is_file()}}
        (stage / 'publication-audit.json').write_text(json.dumps(report, indent=2) + '\n')
        stage.rename(destination)
    print(json.dumps({'status': report['status'], 'directory': str(destination),
                      'release_assets': list(asset_names), 'github_published': False}, indent=2))


if __name__ == '__main__':
    main()
