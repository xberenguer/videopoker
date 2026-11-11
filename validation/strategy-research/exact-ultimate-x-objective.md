# Exact hold advice for classic ten-hand 9/6 DDB

Research only, 2026-11-10. No game or image files changed.

## Source checks

Gary J. Koehler's original *Ultimate X Poker Analysis* models the ongoing game as an average-reward non-discounted Markov decision process. Theorem 1 proves that multiplier boards with the same sum have the same value; the published numerical bias values are nonlinear. Source: https://www.playperfectllc.com/_files/ugd/d82604_9bbe3fae897f4b5791b730fa4acb09a2.pdf (equations1-4; Tables3,5). The paper's worked examples concern Deuces Wild, so their bias vectors cannot be reused for DDB.

Wizard of Odds lists the engine's exact9/6 DDB payout and ten-hand multiplier schedule, with long-run optimal return0.998663. Source: https://wizardofodds.com/games/video-poker/tables/ultimate-x/ (Double Double Bonus9/6 table). This is a rounded external benchmark, not a six-decimal solver certificate. Its static-strategy heuristic is explicitly near-optimal rather than exact.

The author's app distinguishes perfect long-run advice from static approximation: https://www.playperfectllc.com/ultimate-x-and-bonus-streak . Vendor trainer FAQ also describes current-board EV plus future-multiplier XEV: https://www.videopoker.com/pro/?tab=faq . Do not equate the informal XEV label with a universally constant multiplier value.

## Correct objective (our derivation in engine units)

Fix ten lines and10 total credits/line every round. Let S be the sum of frozen current multipliers. Let H be the five initial cards, and K one of32 hold masks. The replacement pool excludes all five initial cards, including discards.

For category j:

    p_j(H,K) = exact_count_j / choose(47,5-popcount(K))
    r(H,K) = 5 * sum_j p_j * PAYOUTS[j]
    q_m(H,K) = sum_{j:MULTIPLIERS[j]=m} p_j
    Q_s(H,K) = coefficient of z^s in (sum_m q_m*z^m)^10

Each line draws independently, conditional on H and K. S_next is a sum of ten IID multiplier-valued draws, hence Q is a tenfold convolution. Define relative continuation value v and gross gain g by:

    g + v(S) = E_H max_K [S*r(H,K) + sum_s Q_s(H,K)*v(s)]

Subtracting the constant100-credit round cost changes g but not the selected hold. Use normalization v(10)=0 during relative value iteration. A hint maximizes the bracket for the actual H and frozen current S. This maximizes long-run expected credits at the fixed setting; it does not maximize the chance of avoiding bankruptcy or guarantee individual wins.

For this multiplier set {1,2,3,4,8,10,12}, exactly107 sums are reachable:10..120 except113,115,117,119 (direct set enumeration). The distribution across individual lines is unnecessary for this expected-value objective. It is necessary for variance-sensitive objectives.

A score of S*r + constant*E[S_next] is only a linear-continuation approximation unless the exact bias is affine. The nonlinear published values disprove a general affine collapse. Likewise, maximizing the immediate hand only misses earned future multipliers.

For base-only rounds, the next multipliers reset to1 regardless of result, so continuation is hold-independent. Exact immediate payout EV is then sufficient; use royal250 per coin for base wagers1..4 and800 at5.

## Fast exact category counts (our derivation)

Build F(A,j), the number of all52-card-deck terminal five-card hands containing subset A and classified as j. Store all subsets with size0..4; classify a size5 subset directly. There are294,204 stored subsets. Fourteen uint32 counts per subset occupy16,475,424 bytes (15.71MiB).

Generate F by enumerating2,598,960 terminal hands once. For each terminal hand increment its category in the31 proper-subset histogram rows. For any initial five-card H, read F for all32 subsets. The exact replacement histogram for hold K is:

    N_H(K,j) = sum_{K subset T subset H} (-1)^(|T|-|K|) F(T,j)

Obtain all32 histograms with an in-place five-bit superset Möbius transform: for each bit b and each mask without b, subtract histogram[mask|b] from histogram[mask]. This is80 vector subtractions,1120 integer subtractions total. Every category sum must equal choose(47,5-|K|).

This eliminates millions of per-query terminal evaluations. Combinadic ranking gives compact lookup rows: for a sorted k-subset c0<...<c(k-1), rank=sum_i choose(c_i,i+1), plus an offset for k. Include format/version, card encoding, category ordering, and checksum in the shipped table.

A toy-deck independent check matched this formula to brute force for100 initial hands x32 holds x3 arbitrary categories in a12-card deck. This is not a replacement for verifying the real52-card classifier and table.

## Offline solution / small Pi runtime

The expensive solution belongs in reproducible build tooling on the Mac, not the Pi. Enumerate the134,459 suit-canonical initial hands and exact category histograms, weighted by suit orbit sizes (weights sum2,598,960). Full32x14 uint32 histograms occupy229.79MiB. Iteration reads these, convolves each hold's multiplier distribution, and applies the Bellman operator over107 states.

Continuation for a hold does not depend on current S, so compute it once and compare32 affine lines S*r+continuation over the107 S values. Their upper envelope can reduce comparisons.

Exact pruning: write the current iterate v(s)=a*s+b+e(s), with emin=min e and emax=max e. Define L_i(S)=S*r_i+a*10*E[M_i]. If L_i(S)+emax < max_k L_k(S)+emin, hold i is dominated at that S. A hold dominated for every S requires no convolution. This remains exact for the current Bellman iterate; it is not substituting a linear value function. Fit a using endpoint slope to make the residual range small.

Ship either (a) the15.71MiB subset table plus the107 solved bias values and a small native convolution/scoring helper, or (b) the precomputed optimal hold mask for every suit-canonical hand and current sum, about13.72MiB at one byte per mask plus lookup metadata. Runtime option(a) also supports alternate ordinary base wagers without additional strategy tables. Actual ARMv6 timings still need benchmarking.

## Validation / claims

1. Check all2,598,960 terminal categories against independent known category totals and Python engine evaluator; target kicker and wheel cases.
2. Cross-check real52-card Möbius results against the independent brute-force enumerator for every hold on random hands, suit/card permutations, royal draws, four-flushes, AAAxx, AAxxy, and low-kicker quads. Check nonnegative counts and denominators.
3. Verify q/Q normalization, nonnegativity, support, deterministic outcomes for hold-all, and exact mean E[S_next]=10*E[M].
4. Iterate to stable actions and a tight Bellman residual. For candidate v, let delta(S)=(T v)(S)-v(S). min(delta) and max(delta) bound optimal gross gain; their span bounds the average-gain loss of v's greedy policy. Record residual, precision, iteration count, and table fingerprint. This is a numerical certificate with enumerated probabilities, not rational symbolic proof of every tie.
5. Compare computed return g/100 with the rounded external0.998663. Also verify an independent policy evaluation/stationary distribution.
6. Confirm on-device hint latency, no input/main-loop blocking, and cancellation of stale jobs after phase/hand changes. Do not change the RNG or sample outcomes to achieve a target return.

Safe wording before full convergence/certification: "multiplier-aware expected-value advice" plus the actual calculation method and limitations. Claim exact long-run optimal advice only after completing the continuation solve and validations. "Always wins" is never true. Do not call a fixed linear-XEV heuristic perfect.

## Implemented and frozen results (2026-11-10)

The generator is `native/strategy_tables.cpp`, invoked by `scripts/build_strategy_tables.py`. It uses the exact category-count/average-reward method above, with safe affine-residual pruning. The final packed table stores subset sizes0/1 as uint32,2/3 as uint16,4 as uint8; this reduces it to4,449,110 bytes including64-byte header. Packed widths are safe because all completions for subsets of sizes2,3,4 total at most19,600,1,176,48 respectively. Its SHA-256 is249615df37a6b18d3b5f96a9d7f1fb2a6ec0fbfe712fab679b93bcba37abb6f2.

A full solve converged in seven iterations, with no hold-policy changes after iteration3. Gross gain is99.8663394862671 credits per100 credits wagered, yielding0.998663394862671 return. The numerical Bellman residual span is3.5129232856e-11 credits/round. Independent fixed-policy transition-matrix and stationary-distribution evaluation gives0.998663394862666 return, with stationary residual5.59e-15 and policy-bias agreement within1.93e-10 credits. These values match the published rounded return0.998663.

The probability counts are exhaustive integers, not Monte Carlo. The continuation solution is IEEE754 numerical value iteration, not a rational or interval-arithmetic proof of every close tie. Runtime treats scores within1e-9 credits as ties, preferring more held cards and then the lower mask. The Bellman residual's algebraic average-gain bound assumes exact arithmetic; the validation certificate adds a conservative1e-8-credit floating-point guard for interpretation. Advice assumes ongoing fixed ten-hand maximum-feature-bet play and optimizes average expected credits. It does not guarantee wins or maximize bankroll survival.

Validation completed:

- All14 global outcome counts match independent combinatorial counts, totaling2,598,960 hands.
- All134,459 canonical hands were generated with suit-orbit weights totaling2,598,960; every one of their32 integer histograms was checked for nonnegativity and the exact replacement denominator.
-288 real52-card hold histograms for18 random/pathological initial hands, holding3/4/5 cards, match independent Python-engine brute force;576 denominator checks pass.
-180 feature-advice queries over30 canonical hands and six current multiplier sums match an independent unpruned scorer over all32 native-cache hold rows. Maximum value difference is2.28e-13. Thirty ordinary base5 queries also agree.
- A fresh from-scratch build, with the same host/thread count, reproduced the packed table, metadata, bias and independent policy certificate byte for byte. Floating-point last digits can vary with other architectures/compiler/thread partitions.

Rebuild with `python3 -B scripts/build_strategy_tables.py --threads 4 --max-iterations 100 --tolerance 1e-10 --output <empty directory>`. Initial host measurements were0.30s for subset generation,0.89s for canonical probabilities, and6.23s for the seven Bellman iterations. A repeat during shared host load took48.25s; these are host measurements, not Pi performance claims.

Top-level evidence files are `validation/strategy-counts-certificate.json`, `validation/strategy-subset-crosscheck-certificate.json`, `validation/strategy-policy-certificate.json`, `validation/strategy-runtime-policy-certificate.json`, and `validation/strategy-reproducibility-certificate.json`. No physical Pi/GPIO behavior is certified by these mathematical tests. Final generated metadata and packed data are frozen; no payload files were edited by this subtask.
