# Boring Breakouts — Can Execution Adjustments Salvage the Edge?

**Date:** 2026-08-30
**Read-only.** SELECT-only against `psx_data.db`. Existing signal set reused (first-fire-per-run,
`gap_distribution_detail.csv`); signal logic not recomputed.
**No parameter tuning.** Exit rule (HYBRID trailing stop, −8% floor), cost model, and the
tested gap thresholds are all fixed in advance. Every grid cell is reported, nothing selected.

**Cost model:** round-trip 0.845% (0.15% brokerage ×1.15 FED + 0.25% slippage, per side ×2)
+ 15% CGT on a net-positive trade. This is the dashboard's documented model — heavier than
the 0.20% the original boring validation used, so BASE numbers here sit ~0.6pp below the
published +2.5%.

---

## Test 1 — Does the edge survive entering at the real open?

Entry moved from `Close(t)` (what the validated numbers assume) to `Open(t+1)` (honest
market-on-open), stop re-anchored to the new entry.

| Cut | BASE net EV (Close entry) | **OPEN net EV (real MOO)** | friction |
|---|--:|--:|--:|
| N20 ALL | +0.49% | **−0.12%** | −0.61 |
| N20 Strategy Confirmed (panel) | +1.77% | **−0.06%** | −1.83 |
| N20 Confirmed (RF1) | +0.79% | **−0.46%** | −1.25 |
| N60 ALL | +0.86% | **+0.03%** | −0.83 |
| N60 Strategy Confirmed | +2.20% | **+0.45%** | −1.75 |

The overnight gap costs **0.6–1.8 pp of net EV** — for every cut except N60 Confirmed it
lands at or below zero. The friction is real and about as large as the whole edge.

---

## Test 2 — A working limit at the signal price

Fill only if `Low(t+1) ≤ Close(t)` (price traded back to your level intraday), entry `Close(t)`.

| Cut | fill rate | win rate | **net EV** |
|---|--:|--:|--:|
| N20 ALL | 74% | 23.0% | **−1.52%** |
| N20 Confirmed | 71% | 20.1% | **−2.10%** |
| N60 ALL | 72% | 23.5% | **−1.34%** |
| N60 Confirmed | 65% | 23.8% | **−1.00%** |

**Firmly negative on 21 years, both lookbacks.** The breakouts that let you fill at your
price are the ones already failing — the same result found on the 2026 cloud sample, now
confirmed across the full history. Not salvageable.

---

## Test 3 — Gap-cap grid: "take the trade at the open only if the gap ≤ X"

Entry = `Open(t+1)`, skip the signal if `gap% > X`. Full grid (net EV, % of signals taken):

| X | N20 ALL | N60 ALL | N20 Confirmed | N60 Confirmed |
|---|--:|--:|--:|--:|
| gap ≤ 0% | **+0.83%** (35%) | **+1.18%** (30%) | −1.18% (19%) | +0.33% (20%) |
| gap ≤ 1% | +0.27% (54%) | +0.56% (48%) | −0.56% (30%) | +1.74% (30%) |
| gap ≤ 2% | +0.04% (68%) | +0.27% (63%) | −0.99% (45%) | +1.11% (42%) |
| gap ≤ 3% | −0.08% (76%) | +0.15% (72%) | −1.14% (56%) | +0.41% (51%) |
| gap ≤ 5% | −0.21% (89%) | −0.06% (86%) | −0.80% (76%) | +0.44% (71%) |
| all | −0.12% (100%) | +0.03% (100%) | −0.06% (100%) | +0.45% (100%) |

The only consistently-positive corner is **gap ≤ 0** on the ALL sets (+0.83% / +1.18%). By era:

| Era | N20 ALL gap≤0 | N60 ALL gap≤0 | `open` data quality |
|---|--:|--:|---|
| 2005–09 | +1.30% | +1.86% | 30% missing, unverified backfill |
| 2010–14 | +1.33% | +1.99% | 13–19% missing, unverified backfill |
| 2015–19 | +0.80% | +0.62% | 15–18% missing, unverified backfill |
| **2020–26** | **+0.13%** | **+0.38%** | clean, verified |

This is positive in all four eras — but it is **weakest exactly where the data is clean and
strongest where the `open` series is unverified backfill.** That inverse correlation is a
red flag, not a green light.

Three further problems with this lead:
1. **It is a different setup.** You're taking only the ~30–35% of breakouts that immediately
   weakened back to/below their breakout close, and buying them at the discounted open. That
   is "buy the failed-day-1 dip," not "buy the breakout."
2. **It is mechanically explainable without a signal.** A lower entry puts the −8% floor and
   the trailing stop further below the same price path, so the win rate rises purely from
   buying cheaper. The median net trade is still −0.84% in every cell.
3. **Not distinguished from index beta** (see Test 4).

---

## Test 4 — Is the residual positive EV just index beta?

Over the study window KSE-100 compounded: +50.9% (2005–09), +240.5% (2010–14), +25.4%
(2015–19), +328.4% (2020–26). A ~3-trading-day hold — the median for this system — captures
roughly **+0.06% to +0.34% of index drift per trade** just from being long.

The pooled positive raw EVs (BASE +0.5% ALL; gap≤0 +0.8–1.2%; clean-era 2020–26 gap≤0
+0.13–0.38%) sit **within or below that beta band.** The original boring validation isolated
the edge with a seed=42 matched control; these execution tests do **not** — so a small
positive raw EV over this period is not demonstrably an edge over just being long the market.

---

## Test 5 — The "Strategy Confirmed" filter fails an era split, before friction

N20 Confirmed **BASE** (idealized Close entry) net EV by era: **−1.60 / +0.93 / +0.60 / +3.90**.
N60 Confirmed BASE: **−2.75 / −0.64 / +0.25 / +6.33**.

The entire "Confirmed is the better subset" result is a 2020–2026 phenomenon; in 2005–09 it
is the *worst* cut. This is the same recent-bull concentration signature this research
program has already used to kill Support Reversal, RSI Divergence, the short-side Donchian,
and the S-006 sector-rank hypothesis.

---

## Verdict

**On the evidence available, execution adjustments do not recover a tradeable edge.**

- Honest market-on-open takes net EV to ≈0 or below on every cut (Test 1).
- A working limit at the signal price is firmly negative, −1.3 to −2.1% (Test 2).
- The one positive lead — take only gap ≤ 0, enter at the discounted open — is a different
  setup, is weakest where the data is cleanest, is mechanically attributable to buying lower
  rather than to a signal, and is not separated from index beta (Tests 3–4).
- The "Strategy Confirmed" quality filter does not survive an era split even at the idealized
  entry (Test 5).

This is a **mechanical-execution finding, not a verdict on reading these charts.** The setup
as *backtested* (fill exactly at the breakout close) shows a modest edge; the setup as
*executable* does not, because the winners gap away from you and the fills you can get are
the failures. That gap is structural to an EOD signal on a market with overnight risk and a
daily price limit.

## The one door left open (a real test, not done here)

A **matched-control (seed=42) version of the gap ≤ 0 / open-entry rule, on the clean
2020–2026 data only**: does its +0.13–0.38% net beat its own matched random-day control, or
is it beta? That is the single test that could still rescue a (different, narrower) edge from
this. It requires the control-generation step the boring study used and was not run here.

Prerequisite either way: the 2005–2019 `open` series needs independent verification before
any pre-2020 number in this analysis is weighted — the lead currently leans on the least
trustworthy data.

---

## Test 6 — Matched-control, clean era: is the one surviving lead an edge, or beta?

The lead: *"take the breakout only if it opens ≤ prior close, enter at that discounted
open."* Tested on **2020–2026 only** (clean `open` data), against a matched random-day
control drawn the boring study's own way — same symbol, same regime (`market_regime`),
random non-breakout day, `np.random.default_rng(42)` — with the control window also
restricted to 2020–2026. Identical rule applied to both sides.

| Cut | Breakout (taken) | Control (taken) | Edge (BO − ctrl) | verdict |
|---|---|---|--:|---|
| **N=20 ALL** | 2,114 trades · win 31.8 % · net EV **+0.15 %** | 2,992 trades · win 31.9 % · net EV **+0.48 %** | **−0.33 %** · 95 % CI [−0.74, +0.06] | **no edge** (point estimate negative) |
| **N=60 ALL** | 729 trades · win 33.1 % · net EV **+0.39 %** | 1,201 trades · win 33.0 % · net EV **+0.40 %** | **−0.00 %** · 95 % CI [−0.77, +0.81] · p=0.17 | **no edge** (identical) |
| N=20 / N=60 Confirmed | N=34 / 4 | N=34 / 4 | — | too few in the clean window to test |

Note the taken-rate asymmetry: only **26–31 % of breakouts** open ≤ prior close (vs 42–44 %
of random days) — so this rule already means skipping ~70 % of your signals, and the ~30 %
you keep do **not** outperform a random day in the same stock and regime, entered the same
way. The residual +0.15–0.39 % net EV is the mechanical effect of buying at a lower price
plus the +0.30 %/3-day index drift of the 2020–26 bull — not a signal.

---

## Final verdict

**The Boring Breakout, as an executable strategy, has no demonstrable edge on this data.**

| Adjustment tested | Result |
|---|---|
| Enter at the real open (MOO) | net EV ≈ 0 to −0.5 % — friction ≈ the whole edge |
| Working limit at the signal close | firmly negative, −1.3 to −2.1 % |
| Only take gaps ≤ 0, enter discounted | not distinguishable from a matched random day |
| "Strategy Confirmed" quality filter | 2020–26 artifact; fails an era split at the ideal entry |

The backtested edge lived in the fill-exactly-at-the-breakout-close assumption. That fill is
not achievable — the winners gap away, the fills you can get are the failures — and none of
the tested adjustments recover it.

**What this is:** a verdict on the *mechanical rule* — Donchian breakout confirmed on the
close, position taken the next session, HYBRID trailing exit. It is **not** a verdict on
reading these setups discretionarily: an intraday trader choosing which breakouts to take,
entering on their own trigger, and sizing by conviction is doing something this backtest
cannot represent. The mechanical version is what was tested, across 21 years and both
lookbacks, and it does not clear the bar.

**Everything above is descriptive of the signals in the existing panels.** Prerequisite for
any weight on the pre-2020 rows specifically: the 2005–2019 `open` series still needs
independent verification (13–30 %/yr missing, unverified backfill).

## Files

- `scripts/s5_salvage_tests.py` → `data/salvage_detail.csv` — tests 1–5.
- `scripts/s6_matched_control_2020_2026.py` → `data/mc_{breakouts,controls}_N{20,60}.csv` — test 6.
