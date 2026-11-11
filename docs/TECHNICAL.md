# 10-Play Multiplier Poker for SeedSigner Play

An independent offline, play-credit implementation of classic 10-hand 9/6 Double Double Bonus with next-hand multipliers. It boots into poker and opens SeedSigner after the existing outer-action-button hold/release gesture. Version 0.3.2 uses the reference website's actual card and interface graphics with independently written gameplay code. This is not official IGT, Action Gaming, VideoPoker.com, BitKit or SeedSigner software.

## Hardware and operation

- Raspberry Pi Zero 1.3, Plus-compatible ST7789 320 × 240 HAT and standard SeedSigner button wiring, including the matching SeedSigner Play configuration.
- D-pad left/right: select a card. Right middle action button or KEY1: hold/unhold it.
- D-pad center (left middle button): Deal / Draw.
- Up/down: select a result hand; right middle opens a larger view.
- KEY3 (bottom action button): focus the seven gold controls. Left/right selects a control; right middle activates it. KEY3 returns to the cards.
- The D-pad center button skips a running card/win animation without placing another bet. Speed cycles between three presentation rates.
- Hold KEY1 + KEY3, the two outer action buttons, continuously for two seconds; then release every button to enter SeedSigner. Reboot returns to poker.

Version 0.3.2 swaps the two physical center controls for poker: D-pad center deals/draws; the right middle button holds/confirms. Upstream SeedSigner retains its original controls. Input action names in developer tests are logical roles, not a second physical pin layout.

The game samples physical buttons independently of screen drawing and SPI writes. Quick taps are queued once in order instead of being lost during a redraw. Each button is debounced separately; holding Deal still triggers only one action. The two outer buttons act on release so their reserved entry chord does not change a card hold or open a menu. Badge-only animation reuses the static board while preserving the rendered pixels.

The poker menus and help do not identify SeedSigner or display its entry gesture. Keep these instructions separately if the game is being used as a decoy interface.

The default is ten hands at ten credits each: five base credits plus five feature credits, for a 100-credit deal. The selected paytable is exactly 9/6 Double Double Bonus, with the classic **ten-play** next-hand multiplier schedule. A full house earns 12X, a flush 10X, a straight 8X, and the other categories follow the displayed paytable. One through five credits per hand play the ordinary base game without earning new multipliers. Royals pay 250/500/750/1,000/4,000 at one/two/three/four/five base credits.

All active hands share the initial five cards and hold decisions. Each line draws independently from its own remaining 47-card deck, excluding **all five** initially dealt cards. Current multipliers multiply the current line's payout; newly earned multipliers apply only to the next deal. Previously earned multipliers can be collected at lower coin bets. The entire pending board is consumed at the next deal, so reducing active hands forfeits multipliers on inactive lines. A dealt royal flush is automatically held and settled. Production uses a private OS-backed `SystemRandom`, with no result steering or adaptive payout logic.

On Linux, the production sampler checks OS random readiness without blocking. If randomness is still initializing, the game shows “Shuffling is getting ready” and keeps the cards, holds, credits and multipliers unchanged. The D-pad center button retries the intended action; the controls and entry gesture stay responsive. There is no weaker or deterministic RNG fallback. See Python's [`GRND_NONBLOCK` documentation](https://docs.python.org/3.12/library/os.html#os.GRND_NONBLOCK).

The gold controls follow the observed classic reference. At one credit per hand, Select Hands cycles 1–10. Bet Per Hand fills inactive hands first, then advances 1/2/3/4/5/10 credits across all ten hands; its first press after a completed round resets the board to ten one-credit hands. Bet Max selects ten hands at ten credits and starts the deal when sufficient credits are available. Free-credit refills preserve cards and multipliers. Credits and multipliers exist in RAM and reset on reboot; there is no real-money wagering or cash-out.

The renderer composes the reference 640 × 480 logical canvas and reduces it to the Play's 320 × 240 screen. Actual source images supply all 52 card faces, normal/disabled backs, game/paytable backgrounds, gold controls, HELD indicators, win banners, multiplier graphics and animated ACTIVE/activation tags. Arial glyphs are rasterized once into PNG atlases, so the target does not need additional font software. The source colors, layout coordinates and unequal paytable-column widths replace the earlier approximations. Bold, crisp focus borders and solid pointers identify the selected card or bottom control at the native LCD resolution. These navigation overlays deliberately prioritize visibility on the physical D-pad device.

This build contains the selected Ten Play 9/6 DDB configuration; More Games identifies that configuration and offers free credits. It does not include other poker variants, website accounts, contests, trainers or the vendor's server RNG. Artwork identity and measured layout matching do not imply vendor certification or identical pixels across different display resolutions and LCD color depths.

## Flashing

Save the IMG and its SHA-256 file from the GitHub release. Verify the checksum, then use Raspberry Pi Imager → Use custom to write the IMG to the intended microSD card. Writing erases that card. Let Imager's verification finish, insert the card and power the device.

Qualification requires a physical cold boot, all buttons, card holds, Deal/Draw, display orientation, SeedSigner entry, camera scanning and a signing round trip using a disposable test seed. Automated and emulated tests cannot establish physical hardware behavior. The game and signer share one operating system; the entry gesture is not authentication or security isolation. Never enter a seed into a website.

## Reproduction

The base is the official `seedsigner_os.0.8.7.pi0.img`, SHA-256 `67f005c7ace26500a78be3f4d97eaf02d76d018550ec54df011741dde1933ce9`, 52,428,800 bytes, downloaded from the [official 0.8.7 release](https://github.com/SeedSigner/seedsigner/releases/tag/0.8.7). The signed checksum was verified against the previously pinned public fingerprint `46739B74B56AD88F14B0882EC7EF709007260119`; see `validation/base-verification.json`.

Host prerequisites: Python 3.10 or later, Pillow, pytest, mtools (`mcopy`) and GnuPG (`gpg`). The target uses Python and Pillow already present in the official image. The build only edits regular files; it does not mount images or write raw devices. The image builder verifies the base hash, adds a deterministic external initramfs, and independently reads the finished FAT16 filesystem and CPIO archive back. The official kernel, firmware and SeedSigner application are retained. Only the boot configuration, Plus display settings and external launcher are added.

Build and check from this directory:

Run these commands from the repository root.

```sh
mkdir -p outputs
python3 scripts/verify_base_release.py --downloads inputs
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/validate_math.py
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/validate_game_contract.py
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/build_poker_image.py build \
  --base inputs/seedsigner_os.0.8.7.pi0.img --payload payload \
  --output outputs/seedsigner-v0.8.7-poker-v0.3.2-play-plus-pi0.img
```

The builder refuses to overwrite existing outputs; use a fresh output name for a rebuild. Put the official base IMG, signed checksum, signature and provided public key in `inputs/` when reproducing from the source archive. The test suite's base-file tests run when the pinned base and `mcopy` are available. Development previews can be rendered with `scripts/render_previews.py --font-dir /path/to/stock/fonts`.

The source archive includes the poker implementation, hardware integration, tests, image builder, declared runtime PNG assets and their provenance manifest. It excludes flashable disk images, private ROMs, credentials, proprietary gameplay JavaScript and raw font outlines. Existing PNGs are sufficient for an ordinary image rebuild; regenerating the Arial atlases uses the specified installed fonts. The builder verifies every declared asset's hash, format, dimensions and bounded decoded size.

## Validation for 0.3.2

- All 132 host tests passed, covering visual asset identity, all 52 card mappings, bounded asset decoding, artwork/frame timing, exact palette values, real UI/engine through simulated GPIO input, animation skipping, betting controls, entropy-wait retries, held-button behavior, hidden-entry non-disclosure and close-before-signer ordering. All 155 runtime file hashes are bound to `validation/tests.json` and `validation/release-validation.json`.
- Eight real-clock input tests exercise the production sampler with simulated GPIO: 35–50 ms requested taps entirely inside 150–250 ms blocked rendering/display calls register once and in order; held Deal does not repeat. Faults, queue overflow, stale input and stop-before-cleanup behavior are also checked. See `validation/input-latency.json`.
- Cached and uncached renderer frames match byte-for-byte across 92 state/badge/focus comparisons. Focus-only moves avoid card recomposition; badge-only updates filter 5.5% of the logical canvas. Sixteen of 18 deterministic PNGs are unchanged from 0.3.1; the two changed notice screens now identify the D-pad center for retrying or adding credits. The larger card/control focus overlays remain.
- All 2,598,960 five-card combinations matched an independent evaluator and the expected category counts.
- All 144 public image sources match the runtime PNGs pixel-for-pixel after lossless decoding. The two Arial atlases, 190 sampled glyphs and complete rendered text runs were checked independently. The engine and input sampler are unchanged from 0.3.1. The poker GPIO mapping swaps only physical pins 33 and 38; the outer-button hold/release gesture and upstream signer mapping remain unchanged.
- A separately transcribed payout oracle checks 1,470 scenarios and 10,290 individual settlements across every category, coin bet, available multiplier and active hand count. All 32 hold masks are checked against the exact initial 52-card and replacement 47-card sampling boundaries. See `validation/game-contract.json`.
- Two image builds were byte-identical. Independent FAT16/CPIO readback preserved 334 stock files unchanged, with the expected boot-configuration change and added settings/overlay only.
- The delivered payload renders 320 × 240 screens under the stock ARMv6 kernel, Python 3.12.10 and Pillow 10.3.0 in QEMU. The exact round count and entropy-readiness result are recorded in `validation/arm-runtime.json`. GPIO/LCD and the final signer callback are simulated. The diagnostic device tree disables unsupported emulated peripherals and enables the emulated SD controller; the delivered image's device tree is unchanged. Emulated timings are not measurements of physical Pi speed. This check does not exercise the GPU bootloader, physical HAT, camera or actual signing.
- The owner-supplied photo shows the game running on SeedSigner Play. It does not identify an exact image hash or establish complete camera/signing qualification. See `validation/release-validation.json` for software scope.

## Sources and licenses

Original/adapted project code is GPL-2.0-or-later; see `LICENSE` and `NOTICE`. Stock components retain their own licenses. Website artwork and font-derived PNGs retain their owners' rights and are not relicensed under the code's GPL. See `payload/opt/dino/THIRD-PARTY-ASSETS.txt` and `payload/opt/dino/assets/videopoker/manifest.json` for sources, hashes, transformations and font provenance. The archived validation describes how the release was prepared; public status is separate from those reports.

- [Official game description](https://www.videopoker.com/play/?game=69&title=Ultimate+X+Poker)
- The actual classic Ten Play Double Double Bonus pay screen, four help screens and initial board were inspected in Brave. All five payout columns and the ten-play multiplier matrix were transcribed and compared. Read-only static inspection of the public client clarified the selectors, Bet Max behavior, royal auto-settlement, native geometry and insufficient-credit branches. Development reference screenshots and vendor JavaScript are excluded from the deliverables; the declared public visual assets are included deliberately with separate notices.
- [IGT / Loto-Québec rules](https://assets.lotoquebec.com/ressources/assets/v3/assets/blt8296e79a7001648c/blt356b997b1c75bb8a/65a6ca31cdbb964331c4f545/ultimate-x-five-play-poker_rules_en.pdf): independent replacement decks and dealt royal behavior. Its separate Bonus control and per-bet bank belong to a different online variant and are not imported into this classic configuration.
- [Classic multi-line payout and multiplier reference](https://wizardofodds.com/games/video-poker/tables/ultimate-x/): independently corroborates the selected 10-play 9/6 DDB schedule and collecting existing multipliers without the feature wager.
- [Original observation of lower-coin and inactive-line behavior](https://wizardofvegas.com/articles/ultimate-expected-value/): corroborates collecting multipliers below five credits and forfeiting inactive-line multipliers in classic Ultimate X. The reference site's bank settlement is server-side, so this policy is supported by classic game documentation and observation rather than direct inspection of its private server implementation.
- [SeedSigner application source](https://github.com/SeedSigner/seedsigner/tree/0.8.7) and [OS source](https://github.com/SeedSigner/seedsigner-os).
- [Complete stock OS corresponding-source archive](https://github.com/xberenguer/seedsigner-dino/releases/download/v0.1.1-beta/seedsigner-v0.8.7-os-corresponding-source.tar.gz), SHA-256 `20751b5076b6b309928bd650f9846d2481f16a5f5d85943071b285abc246f6c6` (808,807,486 bytes). This is separate from the small poker source archive and covers retained stock OS components.

No theoretical return percentage, casino certification, independent wallet audit or physical-device validation is claimed by software checks alone.
