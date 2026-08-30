# Overnight-Gap Distribution — Full History (2005–2026)

**Date:** 2026-08-30
**Read-only.** SELECT-only against `psx_data.db`. No writes, no signal regeneration.

---

## Methodology — answering "recompute or just analyse?"

**Just analyse.** The fired-signal set is taken as-is from the already-generated
`boring_study/boring_heterogeneity_panel_{20,60}d.csv` (`breakout == 1` rows — the
Donchian-20 and Donchian-60 fires the boring study produced in July 2026). The signal
logic — `close[t] > MAX(high[t-N..t-1]) × 1.01`, RS_60, liquidity gate, decile ranking —
is **not** re-run.

The only new step: for each fired signal, look up `Open(t+1)` from `prices_adjusted` and
compare it to `Close(t)`. One lookup + one subtraction per signal.

**Processing applied to the existing set:**
- **First-fire-per-run** dedup: a new run starts when the gap since the previous fire in
  the same subset exceeds `N` trading days (the exact `build_run_population` convention the
  validated trailing-stop study used).
- **Restricted to symbols still present in `prices_adjusted`.** The panels were built
  before the 2026-08-27 non-equity purge and contained ~75 futures contracts
  (`AIRLINK-JUN`, `ATRL-MARB`, `786`, …) that passed the liquidity gate and even reached
  RS decile 9. Those are 3.6% of breakout rows, are not tradeable equity signals, and are
  correctly excluded from production's universe — so they're dropped here too. (This is
  why the N=20 Confirmed run count is 570, vs the 647 the pre-purge validated study
  reported.)
- **Signal cutoff:** 2005-10-14 → 2026-07-09 (the panels' own span).

**Buckets:**
| | rule | |
|---|---|---|
| **(a) Gap Up** | `Open(t+1) > Close(t)` | |
| Unchanged | `Open(t+1) = Close(t)` | |
| **(c) Gap Down** | `Open(t+1) < Close(t)` | |
| **(b) At / below prior close** | `Open(t+1) ≤ Close(t)` | = Unchanged + (c); entry at last close or better |

(a) + (b) = 100 %. (c) is the strict subset of (b).

---

## Results

Percentages are of the **evaluable** set (signals with a usable next-day open). Signals
dropped for a missing/zero `open` are shown separately — this is the known pre-2020
`open`-coverage gap and it is material.

### N = 20 (Donchian-20)

| Subset | Signals | Missing open | Evaluable | **(a) Gap Up** | Unchanged | **(c) Gap Down** | **(b) ≤ prior close** |
|---|--:|--:|--:|--:|--:|--:|--:|
| **ALL breakouts** | 21,700 | 2,751 (12.7 %) | **18,949** | **12,359 · 65.2 %** | 1,032 · 5.4 % | **5,558 · 29.3 %** | **6,590 · 34.8 %** |
| **Strategy Confirmed** (decile-9 + liq) | 570 | 29 (5.1 %) | **541** | **440 · 81.3 %** | 20 · 3.7 % | **81 · 15.0 %** | **101 · 18.7 %** |
| **Not Fit** | 21,604 | 2,750 (12.7 %) | **18,854** | 12,286 · 65.2 % | 1,028 · 5.5 % | 5,540 · 29.4 % | 6,568 · 34.8 % |
| *Confirmed — RF1 cross-check* (per-date recon, today's universe) | 1,275 | 49 (3.8 %) | *1,226* | *960 · 78.3 %* | *43 · 3.5 %* | *223 · 18.2 %* | *266 · 21.7 %* |

Gap magnitude, N=20: ALL mean **+0.89 %** / median +0.80 % / mean\|gap\| 3.25 %;
Confirmed mean **+2.95 %** / median +2.53 %; Confirmed up-gaps average **+4.04 %**.

### N = 60 (Donchian-60)

| Subset | Signals | Missing open | Evaluable | **(a) Gap Up** | Unchanged | **(c) Gap Down** | **(b) ≤ prior close** |
|---|--:|--:|--:|--:|--:|--:|--:|
| **ALL breakouts** | 8,453 | 991 (11.7 %) | **7,462** | **5,229 · 70.1 %** | 356 · 4.8 % | **1,877 · 25.2 %** | **2,233 · 29.9 %** |
| **Strategy Confirmed** (decile-9 + liq) | 293 | 16 (5.5 %) | **277** | **222 · 80.1 %** | 16 · 5.8 % | **39 · 14.1 %** | **55 · 19.9 %** |
| **Not Fit** | 8,456 | 991 (11.7 %) | **7,465** | 5,235 · 70.1 % | 354 · 4.7 % | 1,876 · 25.1 % | 2,230 · 29.9 % |

Gap magnitude, N=60: ALL mean **+1.44 %** / median +1.10 %; Confirmed mean **+3.20 %** /
median +2.80 %; Confirmed up-gaps average **+4.49 %**.

---

## By era — does it hold across regimes?

Gap-up % (a) / at-or-below-close % (b), evaluable N per cell:

| Era | N20 ALL (a / b) | N20 Confirmed (a / b) | N60 ALL (a / b) | N60 Confirmed (a / b) |
|---|---|---|---|---|
| 2005–09 | 59.3 % / 40.7 % (N=3,358) | 70.1 % / 29.9 % (N=67) | 63.7 % / 36.3 % (N=1,274) | 58.1 % / 41.9 % (N=31) |
| 2010–14 | 63.0 % / 37.0 % (N=4,617) | 86.6 % / 13.4 % (N=119) | 68.2 % / 31.8 % (N=1,922) | 84.0 % / 16.0 % (N=75) |
| 2015–19 | 67.2 % / 32.8 % (N=4,358) | 79.4 % / 20.6 % (N=131) | 69.8 % / 30.2 % (N=1,561) | 82.1 % / 17.9 % (N=56) |
| 2020–26 | 68.5 % / 31.5 % (N=6,616) | 83.0 % / 17.0 % (N=224) | 74.6 % / 25.4 % (N=2,705) | 82.6 % / 17.4 % (N=115) |

- **The direction is stable in every era.** Signals gap up far more often than down, in
  every 5-year block, both lookbacks, both subsets.
- **Strategy-Confirmed signals gap up ~80–87 % from 2010 onward** — remarkably flat across
  regimes. The 2005–09 Confirmed cells (N=31–67) are too thin to weigh.
- **The friction has intensified, not weakened, over time** — the all-signal gap-up rate
  rises from ~59–64 % (2005–09) to ~69–75 % (2020–26), and mean gap from ~+0.2 % to
  ~+1.5–2.1 %.
- The recent cloud-only sample (2026: 76 % gap-up all-signals, ~75–79 % Confirmed) is
  **consistent with the 21-year history** — it was not a regime artifact. If anything the
  full-history "all signals" number is milder.

---

## Caveats

1. **Missing-open exclusion is real and pre-2020-heavy** — 12.7 % (N=20) / 11.7 % (N=60)
   of signals have no usable next-day open, almost all before 2020. The evaluable
   pre-2020 sample is genuine but smaller than the raw counts suggest, and its `open`
   values carry the unverified-backfill provenance flagged in Phase 0.
2. **Panel signal set, not production.** The heterogeneity panels define the breakout and
   compute `stock_rs` (RS_60); the decile-9 "Confirmed" flag here is the panel-global
   `qcut` (the `build_run_population` convention). The RF1 cross-check row uses the
   per-date cross-sectional reconstruction that matches production's intent — it agrees
   directionally (78.3 % vs 81.3 % gap-up) but is not identical.
3. **Survivorship** — the RF1 cross-check is limited to today's 305-symbol active roster.
   The panel-global rows are not, but the non-equity purge still trims the set to current
   `prices_adjusted` membership.
4. **First-fire-per-run only.** Continuation-day breakouts within a run are excluded, by
   design (a trader acts once per run).
5. This is a **distribution of the open vs the prior close** — it does not address whether
   a limit at the close would later fill on a gap-up day (that is the separate
   `Low(t+1) ≤ Close(t)` question answered in the earlier cloud-sample work).

---

## Winner % of bucket (b) — "available at ≤ prior close"

Outcome joined per signal. Two definitions:
- **HYBRID trailing stop** = production exit rule (entry `Close(t)`, prior-day-low trail,
  −8 % floor, no take-profit). Win = exit above entry. Censored (never stopped) excluded —
  negligible over this horizon.
- **+10 / −6 race** = `hit_tp_10` from the `_race` panels (already computed; pure join).

| Subset | Bucket (b) N | **(b) win % — HYBRID** | (b) win % — race | (a) Gap-Up win % — HYBRID | (b) mean trail return |
|---|--:|--:|--:|--:|--:|
| **N=20 ALL** | 6,590 | **18.6 %** (1,226) | 28.1 % | 52.7 % | **−1.06 %** |
| **N=20 Strategy Confirmed** (panel) | 101 | **10.9 %** (11) | 13.9 % | 45.7 % | −2.86 % |
| *N=20 Confirmed (RF1 sc_corrected)* | *266* | *19.5 %* (52) | *28.9 %* | *47.6 %* | *−0.30 %* |
| **N=20 Not Fit** | 6,568 | 18.6 % | 28.1 % | 52.6 % | −1.06 % |
| **N=60 ALL** | 2,233 | **18.9 %** (421) | 31.5 % | 52.1 % | −1.09 % |
| **N=60 Strategy Confirmed** | 55 | **14.5 %** (8) | 16.4 % | 53.2 % | −2.10 % |
| **N=60 Not Fit** | 2,230 | 18.9 % | 31.6 % | 52.0 % | −1.08 % |

**Within bucket (b):** the "unchanged at close" slice wins ~27–28 % (HYBRID); the true
gap-down slice wins ~17 %. Both far below the ~52–53 % of the gap-up signals.

**Reading:** a signal that opens at or below its prior close wins **~19 %** of the time
(HYBRID) — roughly a third the rate of the gap-up signals — and its average trailing-stop
return is **negative**. The breakouts that let you in at your price are overwhelmingly the
ones that were already failing; the winners gap up and away from you. This confirms the
2026-only cloud finding across the full 21-year history and both lookbacks.

*Caveats:* the panel-Confirmed (b) cells are tiny (N=101 / N=55) — directionally clear,
wide error bars; RF1 Confirmed (N=266) is firmer at 19.5 %. HYBRID exits are modelled at
the stop level (optimistic; circuit-lock fills worse). Neither win definition is
net-of-cost.

## Files

- `scripts/s3_fullhist_gap_distribution.py` → `data/fullhist_gap_distribution.csv` — bucket distribution.
- `scripts/s4_fullhist_bucket_win_rates.py` → `data/fullhist_bucket_win_detail.csv` — per-signal outcome + win rates by bucket.
