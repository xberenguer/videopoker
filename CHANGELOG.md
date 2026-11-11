# Changelog

## 0.4.0

- Make both middle buttons hold/unhold and confirm; after completed results, either middle deals the next hand. DOWN is Deal/Draw, with animation skip guards.
- Add single-UP best-hold advice with flashing red card borders and double-UP autoplay.
- Evaluate all 32 holds from exhaustive replacement-deck category counts. Ten-hand feature advice includes current multipliers and numerically solved continuation values for the next multiplier board.
- Pause autoplay before manual input, the reserved SeedSigner entry gesture, insufficient credits, entropy wait or unavailable advice. Never refill credits automatically.
- Run advice in a cancellable worker loaded on first use; require shutdown before signer handoff.
- Preserve the evaluator, payouts, reference artwork, independent physical-input sampling and stock SeedSigner controls.

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
