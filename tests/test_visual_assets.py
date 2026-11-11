"""Adversarial tests for declared local artwork, not artwork licensing claims."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from test_poker_image import minimal_payload, image as builder
import payload_assets as assets


def png(width=1,height=1,data=None):
    def chunk(kind,body):
        return struct.pack(">I",len(body))+kind+body+struct.pack(">I",zlib.crc32(kind+body)&0xffffffff)
    pixels = data if data is not None else (b"\0"*(width*3+1))*height
    return (b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,2,0,0,0))
            +chunk(b"IDAT",zlib.compress(pixels))+chunk(b"IEND",b""))


class VisualAssetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        minimal_payload(self.root)
        self.files = {p.relative_to(self.root).as_posix():p.read_bytes()
                      for p in self.root.rglob('*') if p.is_file()}

    def manifest(self):
        return json.loads(self.files[assets.MANIFEST])

    def save(self,manifest):
        self.files[assets.MANIFEST] = json.dumps(manifest).encode()

    def replace_png(self,body):
        manifest = self.manifest()
        manifest['assets'][0].update(bytes=len(body),sha256=hashlib.sha256(body).hexdigest())
        self.files[assets.PREFIX+'fixture.png'] = body
        self.save(manifest)

    def test_valid_inventory_and_sequence_report_are_bound_to_bytes(self):
        manifest = self.manifest()
        manifest['sequences'] = {'pulse':{'frames':['fixture.png'],'duration_ms':200}}
        self.save(manifest)
        report = assets.validate_asset_inventory(self.files)
        self.assertEqual(report['png_count'],1)
        self.assertEqual(report['sequence_count'],1)
        self.assertEqual(report['decoded_rgba_budget_bytes'],4)
        self.assertEqual(report['manifest_sha256'],hashlib.sha256(self.files[assets.MANIFEST]).hexdigest())
        self.assertIn('not granted by project GPL',report['artwork_rights'])

    def test_undeclared_files_and_traversal_paths_are_rejected(self):
        self.files[assets.PREFIX+'surprise.png'] = png()
        with self.assertRaises(ValueError):assets.validate_asset_inventory(self.files)
        del self.files[assets.PREFIX+'surprise.png']
        for path in ('../escape.png','/absolute.png','cards//x.png','cards/./x.png','cards\\x.png'):
            manifest = self.manifest()
            manifest['assets'][0]['path'] = path
            self.save(manifest)
            with self.subTest(path=path),self.assertRaises(ValueError):assets.validate_asset_inventory(self.files)

    def test_wrong_digest_size_and_dimensions_are_rejected(self):
        valid = self.manifest()
        for key,value in (('sha256','0'*64),('bytes',1),('width',2),('height',True),('mode','RGBA')):
            manifest = copy.deepcopy(valid)
            manifest['assets'][0][key] = value
            self.save(manifest)
            with self.subTest(key=key),self.assertRaises(ValueError):assets.validate_asset_inventory(self.files)

    def test_png_crc_trailing_data_and_compression_bomb_are_rejected(self):
        original = png()
        bad_crc = bytearray(original);bad_crc[20] ^= 1
        for body in (bytes(bad_crc),original+b'junk',png(data=b'\0'*1000000),b'not a PNG'):
            self.replace_png(body)
            with self.assertRaises(ValueError):assets.validate_asset_inventory(self.files)

    def test_oversized_png_header_is_rejected_before_inflate(self):
        self.replace_png(png(width=5000,height=1,data=b'\0'))
        manifest = self.manifest();manifest['assets'][0]['width']=5000;self.save(manifest)
        with self.assertRaises(ValueError):assets.validate_asset_inventory(self.files)

    def test_duplicate_json_keys_assets_and_invalid_timing_are_rejected(self):
        original = self.files[assets.MANIFEST]
        self.files[assets.MANIFEST] = original.replace(b'"schema": 1',b'"schema": 1, "schema": 1')
        with self.assertRaises(ValueError):assets.validate_asset_inventory(self.files)
        self.files[assets.MANIFEST] = original
        valid = self.manifest()
        manifest = copy.deepcopy(valid);manifest['assets']*=2;self.save(manifest)
        with self.assertRaises(ValueError):assets.validate_asset_inventory(self.files)
        for sequence in ({'frames':['fixture.png'],'duration_ms':0},
                         {'frames':['not-declared.png'],'duration_ms':200},
                         {'frames':[{}],'duration_ms':200},
                         {'frames':['fixture.png'],'durations_ms':[float('nan')]}):
            manifest = copy.deepcopy(valid);manifest['sequences']={'pulse':sequence};self.save(manifest)
            with self.subTest(sequence=sequence),self.assertRaises(ValueError):assets.validate_asset_inventory(self.files)

    def test_installed_font_exception_is_exact_and_metadata_only(self):
        manifest = self.manifest();entry = manifest['assets'][0]
        body = self.files.pop(assets.PREFIX+'fixture.png')
        entry.update(path='fonts/arial-regular.png',role='glyph-atlas-regular',
                     source_kind='installed_font',source_format='ttf',
                     source_url='file:///System/Library/Fonts/Supplemental/Arial.ttf',
                     rights='Source font retains its own rights; no open reuse license asserted.')
        self.files[assets.PREFIX+entry['path']] = body;self.save(manifest)
        self.assertEqual(assets.validate_asset_inventory(self.files)['png_count'],1)
        for url in ('file:///Users/example/private.ttf','file://remote/System/Library/Fonts/Supplemental/Arial.ttf'):
            entry['source_url'] = url;self.save(manifest)
            with self.assertRaises(ValueError):assets.validate_asset_inventory(self.files)

    def test_raw_font_binary_is_not_a_runtime_format(self):
        manifest=self.manifest();entry=manifest['assets'][0]
        entry.update(path='fonts/raw.ttf',kind='font',source_url='https://example.com/raw.ttf')
        self.save(manifest)
        with self.assertRaises(ValueError):assets.validate_asset_inventory(self.files)

    def test_glyph_rectangles_and_numeric_metadata_are_bounded(self):
        manifest = self.manifest();entry = manifest['assets'][0]
        body = self.files.pop(assets.PREFIX+'fixture.png')
        entry.update(path='fonts/arial-regular.png',role='glyph-atlas-regular',source_kind='installed_font',
                     source_url='file:///System/Library/Fonts/Supplemental/Arial.ttf',rights='Original font rights retained.')
        self.files[assets.PREFIX+entry['path']] = body
        glyph={'x':0,'y':0,'width':1,'height':1,'advance':1.0,'bearing_x':0,'bearing_y':0}
        manifest['glyph_atlases']={'regular':{'path':entry['path'],'sizes':{'10':{'glyphs':{'A':glyph},'kerning':{'AA':0.0}}}}}
        self.save(manifest);assets.validate_asset_inventory(self.files)
        for key,value in (('width',2),('advance',float('inf')),('bearing_x',-999)):
            changed=copy.deepcopy(manifest);changed['glyph_atlases']['regular']['sizes']['10']['glyphs']['A'][key]=value
            self.save(changed)
            with self.subTest(key=key),self.assertRaises(ValueError):assets.validate_asset_inventory(self.files)

    def test_executable_asset_mode_symlinks_and_unexpected_code_are_rejected(self):
        fixture=self.root/'opt/dino/assets/videopoker/fixture.png';fixture.chmod(0o755)
        with self.assertRaises(ValueError):builder.collect_payload(self.root)
        fixture.chmod(0o644)
        (self.root/'opt/dino/extra.py').write_text('print("not allowed")')
        with self.assertRaises(ValueError):builder.collect_payload(self.root)


if __name__=='__main__':unittest.main()
