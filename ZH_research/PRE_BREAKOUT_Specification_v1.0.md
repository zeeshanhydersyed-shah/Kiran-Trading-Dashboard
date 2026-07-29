# PRE_BREAKOUT — Formal Specification v1.0

**Status:** Phase 4 (Research Reopening) — construct definition finalized against BREAKOUT V2; first hypothesis test complete and closed. Not yet used for any live trading decision.
**Filed:** 2026-07-10
**Researcher:** Quantitative Analyst
**Reviewer:** Independent Quantitative Reviewer (PI)
**Supersedes:** The `pre_breakout_v2_staging` table (243-symbol, built against the deprecated BREAKOUT V2 table) — left in place, unmodified, as a historical artifact. This document and `pre_breakout_v2_staging_full` are the current, canonical PRE_BREAKOUT research population going forward.
**Related:** [BREAKOUT_Specification_v1.0.md](BREAKOUT_Specification_v1.0.md) (Section 1.5 already anticipated this construct: *"If price subsequently falls back below that same level... the market re-enters a pre-breakout state relative to that same resistance level"*). This document formalizes that state into a testable population, per BREAKOUT_Specification_v1.0.md Section 5's original deferral ("PRE_BREAKOUT construct — to be defined as its own phenomenon in a subsequent phase, using the finalized breakout event... as its fixed reference point").

---

## Session Summary / Current State (2026-07-10)

This section consolidates the full research session held on this date across S-002, S-003, and PRE_BREAKOUT Sections 5–13, so a future reader can understand the complete current state without reconstructing it from chat history. It is a summary/index, not a substitute for the full sections it points to — see each cited section for full statistics, era breakdowns, and reproducibility detail.

### ✅ CONFIRMED, LIVE, VALIDATED

- **`sec_global_rank ≤ 8`** (`sector_signals.rs_rank`, sector-vs-market strength gate) — EV@90d = **+10.50%** (`weinstein_combined_backtest.py`, "Sector only" gate). **Untouched by any finding this session.** Currently live in the Explorer page's Weinstein Watchlist toggle and the combined backtest's base gate. **Status: KEEP, in active use.**

### 🔴 DEAD — DO NOT REOPEN WITHOUT NEW EVIDENCE

Per this project's standing convention (established practice across S-001/S-002/S-003 and the sections below): a closed/dead finding is not re-tested on the same data; reopening requires a new, independently-motivated hypothesis and, where applicable, fresh data.

- **`rs_score_20` / `sector_rs_rank` as post-breakout quality scoring** ([S-002_RS_Rank_Quartile_BREAKOUT_V2.md](S-002_RS_Rank_Quartile_BREAKOUT_V2.md)) — no significant relationship on the corrected BREAKOUT V2 population; the originally-cited baseline finding could not be located anywhere in the repository or git history.
- **`sector_rs_rank ≤ 5` as a standalone pre-screen filter** ([S-003_Sector_RS_Rank_PreScreen.md](S-003_Sector_RS_Rank_PreScreen.md)) — small but statistically significant effect, **reversed direction** from the hypothesis, consistent across all 3 eras.
- **Tightness** (`pct_rank_252`, `pct_rank_756`, `zscore_252`), both **standalone** (Section 5) and **sector-conditioned** on `sec_global_rank≤8` (Section 10) — reversed (loose beats tight) across all 3 measures and all 3 eras; the reversal weakens somewhat but does not flip when conditioned on sector strength.
- **ROC-5/ROC-10 velocity + volume multiplier** (Section 11) — mixed; no single factor independently survives Bonferroni correction across all three eras; ROC_5 and the volume-multiplier gate show a decay-to-reversal pattern in OOS.
- **Stealth Relative Strength ≥2, UNCONDITIONAL** (Section 12) — Development-era result (hit-rate lift +4.87pp, Cliff's δ=+0.0747) **confirmed dead on the locked, one-shot Validation+OOS test** (Cliff's δ=-0.0439, MWU one-sided p=0.9997, reversed on the rank-based confirmatory checks); did not replicate.

### 🟡 MIXED — ERA-INCONSISTENT, NOT ACTIONABLE AS-IS

- **TRENDING_UP regime-transition-age (0-2 vs 6+ days since transition) as a forward-return predictor** ([S-005_Regime_Transition_Age_and_Type.md](S-005_Regime_Transition_Age_and_Type.md)) — market-only test of a PI personal-journal observation (242 discretionary trades). Pooled result is statistically significant in the journal's hypothesized direction (Cliff's δ=+0.0466), but **reverses in Development** (δ=-0.1286, larger magnitude, MWU one-sided p=1.0) while confirming in Validation (δ=+0.1687) and OOS (δ=+0.0912). Not a stable, era-independent effect — **not recommended as a trading rule.**
- **Regime-type (VOLATILE vs TRENDING_UP, VOLATILE vs RANGING)** ([S-005_Regime_Transition_Age_and_Type.md](S-005_Regime_Transition_Age_and_Type.md)) — same document, second sub-claim. `TRENDING_UP > VOLATILE` is **confirmed**, small effect, consistent all 3 eras. `VOLATILE` vs `RANGING` is itself era-inconsistent (VOLATILE ahead in Development/Validation, RANGING ahead in OOS) — **neither is confirmed as the reliably worse regime of the two.**

### ✅ LIVE FIXES APPLIED (2026-07-10) — formerly "FLAGGED, LIVE, UNRESOLVED"

Both items below were previously flagged, unmodified, pending PI review. PI has now approved and both fixes are **live in code** as of this entry.

**Fix A1 — `leaders_scan.py::_raw_score()` (justified by S-002).**
`rs_score_20` and `sector_rs_rank` scoring blocks (2 of 5 components, both confirmed dead per S-002) were **removed entirely** from `_raw_score()` — not zeroed out, the code blocks themselves are gone, and the function signature dropped from 5 params to 3 (`rs_rank, avg_vol_10d, sector_composite`). The call site in `append_leaders_scan()` was updated to match. Max possible raw score dropped from 15 → **9**. `MIN_PICK_SCORE` re-derived proportionally: old threshold 8/15 = 53.3% of max; applied to the new max, 9 × 0.533 = 4.8, rounded to the nearest integer → **`MIN_PICK_SCORE = 5`** (was 8 — left unchanged, 8/9 would have been an unreachable-in-practice near-perfect-score bar). The penalty function (`_compute_penalty`, using `sector_rank`, `rs_score_50`, `rank_change`, `nearest_overhead_pct`, `vol_rejection_flag`, `rs_inflection`, `vol_ratio_today`) is untouched — different fields, out of scope.
*Before/after, most recent scan date (2026-07-09, 31 candidates):* old formula+threshold (raw max 15, `MIN_PICK_SCORE=8`) → **0** qualifying Top Picks. New formula+threshold (raw max 9, `MIN_PICK_SCORE=5`) → **1** qualifying candidate: `(BREAKOUT, CNERGY)`. Recomputed-old-formula sanity check matched the stored `raw_score` column exactly (0 mismatches across all 31 rows) before applying the edit.

**Fix A2 — Explorer's Weinstein Watchlist toggle (justified by S-003).**
The `sector_rs_rank ≤ 5` condition (dead/reversed per S-003) was removed from the filter's 7-condition `AND` block (now 6 conditions) and from the block's `sort_values()` call (now `["sec_global_rank", "rs_rank"]`, was `["sec_global_rank", "sector_rs_rank", "rs_rank"]`). The separately-confirmed-live `sec_global_rank ≤ 8` condition is untouched. The adjacent caption string (same code block, not a separate page) was also updated to drop the now-inaccurate "Sector top 5" phrase — the further-down "How It Works" educational expander (a separate UI section citing the old 7-rule list) was deliberately **not** touched in this task and remains a known, pending documentation-staleness follow-up.
*Before/after, most recent scan date (2026-07-09, 297-row base universe):* **0 → 0** — the screen is currently dormant on this date (consistent with prior project notes that the Weinstein screen is inactive in the current extended-market condition), so this specific date shows no practical change; the fix is nonetheless correct and will matter on future dates where the removed condition would otherwise have blocked a candidate.

Scripts/diffs: applied directly to `leaders_scan.py` and `dashboard.py`; before/after figures computed via ad hoc read-only queries against `psx_data.db`, not saved as a separate script (one-off verification, not a repeatable research artifact).

### 🔬 EXPLORATORY — NOT CONFIRMED, NO HELD-OUT DATA REMAINS (Section 13)

- **Stealth Relative Strength ≥2, CONDITIONED on non-"runaway bull" regime** — recovered the Development-era effect's direction and magnitude in this specific subset (hit-rate lift +5.83pp, Cliff's δ=+0.0419, p=0.000140), while showing a strong reversal inside the runaway-bull subset (δ=-0.2112). Genuinely interesting and mechanistically coherent (matches the Market Structure Diagnostic's independently-derived bull-market timeline), but **tested twice now on already-examined data** — no fresh, independent confirmation is currently possible. **Should be re-evaluated once genuinely new data accrues (2026 H2 onward), tested once, not iteratively.**
- **Runaway-bull filter definition, for future reuse:** `regime = TRENDING_UP AND KSE-100 trailing-252d return > +36.74%` — fixed threshold, derived from **2015-2022 data only**. **Do not re-derive this threshold using post-2022 data if reused later** — its value as a diagnostic tool depends on its non-circular derivation.

**Watch-only dashboard feature added (2026-07-10, updated same day with a practical pre-filter, then updated again same day for UX consistency):** a **"🔬 Stealth RS (Exploratory — Not Validated)"** toggle was added to the Explorer page, surfacing current candidates meeting **both** stealth-count≥2 **and** `sec_global_rank≤8` for observation only.

- **UX note (third revision, same day):** initially rendered as a separate standalone table below the main Explorer table; per user feedback this broke the page's established pattern (every other toggle — Weinstein Watchlist, Stage 4 Shorts — filters the existing main table in place, showing an empty state when nothing qualifies). Restructured to match: Stealth RS now filters `_ex_filtered` directly, **mutually exclusive with Weinstein Watchlist** (`elif`, not stacked — if both toggles are on, Weinstein wins and a warning is shown; this preserves the "never combined with Weinstein" isolation rule without a second table). The Stealth Count and Sec Global Rank columns are appended to the same main table's column set only while the toggle is active.
- **(a) Watch-only, not a validated screener:** mutually exclusive with Weinstein Watchlist filtering (never stacked/combined), not wired into `leaders_scan.py`, `kiran_voice.py`, or `agent.py`'s opportunity generator, no scoring/ranking logic. Both displayed columns — **Stealth Count** and **Sec Global Rank** — are deliberately unweighted; the table's sort control never offers either column, so a user cannot rank by them, since neither "higher stealth count is better" nor "this sector-restricted subset behaves differently" has ever been tested.
- **(b) The `sec_global_rank≤8` restriction is a practical, untested filter, not a finding:** added per PI's explicit workflow decision (PI trades only within top-8 sectors as a rule) — it reuses Market Gate's confirmed, already-live field/logic verbatim (same `fillna(999)<=8` convention as the Weinstein Watchlist block and `weinstein_combined_backtest.py`), but **Stealth RS has never been tested conditioned on `sec_global_rank` in any form.** This is not the same claim as Section 13's "runaway bull" conditioning — a different, untested conditioning variable.
- **(c) Re-evaluation reminder:** re-run the Section 12/13 confirmatory methodology once sufficient new post-2026-07 data accrues (PI's stated target: year-end) before this feature is ever considered for anything beyond observation — and **at that time, separately check whether the `sec_global_rank≤8`-qualifying subset behaves differently from the non-qualifying subset**, once enough observations exist to say anything about it (not yet testable — see verification below).

Uses the exact locked Section 12 stealth-count definition (20-trading-day trailing window, KSE-100 daily return ≤-1.5% = adverse day, stock closes flat-or-positive with the existing `avg_vol_10d` liquidity gate) — unmodified. A persistent warning caption ("Exploratory research signal... The sec_global_rank≤8 restriction is a practical trading-workflow filter, not a tested combination...") is shown whenever the toggle is on, both directly under the toggle and above the results table. SQLite/local-only for now — degrades to an info message on Streamlit Cloud (`_PG_URL` set), consistent with several other research-derived features' current Postgres-parity gap (see CLAUDE.md Known Gaps).

*Verified against real current data (2026-07-09):* only 1 adverse KSE-100 day (2026-07-08) currently sits in the trailing 20-day window, so today's maximum possible stealth count is 1 (31 stocks at count=1, 216 at 0) — **0 rows meet stealth≥2 today regardless of sector**, so the combined filter also shows 0 (mathematically expected, not a bug). Separately confirmed the `sec_global_rank≤8` join/filter itself works correctly: 115 of 297 universe stocks currently sit in a qualifying sector.

### 📊 MARKET STRUCTURE DIAGNOSTIC (context for future reference — [Market_Structure_Diagnostic_2015-2026.md](Market_Structure_Diagnostic_2015-2026.md))

- **No cross-sectional microstructure break:** correlation, dispersion, liquidity concentration, and sector concentration are all stable/continuous across 2015-2026 — average pairwise correlation is if anything mildly *lower* in 2023-2025 than 2015-2022.
- **Clear index-level regime break:** a sustained bull market 2023-2025 (KSE-100 +53%/+78%/+49%), following the January 2023 PKR devaluation and an IMF-program-driven macro recovery (inflation 38%→11.8%), plus a mechanical circuit-breaker price-band widening to ±10% (May–July 2024) — directly relevant to any fixed-threshold daily-return signal (adverse-day counts, ROC).

---

## 1. PRE_BREAKOUT Definition

A `(symbol, date)` row is in the PRE_BREAKOUT population if, on that date:

1. **`active_resistance` is not null** — a qualifying pivot high (per BREAKOUT_Specification_v1.0.md Section 1) is currently in effect for this symbol.
2. **`close ≤ active_resistance`** — price has not closed above the level (i.e., no `breakout_event` fired today against this level).
3. **`already_broken` (eligibility reading) is False** — this specific resistance level has not already been broken and is still "live": the eligibility state is the value `compute_breakout_events()`'s internal `already_broken` variable holds at the moment it tests today's close against `active_resistance` (post any same-day pivot-supersession reset, pre today's own fallback/continuation update). This is the same reading validated and documented in the prior PRE_BREAKOUT inventory session — not re-litigated here. It excludes the single day price first falls back below a level it was continuing above (a "stale post-breakout continuation" day), while including subsequent days of genuine re-approach.

No tightness/volume/RS filter is part of this definition — those are candidate quality layers (Section 4), tested independently, not part of population membership.

---

## 2. Population Rebuild

### 2.1 Source and rebuild

Previously built against `stock_signals_breakout_v2_staging_DEPRECATED_243sym` (the pre-fix, undocumented 243-symbol snapshot). Rebuilt here against **`stock_signals_breakout_v2_staging_full`** (252 symbols, rolling-liquidity-gated, per the BREAKOUT V2 fix).

**Derivation correction found and fixed during this rebuild:** `stock_signals_breakout_v2_staging_full` has date *gaps* per symbol (only liquidity-eligible dates are stored — unlike the deprecated table, which held each of its 243 symbols' full unconditional history). An initial attempt to derive `already_broken` by walking that gapped table directly produced 91 mismatches against the stored `breakout_event` — the exact same failure mode diagnosed in the BREAKOUT V2 rolling-liquidity session (a gap-blind incremental walk misattributes state across gaps). Fixed by recomputing `compute_breakout_events()` (imported from `breakout_events_v2.py`, unmodified) fresh from each symbol's full continuous `prices_adjusted` history, deriving `already_broken` on that gapless sequence, then filtering down to the liquidity-eligible dates afterward. A second issue surfaced during that fix (602 apparent mismatches, `NaN` vs `None` comparison artifact for unset `active_resistance` — not a logic bug) was also found and corrected. Final validation: **0 mismatches out of 291,674 rows** — every stored `(close, active_resistance, breakout_event)` in the source table matches an independent fresh recompute exactly.

### 2.2 Before / after

| | Symbols | Rows |
|---|---|---|
| OLD (`pre_breakout_v2_staging`, deprecated source) | 243 | 922,056 |
| NEW (`pre_breakout_v2_staging_full`) | 247 | 280,881 |

New population is **30.5%** of the old row count. This is expected, not a regression: `stock_signals_breakout_v2_staging_full` itself only contains liquidity-eligible dates (the BREAKOUT V2 rolling-liquidity fix), whereas the deprecated table held each of its 243 symbols' full unconditional history regardless of liquidity. The same size reduction pattern was already observed and explained in the RS-rank re-validation work (S-002).

Per-symbol row counts (new population, 247 symbols): min=1, median=847, max=2,850, mean=1,137.2.

---

## 3. Volume-Coupling Recovery (research-level only)

`stock_signals.base_tightness` is nulled whenever the 10-day/50-day trailing volume window has a null/zero value, even though the formula itself (`4×std/mean×100` over 20-day close) never references volume — a known coupling documented in the earlier PRE_BREAKOUT inventory session. Part B recovers `base_tightness` for population rows affected by exactly this bug, computed independently within this research pipeline via `_compute_bt_vc` (imported from `stock_signals.py`, unmodified) — **`stock_signals.py` and the production `stock_signals` table are not touched anywhere in this process.**

| | Count |
|---|---|
| Population rows | 280,881 |
| `base_tightness` NULL in `stock_signals` for this (symbol, date) | 147 (0.05%) |
| Recovered via price-only recomputation (volume-coupling casualties) | **0** |
| Still null — no `stock_signals` row at all for this date | 147 |
| Still null — insufficient price history (<20-day window) | 0 |
| Still null — unexplained | 0 |

**No volume-coupling casualties found in the rebuilt population** (0 of 147 nulls). This is a materially different outcome from the ~9,070 figure quantified against the *old* population, and is fully explained by Section 2's population-size reduction: the rolling-liquidity gate that shrank the population from 922,056 to 280,881 rows disproportionately removed exactly the kind of illiquid-period dates where the volume-window coupling bug was concentrated (a stock's *own* 10-/50-day volume window is null/zero almost exclusively during genuinely thin, largely-pre-liquidity-eligible stretches — the same dates the rolling gate now excludes at the source). The 147 remaining nulls are dates with no `stock_signals` row at all (outside that table's coverage window for the symbol), not volume-coupling — a different, legitimate reason, unrelated to the bug quantified previously.

Net effect: `bbw_pct` is 99.9% non-null on the rebuilt population (280,511 / 280,881) without needing any recovery to achieve it.

---

## 4. Candidate Tightness Measures

Reused verbatim from the prior PRE_BREAKOUT inventory session — no new formula introduced:

- **`bbw_pct`** — `stock_signals.base_tightness` (or the Part-B-recovered value where applicable), the project's existing BBW%-equivalent.
- **`pct_rank_252`** — percentile rank of today's `bbw_pct` within that symbol's trailing 252-day `bbw_pct` history (inclusive of today).
- **`pct_rank_756`** — same, trailing 756-day window.
- **`zscore_252`** — z-score of today's `bbw_pct` vs. trailing 252-day mean/std (inclusive of today).

Minimum 60 valid trailing observations required before a percentile/z-score is computed (rows below this are left null, not silently computed on thin data).

| Measure | Non-null | % |
|---|---|---|
| `bbw_pct` | 280,511 / 280,881 | 99.9% |
| `pct_rank_252` | 275,272 / 280,881 | 98.0% |
| `pct_rank_756` | 275,272 / 280,881 | 98.0% |
| `zscore_252` | 275,272 / 280,881 | 98.0% |

---

## 5. Hypothesis Test — Does Tightness Predict `fwd_return_10d`?

**Hypothesis (PI-stated):** tighter (lower percentile rank / lower z-score, relative to the stock's own history) predicts better forward returns than looser. Tested via tightest-quartile (Q1) vs. loosest-quartile (Q4), matching the S-002/S-003 statistical suite: Mann-Whitney U (two-sided and one-sided, directional per "tighter is better"), Welch's t-test, Cliff's delta. `fwd_return_10d` computed fresh (`stock_signals` and this population carry no such column) using `compute_forward_returns.py`'s exact formula, reused verbatim. Valid for 279,659 / 280,881 rows (99.6%).

### 5.1 Full population (all eras combined)

| Measure | N | Tight (Q1) mean | Loose (Q4) mean | Mean Δ | MWU 2-sided p | MWU 1-sided p (tight>loose) | Welch t p | Cliff's δ |
|---|---|---|---|---|---|---|---|---|
| `pct_rank_252` | 274,050 | +0.408% | +1.546% | **-1.138pp** | <0.000001 | **1.000000** | <0.000001 | -0.0387 |
| `pct_rank_756` | 274,050 | +0.325% | +1.626% | **-1.301pp** | <0.000001 | **1.000000** | <0.000001 | -0.0485 |
| `zscore_252` | 274,050 | +0.354% | +1.501% | **-1.148pp** | <0.000001 | **1.000000** | <0.000001 | -0.0380 |

All three measures agree, unambiguously: the tightest quartile **underperforms** the loosest quartile by ~1.1–1.3 percentage points, and the one-sided test in the hypothesized direction returns p=1.0 for all three — there is no evidence whatsoever supporting "tighter is better" in this operationalization. If anything, the reverse holds, with small-to-moderate, highly significant effect sizes at this sample size.

### 5.2 Era consistency

| Era | Measure | N (tight/loose) | Mean Δ | MWU 2-sided p | Cliff's δ |
|---|---|---|---|---|---|
| Development | `pct_rank_252` | 24,049 / 23,700 | -1.579pp | <0.000001 | -0.0770 |
| Development | `pct_rank_756` | 23,924 / 23,888 | -1.390pp | <0.000001 | -0.0618 |
| Development | `zscore_252` | 23,924 / 23,923 | -1.569pp | <0.000001 | -0.0768 |
| Validation | `pct_rank_252` | 18,925 / 18,606 | -1.429pp | <0.000001 | -0.0673 |
| Validation | `pct_rank_756` | 18,684 / 18,638 | -1.796pp | <0.000001 | -0.0940 |
| Validation | `zscore_252` | 18,684 / 18,684 | -1.410pp | <0.000001 | -0.0674 |
| OOS | `pct_rank_252` | 26,128 / 25,860 | -0.420pp | 0.000007 | +0.0227 |
| OOS | `pct_rank_756` | 25,968 / 25,906 | -0.611pp | 0.120118 (n.s.) | +0.0079 |
| OOS | `zscore_252` | 25,906 / 25,906 | -0.458pp | 0.000017 | +0.0218 |

**Direction is consistent — never once does tight outperform loose, in any era, for any measure.** Development and Validation are both strongly significant for all three measures (Cliff's δ -0.06 to -0.09, the largest effect sizes observed anywhere in this test). OOS attenuates sharply for all three (mean Δ shrinks to -0.42 to -0.61pp), and `pct_rank_756` specifically loses significance on the two-sided MWU test in OOS (p=0.12) while `pct_rank_252` and `zscore_252` remain significant there (p<0.0001). Notably, **Cliff's delta flips to small positive in OOS for all three measures** even though the mean delta stays negative — the same rank-vs-mean divergence pattern already documented in S-001/S-003 for OOS-era dispersion effects, not a new phenomenon specific to this construct.

---

## 6. Classification

**REVERSED — not confirmed, not simply dead.** All three candidate measures agree on direction (loose beats tight), agree on rough magnitude in Development and Validation, and never show the hypothesized direction in any era. This clears the task's "broadly agree" bar (same direction, comparable significance) — no escalation to PI chart-level judgment is triggered by measure disagreement, since there is no meaningful disagreement between the three.

**Recommendation, if any single measure is needed for future reference:** `pct_rank_252`. Reasoning, tied to stability across eras and sample coverage rather than raw p-value:
- Remains statistically significant in **all three** eras (Development, Validation, and OOS) — `pct_rank_756` loses significance in OOS.
- Requires only a 252-day (≈1yr) trailing window vs. 756 days (≈3yr) for `pct_rank_756` — fewer rows are excluded for insufficient history, and it becomes usable earlier in a stock's post-listing life.
- Percentile rank carries no distributional assumption, unlike `zscore_252`, while showing a near-identical effect-size profile to it across every era in this test.

This recommendation is about which measure is the most stable and interpretable *representation of the reversed relationship found here* — it is explicitly **not** a recommendation to use tightness as a "buy the tight base" filter, since the tested direction is the opposite of that.

---

## 7. Phase Note

This is **Phase 4 (Research Reopening)** for PRE_BREAKOUT — the first hypothesis actually tested against this construct since it was formally defined relative to BREAKOUT V2's `active_resistance`. No prior tested finding exists for this exact population/definition to compare against (the deprecated table's population was never hypothesis-tested before being superseded). Per standing project convention, this classification stands on its own — it does not reference or depend on H-001–H-008 or the RS-rank findings (S-002/S-003/S-004), all of which concern different constructs entirely.

---

## 8. Limitations

1. **Overlapping 10-day return windows** — as in S-002/S-003, forward-return windows for the same symbol on adjacent dates overlap heavily. Neither MWU nor Welch's t-test accounts for this within-symbol serial correlation; this affects the *precision* of the significance claim, not the observed direction, which is unanimous across measures and (mostly) across eras.
2. **OOS attenuation and the Cliff's-delta sign flip** are observed and reported, not explained — consistent with, but not re-derived from, the dispersion-based explanation given in S-001/S-003 for similar OOS patterns.
3. **No tightness×liquidity or tightness×sector interaction tested** — out of scope per task constraint (no new candidate variables).
4. **147 rows remain null for `bbw_pct`** (no `stock_signals` coverage for that date) — left null, not imputed, per the same discipline as the earlier volume-coupling recovery work.

---

## 9. Reproducibility

Script: `prebreakout_v2_rebuild_and_test.py` (project root). Read-only against production tables and `stock_signals.py`; writes only to `pre_breakout_v2_staging_full`. Part D's full result table (12 rows: 4 quartile rows × 3 measures) also saved to `prebreakout_v2_partD_results.csv`.

---

## 10. Phase 4b — Conditional Tightness Test (2026-07-10)

**Question:** Section 5 tested tightness (`pct_rank_252`) standalone against the full PRE_BREAKOUT population and found the reversed result (loose beats tight). But PI's actual trading process never applies tightness standalone — it is the last filter, applied only after the sector-strength screen has already narrowed the universe. This section re-tests `pct_rank_252` **conditional on `sec_global_rank ≤ 8`**, the validated, live sector-strength gate (per `weinstein_combined_backtest.py`'s "Sector only" gate), to see whether discrimination emerges within an already-qualified population, rather than as a standalone filter on the unconditioned universe again.

Per task constraint, only `pct_rank_252` is re-tested here (not `pct_rank_756` or `zscore_252`), and no conditioning variable beyond `sec_global_rank ≤ 8` is introduced (no trend/RS/EMA stacking).

### 10.1 Conditioning join and population size

`sec_global_rank` joined onto `pre_breakout_v2_staging_full` via the same logic as `weinstein_combined_backtest.py`: `sectors` (symbol → sector) then `sector_signals` (date, sector) → `rs_rank AS sec_global_rank`.

| | Rows | % of full population |
|---|---|---|
| Full population (`pre_breakout_v2_staging_full`) | 280,881 | 100.0% |
| — sector-rank join NULL (no `sector_signals` row for that date/sector) | 1,307 | 0.47% |
| **Conditioned (`sec_global_rank ≤ 8`)** | **103,052** | **36.69%** |

The conditioned population is well under half the full population — expected, since `sec_global_rank ≤ 8` is itself a materially restrictive sector-strength screen (top 8 of typically 23 sectors, roughly the top third, on any given date).

### 10.2 Conditioned quartile test — `pct_rank_252` (all eras combined)

n = 100,680 (after dropping rows with null `pct_rank_252` or `fwd_return_10d`).

| Quartile | N | Mean fwd_return_10d | Median |
|---|---|---|---|
| Q1 (tight) | 25,257 | +0.579% | -0.323% |
| Q2 | 25,179 | +0.573% | -0.417% |
| Q3 | 25,369 | +0.754% | -0.319% |
| Q4 (loose) | 24,875 | +1.513% | -0.116% |

TIGHT (Q1) vs LOOSE (Q4): mean delta **-0.934pp**. MWU two-sided p=0.000288; MWU one-sided (tight>loose) p=0.999856; Welch's t p<0.000001; Cliff's δ = **-0.0187**.

Direction is unchanged from the unconditioned result — tight still underperforms loose — but the effect is **weaker**: mean delta shrinks from -1.138pp (unconditioned) to -0.934pp, and Cliff's δ shrinks from -0.0387 to -0.0187 (roughly half the effect size).

### 10.3 Era consistency (conditioned population)

| Era | N (tight/loose) | Mean Δ | MWU 2-sided p | MWU 1-sided (tight>loose) p | Welch p | Cliff's δ |
|---|---|---|---|---|---|---|
| Development | 8,720 / 8,638 | -1.283pp | <0.000001 | 1.000000 | <0.000001 | -0.0603 |
| Validation | 7,462 / 7,348 | -1.532pp | <0.000001 | 1.000000 | <0.000001 | -0.0553 |
| OOS | 9,102 / 9,073 | -0.066pp | <0.000001 | **0.000000** | 0.727246 (n.s.) | **+0.0495** |

All quartile groups in all three eras exceed the ~200–500 Weak-confidence floor by a wide margin (smallest group: 7,348, Validation) — no insufficient-N flag applies anywhere in this test.

**Development and Validation reproduce the reversed effect at comparable-or-slightly-larger magnitude** than their unconditioned counterparts (unconditioned Dev: -1.579pp/δ=-0.0770; unconditioned Val: -1.429pp/δ=-0.0673) — sector-strength conditioning does not rescue tightness as a positive filter in either era; if anything the rank-based effect size is similar.

**OOS all but disappears on the mean (-0.066pp, Welch's t not significant, p=0.727) and the rank-based test flips sign** — MWU one-sided (tight>loose) is significant at p≈0 and Cliff's δ is small positive (+0.0495), meaning tight actually ranks better than loose in OOS even though the mean difference is negligible. This is the same mean-vs-rank divergence pattern already observed and reported (not re-explained) for the unconditioned OOS result in Section 5.2 and documented earlier in S-001/S-003 — not a new phenomenon introduced by conditioning.

### 10.4 Before / after — does conditioning change the standalone finding?

| | Mean Δ (tight − loose) | Cliff's δ | Direction |
|---|---|---|---|
| Unconditioned (Section 5.1) | -1.138pp | -0.0387 | tight underperforms loose |
| Conditioned (`sec_global_rank≤8`) | -0.934pp | -0.0187 | tight underperforms loose |

**Direction is unchanged** — tighter still does not predict a better `fwd_return_10d` than looser, even within the sector-strength-qualified population. **Magnitude is weakened** (mean delta shrinks by ~0.20pp, Cliff's δ roughly halves), and the OOS era in particular collapses toward null on the mean while flipping sign on the rank-based test — but this last pattern mirrors the unconditioned OOS behavior already on record, not a divergence caused by conditioning itself.

### 10.5 Classification

**REVERSED, WEAKENED — not confirmed, not rescued by conditioning.** Sector-strength conditioning does not reverse the standalone finding into confirmation ("tighter is better" is not supported), nor does it fully kill the reversed effect — it survives, at reduced magnitude, and remains highly significant overall and in both Development and Validation. It does materially attenuate in OOS, consistent with the OOS attenuation pattern already documented for the unconditioned test.

**Practical implication:** there is no evidence here that stacking `pct_rank_252` tightness on top of the live `sec_global_rank ≤ 8` sector gate turns tightness into a useful additional filter. The live gate's own validated edge (EV@90d = +10.50%) stands on its own merits; this test finds no basis for layering a tightness condition on top of it in the hypothesized ("tighter is better") direction.

### 10.6 Limitations

1. Same overlapping-10-day-return serial-correlation caveat as Section 8.1 — affects precision of significance, not the observed direction.
2. Only one conditioning variable (`sec_global_rank ≤ 8`) was tested, per task constraint — trend/RS/EMA stacking on top of this remains untested.
3. Only `pct_rank_252` was re-tested, per task constraint — `pct_rank_756`/`zscore_252` conditional behavior is unknown.
4. The OOS mean-vs-rank divergence is observed and reported, not re-derived or newly explained, consistent with Section 8.2's treatment of the same pattern in the unconditioned test.

### 10.7 Reproducibility

Script: `prebreakout_v2_phase4b_conditional_tightness.py` (project root). Read-only against `pre_breakout_v2_staging_full`, `sectors`, `sector_signals` — no production writes, no live-system changes. Full result table (4 rows: all-eras + 3 eras) saved to `prebreakout_v2_phase4b_results.csv`.

### 10.8 Pending — Path B (Trend/EMA-Stack Conditioning of Tightness), NOT YET RUN

PI-deferred item, logged here rather than silently dropped: a further conditional test of `pct_rank_252` restricted to a trend/EMA-stack (`close_above_ema50`/`ema50_slope_pos` or the EMA150 equivalents) has not been run. **If ever executed, it must be treated as a third conditioning pass on the same tightness variable family** — after Section 5 (standalone) and Section 10 (sector-conditioned) — and should carry an explicit multiple-comparison disclosure per [Decision D-001](Decisions.md) covering all three passes together, not be reported as an isolated single test. Not scoped or run as part of Phase 4b or 4c.

---

## 11. Phase 4c — Velocity/Volume Test (ROC + Volume Multiplier) (2026-07-10)

**Pivot rationale:** tightness is closed dead/reversed under both standalone (Section 5) and sector-conditioned (Section 10) testing. PI authorized a pivot to a different construct — rate-of-change (velocity) combined with a volume-expansion gate — motivated by BREAKOUT V1's H-005 (Volume Expansion Ratio), this project's strongest individual factor result before decaying to null at OOS (Cliff's δ: 0.0690 Development → 0.0445 Validation → -0.0037 OOS). H-005 was terminated for decay, not for being wrong in principle, which is why the underlying construct (velocity/volume) is revisited here in a new form rather than treated as closed.

### 11.1 Variable definitions

- **`ROC_5`** = `(close_t − close_t−5) / close_t−5 × 100`, **`ROC_10`** = same with a 10-day lookback. Both computed via **position-based lookback against each symbol's full continuous `prices_adjusted` history** (trading days, not calendar days) — not the gapped PRE_BREAKOUT staging table directly, the same discipline established in Section 2.1's `already_broken` derivation correction.
- **`vol_multiplier`** = `avg_vol_10d / avg_vol_20d`.
  - `avg_vol_10d`: reused verbatim from `stock_signals` (existing column).
  - `avg_vol_20d`: **no stored column exists** for this in `stock_signals`. Checked before inventing anything new — an established convention for a trailing 20-trading-day mean volume (today inclusive) already exists identically in `backtest_recovery_bases.py` and `backtest_recovery_sim.py` (`volumes[max(0, t-19):t+1].mean()`), reused verbatim here. This is deliberately **not** `stock_signals.vol_contraction` (a 10d/50d ratio with a stricter no-null/no-zero exclusion rule) — a different, non-equivalent construct with a different denominator window; substituting it would silently change the variable the task specified.

**Structural finding, found before testing began:** `vol_multiplier` has a **hard mathematical ceiling approaching but never reaching 2.0x**. Because `avg_vol_10d`'s 10-day window is nested inside `avg_vol_20d`'s 20-day window (same end date), `avg_vol_20d = (10·avg_vol_10d + k·avg_vol_prior10) / (10+k)` for `k≤10` valid prior-window days — as the preceding 10-day volume approaches zero, the ratio approaches but cannot exceed 2.0x. Observed max across the full population: **1.999320** — consistent with this derivation, not a data-quality artifact. **Consequence: the task's 2.0x threshold candidate is structurally unreachable** (0 rows clear it in every era and pooled) — reported as such rather than treated as a real "too few rows" case. This shrinks the primary-test family from a naively-counted 6 to **4 actual tests** (ROC_5 quartile, ROC_10 quartile, `vol_multiplier>1.5x`, combined `ROC_10`-Q4+`vol_multiplier>1.5x`); the 2.0x variants are excluded from the Bonferroni denominator since they never execute a comparison.

### 11.2 Descriptive statistics (full population, N=280,881)

| | ROC_5 | ROC_10 | vol_multiplier |
|---|---|---|---|
| Mean | +0.582% | +1.305% | 1.046 |
| Min | -99.71% | -99.68% | 0.021 |
| 25th pct | -3.320% | -4.540% | 0.793 |
| Median | -0.135% | +0.093% | 1.025 |
| 75th pct | +3.550% | +5.653% | 1.281 |
| Max | +484.16% | +248.80% | 1.999 (structural ceiling, see above) |

Non-null coverage: `roc_5`/`roc_10` 100.0% (280,881/280,881); `avg_vol_10d`/`vol_multiplier` 99.9% (280,726/280,881).

### 11.3 Bonferroni correction (per Decision D-001)

Real primary-test family size = **4**. Uncorrected α = 0.05. **Bonferroni-adjusted α = 0.05 / 4 = 0.0125** (one-sided, applied to the MWU test in the hypothesized direction — higher velocity/volume predicts higher `fwd_return_10d`).

### 11.4 Pooled results (all eras combined)

| Test | N (hi/lo) | Mean Δ | MWU 2-sided p | MWU 1-sided p | Welch p | Cliff's δ | Uncorrected@0.05 | Bonferroni@0.0125 |
|---|---|---|---|---|---|---|---|---|
| ROC_5 quartile (Q4 vs Q1) | 69,915/69,915 | +0.624pp | 0.167384 | 0.083692 | <0.000001 | 0.0043 | n.s. | does not survive |
| **ROC_10 quartile (Q4 vs Q1)** | 69,915/69,915 | +0.799pp | 0.000066 | **0.000033** | <0.000001 | 0.0123 | significant | **SURVIVES** |
| vol_multiplier > 1.5x | 30,949/248,555 | +0.597pp | 0.831277 | 0.584362 | <0.000001 | -0.0007 | n.s. | does not survive |
| Combined ROC_10-Q4 & vol>1.5x | 18,153/261,351 | +0.928pp | 0.140810 | 0.929595 | <0.000001 | -0.0065 | n.s. (reversed rank) | does not survive |

Only **ROC_10 quartile** survives the Bonferroni-corrected bar at the pooled level. Note already at this stage: the **combined** test has a *positive* mean delta (+0.928pp, the largest of the four) but a *negative* Cliff's delta and a one-sided p of 0.93 — i.e., the rank-based test actively rejects the hypothesized direction while the mean looks attractive. This mean-vs-rank divergence (first seen in Section 5.2/10.3's OOS results) recurs throughout this test's era breakdown below, and is flagged as a finding in its own right in Section 11.6.

### 11.5 Era consistency

| Test | Era | N (hi/lo) | Mean Δ | MWU 1-sided p | Cliff's δ | Survives α=0.0125? |
|---|---|---|---|---|---|---|
| ROC_5 quartile | Development | 25,172/25,172 | +0.605pp | 0.000015 | 0.0215 | YES |
| ROC_5 quartile | Validation | 18,767/18,767 | +0.775pp | 0.001051 | 0.0183 | YES |
| ROC_5 quartile | OOS | 25,977/25,977 | +0.376pp | **1.000000** | **-0.0297** | no (reversed) |
| ROC_10 quartile | Development | 25,172/25,172 | +0.602pp | 0.000043 | 0.0202 | YES |
| ROC_10 quartile | Validation | 18,767/18,767 | +0.532pp | 0.181277 | 0.0054 | no |
| ROC_10 quartile | OOS | 25,977/25,977 | +0.902pp | 0.813277 | -0.0045 | no (rank-reversed) |
| vol_multiplier>1.5x | Development | 10,819/89,867 | +0.773pp | 0.000050 | 0.0229 | YES |
| vol_multiplier>1.5x | Validation | 7,528/67,530 | **-0.492pp** | **0.999984** | **-0.0292** | no (**significantly reversed**) |
| vol_multiplier>1.5x | OOS | 12,602/91,158 | +0.969pp | 0.973561 | -0.0106 | no (rank-reversed) |
| Combined ROC10-Q4+vol>1.5x | Development | 5,960/94,726 | +1.063pp | 0.043414 | 0.0132 | no (uncorrected-only) |
| Combined ROC10-Q4+vol>1.5x | Validation | 4,471/70,587 | -0.130pp | 0.999474 | -0.0292 | no (reversed) |
| Combined ROC10-Q4+vol>1.5x | OOS | 7,664/96,096 | +1.180pp | 0.999288 | -0.0219 | no (rank-reversed) |

All groups, across every era and every test, comfortably exceed the ~200–500 Weak-confidence floor (smallest group: 4,471, Validation combined test) — no insufficient-N flag applies anywhere in this test.

### 11.6 Findings that diverge meaningfully between eras (reported as findings, not footnotes)

1. **ROC_5 and ROC_10 both show a Development/Validation-agree, OOS-reverses pattern reminiscent of H-005's own decay** — but sharper: H-005 decayed smoothly to a small, non-significant near-null OOS result (δ=-0.0037). Here, ROC_5's OOS one-sided p is **1.000000** with Cliff's δ=**-0.0297** — a clean, unambiguous reversal, not a fade to null. ROC_10 similarly reverses in sign (δ=-0.0045) though closer to zero. **Classification for both: DECAY-PATTERN-LIKE-H-005**, arguably a more decisive OOS rejection than H-005's own.
2. **`vol_multiplier>1.5x` does not show a graceful decay at all — it reverses with statistical significance in Validation.** Development supports the hypothesis on its own (survives Bonferroni independently, p=0.000050). Validation does not merely fail to replicate — the mean delta flips to **-0.492pp** and the MWU test is significant **in the wrong direction** (one-sided-hypothesized p=0.999984, i.e., p≈0.000016 for the opposite direction). OOS then reverts to a positive mean but a rank-reversed, non-significant result. This is an **erratic, era-flipping pattern**, not a monotonic decay — worse-behaved than H-005, which never flipped sign with significance in an interior era.
3. **The combined test (ROC_10-Q4 & vol>1.5x) shows the mean-vs-rank divergence in every single era, not just OOS.** Mean deltas are positive throughout (Dev +1.06pp, Val -0.13pp is the lone exception, OOS +1.18pp — the single largest raw mean delta anywhere in this study), yet Cliff's delta is negative in Validation and OOS and the one-sided MWU actively rejects the hypothesized direction (p≈0.999) in both. This is consistent with a right-skewed distribution where a small number of large positive outliers inflate the mean while the bulk of the distribution (what the rank-based tests detect) does not support the effect — the same phenomenon flagged for tightness's OOS era (Sections 5.2/10.3), but here present across the whole era range for this specific combined test, not confined to OOS.

### 11.7 Classification (per test)

| Test | Pooled Bonferroni verdict | Era pattern | Classification |
|---|---|---|---|
| ROC_5 quartile | Fails (p=0.0837) | Dev/Val independently significant & correctly signed; OOS cleanly reverses (δ=-0.0297, p=1.0) | **DECAY-PATTERN-LIKE-H-005** (sharper reversal than H-005) |
| ROC_10 quartile | **Survives** (p=0.000033) — but driven by Development + pooled N, not independent replication | Only Development independently clears α=0.0125; Validation n.s.; OOS rank-reversed | **MIXED** — pooled "survival" does not reflect a stable, era-independent effect; do not treat as confirmed on the pooled figure alone |
| vol_multiplier > 1.5x | Fails (p=0.584) | Development significant & correct; Validation significantly **reversed**; OOS rank-reversed | **MIXED / erratic** — worse than a clean decay, actively flips sign with significance in Validation |
| Combined ROC_10-Q4 & vol>1.5x | Fails (p=0.930, rank-reversed) | Mean-vs-rank divergence in every era; rank-based test never supports the hypothesis outside Development (uncorrected-only) | **DEAD** — attractive-looking mean deltas throughout are not corroborated by any rank-based test at any era after Development, and Development itself does not survive Bonferroni |

**Overall Phase 4c classification: MIXED, no confirmed factor.** Nothing here is unambiguously dead in the way tightness (Sections 5/10) was — Development and, for ROC_5, Validation show genuine, correctly-directioned, Bonferroni-surviving effects — but nothing survives independently across all three eras, and `vol_multiplier`'s Validation reversal and the combined test's pervasive mean-vs-rank divergence are worse-behaved than H-005's own graceful decay. **No factor from this test is recommended for promotion to a live filter.**

### 11.8 Limitations

1. Same overlapping-return-window serial-correlation caveat as Sections 8.1/10.6 — affects precision of significance, not the observed direction or the reversal patterns reported.
2. `vol_multiplier`'s 2.0x threshold is structurally unreachable by construction (Section 11.1) — this is a property of the specific 10d/20d nested-window definition used here, not evidence about volume expansion in general; a differently-constructed volume ratio (e.g., H-005's non-overlapping `volume[t]/mean(volume[t-20..t-1])`) would not have the same ceiling and was not re-tested here (out of scope — H-005 itself is closed on BREAKOUT, not re-opened).
3. Path B (trend/EMA-stack conditioning) remains deferred per Section 10.8 and was not touched by this task.
4. The mean-vs-rank divergence pattern (Section 11.6) is observed and reported, not newly explained — consistent with, but not a formal re-derivation of, the same phenomenon documented for tightness's OOS results in Sections 5.2/10.3.

### 11.9 Reproducibility

Script: `prebreakout_v2_phase4c_velocity_volume.py` (project root). Read-only against `pre_breakout_v2_staging_full`, `prices_adjusted`, `stock_signals` — no production writes, no live-system changes. Full result table (16 rows: 4 pooled + 12 era-level) saved to `prebreakout_v2_phase4c_results.csv`.

---

## 12. Phase 5 — Development-Era Exploratory (12.1–12.7) + CONFIRMATORY RESULT (12.8–12.11) (2026-07-10)

**CONFIRMATORY VERDICT (see 12.8–12.11 for full detail): DEAD — reversed on the pre-registered secondary/confirmatory distributional tests (Cliff's δ, MWU).** The Development-era finding (Section 12.2, Candidate A, stealth≥2) does **not** hold up against the combined Validation+OOS population under the locked, single-shot confirmatory rule. The primary right-tail hit-rate metric itself does show a statistically significant lift of comparable magnitude to Development — but the secondary confirmatory tests (explicitly specified as the checks that establish whether an effect is real, not just a raw-number artifact) reverse, driven by the stealth≥2 group's median/bulk performance being *worse* than baseline in the confirmatory data — the opposite of Development's broad, non-outlier-driven shift. Per the task's explicit instruction not to soften a negative result: this is reported as DEAD, not CONFIRMED or WEAKENED, with the full nuance below.

**⚠ Sections 12.1–12.7 below are EXPLORATORY, HYPOTHESIS-GENERATING WORK — NOT A CONFIRMATORY FINDING ON THEIR OWN.** This section uses **Development-era data only (2015-01-01 → 2019-12-31)**, by deliberate design, to avoid overfitting to the full sample — exactly the failure mode this project's three-era split exists to prevent. Any candidate below that looks promising is explicitly **not** iterated on further here; it would be confirmed **once**, in a separate later task, against Validation+OOS together. This section is not numbered as an `S-00X` confirmatory study for that reason.

**Explicit confirmation: Validation (2020-2022) and OOS (2023+) data were never queried, loaded, or viewed at any point during this task.** Every SQL query in `prebreakout_v2_phase5_exploratory_footprints.py` carries a hard `date <= '2019-12-31'` filter, and every loaded DataFrame is checked at runtime by an assertion (`guard_no_future_leakage`) that aborts the script if any row's date exceeds that boundary. Price/volume history from *before* 2015-01-01 was used for trailing-window warmup where needed (e.g., a 180-day volume window ending in early January 2015 reaches back into 2014) — this is pre-Development history, not Validation/OOS, and does not violate the constraint.

**Primary metric:** right-tail hit rate, `P(fwd_return_10d > +10%)`, per task instruction — given the mean-vs-rank divergence already documented in Sections 5.2/10.3/11.6, mean `fwd_return_10d` is not used as the headline comparison. Cliff's delta and MWU are reported as secondary/confirmatory checks only.

### 12.1 KSE-100 adverse-day threshold justification

Development-era KSE-100 daily returns (N=3,705 trading days, includes pre-2015 warmup, all ≤2019-12-31): mean +0.059%, std 1.253%, min -5.88%, max +8.60%.

| Percentile | Value |
|---|---|
| 1% | -3.976% |
| 5% | -2.106% |
| 10% | -1.293% |
| 25% | -0.499% |
| 50% (median) | +0.068% |
| 75% | +0.688% |
| 90% | +1.399% |

| Threshold | Days below | % of days | ~Days/year |
|---|---|---|---|
| < -1.0% | 491 | 13.25% | 33.4 |
| **< -1.5%** | **303** | **8.18%** | **20.6** |
| < -2.0% | 200 | 5.40% | 13.6 |

**Kept the task's starting threshold of -1.5%.** It sits between the 5th and 10th percentiles — clearly a bad day, not a routine down-day, while still frequent enough (~20.6/year, roughly 1.7/month) that a 20-day trailing window plausibly contains at least one such day for most stocks most of the time. 303 adverse days identified in the Development-era + warmup window.

### 12.2 Candidate A — "Stealth Relative Strength"

**Definition:** for each PRE_BREAKOUT-eligible row, over the trailing 20 trading days (inclusive of the row's own date), count "stealth days" — adverse KSE-100 days on which the stock itself closed flat-or-positive (≥0% daily return) **and** had a non-null `avg_vol_10d` on that specific day (the existing liquidity-gate convention used throughout this project, applied per-day rather than only at the population's eligibility date).

Rows analyzed: 100,686 (all Development-era PRE_BREAKOUT rows; 0 excluded for missing price history).

**Distribution of adverse days present in the trailing 20d window** (`n_adverse_in_window`): 49,307 rows see 0 adverse days in their window, 21,898 see 1, 13,073 see 2, 7,180 see 3, 5,025 see 4, 2,956 see 5, and 1,247 see 6+.

**Distribution of stealth count** (`n_stealth_in_window`, the candidate signal): 93,012 rows have 0 stealth days, 6,646 have 1, 822 have 2, 148 have 3, 48 have 4, 10 have 5. Groups formed from this distribution: **0 / 1 / 2+** (2+ pools 822+148+48+10 = 1,028 rows — a workable exploratory sample, not degenerately thin).

| Stealth group | N | Hit rate (>+10%) | Mean | Median |
|---|---|---|---|---|
| 0 | 93,012 | 11.47% | +0.242% | -0.559% |
| 1 | 6,646 | 12.22% | +0.102% | -0.651% |
| **2+** | **1,028** | **16.34%** | **+1.536%** | **+0.340%** |

**Secondary stats, stealth≥2 vs stealth=0:** hit-rate delta **+4.87pp**. MWU two-sided p=0.000037; MWU one-sided (hi>lo) p=**0.000019**; Cliff's δ=**0.0747** — the largest effect size observed anywhere in this session's factor work (larger than tightness's -0.0387, ROC_10's 0.0123, or `vol_multiplier`'s 0.0229). N=1,028 comfortably clears the ~200–500 Weak-confidence floor.

**Secondary stats, stealth≥1 vs stealth=0 (broader grouping):** hit-rate delta only +1.30pp, MWU one-sided p=0.644 (n.s.), Cliff's δ=-0.0025 (~zero). **The signal is concentrated at stealth≥2, not a smooth dose-response** — 1 stealth day alone shows essentially no lift over 0. This is reported as an explicit limitation (Section 12.5), since the 0/1/2+ grouping was chosen after viewing the distribution, per the task's own instruction to do so — an exploratory, not pre-registered, cut.

### 12.3 Candidate B — "Volume Regime Shift"

**Definitions:**
- `vol_high_180`: today's volume strictly exceeds the max of the prior 180 trading days' volume (≥30 valid prior-window observations required).
- Local tightness: **the existing `base_tightness`/BBW% formula, reused verbatim** — only the ranking window is new. Percentile-ranked over a trailing **20-day** window (`pct_rank_local20`), chosen because it matches `base_tightness`'s own native 20-day close window (a "local" percentile on the same timescale as the tightness measure itself) and gives more stable trailing samples (min 10 of 20 required) than a 10-day span would. Tightest quartile = `pct_rank_local20 ≤ 25`.
- Compound condition = `vol_high_180 AND tight_local_q1`.

`vol_high_180=True`: 1,182/100,686 (1.17%). `pct_rank_local20` non-null: 99,992/100,686 (99.3%). Compound condition True: **236 / 99,992 (0.236%)**.

| Compound | N | Hit rate (>+10%) | Mean | Median |
|---|---|---|---|---|
| False | 99,756 | 11.49% | +0.210% | -0.586% |
| **True** | **236** | **20.34%** | **+1.396%** | **-0.276%** |

**Secondary stats, compound=True vs compound=False:** hit-rate delta +8.85pp, but MWU one-sided p=**0.091** — **not significant even at the uncorrected 0.05 level**. Cliff's δ=0.0502. N=236 clears the Weak-confidence floor but only barely.

**Component breakdown (context, not separate primary tests):**
- `vol_high_180` alone (n=1,169 True): hit rate 18.14% vs 11.43%, Cliff's δ=0.0172, MWU one-sided p=0.156 (n.s.).
- `tight_local_q1` alone (n=33,096 True): hit rate **10.54% vs 12.00% — worse**, Cliff's δ=**-0.0449**, MWU one-sided p=**1.000** (strongly reversed). This independently reproduces, at a 20-day local ranking window, the same reversed tightness effect already closed at 252-day windows in Sections 5/10 — a useful internal consistency check, not a new finding.

**Interpretation:** the compound condition's nominal lift appears driven almost entirely by the volume component; the tightness component is actively a drag on its own (consistent with the closed tightness finding), and combining the two does not clearly outperform `vol_high_180` alone once the sample size is accounted for (n crashes from 1,169 to 236, and significance is lost).

### 12.4 Bridging the mean-vs-rank gap (Step 3)

**Candidate A (stealth≥2 vs stealth=0) — decile breakdown of `fwd_return_10d`:**

| Decile | stealth≥2 | stealth=0 |
|---|---|---|
| 0 (min) | -24.81% | -66.89% |
| 10 | -8.90% | -9.74% |
| 20 | -5.49% | -6.19% |
| 30 | -3.44% | -3.94% |
| 40 | -1.45% | -2.13% |
| 50 (median) | +0.34% | -0.56% |
| 60 | +2.10% | +1.06% |
| 70 | +4.37% | +3.12% |
| 80 | +8.14% | +5.97% |
| 90 | +13.49% | +11.02% |
| 100 (max) | +44.07% | +116.62% |

**This is a broad shift across the whole distribution (30th–90th percentiles all favor stealth≥2), not a mean-vs-rank artifact.** Notably, stealth≥2's own maximum (44.07%) is *lower* than baseline's (116.62%), and stealth≥2 has **zero** rows above +50% vs baseline's 0.18% — the lift is coming from many moderate winners shifting the whole bulk of the distribution upward, not a handful of extreme outliers. This is the opposite pattern from the combined ROC/volume test's outlier-driven mean inflation (Section 11.6) — a genuinely encouraging sign for this candidate.

**Candidate B (compound=True vs compound=False) — decile breakdown:** shows a similar-shaped mid-distribution improvement (50th: -0.28% vs -0.58%; 70th: +5.55% vs +3.08%; 80th: +10.03% vs +5.94%) but compound=True's max (64.83%) is again lower than baseline's (133.80%) — also not outlier-driven — but this candidate did not reach significance (Section 12.3), so the broad-shift shape is descriptively reassuring but does not rescue the underpowered result.

### 12.5 Limitations

1. **Development-era only, by design** — nothing here has been checked against Validation or OOS. No claim of a stable, era-independent effect is made or implied.
2. **Candidate A's 0/1/2+ grouping was chosen after viewing the distribution**, per the task's explicit instruction to do so for exploratory work — this is not a pre-registered cutoff, and the concentration of the effect at exactly "2+" (with "1" showing no lift) should be treated as a hypothesis to test, not an established threshold. A future confirmatory pass should pre-register this specific 0/1/2+ split (or a smoother/continuous version) before touching Validation+OOS, not re-derive it there.
3. **Candidate B is underpowered** (n=236 for the compound condition) and did not reach even uncorrected significance — it is reported in full per task instruction ("do not silently drop a candidate"), not because it is a strong finding.
4. Same overlapping-10-day-return serial-correlation caveat as prior sections applies to all secondary MWU/t-test statistics here.
5. No multiple-comparison (Bonferroni) correction is applied in this section — per task framing, this is exploratory/hypothesis-generating work, not a confirmatory test family under [Decision D-001](Decisions.md). The planned one-shot Validation+OOS confirmation task is where a pre-registered, corrected test should occur.

### 12.6 Recommendation

**Candidate A (stealth≥2) is the stronger candidate** — larger effect size than anything else tested this session, statistically significant even before any correction, and supported by a broad (not outlier-driven) distributional shift. **Recommended as the primary candidate to carry into a single, pre-registered Validation+OOS confirmation task.** Candidate B is directionally interesting but weak and underpowered; it may be worth including in the same follow-up confirmation task for completeness, but should not be treated as independently promising on this evidence alone.

### 12.7 Reproducibility

Script: `prebreakout_v2_phase5_exploratory_footprints.py` (project root). Read-only against `pre_breakout_v2_staging_full`, `index_prices`, `prices_adjusted`, `stock_signals` — every query hard-filtered to `date <= '2019-12-31'`, with a runtime leakage-guard assertion on every loaded frame. No production writes. Results saved to `prebreakout_v2_phase5_results.csv`.

---

## CONFIRMATORY RESULT — Stealth Relative Strength ≥2, Combined Validation+OOS (2026-07-10)

**FINAL VERDICT: DEAD — reversed on the confirmatory distributional tests.**

**One-shot, locked run, per explicit PI sign-off.** No parameter was adjusted at any point: adverse-day threshold (-1.5%), trailing window (20 trading days), liquidity gate (existing `avg_vol_10d` convention), and comparison groups (stealth≥2 vs stealth=0 only, no stealth=1 group, no new grouping) are copied verbatim from Section 12.2. Population: `pre_breakout_v2_staging_full` filtered to **Validation (2020-01-01→2022-12-31) + OOS (2023-01-01 onward) combined into one population**, per explicit PI instruction — this combined figure is the primary verdict; era-by-era is reported separately below, clearly labeled secondary.

### 12.8 Primary result — combined Validation+OOS

Population: 180,195 rows, 238 symbols, date range 2020-01-01 → 2026-07-07. Adverse days identified (full index history, -1.5% threshold): 406. Stealth-count distribution: 0→162,866; 1→15,298; 2→1,836; 3→162; 4→29; 5→4.

| Group | N | Hit rate (>+10%) | Mean | Median |
|---|---|---|---|---|
| stealth=0 | 161,843 | 13.52% | +0.978% | -0.219% |
| **stealth≥2** | **2,024** | **17.09%** | **+1.305%** | **-0.588%** |

**Primary metric (hit rate):** delta **+3.58pp** (vs Development's +4.87pp — same direction, smaller).

**Secondary/confirmatory stats:** MWU two-sided p=0.000679; **MWU one-sided (hi>lo, hypothesized direction) p=0.999660** (i.e., significant in the *opposite* direction); **Cliff's δ = -0.0439** (Development: +0.0747 — sign has flipped).

**A direct significance test on the hit-rate proportion itself** (two-proportion z-test, not part of the original locked stat suite but computed for honesty given the divergence below): stealth≥2 346/2,024 vs stealth=0 21,879/161,843 → z=4.670, one-sided p=0.000002 — **the raw hit-rate lift is itself statistically significant**, comparable to Development's own proportion-test significance (z=4.868, p=0.000001). This is reported transparently, but per the task's explicit instruction, the pre-specified secondary/confirmatory checks (Cliff's δ, MWU on the full distribution) are what determine confirmation — and those reverse.

### 12.9 Distribution breakdown — why the hit rate and Cliff's delta disagree

| Decile | stealth≥2 | stealth=0 |
|---|---|---|
| 0 (min) | -47.77% | -90.56% |
| 10 | -15.35% | -9.35% |
| 20 | -9.07% | -5.91% |
| 30 | -5.40% | -3.68% |
| 40 | -2.95% | -1.86% |
| 50 (median) | **-0.59%** | **-0.22%** |
| 60 | +1.47% | +1.50% |
| 70 | +4.22% | +3.67% |
| 80 | +8.04% | +6.85% |
| 90 | +19.04% | +12.47% |
| 100 (max) | +221.26% | +509.69% |

**This is the opposite shape from Development.** In Development (Section 12.4), stealth≥2 was better across nearly the whole distribution (30th–90th percentile) with a *smaller* max than baseline — a genuine broad-based lift. Here, stealth≥2 is **worse than baseline from the 10th through 50th percentile** (median -0.59% vs -0.22%), roughly even at the 60th, and only pulls ahead from the 70th percentile up — while again showing a smaller max (221% vs 510%). Right-tail composition confirms stealth≥2 does cross every tail threshold more often (>10%: 17.09% vs 13.52%; >20%: 9.44% vs 4.30%; >30%: 5.39% vs 1.71%; >50%: 2.12% vs 0.41%) — but this elevated tail-crossing now coexists with a **worse median/bulk**, not a broadly better one. That bulk-distribution deterioration is what drags Cliff's delta and the whole-distribution MWU test into reversal, even though the specific >10% crossing rate is nominally higher.

### 12.10 Secondary, not the primary verdict — era-by-era breakdown

| Era | N (stealth≥2 / stealth=0) | Hit rate (≥2 / 0) | Hit-rate Δ | Cliff's δ | MWU 1-sided p |
|---|---|---|---|---|---|
| Validation (2020-2022) | 798 / 68,617 | 22.56% / 11.84% | **+10.71pp** | **+0.1007** | **0.000000** |
| OOS (2023+) | 1,226 / 93,226 | 13.54% / 14.75% | **-1.21pp** | **-0.1450** | **1.000000** |

**Validation alone independently confirms and even amplifies the Development finding** (Cliff's δ=0.1007, larger than Development's 0.0747, highly significant, correct direction). **OOS alone completely reverses it** (δ=-0.1450, significant in the wrong direction). The combined primary figure (12.8) is dragged to net reversal because OOS's larger, more negative effect outweighs Validation's positive one in the pooled test. This is reported as secondary context only, per task instruction — the primary verdict is the combined figure, precisely to prevent selectively citing the better-looking era (Validation) as if it were the whole story.

### 12.11 Direct comparison table

| Metric | Development (Section 12.2) | Validation+OOS combined (this run) |
|---|---|---|
| N (stealth≥2) | 1,028 | 2,024 |
| Hit-rate lift | +4.87pp | +3.58pp |
| Cliff's δ | 0.0747 | **-0.0439** |
| MWU one-sided p (hi>lo) | 0.000019 | **0.999660** |

**Data-quality note (checked, not swept aside):** the script's price-return computation triggered a divide-by-zero/invalid-value runtime warning during execution. Traced to 600 zero-close rows in `prices_adjusted`, all belonging to a single symbol (SGPL), all dated 2005 (pre-listing placeholder data). None fall within or near the confirmatory window (2020+) — confirmed via direct query (0 rows with `date >= '2019-12-01'`). **No impact on this result.**

### 12.12 Final classification

**DEAD.** Per the task's verdict criteria (CONFIRMED / WEAKENED / DEAD) and its explicit instruction not to soften a negative result: the pre-specified secondary/confirmatory tests (Cliff's delta, MWU one-sided) — the checks designated to establish whether an effect is statistically real — reverse sign in the combined Validation+OOS population. The specific claim tested and classified as the Development-era finding (Section 12.2/12.4) was a **broad, non-outlier-driven distributional improvement**; that specific shape does not reproduce here — the confirmatory data shows a worse median/bulk alongside an elevated tail-crossing rate, a materially different and more mixed pattern than what was confirmed against. The raw hit-rate proportion difference remains nominally significant on its own (Section 12.8), but this does not override the reversal on the tests the task specified as confirmatory. **Per the task's locked-rule discipline, this candidate is not carried forward to any live filter or further tuning.**

### 12.13 Reproducibility

Script: `prebreakout_v2_phase5_confirmatory.py` (project root). Read-only against `pre_breakout_v2_staging_full`, `index_prices`, `prices_adjusted`, `stock_signals`. Population: `date >= '2020-01-01'` (Validation+OOS combined), no parameter tuning, single run. Results saved to `prebreakout_v2_phase5_confirmatory_results.csv`.

---

## Related — Market Structure Diagnostic (2026-07-10)

The recurring pattern of Phase 4c (ROC/volume velocity) and Phase 5 (Stealth Relative Strength) both holding through Development+Validation and reversing specifically in OOS (2023+) motivated a project-wide, diagnostic-only investigation into what changed in PSX market structure around 2023. Filed as a **separate standalone document**, not a section here, since it is not specific to the PRE_BREAKOUT construct: [`Market_Structure_Diagnostic_2015-2026.md`](Market_Structure_Diagnostic_2015-2026.md). Headline finding: no clear break in cross-sectional market microstructure (correlation, dispersion, liquidity concentration, sector concentration all stable/continuous), but a clear, externally-corroborated break in KSE-100's own trend regime — a historic, sustained bull market beginning mid-2023, following a January 2023 currency devaluation and IMF-program-driven macro stabilization, plus a dated 2024 circuit-breaker price-band widening. Diagnostic only — does not establish causality with the Phase 4c/Phase 5 reversals.

---

## 13. Phase 6 — EXPLORATORY, NO HELD-OUT DATA REMAINS, NOT CONFIRMATORY (2026-07-10)

**⚠ EXPLORATORY ONLY.** Both clean eras — Development (used for exploration, Section 12.1–12.7) and Validation+OOS (used for confirmation, Section 12.8–12.13 and Section 11) — have already been spent this session on these exact constructs. **No fresh held-out data remains.** This section re-slices the full 2015-2026 dataset by a regime filter to investigate *why* two constructs reversed in OOS (following directly from the Market Structure Diagnostic's finding of a historic 2023+ bull market). **Nothing in this section is a confirmed, tradeable edge** — it is directional/diagnostic evidence only, using data every construct here has already been tested against at least once (Stealth RS twice: Development exploratory + Validation+OOS confirmatory).

### 13.1 Step 1 — Defining RUNAWAY_BULL_THRESHOLD (derived from 2015-2022 only, applied blindly forward)

KSE-100 trailing-252-trading-day return computed for the full history; distribution taken from the **2015-2022 (Development+Validation) portion only** (N=1,985 valid days):

| Percentile | Trailing-252d return |
|---|---|
| 50th | +4.00% |
| 75th | +17.43% |
| 90th | **+36.74%** |
| 95th | +44.06% |

**RUNAWAY_BULL_THRESHOLD = 36.7447%** (90th percentile of 2015-2022 trailing-252d return) — fixed once, not adjusted after Step 2. A day is "runaway bull" if `regime == TRENDING_UP` AND `trailing_252d_return > 36.7447%`.

**Year-by-year runaway-bull day %:**

| Year | % runaway-bull days |
|---|---|
| 2015 | 0.0% |
| 2016 | 7.3% |
| 2017 | 23.3% |
| 2018 | 0.0% |
| 2019 | 0.0% |
| 2020 | 3.6% |
| 2021 | 12.6% |
| 2022 | 0.0% |
| 2023 | 8.1% |
| **2024** | **74.0%** |
| **2025** | **70.8%** |
| 2026* | 48.0% |

*2026 partial year. 2015-2022 average: 5.8%. 2023-2025 average (excl. partial 2026): **51.0%**.

**Sanity check: YES — 2023-2025 sharply concentrates runaway-bull days** (51.0% vs 5.8%, ~9x), without the filter having been built to force this outcome (it was derived purely from 2015-2022's own percentile + the existing regime classifier, then applied blindly). This is fully consistent with, and independently corroborates, the Market Structure Diagnostic's finding of a historic 2023+ bull market.

### 13.2 Step 2 — Re-testing the three dead/mixed constructs, split by runaway-bull status (full 2015-2026)

Primary metric for this re-test: right-tail hit rate (per task instruction, overriding each construct's original primary metric for consistency across this investigation). Cliff's delta and MWU reported as secondary.

| Cell | N (hi/lo) | Hit rate (hi/lo) | Hit-rate Δ | Cliff's δ | MWU 1-sided p |
|---|---|---|---|---|---|
| **(a) Stealth RS≥2 — RUNAWAY BULL** | 512 / 63,012 | 10.94% / 14.49% | **-3.55pp** | **-0.2112** | 1.000000 |
| **(a) Stealth RS≥2 — NON-runaway-bull** | 2,540 / 191,843 | 18.03% / 12.20% | **+5.83pp** | **+0.0419** | **0.000140** |
| (b) Tightness Q1(tight) vs Q4(loose) — RUNAWAY BULL | 16,993 / 16,760 | 12.68% / 16.86% | -4.17pp | +0.0743 | 0.000000 |
| (b) Tightness Q1(tight) vs Q4(loose) — NON-runaway-bull | 52,179 / 51,395 | 9.67% / 16.47% | -6.80pp | -0.0778 | 1.000000 |
| (c) ROC_10 Q4(fast) vs Q1(slow) — RUNAWAY BULL | 16,936 / 16,937 | 18.59% / 12.03% | +6.55pp | -0.0119 | 0.971353 |
| (c) ROC_10 Q4(fast) vs Q1(slow) — NON-runaway-bull | 52,978 / 52,978 | 15.74% / 14.87% | +0.87pp | +0.0053 | 0.068349 |

**N-floor check:** all 6 cells clear the ~200–500 Weak-confidence floor. The thinnest cell — Stealth RS≥2 inside runaway-bull, n=512 — clears it but is noticeably thinner than its counterpart cells (2,540–63,012); flagged as a relatively thin sample even though it does not trigger the formal floor.

### 13.3 Construct-by-construct read

**(a) Stealth RS — the one clean, internally-consistent pattern.** The original Development-era effect (Section 12.2: hit-rate lift +4.87pp, Cliff's δ=+0.0747) **reappears in the non-runaway-bull subset** (+5.83pp, δ=+0.0419, p=0.000140 — same direction, statistically significant, comparable-to-slightly-smaller magnitude) while showing a **strong, unambiguous reversal inside the runaway-bull subset** (-3.55pp, δ=**-0.2112**, p=1.000000). This is the pattern the task was looking for, and it appears cleanly for this one construct.

**(b) Tightness — does NOT recover; if anything the closed reversal is more robust outside runaway-bull.** Non-runaway-bull shows the closed/reversed finding (loose beats tight) **more strongly** than the original standalone result (δ=-0.0778 here vs. -0.0387 in Section 5's pooled result) — the opposite of "recovery." Inside runaway-bull, the picture is genuinely confusing rather than a clean flip-back-to-confirmed: hit rate favors loose (-4.17pp for tight) while the rank-based test favors tight (δ=+0.0743, MWU p=0.000000 in the tight>loose direction) — a hit-rate-vs-rank divergence within the same cell, not a coherent reversal.

**(c) ROC_10 — no clear recovery, and another internal hit-rate-vs-rrank divergence.** Non-runaway-bull shows a small, same-direction, borderline-non-significant effect (+0.87pp, δ=+0.0053, p=0.068) — roughly consistent with, not stronger than, Section 11's already-mixed pooled finding (δ=+0.0123). Inside runaway-bull, hit rate shows an attractive-looking +6.55pp lift, but Cliff's delta is slightly *negative* (-0.0119) and MWU is essentially reversed (p=0.971) — the same mean/hit-rate-vs-rank divergence pattern documented repeatedly elsewhere in this project (Sections 5.2/10.3/11.6/12.9), here appearing inside the runaway-bull regime rather than outside it.

### 13.4 Honest synthesis (Step 3)

**Mixed — regime-conditioning recovers exactly ONE of the three constructs, not none, and not all three.** Only **Stealth RS** shows the clean pattern of "original effect intact outside runaway-bull conditions, reversed specifically inside them." **Tightness and ROC_10 do not show this pattern** — tightness's closed reversal is if anything more robust outside runaway-bull (not rescued), and both tightness (inside runaway-bull) and ROC_10 (inside runaway-bull) show internally inconsistent hit-rate-vs-rank divergences rather than a coherent regime-dependent story.

**This does not support a general claim that "the 2023+ bull market explains all three OOS reversals."** It is, at best, a plausible, exploratory, non-independent explanation specific to Stealth RS — and even that result must not be treated as a rescued or tradeable edge, since it reuses data (both Development and Validation+OOS) already spent on this exact construct this session. A genuinely independent confirmatory test of "Stealth RS, conditional on non-runaway-bull," would require fresh data this project does not currently have.

### 13.5 Limitations

1. **No held-out data remains.** This is a re-slicing of already-tested populations by a new conditioning variable, not independent evidence. Nothing here should inform a live filter or trading decision.
2. The runaway-bull filter is a single, specific operationalization (regime=TRENDING_UP AND trailing-252d return > 2015-2022's 90th percentile) — an untested alternative definition might behave differently; this was not explored, per the task's constraint against testing additional constructs/definitions.
3. The recurring hit-rate-vs-rank divergence (tightness and ROC_10, inside runaway-bull) is observed and reported, not newly explained — consistent with the pattern already documented in Sections 5.2/10.3/11.6/12.9.
4. Same benign zero-close data artifact (SGPL, 2005, previously traced and ruled out in the Phase 5 confirmatory run) triggered an identical runtime warning here — confirmed to have no bearing on any 2015+ population row, not re-verified in full here since it was already traced to source.

### 13.6 Reproducibility

Script: `prebreakout_v2_phase6_regime_conditional.py` (project root). Read-only against `pre_breakout_v2_staging_full`, `index_prices`, `prices_adjusted`, `stock_signals`, `market_regime`. RUNAWAY_BULL_THRESHOLD fixed once from 2015-2022 data, not adjusted after seeing results. Results saved to `prebreakout_v2_phase6_results.csv` and `prebreakout_v2_phase6_runaway_bull_by_year.csv`.
