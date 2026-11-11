# 10-Play Multiplier Poker for SeedSigner Play

An independent offline, play-credit implementation of classic 10-hand 9/6 Double Double Bonus with next-hand multipliers. It boots into poker and opens SeedSigner after the existing outer-action-button hold/release gesture. Version 0.4.0 uses the reference website's actual card and interface graphics with independently written gameplay code. This is not official IGT, Action Gaming, VideoPoker.com, BitKit or SeedSigner software.

## Hardware and operation

- Raspberry Pi Zero 1.3, Plus-compatible ST7789 320 × 240 HAT and standard SeedSigner button wiring, including the matching SeedSigner Play configuration.
- D-pad left/right: select a card.
- Both middle buttons (D-pad center and right middle): hold/unhold the selected card; after results, start the next deal. In menus, confirm the selection.
- D-pad DOWN: Deal / Draw. During animation, skip presentation without placing another bet.
- D-pad UP: request best-hold advice. Recommended cards flash red. Double-tap UP within 350 ms to toggle autoplay.
- Any other manual button stops autoplay before handling its normal action. UP/DOWN navigate normally inside menus.
- KEY1 (top right): inspect completed hands; in the enlarged view, UP/DOWN select a result.
- KEY3 (bottom right): focus the gold controls or return from a menu.
- Hold KEY1 + KEY3 continuously for two seconds, then release every button to open SeedSigner. Autoplay pauses as soon as the entry gesture begins. Reboot returns to poker.

Standard button wiring is used in both poker and the upstream signer. Hold/Deal roles are selected by game phase, not by swapping GPIO pins.

The game samples physical buttons independently of screen drawing and SPI writes. Quick taps are queued once in order instead of being lost during a redraw. Each button is debounced separately; holding Deal still triggers only one action. The two outer buttons act on release so their reserved entry chord does not change a card hold or open a menu. Badge-only animation reuses the static board while preserving the rendered pixels.

The poker menus and help do not identify SeedSigner or display its entry gesture. Keep these instructions separately if the game is being used as a decoy interface.

The default is ten hands at ten credits each: five base credits plus five feature credits, for a 100-credit deal. The selected paytable is exactly 9/6 Double Double Bonus, with the classic **ten-play** next-hand multiplier schedule. A full house earns 12X, a flush 10X, a straight 8X, and the other categories follow the displayed paytable. One through five credits per hand play the ordinary base game without earning new multipliers. Royals pay 250/500/750/1,000/4,000 at one/two/three/four/five base credits.

All active hands share the initial five cards and hold decisions. Each line draws independently from its own remaining 47-card deck, excluding **all five** initially dealt cards. Current multipliers multiply the current line's payout; newly earned multipliers apply only to the next deal. Previously earned multipliers can be collected at lower coin bets. The entire pending board is consumed at the next deal, so reducing active hands forfeits multipliers on inactive lines. A dealt royal flush is automatically held and settled. Production uses a private OS-backed `SystemRandom`, with no result steering or adaptive payout logic.

On Linux, the production sampler checks OS random readiness without blocking. If randomness is still initializing, the game shows “Shuffling is getting ready” and keeps the cards, holds, credits and multipliers unchanged. The D-pad DOWN button retries the intended action; the controls and entry gesture stay responsive. There is no weaker or deterministic RNG fallback. See Python's [`GRND_NONBLOCK` documentation](https://docs.python.org/3.12/library/os.html#os.GRND_NONBLOCK).

The gold controls follow the observed classic reference. At one credit per hand, Select Hands cycles 1–10. Bet Per Hand fills inactive hands first, then advances 1/2/3/4/5/10 credits across all ten hands; its first press after a completed round resets the board to ten one-credit hands. Bet Max selects ten hands at ten credits and starts the deal when sufficient credits are available. Free-credit refills preserve cards and multipliers. Credits and multipliers exist in RAM and reset on reboot; there is no real-money wagering or cash-out.

The renderer composes the reference 640 × 480 logical canvas and reduces it to the Play's 320 × 240 screen. Actual source images supply all 52 card faces, normal/disabled backs, game/paytable backgrounds, gold controls, HELD indicators, win banners, multiplier graphics and animated ACTIVE/activation tags. Arial glyphs are rasterized once into PNG atlases, so the target does not need additional font software. The source colors, layout coordinates and unequal paytable-column widths replace the earlier approximations. Bold, crisp focus borders and solid pointers identify the selected card or bottom control at the native LCD resolution. These navigation overlays deliberately prioritize visibility on the physical D-pad device.

This build contains the selected Ten Play 9/6 DDB configuration; More Games identifies that configuration and offers free credits. It does not include other poker variants, website accounts, contests, trainers or the vendor's server RNG. Artwork identity and measured layout matching do not imply vendor certification or identical pixels across different display resolutions and LCD color depths.

## Flashing

Save the IMG and its SHA-256 file from `outputs/`. Verify the checksum, then use Raspberry Pi Imager → Use custom to write the IMG to the intended microSD card. Writing erases that card. Let Imager's verification finish, insert the card and power the device.

Qualification requires a physical cold boot, all buttons, card holds, Deal/Draw, display orientation, SeedSigner entry, camera scanning and a signing round trip using a disposable test seed. Automated and emulated tests cannot establish physical hardware behavior. The game and signer share one operating system; the entry gesture is not authentication or security isolation. Never enter a seed into a website.

## Reproduction

The base is the official `seedsigner_os.0.8.7.pi0.img`, SHA-256 `67f005c7ace26500a78be3f4d97eaf02d76d018550ec54df011741dde1933ce9`, 52,428,800 bytes, downloaded from the [official 0.8.7 release](https://github.com/SeedSigner/seedsigner/releases/tag/0.8.7). The signed checksum was verified against the previously pinned public fingerprint `46739B74B56AD88F14B0882EC7EF709007260119`; see `validation/base-verification.json`.

Host prerequisites: Python 3.10 or later, Pillow, pytest, and mtools (`mcopy`). A C++17 compiler is needed only to regenerate strategy data. The target uses Python and Pillow already present in the official image. The build only edits regular files; it does not mount images or write raw devices. The image builder verifies the base hash, adds a deterministic external initramfs, and independently reads the finished FAT16 filesystem and CPIO archive back. The official kernel, firmware and SeedSigner application are retained. Only the boot configuration, Plus display settings and external launcher are added.

Build and check from this directory:

```sh
python3 scripts/verify_base_release.py --downloads inputs
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/validate_math.py
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/validate_game_contract.py
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/build_poker_image.py build \
  --base inputs/seedsigner_os.0.8.7.pi0.img --payload payload \
  --output outputs/seedsigner-v0.8.7-poker-v0.4.0-play-plus-pi0.img
```

The builder refuses to overwrite existing outputs; use a fresh output name for a rebuild. Put the official base IMG, signed checksum, signature and provided public key in `inputs/` when reproducing from the source archive. The test suite's base-file tests run when the pinned base and `mcopy` are available. Development previews can be rendered with `scripts/render_previews.py --font-dir /path/to/stock/fonts`.

The source archive includes the poker implementation, hardware integration, tests, image builder, declared runtime PNG assets and their provenance manifest. It excludes flashable disk images, private ROMs, credentials, proprietary gameplay JavaScript and raw font outlines. Existing PNGs are sufficient for an ordinary image rebuild; regenerating the Arial atlases uses the specified installed fonts. The builder verifies every declared asset's hash, format, dimensions and bounded decoded size.

## Hints and autoplay

Advice evaluates all 32 possible holds using exhaustive integer category counts from the actual remaining 47-card deck. For ten-hand feature play it includes the current multiplier total and the nonlinear value of the ten next-hand multipliers. The continuation values are solved offline over all 134,459 suit-equivalent initial hands and 107 reachable multiplier totals, with an independent stationary-policy check. This is numerical expected-value optimization; ties within 1e-9 credits use more held cards, then the lower mask. It never predicts the actual next draw or reads the random generator.

One through five credits use exact ordinary draw-poker payout EV, including the lower royal payout below five base credits and any existing multipliers. Feature advice is qualified for the selected ten-hand, ten-credit game. Autoplay stops on insufficient credits, entropy wait, unavailable advice or manual input. Credits are never replenished automatically.

The advisor is loaded on first use, runs on a cancellable background worker and shuts down before SeedSigner opens. It does not add strategy loading to normal startup. The 4.45 MB strategy table is generated by the included original C++ source; it contains counts, not game code or ROMs. Rebuild it with a C++17 compiler:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/build_strategy_tables.py --threads 4 --tolerance 1e-10
```

Copy the generated `subset_counts.dat` and `strategy.json` from `validation/strategy-research/generated` into `payload/opt/dino/strategy` before rebuilding the image. Native host compiler output and intermediate caches are not payload files. The packaged data is sufficient for a normal image rebuild.

## Validation for 0.4.0

The source-bound host, input, image readback, target-runtime and strategy reports are in `validation/`. They cover both middle controls, DOWN Deal/Draw, hints, autoplay, cancellation and cleanup, all 32 hold masks, the exact replacement deck, and the unchanged poker evaluator and payouts. Strategy counts are checked against independent enumeration; full-game policy evaluation agrees with the Bellman solution. Numerical certificates use floating-point arithmetic rather than formal interval proofs.

Automated tests use simulated GPIO/LCD and an emulated ARMv6 kernel/rootfs. The delivered firmware and SeedSigner application remain stock. These tests do not establish physical Pi speed, a physical cold boot, camera scanning or actual signing. No SD card is flashed by the build scripts.

## Sources and licenses

Original/adapted project code is GPL-2.0-or-later; see `LICENSE` and `NOTICE`. Stock components retain their own licenses. Website artwork and font-derived PNGs retain their owners' rights and are not relicensed under the code's GPL. See `payload/opt/dino/THIRD-PARTY-ASSETS.txt` and `payload/opt/dino/assets/videopoker/manifest.json` for sources, hashes, transformations and font provenance. Public releases are available at https://github.com/xberenguer/videopoker/releases .

- [Official game description](https://www.videopoker.com/play/?game=69&title=Ultimate+X+Poker)
- The actual classic Ten Play Double Double Bonus pay screen, four help screens and initial board were inspected in Brave. All five payout columns and the ten-play multiplier matrix were transcribed and compared. Read-only static inspection of the public client clarified the selectors, Bet Max behavior, royal auto-settlement, native geometry and insufficient-credit branches. Development reference screenshots and vendor JavaScript are excluded from the deliverables; the declared public visual assets are included deliberately with separate notices.
- [IGT / Loto-Québec rules](https://assets.lotoquebec.com/ressources/assets/v3/assets/blt8296e79a7001648c/blt356b997b1c75bb8a/65a6ca31cdbb964331c4f545/ultimate-x-five-play-poker_rules_en.pdf): independent replacement decks and dealt royal behavior. Its separate Bonus control and per-bet bank belong to a different online variant and are not imported into this classic configuration.
- [Classic multi-line payout and multiplier reference](https://wizardofodds.com/games/video-poker/tables/ultimate-x/): independently corroborates the selected 10-play 9/6 DDB schedule and collecting existing multipliers without the feature wager.
- [Original observation of lower-coin and inactive-line behavior](https://wizardofvegas.com/articles/ultimate-expected-value/): corroborates collecting multipliers below five credits and forfeiting inactive-line multipliers in classic Ultimate X. The reference site's bank settlement is server-side, so this policy is supported by classic game documentation and observation rather than direct inspection of its private server implementation.
- [SeedSigner application source](https://github.com/SeedSigner/seedsigner/tree/0.8.7) and [OS source](https://github.com/SeedSigner/seedsigner-os).
- [Complete stock OS corresponding-source archive](https://github.com/xberenguer/seedsigner-dino/releases/download/v0.1.1-beta/seedsigner-v0.8.7-os-corresponding-source.tar.gz), SHA-256 `20751b5076b6b309928bd650f9846d2481f16a5f5d85943071b285abc246f6c6` (808,807,486 bytes). This is separate from the small poker source archive and covers retained stock OS components.

No theoretical return percentage, casino certification, independent wallet audit or physical-device validation is claimed by software checks alone.
