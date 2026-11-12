"""Independent image reconstruction/readback and payload-boundary tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import struct
import stat
import zlib

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "inputs/seedsigner_os.0.8.7.pi0.img"
SPEC = importlib.util.spec_from_file_location("poker_image", ROOT / "scripts/build_poker_image.py")
image = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(image)


def minimal_payload(root):
    app = root / "opt/dino"
    app.mkdir(parents=True)
    (root / "start.sh").write_text("#!/bin/sh\n/usr/bin/python3 /opt/dino/launcher.py\n")
    for filename in ("launcher.py", "hardware.py", "poker_engine.py", "poker_ui.py", "poker_strategy.py"):
        (app / filename).write_text("# image assembly safety fixture\n")
    assets = app / "assets/videopoker"
    assets.mkdir(parents=True)
    def chunk(kind, body):
        return struct.pack(">I",len(body))+kind+body+struct.pack(">I",zlib.crc32(kind+body)&0xffffffff)
    png = (b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",1,1,8,2,0,0,0))
           +chunk(b"IDAT",zlib.compress(b"\0\0\0\0"))+chunk(b"IEND",b""))
    (assets / "fixture.png").write_bytes(png)
    entry = {"path":"fixture.png","role":"test-fixture","bytes":len(png),
             "width":1,"height":1,"sha256":image.sha(png),
             "source_url":"https://example.com/test-fixture.png","source_sha256":image.sha(png)}
    (assets / "manifest.json").write_text(json.dumps({"schema":1,"assets":[entry]}))
    # Structural assembly fixture, deliberately not a usable advice table.
    from strategy_assets import CATEGORIES, PAYOUTS, MULTIPLIERS
    strategy = app / 'strategy'
    strategy.mkdir()
    raw = struct.pack('<8s6I4Q', b'UXSUB01\0', 1, 64, 14, 52, 4, 0,
                      64, 4449046, 0, 0) + bytes(4449046)
    (strategy / 'subset_counts.dat').write_bytes(raw)
    reachable = {0}
    for _ in range(10):
        reachable = {s+m for s in reachable for m in (1, 2, 3, 4, 8, 10, 12)}
    metadata = {'schema': 1, 'category_order': CATEGORIES, 'payouts': PAYOUTS,
                'multiplier_order': MULTIPLIERS, 'table_sha256': image.sha(raw),
                'bias': {'num_hands': 10, 'states': sorted(reachable),
                         'values': [0.0] * len(reachable), 'bellman_span': 0.0}}
    (strategy / 'strategy.json').write_text(json.dumps(metadata))


class PayloadTests(unittest.TestCase):
    def test_gzip_overlay_is_deterministic_and_decodes_to_identical_newc(self):
        records={'start.sh':(stat.S_IFREG|0o755,b'#!/bin/sh\n')}
        first=image.pack_overlay(records)
        self.assertEqual(first,image.pack_overlay(records))
        self.assertEqual(image.inspect_newc(first),image.inspect_newc(image.pack_newc(records)))
        for damaged in (first[:-1],first+b'unexpected suffix',b'\x1f\x8bnot gzip'):
            with self.assertRaises(ValueError):image.inspect_newc(damaged)

    def test_payload_newc_roundtrip_preserves_every_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            minimal_payload(root)
            records = image.collect_payload(root)
            archive = image.pack_newc(records)
            decoded = image.inspect_newc(archive)
            self.assertEqual(set(decoded), set(records))
            for name, (mode, content) in records.items():
                self.assertEqual(decoded[name]["content"], content)
                self.assertEqual(decoded[name]["mode"], mode)
                self.assertEqual(decoded[name]["mtime"], image.EPOCH)

    def test_symlinks_roms_binaries_and_host_cache_are_rejected(self):
        for filename in ("User-Game.gba", "core.so", "boot.bin", ".DS_Store", "host.pyc"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                minimal_payload(root)
                (root / "opt/dino" / filename).write_bytes(b"not allowed")
                with self.assertRaises(ValueError):
                    image.collect_payload(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            minimal_payload(root)
            (root / "opt/dino/link").symlink_to(root / "start.sh")
            with self.assertRaises(ValueError):
                image.collect_payload(root)

    def test_missing_engine_and_unexpected_root_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            minimal_payload(root)
            (root / "opt/dino/poker_engine.py").unlink()
            with self.assertRaises(ValueError):
                image.collect_payload(root)
            (root / "opt/dino/poker_engine.py").write_text("# restored fixture\n")
            (root / "etc").mkdir()
            with self.assertRaises(ValueError):
                image.collect_payload(root)

    def test_strategy_resources_are_required_bounded_and_hash_checked(self):
        for mutation in ('missing', 'truncated', 'changed', 'bad-bias'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                minimal_payload(root)
                data = root / 'opt/dino/strategy/subset_counts.dat'
                if mutation == 'missing':
                    data.unlink()
                elif mutation == 'truncated':
                    data.write_bytes(data.read_bytes()[:-1])
                elif mutation == 'changed':
                    raw = bytearray(data.read_bytes())
                    raw[-1] = 1
                    data.write_bytes(raw)
                else:
                    path = data.with_name('strategy.json')
                    meta = json.loads(path.read_text())
                    meta['bias']['bellman_span'] = float('nan')
                    path.write_text(json.dumps(meta))
                with self.assertRaises(ValueError):
                    image.collect_payload(root)

    def test_existing_and_raw_device_outputs_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "existing.img"
            existing.write_bytes(b"preserve me")
            with self.assertRaises(ValueError):
                image.new_path(existing)
            self.assertEqual(existing.read_bytes(), b"preserve me")
        with self.assertRaises(ValueError):
            image.new_path("/dev/poker-test-device")

    def test_archive_decoder_rejects_truncation_and_unsafe_names(self):
        records = {"opt": (0o40755, b""), "opt/dino": (0o40755, b""),
                   "opt/dino/a.py": (0o100644, b"payload")}
        archive = image.pack_newc(records)
        with self.assertRaises(ValueError):
            image.inspect_newc(archive[:150])
        entry = b"opt/dino/a.py\0"
        mutated = archive.replace(entry, b"opt/dino/../x\0")
        with self.assertRaises(ValueError):
            image.inspect_newc(mutated)


@unittest.skipUnless(BASE.is_file(), "Pinned stock base unavailable")
class ImageTests(unittest.TestCase):
    def test_pinned_stock_base_is_exact(self):
        data = BASE.read_bytes()
        self.assertEqual(len(data), image.BASE_SIZE)
        self.assertEqual(image.sha(data), image.BASE_SHA256)
        fat = image.Fat16(data)
        for name in ("bootcode.bin", "start_x.elf", "zImage", "config.txt"):
            self.assertIn(name, fat.files)

    def test_real_application_build_is_reproducible_and_preserves_stock(self):
        required = ("launcher.py", "hardware.py", "poker_engine.py", "poker_ui.py")
        if not all((ROOT / "payload/opt/dino" / name).is_file() for name in required):
            self.skipTest("Application source is still being assembled")
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "one.img"
            second = Path(directory) / "two.img"
            report = image.build(BASE, ROOT / "payload", first)
            other = image.build(BASE, ROOT / "payload", second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(report["sha256"], other["sha256"])
            base_fat, built_fat = image.Fat16(BASE.read_bytes()), image.Fat16(first.read_bytes())
            unchanged = set(base_fat.files) - {"config.txt"}
            self.assertEqual(report["preserved_upstream_file_count"], len(unchanged))
            for name in unchanged:
                self.assertEqual(built_fat.files[name], base_fat.files[name], name)
            self.assertEqual(json.loads(built_fat.files["settings.json"]), image.SETTINGS)
            self.assertEqual(set(built_fat.files), set(base_fat.files) | {image.OVERLAY_NAME, "settings.json"})
            overlay = image.inspect_newc(built_fat.files[image.OVERLAY_NAME])
            self.assertTrue(all("native/" not in name and not name.endswith((".gba", ".so")) for name in overlay))
            for name in required:
                self.assertEqual(overlay["opt/dino/" + name]["content"], (ROOT / "payload/opt/dino" / name).read_bytes())
            self.assertFalse(report["hardware_tested"])
            self.assertFalse(report["physical_device_written"])
            self.assertFalse(report["emulator_or_rom_included"])
            self.assertEqual((Path(str(first) + ".sha256")).read_text(), report["sha256"] + "  one.img\n")


if __name__ == "__main__":
    unittest.main()
