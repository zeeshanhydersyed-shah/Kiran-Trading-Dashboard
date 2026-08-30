# Phase 0 — Evidence Inventory & Feasibility Memo
## Historical extension of the Boring-Breakouts overnight-gap / execution-friction study

**Date:** 2026-08-30
**Phase constraint:** strictly read-only. No database writes, **no new computations** — this
memo only inventories what already exists on disk and maps it to the metrics the study needs.
**Backend decision:** local `psx_data.db` only (SQLite). Cloud/Supabase historical data is
explicitly out of scope for now.

---

## 1. Why local SQLite is the correct and only source

Verified by direct schema/'`information_schema`' reads on 2026-08-28–30:

| | local `psx_data.db` | cloud Supabase |
|---|---|---|
| `prices` / `prices_adjusted` span | **2005-01-03 → 2026-08-25**, 1,756,918 rows | 2024-08-28 → 2026-08-27 only, 231,624 rows |
| `open` column on both tables | ✅ present (REAL) | ✅ present (numeric) but no rows before 2024-08 |
| `index_prices` KSE-100 (needed for RS_60) | 2005-01-03 → 2026-08-25, 0 % missing | close back to 2005, **`open` only 2020+** |
| `market_regime` (regime axis) | full history | full history (2005-01-03 →), all 4 states populated |

A historical study **must** run against `psx_data.db` with `DATABASE_URL` / `SUPABASE_DB_URL`
unset (SQLite branch of every module). The cloud table cannot contribute anything pre-2024.

---

## 2. The metric taxonomy this study needs

| # | Metric | Definition |
|---|---|---|
| M1 | Gap-up rate | share of signals where `Open(t+1) > Close(t)` |
| M2 | Gap magnitude | `(Open(t+1) − Close(t)) / Close(t) × 100`; signed mean, \|mean\|, median, distribution |
| M3 | Limit-fillable rate | share of up-gaps where `Low(t+1) ≤ Close(t)` (a limit at the signal close fills next day) |
| M4 | Fill-to-loss rate | of M3's fillable trades, share that exit at a loss |
| M5 | Gap-up win probability | of all gap-up signals, share that close positive at resolution |
| M6 | All of M1–M5 conditioned on **regime** and **calendar era** |
| M7 | All of M1–M5 split by **Strategy Confirmed** vs **Not Fit** |

---

## 3. Inventory — availability of each metric from existing files

Legend: **A** = already computed, sitting in a file · **J** = derivable by joining existing
files with **no** DB hit and **no** modelling · **C** = needs a computation (a DB join +
arithmetic) → next phase.

| Metric | Status | Where / what is missing |
|---|---|---|
| **Signal population** (dates, entry close) | **A** | `boring_study/boring_donchian_occurrences.csv` — 80,745 N=20 breakouts, 2005–2026, cols `symbol,date,entry_close,prior20high,ret_5/10/20/30/60/90d,mfe_pct,mae_pct,days_tracked`. No liquidity/RS/universe filter. |
| **Strategy Confirmed label** (historical) | **A** | `boring_study/boring_rf1_misclassification_detail.csv` — 47,414 obs, N=20 only, restricted to today's 305-symbol eligible universe. Cols `decile_current, decile_corrected, liquidity_pass, sc_current, sc_corrected`. `sc_current` = what production `boring_signals.py` actually flags today (buggy: liquidity gate applied *after* ranking); `sc_corrected` = the Addendum-B-correct label (gate *before* ranking). Use `sc_corrected`. |
| **Regime tag per signal** | **J** | join signal `date` → `boring_study/boring_donchian_daily_environment.csv` (`date,regime,breadth,…`, 2005-01-04 →) or the `market_regime` DB table. No compute. |
| **RS_60 / liquidity / decile per signal** | **A** (N=20 & N=60) | `boring_study/boring_heterogeneity_panel_20d.csv` (156,786 rows) / `_60d.csv` (91,768). Cols `symbol,date,breakout,regime,outcome,stock_rs,vol_ratio,liquidity,lookback`. `breakout=1` are real breakouts; `breakout=0` are seed=42 matched random controls. `stock_rs` = RS_60. |
| **Trade outcome — TP/−6 % race** | **A** | `_race` variants: `boring_heterogeneity_panel_20d_race.csv` / `_60d_race.csv` add `hit_tp_10` ∈ {0,1} (hit +10 % before −6 %, tie → stop). |
| **Trade outcome — production HYBRID trailing stop** | **A** (aggregates only) | `boring_study/boring_donchian_trailing_stop_race_v2_output.txt` — decile-9 + liquidity-gated, run-collapsed: **N=20 → 647 runs, 41.5 % win, +3.6 % gross / +2.5 % net-of-cost+CGT, median hold 2 d, 98–99 % resolve via stop; N=60 → 343 runs, 47.1 % win, +4.3 %.** Per-trade rows are **not** saved to a CSV — only the printed summary. |
| **Edge by regime (raw breakout vs control)** | **A** | `boring_study/boring_donchian_regime_sweep_detail.csv` — `lookback × regime × threshold` grid, cols `n_raw,n_matched,bo_tp_pct,ctrl_tp_pct,improvement_pp`. 2005–2026 pooled. |
| **M1 — gap-up rate** | **C** | No file carries `Open(t+1)`. Needs a join of signal `date` → `prices_adjusted` at the next trading row. |
| **M2 — gap magnitude** | **C** | Same. `mfe_pct` / `ret_5d` in the occurrences file are close-anchored forward returns, not the overnight open gap. |
| **M3 — limit-fillable rate** | **C** | Needs `Low(t+1)` vs `Close(t)`. `mae_pct` is the 90-day min-low excursion, **not** "did day t+1 trade back to entry" — cannot substitute. |
| **M4 — fill-to-loss** | **C** (gap side) + **A/J** (outcome side) | Once M3 exists, the loss flag joins from the race panels (`hit_tp_10`) or a re-run trailing-stop walk. |
| **M5 — gap-up win probability** | **J** for the TP-race definition, **C** for the HYBRID definition | M5 = P(win \| gap-up). "Gap-up" needs M1 (→ C). But if you accept the TP-race `hit_tp_10` as the outcome, everything except the gap-up flag is already in the `_race` panels. |
| **M6 — regime / era conditioning** | inherits the worst of its inputs | regime tag is J; era is trivial from `date`. So M6 is available for any metric whose base is A/J, and blocked only where the base is C. |
| **M7 — Confirmed vs Not Fit split** | **A** | `sc_corrected` (N=20) from the RF1 file; `stock_rs` decile from the panels (N=20 & N=60). |

**Bottom line:** the signal set, its labels, the regime axis, and the *outcome* side are all
already on disk. The **overnight gap itself (M1–M3) is in no file** and is the single genuine
computation the study still needs.

---

## 4. The one computation that is unavoidable (→ next phase)

**What:** for each historical breakout `(symbol, signal_date)`, look up the **next** trading
row in `prices_adjusted` and record `open_t1`, `low_t1`, `close_t1`, then derive
`gap_pct`, `gap_up`, `fillable`.

**Why it can't be skipped:** every existing results CSV anchors forward measurement to
`Close(t)` and reports close-to-close returns or 90-day MFE/MAE extrema. None ever recorded
the *next open* because the boring study entered at the close — and the rulebook explicitly
flagged this as the untested deviation:

> `boring_study_trading_rulebook_v1_2026-07-11.md` §2.4 — *"Entry price = Close(t) … using
> Open(t+1) instead is a small, untested deviation from what was validated — worth tracking
> separately (slippage vs. the backtested entry)."*

**Size:** ~15–20 lines added to a copy of `boring_study/boring_donchian_scan.py` (it already
loads `prices_adjusted` with `open`; only the per-occurrence record changes). Output a single
CSV to `boring_gap_study/`. Read-only against `psx_data.db`, resumable by year per the
standing long-running-script rule.

**Precedent that already exists:** `boring_study/boring_donchian_trailing_stop_race_v2.py`
Part 2 already computes an overnight gap — `(Open(exit_day) − overnight_stop_level) /
stop_level` — for the *exit* side, and handles the `open`-coverage gap explicitly (skips and
counts, never assumes zero). That is the template. Result there, for reference:
**18 / 616 evaluable exits (2.9 %) gapped > 2 % through the stop; among those mean −4.5 %,
median −4.4 %, worst −8.3 %; 24 / 640 exits (3.8 %) had no `open` price at all.**

---

## 5. Data-quality ceiling (from numbers already measured — no new computation)

| Window | `prices_adjusted.open` usable? | Provenance | Verdict for M1–M3 |
|---|---|---|---|
| 2005–2019 | **14–30 % of rows NULL/zero per year** (worst: 2005 30 %, 2008 29 %) | Open never scraped pre-2020; backfilled 2026-07 from a source with **no independent cross-check** | descriptive only; heavy asterisk |
| 2020–2023 | ~1–2 % missing | spot-verified 40/40 vs BI Postgres | clean |
| 2024–2026 | ~1–2 % missing | native scrape | clean |

`Low` / `High` are ≥ 98–99 % complete across the whole span, so **M3 (fillable) and the
trailing-stop outcome survive deeper than M2 (gap magnitude) does** — the binding constraint
is specifically the `open` series pre-2020.

For the decile-9 population specifically, the already-run trailing-stop script measured a
**3.8 % `open`-coverage gap** (24 / 640 exits) — a concrete floor for how much of the
Strategy-Confirmed subset the gap study simply can't evaluate.

---

## 6. Caveats when reusing the `boring_study/` files

1. **Short-side vs long-side.** `phase1a/1b/1c_*` files and `short_*` / `short_panel_*` are
   the **2026-07-17 short Donchian thread** (breakdowns, TP = −15 %/−10 %, SL = −3 %) —
   CLOSED, no tradeable edge, driven by 2008. **Do not mine these for the long-side study.**
   The long-side artifacts are `boring_donchian_*`, `boring_heterogeneity_*`,
   `boring_leadership_*`, `boring_rf1_*`, `boring_state_dedup_*`,
   `boring_donchian_trailing_stop_race*`.
2. **Panel signal construction ≠ production signal construction.** The heterogeneity panels
   define a breakout as `close[t] > MAX(high[t-N..t-1]) × 1.01` with the decile taken
   post-hoc over the *full* population; production `boring_signals.py` freezes RS_60 as of
   `t-1`, applies the liquidity gate *before* ranking, and takes decile 9 of the gated set.
   The RF1 file is the reconciliation of exactly this — `sc_corrected` is the
   production-intent label, `sc_current` is the (buggy) live one. Decide which the study
   should key on and state it.
3. **Universe = today's roster.** `boring_signals._eligible_universe()` and the RF1 file both
   use today's 305-symbol `stock_metadata.is_active` list with **no point-in-time
   reconstruction** → survivorship bias. Milder for a gap/friction study than for a return
   study, but must be disclosed. The unfiltered `boring_donchian_occurrences.csv` (all
   symbols ever) is the alternative base if survivorship needs bounding.
4. **N=20 vs N=60.** The occurrences file and the RF1 label file are **N=20 only**. N=60
   labels exist only via the `_60d` heterogeneity panels (post-hoc decile). If the study
   wants both lookbacks with the production-correct Confirmed label, that's an extra
   reconciliation step.
5. **Modelled, optimistic exits.** Every outcome number in these files books out at the
   modelled stop/target level, not a printed fill; circuit-lock days make real fills worse.
   Any win-rate reused here carries that caveat unchanged.
6. **Run-collapse / dedup.** The trailing-stop-race aggregates are **run-collapsed** (a fresh
   fire within `lookback` days of the previous one is folded into the same run). The raw
   occurrences and panels are **not**. Match the dedup convention before comparing counts.
7. **`days_tracked` truncation.** Recent occurrences in `boring_donchian_occurrences.csv`
   have partial forward windows (e.g. `ZUMA 2026-06-19`, `days_tracked=13`) — filter on
   `days_tracked` before using the forward-return columns.

---

## 7. What can be assembled *now* (read-only, no compute) vs what waits

**Now — from existing files, zero DB, zero compute:**
- The historical signal count by year, lookback, regime, and Confirmed/Not-Fit
  (occurrences + daily_environment + RF1 files) → tells us the **effective sample size and
  regime coverage** the eventual gap study will have, which is the direct answer to the
  "our current window is small" concern.
- A consolidated **edge-by-regime / edge-by-era** table for the raw breakout and the
  TP-race outcome (`regime_sweep_detail.csv` + the `_race` panels) → most of "does the
  *edge* hold across regimes," already done.
- The **HYBRID trailing-stop headline** by lookback (from the race v2 output).
- The **`open`-coverage ceiling** table (§5) restated against the actual per-year counts.

**Waits for the next (small) computation phase:**
- M1, M2, M3 — the overnight gap and the fillable flag.
- M4, M5 under the HYBRID exit (M5 under the TP-race exit is a join, not a compute).
- M6/M7 for whichever of the above land in C.

---

## 8. Recommended next phase (for sign-off, not this phase)

**Scope:** one script, `boring_gap_study/build_gap_panel.py` — a ~15–20-line extension of
`boring_study/boring_donchian_scan.py`.
- Input: the historical breakout dates (regenerate from `prices_adjusted`, or read
  `boring_donchian_occurrences.csv` directly and just add columns).
- Add per row: `open_t1`, `low_t1`, `close_t1`, `gap_pct`, `gap_up`, `fillable`,
  `open_t1_missing` flag.
- Join: `sc_corrected` (RF1 file), `regime` (daily_environment / `market_regime`),
  `hit_tp_10` (race panels) — all no-DB joins.
- Output: one CSV in `boring_gap_study/`, plus a summary txt mirroring the current
  `boring_gap_study.py` report but segmented by regime and era.
- Discipline: read-only against `psx_data.db`; resumable by year; no production module
  imported for its write paths.
**Estimated effort:** ~1–1.5 sessions for the panel + a first segmented result;
+1 session for block-bootstrap CIs (breakouts cluster hard in calendar time) and the
era-consistency write-up.

---

## Appendix — file-by-file pointer (`psx_pipeline/boring_study/`)

| File | Rows | Use for this study |
|---|---|---|
| `boring_donchian_occurrences.csv` | 80,745 | signal population (N=20, unfiltered), 2005–2026, entry close + fwd close-returns + MFE/MAE |
| `boring_donchian_control_occurrences.csv` | 80,706 | matched-control occurrences (baseline for "is the gap breakout-specific") |
| `boring_donchian_daily_environment.csv` | 5,320 | date → regime / breadth / dispersion, no-DB regime join |
| `boring_donchian_regime_sweep_detail.csv` | ~75 | edge by lookback × regime × threshold (raw breakout vs control) |
| `boring_heterogeneity_panel_20d.csv` / `_60d.csv` | 156,786 / 91,768 | breakout+control rows w/ `regime, stock_rs (RS_60), vol_ratio, liquidity, outcome` |
| `boring_heterogeneity_panel_20d_race.csv` / `_60d_race.csv` | same | + `hit_tp_10` (validated +10 %/−6 % race outcome) |
| `boring_rf1_misclassification_detail.csv` | 47,414 | historical Strategy-Confirmed label (`sc_corrected`), N=20, today's universe |
| `boring_donchian_trailing_stop_race_v2.py` + `_output.txt` | — | production HYBRID-exit aggregates by lookback; **template for the M1–M3 computation** (its Part 2 already does an exit-side gap) |
| `boring_state_dedup_test_hybrid.py` + `_output.txt` | — | run-collapse / dedup convention matching production |
| `boring_liquidity_gated_replication_output.txt` | — | corrected headline hit rates (49.0 % / 48.5 %) |
| `boring_study_trading_rulebook_v1_2026-07-11.md` | — | §2.4 flags the Open(t+1) entry deviation as the open item this study addresses |
| `BORING_STUDY_STATUS.md` | — | canonical index of the whole thread; long-side vs short-side map |
| `phase1a/1b/1c_*`, `short_*`, `short_panel_*` | — | **SHORT-side thread — do NOT use for this study** |

---

*Prepared read-only. No database writes, no computations performed. All row counts and
column lists are from direct `head`/schema reads of the files named.*
