#!/usr/bin/env python3
"""Verify the unmodified official pi0 release using an isolated GnuPG keyring."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

EXPECTED_FINGERPRINT = "46739B74B56AD88F14B0882EC7EF709007260119"
EXPECTED_IMAGE = "seedsigner_os.0.8.7.pi0.img"
EXPECTED_SHA256 = "67f005c7ace26500a78be3f4d97eaf02d76d018550ec54df011741dde1933ce9"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downloads", type=Path, required=True)
    parser.add_argument("--key", type=Path, default=Path(__file__).resolve().parents[1] / "inputs/seedsigner-pgp.asc")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not shutil.which("gpg"):
        parser.error("GnuPG gpg is required in the build environment")
    checksum = args.downloads / "seedsigner.0.8.7.sha256.txt"
    signature = checksum.with_suffix(checksum.suffix + ".sig")
    image = args.downloads / EXPECTED_IMAGE
    for path in (checksum, signature, image, args.key):
        if not path.is_file():
            parser.error(f"Missing file: {path}")
    with tempfile.TemporaryDirectory(prefix="seedsigner-gpg-") as home:
        Path(home).chmod(0o700)
        base = ["gpg", "--no-options", "--homedir", home, "--batch"]
        subprocess.run(base + ["--import", str(args.key.resolve())], check=True, capture_output=True)
        listing = subprocess.run(base + ["--with-colons", "--fingerprint", "--list-keys"],
                                 check=True, capture_output=True, text=True).stdout
        fingerprints = [line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")]
        if EXPECTED_FINGERPRINT not in fingerprints:
            raise SystemExit("Imported key does not match the official pinned fingerprint")
        result = subprocess.run(base + ["--status-fd", "1", "--verify", str(signature.resolve()), str(checksum.resolve())],
                                capture_output=True, text=True)
        statuses = result.stdout.splitlines()
        invalid = ("BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG")
        if result.returncode or any(any(f"[GNUPG:] {item} " in line for item in invalid) for line in statuses):
            raise SystemExit(f"GPG signature verification failed:\n{result.stderr}")
        valid = [line.split() for line in statuses if line.startswith("[GNUPG:] VALIDSIG ")]
        if not any(EXPECTED_FINGERPRINT in line[2:] for line in valid):
            raise SystemExit("Signature is not valid under the pinned SeedSigner primary key")
        records = {}
        for line in checksum.read_text().splitlines():
            digest, name = line.split(maxsplit=1)
            records[name.lstrip("*")] = digest.lower()
        if records.get(EXPECTED_IMAGE) != EXPECTED_SHA256:
            raise SystemExit("Signed checksum differs from the pinned release metadata")
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        if digest != records[EXPECTED_IMAGE]:
            raise SystemExit("Official image checksum does not match its signed checksum file")
        report = {
            "release": "0.8.7", "image": EXPECTED_IMAGE,
            "sha256": digest, "checksum_matches": True,
            "detached_signature_valid": True,
            "expected_primary_fingerprint": EXPECTED_FINGERPRINT,
            "gpg_validsig_status": [" ".join(line) for line in valid],
            "key_url": "https://keybase.io/seedsigner/pgp_keys.asc",
            "fingerprint_source": "https://keybase.io/_/api/1.0/user/lookup.json?usernames=seedsigner",
        }
        output = json.dumps(report, indent=2) + "\n"
        if args.report:
            args.report.write_text(output)
        print(output, end="")


if __name__ == "__main__":
    main()
