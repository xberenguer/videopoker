# Changelog

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
