# Findings — Overnight-Gap / Execution-Friction Study

**Concluded 2026-08-30. Verdict: the Boring Breakout has no demonstrable edge as an
executable mechanical strategy on this data.** It is a verdict on the systematic rule
(Donchian breakout confirmed on the close → position next session → HYBRID trailing exit),
not on discretionary intraday reading of these setups.

---

## 1. The friction is real (full history, 2005-2026)

Of first-fire boring-breakout signals, next-day open vs prior close:

| | N=20 ALL | N=60 ALL | N=20 Strategy Confirmed | N=60 Strategy Confirmed |
|---|--:|--:|--:|--:|
| evaluable signals | 18,949 | 7,462 | 541 | 277 |
| **(a) gapped up** | **65.2 %** | **70.1 %** | **81.3 %** | **80.1 %** |
| unchanged at close | 5.4 % | 4.8 % | 3.7 % | 5.8 % |
| **(c) gapped down** | **29.3 %** | **25.2 %** | **15.0 %** | **14.1 %** |
| **(b) open ≤ prior close** (F+C) | **34.8 %** | **29.9 %** | **18.7 %** | **19.9 %** |
| mean gap | +0.9 % | +1.4 % | +3.0 % | +3.2 % |

Stable in every 5-year era; the all-signal gap-up rate has *risen* over time (59-64 % in
2005-09 → 69-75 % in 2020-26). The 2026 cloud sample (76 % gap-up) was not a regime
artifact. **~12-13 % of signals dropped for missing `open` — concentrated pre-2020.**

## 2. Bucket (b) — "available at your price" — is where the losers are

Win rate (HYBRID trailing stop, entry at `Close(t)`):

| | (b) ≤ prior close | (a) gap up |
|---|--:|--:|
| N=20 ALL | **18.6 %** (mean trail ret **−1.06 %**) | 52.7 % |
| N=60 ALL | **18.9 %** (−1.09 %) | 52.1 % |
| N=20 Confirmed | 10.9 % (N=101) | 45.7 % |

The breakouts that let you fill at your price are overwhelmingly the ones already failing.

## 3. No execution adjustment recovers a positive net edge

Net EV per trade (0.845 % round-trip + 15 % CGT on wins):

| Adjustment | N=20 ALL | N=60 ALL | N=20 Confirmed | verdict |
|---|--:|--:|--:|---|
| **BASE** — fill at `Close(t)` (as backtested) | +0.49 % | +0.86 % | +1.77 % | the edge that *doesn't survive execution* |
| **OPEN** — honest market-on-open | **−0.12 %** | **+0.03 %** | **−0.06 %** | friction ≈ the whole edge |
| **LIMIT** — working limit at the signal close | −1.52 % | −1.34 % | −2.10 % | firmly negative |
| **gap ≤ 0, enter at discounted open** | +0.83 % | +1.18 % | −1.18 % | the one positive-looking corner → test 4 |

**"Strategy Confirmed" fails an era split even at the ideal BASE entry:** N=20 Confirmed net
EV by era = −1.60 / +0.93 / +0.60 / **+3.90**; N=60 = −2.75 / −0.64 / +0.25 / **+6.33**.
The whole "Confirmed is better" result is 2020-2026 — the same recent-bull concentration
signature that ended Support Reversal, RSI Divergence, the short Donchian, and S-006.

## 4. The surviving lead is not an edge — matched-control test, clean 2020-2026

*"Take the breakout only if it opens ≤ prior close, enter at that discounted open."*
Control = same symbol, same regime, random non-breakout day, `rng(42)`, 2020-2026 window.

| Cut | Breakout (taken) | Matched control (taken) | Edge |
|---|---|---|--:|
| **N=20 ALL** | 2,114 trades · win 31.8 % · net EV **+0.15 %** | 2,992 trades · win 31.9 % · net EV **+0.48 %** | **−0.33 %** · CI [−0.74, +0.06] |
| **N=60 ALL** | 729 trades · win 33.1 % · net EV **+0.39 %** | 1,201 trades · win 33.0 % · net EV **+0.40 %** | **−0.00 %** · CI [−0.77, +0.81] · p=0.17 |

The breakout carries **no edge over a random day**. Only 26-31 % of breakouts open ≤ prior
close (vs 42-44 % of random days), so the rule already means skipping ~70 % of signals —
for a remainder that doesn't beat noise. The residual +0.15-0.39 % net is the mechanical
effect of buying at a lower price plus the +0.30 %/3-day index drift of the 2020-26 bull.
KSE-100 compounded +50 / +240 / +25 / +328 % across the four eras; a ~3-day hold captures
+0.06 to +0.34 % of that drift per trade just from being long.

## 5. Data-quality boundary

The `open` series 2005-2019 is 14-30 %/yr missing and its populated values are unverified
2026-07 backfill (`psx_pipeline/CLAUDE.md`). Any weight on pre-2020 numbers here is
provisional until that series is independently verified. 2020-2026 (the era that decides
the verdict) is clean.

## What this does NOT close

- A **discretionary** version — an intraday trader choosing which breakouts to take,
  entering on their own trigger, sizing by conviction — is not represented by any backtest
  here.
- The **raw breakout edge over matched control** (the boring study's original validated
  finding, `hit_tp_10` at `Close(t)` entry) is not overturned — it was never claimed to be
  executable at that entry, and §2.4 of the rulebook flagged exactly that.
