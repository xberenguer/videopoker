"""Strict, non-executing inventory checks for declared poker visual assets.

This verifies formats, hashes and resource bounds. It does not grant or infer
copyright permissions; source and rights records remain the owner's notices.
"""
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
import struct
from urllib.parse import unquote, urlsplit
import zlib

PREFIX = "opt/dino/assets/videopoker/"
MANIFEST = PREFIX + "manifest.json"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_ASSETS = 512
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_TOTAL_RGBA_BYTES = 32 * 1024 * 1024
MAX_DIMENSION = 4096
MAX_IMAGE_PIXELS = 4 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}\Z")
PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")
APP_FILES = frozenset(("start.sh", "opt/dino/LICENSE", "opt/dino/NOTICE",
                      "opt/dino/THIRD-PARTY-ASSETS.txt",
                      "opt/dino/hardware.py", "opt/dino/launcher.py",
                      "opt/dino/poker_app.py", "opt/dino/poker_calculator.py",
                      "opt/dino/poker_engine.py", "opt/dino/poker_ui.py",
                      "opt/dino/poker_strategy.py",
                      "opt/dino/strategy/subset_counts.dat",
                      "opt/dino/strategy/strategy.json",
                      "opt/dino/poker_games.py", "opt/dino/poker_evaluate.py",
                      "opt/dino/poker_cabinet_strategy.py", "opt/dino/poker_cabinet_ui.py",
                      "opt/dino/strategy/deuces_counts.dat", "opt/dino/strategy/joker_counts.dat"))
APP_FILES = APP_FILES | frozenset("opt/dino/strategy/cabinet/"+name+".json" for name in
    ("bp3","bpd3","ddb3","dw3","job5","db5","joker5","dw5","bp10","ddb10","tdb10","dwb10"))
APP_FILES = APP_FILES | frozenset(('opt/dino/poker_training.py', 'opt/dino/poker_training_ui.py',
    'opt/dino/poker_training_store.py', 'opt/dino/poker_training_hud.py', 'opt/dino/training_drills.json',
    'opt/dino/poker_settings.py'))
APP_FILES = APP_FILES | frozenset('opt/dino/strategy/cabinet/'+base+'_'+suffix+'.json'
    for base in ('ddb3','ddb10') for suffix in ('95','85','75'))


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid asset " + label)
    return value


def _path(value):
    if (not isinstance(value, str) or not PATH.fullmatch(value)
            or str(PurePosixPath(value)) != value
            or PurePosixPath(value).is_absolute()
            or any(part in (".", "..") or part.startswith(".")
                   for part in PurePosixPath(value).parts)):
        raise ValueError("Unsafe visual asset path")
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate asset manifest key")
        result[key] = value
    return result


def _number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Invalid glyph " + label)
    return value


def _glyph_atlases(atlases, dimensions):
    if not isinstance(atlases,dict) or not 1 <= len(atlases) <= 2 or set(atlases)-{"regular","bold"}:
        raise ValueError("Unexpected glyph atlas inventory")
    for style,atlas in atlases.items():
        expected = "fonts/arial-" + style + ".png"
        if not isinstance(atlas,dict) or set(atlas)!={"path","sizes"} or atlas["path"] != expected or expected not in dimensions:
            raise ValueError("Glyph atlas does not match declared Arial PNG")
        width,height = dimensions[expected]
        sizes = atlas["sizes"]
        if not isinstance(sizes,dict) or not 1 <= len(sizes) <= 64:
            raise ValueError("Invalid glyph size inventory")
        for size,description in sizes.items():
            try:
                numeric_size = float(size)
            except (TypeError,ValueError) as error:
                raise ValueError("Invalid glyph size") from error
            _number(numeric_size,1,80,"size")
            if not isinstance(description,dict) or set(description)!={"glyphs","kerning"}:
                raise ValueError("Unexpected glyph size description")
            glyphs = description["glyphs"]
            if not isinstance(glyphs,dict) or not 1 <= len(glyphs) <= 95:
                raise ValueError("Invalid glyph character inventory")
            for char,glyph in glyphs.items():
                if (not isinstance(char,str) or len(char)!=1 or not 32 <= ord(char) <= 126
                        or not isinstance(glyph,dict)
                        or set(glyph)!={"x","y","width","height","advance","bearing_x","bearing_y"}):
                    raise ValueError("Unexpected glyph descriptor")
                x = _integer(glyph["x"],0,width,"glyph x")
                y = _integer(glyph["y"],0,height,"glyph y")
                w = _integer(glyph["width"],0,256,"glyph width")
                h = _integer(glyph["height"],0,256,"glyph height")
                if x+w>width or y+h>height:
                    raise ValueError("Glyph rectangle exceeds atlas")
                _number(glyph["advance"],0,256,"advance")
                _number(glyph["bearing_x"],-256,256,"bearing x")
                _number(glyph["bearing_y"],-256,256,"bearing y")
            kerning = description["kerning"]
            if not isinstance(kerning,dict) or len(kerning)>95*95:
                raise ValueError("Invalid kerning inventory")
            for pair,value in kerning.items():
                if not isinstance(pair,str) or len(pair)!=2 or any(not 32 <= ord(c) <= 126 for c in pair):
                    raise ValueError("Invalid kerning pair")
                _number(value,-80,80,"kerning")


def _png(body):
    """Verify PNG framing/CRCs and bounded noninterlaced pixel decompression."""
    if body[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Visual asset is not PNG")
    offset, header, compressed = 8, None, bytearray()
    saw_end, saw_data, data_finished = False, False, False
    palette = None
    while offset < len(body):
        if len(body) - offset < 12:
            raise ValueError("Truncated PNG chunk")
        size = struct.unpack_from(">I", body, offset)[0]
        kind = body[offset+4:offset+8]
        end = offset + 12 + size
        if end > len(body) or not re.fullmatch(b"[A-Za-z]{4}", kind):
            raise ValueError("Invalid PNG chunk")
        value = body[offset+8:offset+8+size]
        checksum = struct.unpack_from(">I", body, offset+8+size)[0]
        if zlib.crc32(kind+value) & 0xffffffff != checksum:
            raise ValueError("PNG chunk CRC mismatch")
        if header is None and kind != b"IHDR":
            raise ValueError("PNG must begin with IHDR")
        if kind == b"IHDR":
            if header is not None or size != 13:
                raise ValueError("Invalid PNG header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", value)
            _integer(width, 1, MAX_DIMENSION, "PNG width")
            _integer(height, 1, MAX_DIMENSION, "PNG height")
            if width*height > MAX_IMAGE_PIXELS:
                raise ValueError("PNG decoded pixel budget exceeded")
            allowed = {0:(1,2,4,8), 2:(8,), 3:(1,2,4,8), 4:(8,), 6:(8,)}
            if (color not in allowed or depth not in allowed[color]
                    or compression or filtering or interlace):
                raise ValueError("Unsupported PNG encoding; use lossless noninterlaced 8-bit RGB/RGBA")
            header = width, height, depth, color
        elif kind == b"PLTE":
            if saw_data or palette is not None or not size or size % 3 or size > 768:
                raise ValueError("Invalid PNG palette")
            palette = size // 3
        elif kind == b"IDAT":
            if data_finished:
                raise ValueError("Noncontiguous PNG data")
            compressed.extend(value)
            saw_data = True
        elif kind == b"IEND":
            if size or not saw_data or end != len(body):
                raise ValueError("Invalid PNG end")
            saw_end = True
            break
        else:
            if kind == b"acTL":
                raise ValueError("Animated PNG is not a declared static frame")
            if not kind[0] & 32:
                raise ValueError("Unsupported critical PNG chunk")
            if saw_data:
                data_finished = True
        offset = end
    if not saw_end or header is None:
        raise ValueError("Incomplete PNG")
    width, height, depth, color = header
    if color == 3 and (palette is None or palette > (1 << depth)):
        raise ValueError("Missing or invalid indexed PNG palette")
    channels = {0:1, 2:3, 3:1, 4:2, 6:4}[color]
    row = (width*channels*depth+7)//8
    expected = (row+1)*height
    decoder = zlib.decompressobj()
    try:
        pixels = decoder.decompress(bytes(compressed), expected+1)
    except zlib.error as error:
        raise ValueError("Invalid PNG compressed data") from error
    if (len(pixels) != expected or decoder.unconsumed_tail or decoder.unused_data
            or not decoder.eof or any(pixels[y*(row+1)] > 4 for y in range(height))):
        raise ValueError("PNG decompression bounds or scanline filter mismatch")
    return width, height, width*height*4, {0:"L",2:"RGB",3:"P",4:"LA",6:"RGBA"}[color]



def validate_asset_inventory(files):
    """Validate full overlay-name → bytes mappings without extracting assets."""
    raw = files.get(MANIFEST)
    if raw is None or not 1 <= len(raw) <= MAX_MANIFEST_BYTES:
        raise ValueError("Missing or oversized visual asset manifest")
    try:
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid visual asset manifest JSON") from error
    if (not isinstance(manifest, dict) or manifest.get("schema") != 1
            or type(manifest.get("schema")) is not int
            or set(manifest)-{"schema", "assets", "sequences", "rights_note", "scope", "rights", "glyph_atlases"}):
        raise ValueError("Unexpected visual manifest schema")
    assets = manifest.get("assets")
    for key in ("rights_note", "scope", "rights"):
        if key in manifest and (not isinstance(manifest[key],str) or len(manifest[key])>4000):
            raise ValueError("Invalid artwork rights/scope note")
    if not isinstance(assets, list) or not 1 <= len(assets) <= MAX_ASSETS:
        raise ValueError("Invalid visual asset count")
    declared, total_bytes, rgba_bytes = set(), 0, 0
    png_paths, font_paths, dimensions = set(), set(), {}
    required = {"path", "role", "bytes", "sha256", "source_url", "source_sha256"}
    optional = {"kind", "width", "height", "mode", "source_format", "source_kind", "transform", "rights", "acquisition", "source_frame_count"}
    for asset in assets:
        if not isinstance(asset, dict) or not required <= asset.keys() or set(asset)-required-optional:
            raise ValueError("Unexpected visual asset entry")
        path = _path(asset["path"])
        if path in declared:
            raise ValueError("Duplicate visual asset path")
        declared.add(path)
        kind = asset.get("kind", "png")
        extension = PurePosixPath(path).suffix.lower()
        if kind != "png" or extension != ".png":
            raise ValueError("Unsupported visual asset format")
        if not isinstance(asset["role"], str) or not 1 <= len(asset["role"]) <= 80:
            raise ValueError("Invalid visual asset role")
        for key in ("sha256", "source_sha256"):
            if not isinstance(asset[key], str) or not HEX.fullmatch(asset[key]):
                raise ValueError("Invalid visual asset digest")
        url = asset["source_url"]
        if not isinstance(url, str) or not 1 <= len(url) <= 2048:
            raise ValueError("Invalid visual source URL")
        parsed = urlsplit(url)
        source_kind = asset.get("source_kind", "public")
        if source_kind == "installed_font":
            installed = {
                ("glyph-atlas-regular", "fonts/arial-regular.png"): "/System/Library/Fonts/Supplemental/Arial.ttf",
                ("glyph-atlas-bold", "fonts/arial-bold.png"): "/System/Library/Fonts/Supplemental/Arial Bold.ttf"}
            if (kind != "png" or parsed.scheme != "file" or parsed.netloc
                    or parsed.query or parsed.fragment
                    or installed.get((asset["role"], path)) != unquote(parsed.path)
                    or not isinstance(asset.get("rights"), str) or not asset["rights"].strip()):
                raise ValueError("Unexpected installed-font provenance; only declared Arial glyph PNGs are allowed")
        elif (source_kind != "public" or parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password):
            raise ValueError("Visual source URL must be public HTTPS")
        for key in ("source_format", "transform", "rights", "acquisition"):
            if key in asset and (not isinstance(asset[key], str) or len(asset[key]) > 1000):
                raise ValueError("Invalid visual source metadata")
        if "source_frame_count" in asset:
            _integer(asset["source_frame_count"],1,256,"source frame count")
        body = files.get(PREFIX+path)
        size = _integer(asset["bytes"], 1, MAX_FILE_BYTES, "file size")
        if body is None or len(body) != size or hashlib.sha256(body).hexdigest() != asset["sha256"]:
            raise ValueError("Visual asset is missing or changed: " + path)
        total_bytes += size
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError("Total visual asset byte budget exceeded")
        if kind == "png":
            width, height, decoded, actual_mode = _png(body)
            if asset.get("width") != width or type(asset.get("width")) is not int or asset.get("height") != height or type(asset.get("height")) is not int:
                raise ValueError("Visual PNG dimensions differ from declaration")
            if "mode" in asset and asset["mode"] != actual_mode:
                raise ValueError("Visual PNG mode differs from declaration")
            rgba_bytes += decoded
            png_paths.add(path)
            dimensions[path] = width,height
        if rgba_bytes > MAX_TOTAL_RGBA_BYTES:
            raise ValueError("Total decoded visual asset budget exceeded")
    expected = APP_FILES | {MANIFEST} | {PREFIX+path for path in declared}
    if set(files)-expected:
        raise ValueError("Undeclared payload file: " + sorted(set(files)-expected)[0])
    sequences = manifest.get("sequences", {})
    if not isinstance(sequences, dict) or len(sequences) > 64:
        raise ValueError("Invalid visual sequence inventory")
    for name, sequence in sequences.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name)
                or not isinstance(sequence, dict) or set(sequence)-{"frames", "duration_ms", "durations_ms"}):
            raise ValueError("Invalid visual sequence")
        frames = sequence.get("frames")
        if not isinstance(frames, list) or not 1 <= len(frames) <= 256 or any(not isinstance(frame,str) or frame not in png_paths for frame in frames):
            raise ValueError("Visual sequence references an undeclared PNG")
        if ("duration_ms" in sequence) == ("durations_ms" in sequence):
            raise ValueError("Visual sequence needs one timing declaration")
        timings = ([sequence["duration_ms"]] if "duration_ms" in sequence else sequence["durations_ms"])
        if not isinstance(timings, list) or ("durations_ms" in sequence and len(timings) != len(frames)):
            raise ValueError("Invalid visual sequence timings")
        for duration in timings:
            _integer(duration, 20, 60000, "frame duration")
    if "glyph_atlases" in manifest:
        _glyph_atlases(manifest["glyph_atlases"],dimensions)
    return {"manifest_sha256": hashlib.sha256(raw).hexdigest(), "asset_count": len(declared),
            "manifest_bytes": len(raw), "glyph_atlas_count": len(manifest.get("glyph_atlases",{})),
            "png_count": len(png_paths), "font_count": len(font_paths),
            "asset_bytes": total_bytes, "decoded_rgba_budget_bytes": rgba_bytes,
            "sequence_count": len(sequences),
            "artwork_rights": "Third-party artwork retains its source rights; not granted by project GPL"}
