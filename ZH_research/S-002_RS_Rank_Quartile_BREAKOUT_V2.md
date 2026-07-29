# S-002 — Re-validation: RS-Rank Quartile Split Within BREAKOUT

**Status:** CLOSED — 🔴 **DEAD** (not confirmed, not weakened — the cited baseline finding could not be located anywhere in this repository or its git history, and does not replicate on the corrected population)
**Filed:** 2026-07-08
**Researcher:** Quantitative Analyst
**Reviewer:** Independent Quantitative Reviewer (PI)
**Population:** `stock_signals_breakout_v2_staging_full` WHERE `breakout_event = 1` (BREAKOUT V2, corrected rolling-liquidity population)
**Database:** psx_data.db

**See also:** [S-004_RS_Rank_LiveSystem_Reconciliation.md](S-004_RS_Rank_LiveSystem_Reconciliation.md) — clarifies that `sec_global_rank` (used in the separate `sec_global_rank ≤ 8` gate) is a different, sector-level field from `rs_score_20`/`sector_rs_rank` tested here, and is unaffected by this verdict.

---

## 1. What this document is

A re-run of a previously-cited finding — RS-rank quartiles within the BREAKOUT population, Q1 fwd_return_10d ≈ -0.20%, Q4 ≈ +2.07% — against the corrected BREAKOUT V2 population (`stock_signals_breakout_v2_staging_full`, `breakout_event=1`) instead of whatever produced the original figures. Distinct from `H-002` (RS Score 20d Quintile for BREAKOUT, `ZH_research/Hypotheses.md`), which used the old bos_flag=1 population and quintiles (not quartiles) — H-002 is referenced below only for methodology continuity (statistical test choice), not as the source of the cited baseline. Also distinct from, and does not touch, RS_LEADER_MARKET/RS_LEADER_SECTOR (separate, standalone, correctly-closed setup types).

---

## 2. Provenance check on the cited baseline (-0.20% / +2.07%)

Before re-running anything, an exhaustive search was made for the original source of these two figures:
- All `.md` files in `ZH_research/` (Hypotheses.md, Evidence_Register.md, Research_Log.md, Change_Log.md, Factor_Catalog.md, S-001, and others)
- All `.py` files in the project root, and all `.txt`/`.md` result files in the project root
- Full git history (`git log --all -S "quartile"`, `-S "qcut"`, `-S "2.07"`)

**Result: no match.** The closest documented material:
- `H-002` (Hypotheses.md) — RS Score 20d **quintiles** (not quartiles) on the old bos_flag=1 population, Mann-Whitney U test, reports Cliff's delta and win rates, **not** raw mean-return percentages. Result: Q1 win% 52.87% vs Q4 win% 47.94% — **Q1 outperformed Q4**, the opposite sign pattern from the cited -0.20%/+2.07%. Terminated, wrong direction.
- `backtest_rs_score_result.txt` (fixed-threshold RS buckets, not quartiles, additional TRENDING_UP+BBW filters applied) — closest numeric neighbors found: -0.28% / +2.42%. Not an exact match and not the same population or method.
- `git log --all -S "quartile"` / `-S "qcut"`: **zero commits, ever.**

**Conclusion: the -0.20%/+2.07% figures cited as "a prior finding" cannot be independently verified as ever having existed in this codebase's documented research.** This re-validation proceeds anyway per the task's explicit, self-contained methodology (Section 3 below), but the "before" side of the before/after comparison in Section 6 is a cited claim, not a verified baseline.

---

## 3. Methodology

### 3.1 Population

```sql
SELECT symbol, date, close, active_resistance
FROM stock_signals_breakout_v2_staging_full
WHERE breakout_event = 1
```

**N = 927** rows, 135 distinct symbols, date range 2015-01-01 → 2026-07-07.

**Note on population size vs. the task's ~3,000 expectation:** 927 is well below the "roughly ~3,000" figure anticipated going into this task. That expectation traces to the OLD, uncorrected 243-symbol table (`stock_signals_breakout_v2_staging_DEPRECATED_243sym`), which has **3,035** `breakout_event=1` rows — this matches the ~3,000 figure closely and is almost certainly its actual source, not the corrected population. The drop from 3,035 → 927 (69% reduction) has two causes: (1) the rolling avg_vol_10d≥200,000 liquidity gate excludes many event-dates that the old static 243-symbol list counted unconditionally, and (2) `stock_signals` (and therefore the liquidity gate, and therefore eligibility) has essentially no coverage before ~2015 for most symbols, left-truncating the corrected population's earliest event to 2015-01-01 even though `prices_adjusted` goes back to 2005. Both effects are expected consequences of the BREAKOUT V2 rolling-liquidity fix, not new bugs introduced here.

### 3.2 Join to `stock_signals`

`rs_score_20` and `sector_rs_rank` joined on `(symbol, date)`.

| Field | Matched (non-null) | Match rate |
|---|---|---|
| `rs_score_20` | 927 / 927 | 100.0% |
| `sector_rs_rank` | 927 / 927 | 100.0% |

No unmatched rows — every `breakout_event=1` row has a same-date `stock_signals` row with both fields populated.

### 3.3 Forward return

`fwd_return_10d` does not exist on `stock_signals_breakout_v2_staging_full` and was computed fresh, reusing `compute_forward_returns.py`'s exact existing formula (not a new formula): `(close at entry+10 trading days − close at entry) / close at entry × 100`, sourced from `prices_adjusted`.

| | N |
|---|---|
| Valid `fwd_return_10d` | 915 / 927 (98.7%) |
| Window not yet closed (entry+10 trading days beyond available price history — recent events) | 12 |
| No matching `prices_adjusted` row at entry date | 0 |

### 3.4 Quartile construction

Equal-count quartiles via `pandas.qcut(..., 4)`, per task instruction — not fixed score thresholds. `rs_score_20` (continuous) split cleanly into 4 groups. `sector_rs_rank` (integer, heavily clustered at low values — most sectors' top ranks 1–5 dominate the eligible population) **collapsed to 3 groups** under equal-count binning because `qcut` cannot create duplicate-valued bin edges; flagged rather than forcing an artificial 4th split on a coarse variable.

### 3.5 Significance test

The original test methodology for the cited -0.20%/+2.07% figures is unknown (Section 2). **Used Mann-Whitney U (one-sided, high-quartile > low-quartile) as the primary test**, matching the closest documented precedent in this project (`H-002`'s pre-registered-direction MWU on an RS-rank quartile/quintile split within BREAKOUT), plus Welch's t-test and Cliff's delta as secondary/supplementary statistics, also matching `H-002`'s reporting style. This is a methodology-continuity choice, not a confirmed match to whatever originally produced -0.20%/+2.07%.

---

## 4. Results — `rs_score_20`

Quartile boundaries: [-26.72, 4.14, 9.98, 20.01, 369.51]

| Quartile | N | Mean fwd10 | Median fwd10 | Std fwd10 | rs_score_20 range |
|---|---|---|---|---|---|
| Q1 (weakest RS) | 229 | **+3.02%** | +1.59% | 8.17 | [-26.72, 4.13] |
| Q2 | 229 | +1.29% | +0.54% | 10.46 | [4.14, 9.98] |
| Q3 | 228 | +0.56% | -0.02% | 15.05 | [9.99, 19.88] |
| Q4 (strongest RS) | 229 | +4.50% | +1.84% | 24.88 | [20.15, 369.51] |

**Q1 vs Q4 significance:**

| Test | Result |
|---|---|
| Mann-Whitney U, two-sided | p = 0.7140 |
| Mann-Whitney U, one-sided (Q4 > Q1) | p = 0.6432 |
| Welch's t-test, two-sided | t = 0.860, p = 0.3908 |
| Cliff's delta (Q4 vs Q1) | -0.0198 (negligible) |

**Pattern:** non-monotonic (Q1 > Q2 > Q3, then Q4 highest) — not the smooth increasing gradient the cited figures imply. **Q1 mean is positive (+3.02%)**, not negative as cited (-0.20%). No statistically significant Q1-vs-Q4 difference at any conventional threshold; Cliff's delta is near zero and slightly negative (Q1 marginally rank-favored over Q4, if anything).

---

## 5. Results — `sector_rs_rank`

Quartile boundaries: [1.0, 3.0, 5.0, 18.0] — **3 groups, not 4** (see Section 3.4). Lower rank = stronger sector.

| Group | N | Mean fwd10 | Median fwd10 | Std fwd10 | sector_rs_rank range |
|---|---|---|---|---|---|
| Q1 (strongest sector) | 567 | +2.55% | +0.79% | 17.59 | [1, 3] |
| Q2 | 154 | +2.24% | +1.12% | 16.76 | [4, 5] |
| Q3 (weakest sector) | 194 | +1.82% | +0.41% | 9.29 | [6, 18] |

**Q1 vs Q3 (highest-numbered available group) significance:**

| Test | Result |
|---|---|
| Mann-Whitney U, two-sided | p = 0.5810 |
| Mann-Whitney U, one-sided (Q3 > Q1) | p = 0.7096 |
| Welch's t-test, two-sided | t = -0.740, p = 0.4595 |
| Cliff's delta (Q3 vs Q1) | -0.0265 (negligible) |

**Pattern:** monotonically decreasing as sector rank worsens (strongest-sector group has the highest mean return, weakest has the lowest) — directionally sensible on its own terms, but not statistically significant, and not matching the cited magnitudes.

---

## 6. Direct comparison against the cited -0.20% / +2.07%

| | Cited (unverified source) | Re-validated: `rs_score_20` | Re-validated: `sector_rs_rank` |
|---|---|---|---|
| Low-quartile mean | -0.20% | **+3.02%** | +2.55% |
| High-quartile mean | +2.07% | +4.50% | +1.82% |
| Direction (low < high) | Yes (implied) | No — non-monotonic, Q1 exceeds Q2/Q3 | No — monotonically decreasing, opposite direction |
| Statistically significant Q1-vs-top? | Unknown (no source) | No (MWU p=0.64–0.71) | No (MWU p=0.58–0.71) |

**The low quartile does not replicate as negative in either variable** — it is positive in both, and in `rs_score_20`'s case (the more directly matching variable to the cited framing) it is actually the *second-highest*-returning quartile, not the lowest. Neither split clears even nominal significance (p<0.05), let alone anything that would survive a multiple-comparison correction across the two variables and the quartile-selection procedure itself.

---

## 7. Classification

**DEAD.** Two independent reasons, either one sufficient on its own:

1. **The cited baseline (-0.20%/+2.07%) has no verifiable source** in this repository's code, documentation, or git history (Section 2) — it cannot be confirmed as a real, reproducible prior finding rather than a misremembered or external figure.
2. **On the corrected, event-only, rolling-liquidity-gated BREAKOUT V2 population, neither `rs_score_20` nor `sector_rs_rank` shows a significant or even directionally-matching low-quartile-vs-high-quartile split** (all p-values ≥ 0.39, all Cliff's deltas < 0.03 in magnitude, and the low quartile is positive, not negative, in both variables).

No further replication (era splits, regime stratification, IS/OOS) is warranted — per the project's proportional-burden-of-proof principle, a factor this weak on its first clean test does not merit the additional investigative cost that would be appropriate for a stronger or ambiguous result. If PI wants to keep investigating RS-rank as a BREAKOUT quality factor, it should be re-registered as a new hypothesis with its own pre-specified methodology, not treated as a continuation of the cited (unlocated) finding.

---

## 8. Limitations

1. **N=915/927 is modest** relative to the ~3,000 originally expected — a consequence of the corrected population being genuinely smaller (Section 3.1), not a sampling choice made here.
2. **2015-2026 only** — the corrected population has no visibility into 2005-2014 events for symbols whose `stock_signals` coverage starts later, since the liquidity gate has no basis to judge eligibility before that. Any RS-rank effect specific to that earlier era (if one exists) is invisible to this test.
3. **`sector_rs_rank` quartiles collapsed to 3 groups** — the variable's low cardinality in this population (dominated by top-3-5 sector ranks) prevented a clean 4-way equal-count split.
4. **No multiple-comparison correction applied** across testing two variables — not needed given neither clears even an uncorrected p<0.05, but noted for completeness (see S-001's Task 1 for the precedent on why this matters when a result is closer to the margin).
5. **This is a single-pass re-validation, not an IS/OOS study** — no Development/Validation/OOS era split was performed, consistent with the task's scope and the "DEAD on first test" conclusion above not warranting one.

---

## 9. Reproducibility

Script: `breakout_v2_rs_quartile_revalidation.py` (project root). Read-only — no production writes, no changes to `stock_signals_breakout_v2_staging_full`, `pre_breakout_v2_staging`, RS_LEADER_MARKET, or RS_LEADER_SECTOR.
