# Changelog

## 0.3.1

- Capture short button taps independently of rendering and SPI writes.
- Debounce each button separately; preserve ordered input and single-action held buttons.
- Preserve the two-second outer-button hold/release entry gesture and stop sampling before signer handoff.
- Cache the static board; redraw only the badge region for badge animation.
- Add crisp native card/control focus borders without covering HELD tags or footer text.
- Retain the independently validated ten-play 9/6 DDB rules and original artwork.

Validation: 130 host tests, stock ARMv6 checks and deterministic image rebuilds. See the archived reports for scope.
