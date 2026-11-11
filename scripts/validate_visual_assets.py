#!/usr/bin/env python3
"""Independently compare runtime art against the retained original source bytes.

This audit reads local files only. It deliberately does not import the asset
preparer, runtime loader or renderer. Pixel identity is not a rights clearance
and is not evidence that an entire rendered screen matches the reference game.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ROLES = {
    "background": 3, "active-badge-frame": 13, "inactive-badge-frame": 7,
    "card-front": 52, "card-back": 2, "glyph-atlas-bold": 1,
    "glyph-atlas-regular": 1, "gui": 23, "help-control": 7,
    "help-screen": 6, "multiplier": 14, "multiplier-label": 1,
    "win-indicator": 16,
}
FONT_SOURCES = {
    "regular": Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    "bold": Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
}
FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".woff", ".woff2"}
FONT_MAGIC = {b"\x00\x01\x00\x00", b"OTTO", b"ttcf", b"wOFF", b"wOF2"}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_file(root, relative):
    """Require a regular file reached without symlinks or path traversal."""
    require(isinstance(relative, str) and relative, "empty/non-string asset path")
    require("\\" not in relative and "\x00" not in relative, "unsafe path characters")
    path = PurePosixPath(relative)
    require(not path.is_absolute() and all(p not in (".", "..") for p in path.parts),
            "unsafe relative path: " + relative)
    candidate = root
    for component in path.parts:
        candidate = candidate / component
        require(not candidate.is_symlink(), "symlink in audited path: " + relative)
    require(candidate.is_file(), "missing regular file: " + relative)
    require(candidate.resolve().is_relative_to(root.resolve()), "path escaped audit root")
    return candidate


def decode_rgba(data, expected_format=None):
    with Image.open(io.BytesIO(data)) as original:
        if expected_format is not None:
            require(original.format == expected_format.upper(), "decoded format mismatch")
        frames = getattr(original, "n_frames", 1)
        original.seek(0)
        rgba = original.convert("RGBA")
        rgba.load()
        return rgba, frames


def audit_font(style, row, manifest, image):
    """Check source-font provenance and a selection of actual glyph pixels."""
    expected_source = FONT_SOURCES[style]
    url = urlparse(row["source_url"])
    require(url.scheme == "file" and not url.netloc,
            "installed font source must be a local file URI")
    require(Path(unquote(url.path)) == expected_source, "unexpected font source")
    require(sha256(expected_source.read_bytes()) == row["source_sha256"],
            "installed source font SHA mismatch")
    atlas = manifest["glyph_atlases"][style]
    require(atlas["path"] == row["path"], "font atlas points to different image")
    checked = 0
    for size in (7, 11, 15, 19, 13.076923):
        font = ImageFont.truetype(str(expected_source), size)
        glyphs = atlas["sizes"][str(size)]["glyphs"]
        for char in "0123456789AJQKX./- ":
            actual = glyphs[char]
            bounds = font.getbbox(char, anchor="ls")
            width, height = max(1, bounds[2] - bounds[0]), max(1, bounds[3] - bounds[1])
            require((actual["width"], actual["height"]) == (width, height),
                    "font glyph dimensions mismatch")
            require((actual["bearing_x"], actual["bearing_y"]) == bounds[:2],
                    "font glyph bearings mismatch")
            require(actual["advance"] == float(font.getlength(char)),
                    "font glyph advance mismatch")
            x, y = actual["x"], actual["y"]
            require(0 <= x and 0 <= y and x + width <= image.width and
                    y + height <= image.height, "font glyph exceeds atlas")
            expected = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            ImageDraw.Draw(expected).text((-bounds[0], -bounds[1]), char, font=font,
                                         fill=(255, 255, 255, 255), anchor="ls")
            require(expected.tobytes() == image.crop((x, y, x + width, y + height)).tobytes(),
                    "font glyph pixels differ from installed Arial")
            checked += 1
    return {"style": style, "source_sha256": row["source_sha256"],
            "atlas_sha256": row["sha256"], "selected_glyphs_checked": checked}


def audit_assets(project=ROOT):
    project = Path(project)
    runtime = project / "payload/opt/dino/assets/videopoker"
    originals = project / "validation/reference/assets-original"
    manifest_path = safe_file(runtime, "manifest.json")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    rows = manifest["assets"]
    failures = []
    fingerprints = []
    fonts = []
    lost_animation = []
    public_count = 0
    verified_pixels = 0
    verified_runtime = 0
    role_counts = dict(sorted(Counter(row.get("role") for row in rows).items()))

    def check(condition, message):
        if not condition:
            failures.append(message)

    check(manifest.get("schema") == 1, "manifest schema must be 1")
    check(len(rows) == 146, "asset count must be 146")
    check(role_counts == EXPECTED_ROLES, "asset role counts differ from the exact reference set")
    paths = [row["path"] for row in rows]
    check(len(set(paths)) == len(paths), "duplicate runtime asset paths")
    for row in rows:
        path = row["path"]
        try:
            data = safe_file(runtime, path).read_bytes()
            require(len(data) == row["bytes"], "runtime byte count mismatch")
            require(sha256(data) == row["sha256"], "runtime SHA mismatch")
            image, runtime_frames = decode_rgba(data, "PNG")
            require(runtime_frames == 1, "runtime PNG must be a single frame")
            require(image.size == (row["width"], row["height"]), "runtime dimensions mismatch")
            require(row.get("mode") == "RGBA", "manifest mode must be RGBA")
            verified_runtime += 1
            if row.get("source_kind") == "installed_font":
                style = row["role"].removeprefix("glyph-atlas-")
                require(style in FONT_SOURCES, "unexpected installed font style")
                require(path == "fonts/arial-" + style + ".png", "unexpected font atlas path")
                fonts.append(audit_font(style, row, manifest, image))
                continue
            public_count += 1
            parsed = urlparse(row["source_url"])
            require(parsed.scheme == "https" and parsed.hostname == "media.vidpok.com",
                    "unexpected public image origin")
            source_path = safe_file(originals, unquote(parsed.path).lstrip("/"))
            source = source_path.read_bytes()
            require(sha256(source) == row["source_sha256"], "original source SHA mismatch")
            source_image, source_frames = decode_rgba(source, row["source_format"])
            require(row["source_frame_count"] == source_frames, "source frame count mismatch")
            if source_frames != 1:
                lost_animation.append({"path": path, "original_frames": source_frames,
                                       "runtime_frames": runtime_frames})
                raise ValueError("unsupported animation loss: original is not a single-frame image")
            require(source_image.size == image.size, "decoded source/runtime dimensions differ")
            pixels = source_image.tobytes()
            require(pixels == image.tobytes(), "decoded source/runtime RGBA pixels differ")
            verified_pixels += 1
            fingerprints.append({"path": path, "source_sha256": sha256(source),
                                 "runtime_sha256": sha256(data), "rgba_sha256": sha256(pixels),
                                 "size": list(image.size)})
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(path + ": " + str(error))

    check(public_count == 144, "expected 144 public source image entries")
    check(verified_pixels == 144, "not all 144 public image pixel identities were verified")
    check(len(fonts) == 2, "both installed font provenance checks must pass")
    check({r["path"] for r in rows if r["role"] == "card-front"} ==
          {"cards/" + str(n) + ".png" for n in range(52)}, "52 named card faces must be present")
    check({r["path"] for r in rows if r["role"] == "card-back"} ==
          {"cards/Back.png", "cards/Back_Disabled.png"}, "both actual card backs must be present")
    by_path = {row["path"]: row for row in rows}
    sequence_frames = 0
    for name, prefix, count, duration in (("active", "active", 13, 200),
                                           ("inactive", "inactive", 7, 300)):
        expected = ["badges/" + prefix + str(n) + ".png" for n in range(count)]
        sequence = manifest.get("sequences", {}).get(name, {})
        check(sequence.get("frames") == expected, name + " badge frame ordering mismatch")
        check(sequence.get("duration_ms") == duration, name + " badge frame duration mismatch")
        for path in expected:
            check(by_path.get(path, {}).get("role") == name + "-badge-frame",
                  "badge sequence references a missing or incorrectly classified actual source frame")
        sequence_frames += len(expected)

    raw_fonts = []
    payload = project / "payload"
    for path in payload.rglob("*"):
        if path.is_file():
            with path.open("rb") as handle:
                magic = handle.read(4)
            if path.suffix.lower() in FONT_SUFFIXES or magic in FONT_MAGIC:
                raw_fonts.append(path.relative_to(payload).as_posix())
    check(not raw_fonts, "raw font files are present in payload")
    runtime_inventory = {p.relative_to(runtime).as_posix() for p in runtime.rglob("*") if p.is_file()}
    check(runtime_inventory == set(paths) | {"manifest.json"}, "unmanifested or missing runtime files")
    proof = json.dumps(sorted(fingerprints, key=lambda item: item["path"]),
                       sort_keys=True, separators=(",", ":")).encode()
    return {
        "status": "FAIL" if failures else "PASS",
        "scope": "Local original-byte SHA and exact decoded frame-0 RGBA identity; not a license clearance or whole-screen match",
        "manifest_sha256": sha256(manifest_bytes), "asset_count": len(rows),
        "runtime_pngs_verified": verified_runtime, "public_source_images": public_count,
        "exact_rgba_pixel_identities": verified_pixels,
        "identity_set_sha256": sha256(proof), "roles": role_counts,
        "source_animation_policy": "Every cached source must have exactly one frame; badge animation uses individually preserved source files",
        "unsupported_lost_animation": lost_animation, "badge_sequence_frames": sequence_frames,
        "font_provenance": sorted(fonts, key=lambda item: item["style"]),
        "selected_font_glyphs_verified": sum(item["selected_glyphs_checked"] for item in fonts),
        "raw_fonts_in_payload": raw_fonts,
        "network_used": False, "failures": failures,
    }


def compare_reference_frame(rendered_path, reference_path):
    """Measure an actual 320x240 frame against a full uncropped 4:3 reference.

    This intentionally does not select cards, alter alignment, mask differences,
    crop browser controls or impose a success threshold. Callers must supply the
    matching ready/one-hand/one-coin reference state, already captured as game-only
    content. Different state or browser text rasterization remains in the error.
    """
    rendered_path, reference_path = Path(rendered_path), Path(reference_path)
    rendered_bytes, reference_bytes = rendered_path.read_bytes(), reference_path.read_bytes()
    rendered, _ = decode_rgba(rendered_bytes, "PNG")
    reference_format = "JPEG" if reference_bytes.startswith(b"\xff\xd8") else "PNG"
    reference, _ = decode_rgba(reference_bytes, reference_format)
    require(rendered.size == (320, 240), "renderer frame must be its native 320x240")
    require(reference.width * 3 == reference.height * 4, "reference must be an uncropped 4:3 game frame")
    expected = reference.convert("RGB").resize((320, 240), Image.Resampling.LANCZOS)
    actual = rendered.convert("RGB")
    difference = ImageChops.difference(actual, expected)
    means = ImageStat.Stat(difference).mean
    squared = sum(value * value * frequency for channel in difference.split()
                  for value, frequency in enumerate(channel.histogram()))
    mse = squared / (320 * 240 * 3)
    exact = sum(a == b for a, b in zip(actual.getdata(), expected.getdata()))
    return {
        "status": "MEASURED_WITHOUT_PASS_THRESHOLD",
        "candidate_sha256": sha256(rendered_bytes), "reference_sha256": sha256(reference_bytes),
        "reference_original_size": list(reference.size), "comparison_size": [320, 240],
        "reference_format": reference_format,
        "reference_is_lossy": reference_format == "JPEG",
        "method": "Full reference RGB resized once using Pillow LANCZOS; no crop, shift, masks or color adjustment",
        "mean_absolute_rgb_error": sum(means) / 3,
        "root_mean_squared_rgb_error": math.sqrt(mse),
        "psnr_db": None if mse == 0 else 10 * math.log10(255 * 255 / mse),
        "exact_rgb_pixel_fraction": exact / (320 * 240),
        "scope": "Only the supplied captured state; browser compression, labels, state and font rasterization count as differences",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare-render", type=Path)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    require(bool(args.compare_render) == bool(args.reference), "both comparison image paths are required")
    report = audit_assets(args.project)
    if args.compare_render:
        report["renderer_reference_comparison"] = compare_reference_frame(args.compare_render, args.reference)
    output = args.output or args.project / "validation/visual-artwork-identity.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "asset_count": report["asset_count"],
                      "exact_rgba_pixel_identities": report["exact_rgba_pixel_identities"],
                      "selected_font_glyphs_verified": report["selected_font_glyphs_verified"],
                      "failures": report["failures"], "report": str(output)}))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
