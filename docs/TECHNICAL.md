# Video Poker v0.5.1 technical notes

## Build and verification

Use Python 3.12 with Pillow and mtools for image assembly. The checked runtime PNGs, raster glyphs and certified strategy tables are included; a normal rebuild needs no network or raw font files. Obtain the pinned official `seedsigner_os.0.8.7.pi0.img` in `inputs/` and verify it against the supplied upstream checksum/signature material.

```sh
python -B scripts/validate_host.py --deterministic-only
python -B scripts/build_poker_image.py build \
  --base inputs/seedsigner_os.0.8.7.pi0.img --payload payload \
  --output outputs/seedsigner-v0.8.7-poker-v0.5.1-play-plus-pi0.img
```

Final reports are in `validation/`. Host checks bind every runtime file to its SHA-256. Independent image readback compares the packaged files and all 334 preserved upstream files. The stock ARMv6 kernel/rootfs probe boots the compressed overlay and exercises all twelve actual asynchronous advisors, menu selection, full boards, M holds and payouts.

Math checks independently transcribe every displayed paytable, test credit settlement and multiplier carryover, compare all 32 holds against an unpruned EV calculation for every game, and check wild-hand counts against an independent rank/suit oracle. The continuation policies also have Bellman and independent stationary-policy certificates. These are numerical checks, not formal interval proofs.

Actual software screenshots cover every game's menu selection, ready, hold, results and paytable screens. Artwork auditing checks the original pixels and explicitly records the menu graphics cropped from the visible reference screenshot. Browser rasterization and screenshot compression prevent a claim of universal pixel identity. No vendor gameplay JavaScript is shipped.

The functional ARM diagnostic uses virtual instruction and presentation clocks. Physical cold boot, button latency, Pi performance, camera scanning and signing still need device testing. Earlier failed diagnostics remain recorded separately. Do not treat an emulated pass as a physical hardware test.

## Sources and rights

Reference: [Ultimate X Poker](https://www.videopoker.com/play/?game=69&title=Ultimate%20X%20Poker). Original code: GPL-2.0-or-later. Stock components, reference graphics and rasterized Arial glyphs retain their own rights; see `NOTICE` and `payload/opt/dino/THIRD-PARTY-ASSETS.txt`. Public visibility does not itself grant a redistribution license.
