# Changelog

## 0.5.1

- Add the twelve-game cabinet with 3-, 5- and 10-hand modes, wild-card graphics, game-specific pays, multipliers and advice.
- Start and keep every cabinet game at max bet with its complete board. Bet Per Hand and Select Hands remain disabled.
- Restore triple-UP autoplay on/off. Every activation starts M; double-UP cycles M, Medium and Fast. Single/held UP and DOWN in M preserve autoplay.
- Prepare read-only advice as each hand is dealt. Releasing UP hides the hint without aborting first-use table loading, so the first held hint and double-UP best-hold request do not need repeating.
- Preserve game credits and each game's pending multipliers when selecting another game. Keep the existing SeedSigner entry gesture.

Functional host, stock ARM and image/source verification are recorded in the matching release artifacts. Physical Pi performance, cold boot, camera and signing are not qualified by emulation.

## 0.4.8

- Delay red hints until UP has been held continuously for 0.30 seconds. Brief double/triple taps show no red; release immediately clears hints.
- Includes the v0.4.7 manual best holds, double-tap autoplay speed selection, triple-tap toggle, footer A and filled speed triangles.

Validation: 205 functional host checks passed. Stock ARMv6 functional emulation passed the delayed red hint, real-advisor best holds and three autoplay rounds. Virtual clocks do not qualify physical timing; no SD card was written.

## 0.4.7

- Triple-tap UP to toggle autoplay on or off. During autoplay, double-tap UP for the next speed; holding UP no longer changes speed. Other buttons stop autoplay without another action.
- Double-tap UP in manual play to set the exact best holds without drawing or spending credits. Hold UP for solid-red hints only while physically held.
- Resolve double/triple tap overlap using captured button timestamps, so a third tap cancels the double-tap prefix. Cancel pending advice when another manual action changes the board.
- Add separately tuned Slow, Medium and Fast autoplay profiles, with nominal rounds of 12.3, 6.9 and 3.7 seconds including animations.
- Move A beside the speaker and add small filled left/right speed triangles for Medium/Fast.
- Preserve the ten-hand 9/6 DDB rules, strategy data, production randomness and stock SeedSigner base.

Validation: 202 functional host checks passed. Stock ARMv6 functional emulation passed real-advisor manual best holds, three autoplay rounds, double-tap speed selection, triple-tap ON/OFF, and cancellation. Virtual clocks do not qualify physical timing, camera scanning or signing. No SD card was written for this release.

## 0.4.1

- Start autoplay with three quick UP clicks instead of two, using captured button timestamps and at most 350 ms between adjacent clicks.
- Show a small yellow A in the upper-left margin only while autoplay is active, without covering current or next-hand multipliers.
- Stop autoplay on any button click and consume that click so it cannot also deal, draw, change a hold or open a menu. Press again to resume manual controls.
- Clear the indicator when the SeedSigner entry gesture begins. Preserve solid-red held-peek hints, normal yellow autoplay selection and the existing slower pace.
- Preserve the poker math, strategy data, randomness, stock SeedSigner application and image base.

Validation: 188 functional host checks passed with no failures, errors or skips. Stock ARMv6 functional emulation passed three autoplay rounds, delayed-dispatch triple-click activation, indicator-only pixel checks and consumed-key cancellation. Virtual instruction and presentation clocks do not qualify physical timing. No SD card was written and physical cold boot, button timing, camera scanning and signing remain unqualified.

## 0.4.0

- Make both middle buttons hold/unhold and confirm; after completed results, either middle deals the next hand. DOWN is Deal/Draw, with animation skip guards.
- Make UP a held peek: solid red recommended-card borders while pressed, immediate clearing on release, and no hint text or explanation screens. Keep double-UP autoplay.
- Pace autoplay with six seconds of consideration, left-to-right card selection every 0.65 seconds, two seconds before Draw and four seconds of results. Use only ordinary yellow focus and HELD tags, with no auto labels or red hints.
- Evaluate all 32 holds from exhaustive replacement-deck category counts. Ten-hand feature advice includes current multipliers and numerically solved continuation values for the next multiplier board.
- Pause autoplay before manual input, the reserved SeedSigner entry gesture, insufficient credits, entropy wait or unavailable advice. Never refill credits automatically.
- Run advice in a cancellable worker loaded on first use; require shutdown before signer handoff.
- Preserve the evaluator, payouts, reference artwork, independent physical-input sampling and stock SeedSigner controls.

Validation:185 functional host checks passed with no failures, errors or skips. Stock ARMv6 functional emulation passed three paced autoplay rounds and held-peek/release pixel checks using virtual instruction and presentation clocks. Wall-clock input timing and physical-device timing remain unqualified.

Numerical strategy checks use floating-point arithmetic, not a formal interval proof. Software and emulated checks do not qualify physical boot, speed, camera scanning or signing; see the release reports and technical guide.

## 0.3.2

- Swap poker controls: D-pad center (left middle) deals/draws; right middle holds/confirms.
- Update retry and menu prompts to identify the new physical controls.
- Retain upstream SeedSigner controls and the outer-button entry gesture.
- Verify all eight GPIO mappings and the remapped actions in host and ARM checks.

## 0.3.1

- Capture short button taps independently of rendering and SPI writes.
- Debounce each button separately; preserve ordered input and single-action held buttons.
- Preserve the two-second outer-button hold/release entry gesture and stop sampling before signer handoff.
- Cache the static board; redraw only the badge region for badge animation.
- Add crisp native card/control focus borders without covering HELD tags or footer text.
- Retain the independently validated ten-play 9/6 DDB rules and original artwork.

Validation: 130 host tests, stock ARMv6 checks and deterministic image rebuilds. See the archived reports for scope.
