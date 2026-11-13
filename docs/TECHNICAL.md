# Video Poker v0.6.6 technical notes

The trainer extends the calculator source. Original dealing, settlement, evaluator and RNG remain inherited. Twelve original cabinet policies are joined by six alternate DDB policies, independently bound to their payout and multiplier vectors. Training is optional and statistics exclude assisted decisions from unassisted accuracy.

## Hidden mode and live layout

Boot always selects normal mode. Ordinary game frames retain the inherited PokerUI artwork; the startup cabinet has no Settings footer caption. Deal/draw wrappers bypass training settings, statistics, analysis and practice substitution in normal mode. The hardware gate now uses right TOP+BOTTOM and fires at the two-second threshold, before release. It toggles the live trainer sidebar; the next qualified hold returns to normal play. D-pad entry is removed. An input reset requires neutral release before rearming, preventing a held chord from repeating. Ordinary DOWN press edges and right TOP/BOTTOM release actions remain distinct. Entering or exiting pauses autoplay and cancels pending training analysis without changing the live hand.

The trainer uses a 256 x 199 game area and a 64 x 199 sidebar above the unchanged 320 x 41 machine footer. The original card sprites retain their source dimensions; only inter-hand spacing is reduced. Board composition is cached by visual game snapshot. Advice, EV and statistics tabs stay beside the live cards. Test mode hides answers until a submitted Draw; Coach reveals them immediately. Incorrect holds and pending analysis do not open modal pages. A queued Draw is cancelled if the player changes a hold or moves focus. Optional history, settings and full 32-hold analysis remain separate pages inside the hidden mode.

Host checks compare every normal-mode frame and resulting deal/draw snapshot against the inherited renderer/engine across all twelve games, including saved Coach and practice settings. ARM checks exercise the actual delivered hidden gate and render all three hand-count layouts.

## EV analysis

Animated Deal frames update only the newly visible main-card regions in the logical source board and the native frame, with an extra filter halo to preserve full-frame LANCZOS output exactly. Changes to cards, held flags, other game data or reveal direction invalidate that path. Both native layouts retain full rendering as an oracle. The unchanged trainer sidebar is cached by displayed values. The launcher reports completed frame presentation back to the controller; an animated Deal starts its reveal clock when its first frame has been sent, while standalone virtual UI tests retain their existing clock path. AM's immediate reveal and all configured intervals are unchanged. Renderer workload measurements are host observations; physical Pi timing still requires user testing.

The calculator reuses its existing best-hold report for inline total EV, expected current-board credits and the difference attributable to relative future multiplier value. This requires no additional solve. These figures are not a promise of net winnings; future value uses the same all-1x reference as the full trainer. Editing a card, multiplier, game or strategy mode invalidates both the hold and EV.

The detailed reporting path evaluates all 32 holds without pruning. Each hold has an exhaustive replacement-deck histogram, current-board return and relative continuation value. The latter uses each existing game-specific certified Bellman bias, normalized to an all-1x board. The report binds to the exact immutable cards, game, active multiplier sum, hand count, bet and feature flag. Grading accepts numerical ties within 1e-7 credits; the recommended-mask tie break retains the legacy 1e-9 convention.

A first submitted error remains an error if corrected or followed by assistance. Assistance seen before submission (Coach, held hint, auto-hold or autoplay) excludes that decision from unassisted accuracy. Normal draw randomness is not inspected by the solver. Warnings happen before replacement draws, so review does not spend additional credits or consume draw RNG. Failed draws do not update statistics.

## Optional persistent memory

TrainingStore.hardware discovers only a card matching the pinned MBR/header and bounded reserved region. It restores training/device data only when a versioned memory record explicitly enables persistence. An empty or legacy raw save remains OFF. OFF boot and normal OFF gameplay do not write history. ON restores sanitized per-preset training state and validated device preferences. Live cards, credits, RNG state, multipliers and autoplay remain volatile. The boot selection stays index 0, Triple Play Bonus Poker.

Autoplay still has separate counters and actual-hold grading. Late reports use a bounded asynchronous queue tied to the original snapshot and session ID. Failed or unavailable checks remain visibly unchecked. These statistics follow the memory setting; live automatic game state does not.

The image preserves stock partition geometry and a 528,384-byte reserved tail: a 4,096-byte header and two 262,144-byte save slots. Normal ON saves alternate checksummed generations and are coalesced at a two-second interval. Explicit enable/disable/clear waits for in-flight saves, discards superseded work and commits both copies with fsync and readback. A committed OFF record outranks an older ON save if the second update is interrupted. A second-copy failure is reported for retry. Save failure does not discard current RAM data. Clear removes training data while preserving device preferences and memory mode. No general filesystem mount is needed for saving.

## Device settings and paytable profiles

Brightness controls 1 kHz GPIO PWM on the driver's existing BOARD pin 18, with a 10% minimum. The hardware owner stops PWM before releasing GPIO. Host verification uses a fake GPIO/PWM sink; physical brightness behavior is not qualified by that test. Animation preference is separate from automatic pacing. The cabinet opens Settings on BOTTOM without a caption and returns from More Games on TOP when a return target exists.

Alternate profile IDs are separate from the twelve cabinet tile IDs. DDB three/ten-hand 9/5, 8/5 and 7/5 use their original hand-count multiplier schedules and independently generated continuation policies. Game selection, calculator, payouts and trainer snapshots resolve to the same profile ID. Pending boards and training records are keyed by that exact ID. Runtime refuses metadata that does not match the profile's deck, awards, multipliers, shared outcome histogram, reachable states and numerical certificate. No unsupported arbitrary-paytable editing is exposed.

The fifth calculator card triggers an asynchronous request. Complete-hand card/multiplier/mode changes cancel and replace pending analysis. Clearing a card cancels it without requesting an incomplete hand. The explicit Calculate action remains a retry path.

## Verification

Host tests cover all inherited cabinet/calculator behavior, independent dense-polynomial EV values for every hold across every game, difficulty-bank classification, warning/replay/assistance boundaries, journal integrity and recovery, stale-response protection and native rendering.

The stock ARM probe executes delivered Python and renders native PNGs in the upstream ARMv6 rootfs, using diagnostic RNG and a virtual presentation clock. It verifies default OFF behavior and ON/OFF/clear/reboot transitions using a disposable regular file in guest RAM. It never writes a physical SD card. GPIO/LCD are simulated: this is not physical Pi boot, latency, LCD, entropy, or power-loss qualification.

Build with Python 3.12, Pillow 10.3.0 and mtools. Supply the pinned upstream base as `inputs/base-os-v0.8.7-pi0.img`, SHA-256 `67f005c7ace26500a78be3f4d97eaf02d76d018550ec54df011741dde1933ce9`.

```sh
python -B scripts/validate_host.py
python -B scripts/build_poker_image.py build --base inputs/base-os-v0.8.7-pi0.img --payload payload --output outputs/videopoker-v0.6.6-pi0-320x240.img
python -B scripts/probe_arm_guest.py --image outputs/videopoker-v0.6.6-pi0-320x240.img --output validation/arm-training-v066 --training-only --instruction-clock --timeout 480
```

Build tools accept regular image outputs only; no physical card is flashed by build/test scripts. Final source/image checksums and actual outcomes are in validation/.
