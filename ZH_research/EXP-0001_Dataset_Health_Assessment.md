# EXP-0001 — Dataset Health Assessment
## PSX Quantitative Research Platform

---

> ### ⚑ IMMUTABLE RESEARCH PHILOSOPHY
> The purpose of this experiment is to reduce uncertainty — not to confirm a trading belief.
> Negative results are equally valuable. If this experiment concludes the dataset is flawed,
> that is a successful experiment.

---

## ─── BLOCK 1: IDENTITY ────────────────────────────────────────

| Field | Value |
|---|---|
| **Experiment ID** | EXP-0001 |
| **Title** | Dataset Health Assessment — Primary Research Tables |
| **Phase** | 0.5 — Dataset Validation |
| **Status** | `CLOSED` |
| **Opened** | 2026-07-01 |
| **Closed** | 2026-07-01 |
| **Experiment Type** | Descriptive |
| **Evidence Maturity** | Discovery → **Observed** ◉ → Replicated → Validated → Production Ready / Terminated |

---

## ─── BLOCK 2: PRE-REGISTRATION `[PRE-REG]` ───────────────────

### 2.1 Research Question

```
What is the structural integrity of the PSX research database — specifically setup_log,
stock_signals, market_regime, and sector_signals — across completeness, coverage,
temporal stability, and internal consistency?
```

### 2.2 Hypotheses

| | Statement |
|---|---|
| **Null (H₀)** | The dataset contains no structural anomalies that would materially bias factor research |
| **Alternative (H₁)** | The dataset contains at least one structural anomaly significant enough to require documentation, correction, or caveat before factor experiments begin |
| **Expected Direction** | H₁ expected — no real-world dataset of this complexity is anomaly-free |

### 2.3 Primary Outcome Variable

| Field | Value |
|---|---|
| **Outcome Variable** | Anomaly Severity Rating: None / Minor / Moderate / Severe |
| **Metric** | Count and severity of structural anomalies discovered across seven assessment dimensions |

### 2.4 Assessment Dimensions

| Dimension | What Was Measured |
|---|---|
| D1 | Row counts, date ranges, table sizes |
| D2 | NULL rates per column in setup_log |
| D3 | Outcome variable completeness |
| D4 | Setup type distribution over time |
| D5 | Symbol and sector coverage |
| D6 | Outcome label internal consistency |
| D7 | Cross-table join integrity |
| D8 | Duplicate detection |

### 2.5 Pre-Registration Sign-Off

| | |
|---|---|
| **Registered by** | Research Platform |
| **Date registered** | 2026-07-01 |
| **Data examined before registration?** | No |

---

## ─── BLOCK 3: DATA QUALITY CHECK ─────────────────────────────

Self-referential for EXP-0001. The assessment IS the quality check. All tables queried directly from `psx_data.db` via Python/SQLite. No transformations applied. Results are raw counts and rates.

---

## ─── BLOCK 4: RESULTS ─────────────────────────────────────────

### D1 — Row Counts and Date Ranges

| Table | Row Count | Date Min | Date Max | Span |
|---|---|---|---|---|
| `setup_log` | **205,891** | 2015-01-01 | 2026-07-01 | 11.5 years |
| `stock_signals` | **680,340** | 2005-02-16 | 2026-07-01 | 21 years |
| `market_regime` | **5,313** | 2005-01-03 | 2026-07-01 | 21 years |
| `sector_signals` | **63,397** | 2015-01-01 | 2026-07-01 | 11.5 years |
| `prices_adjusted` | **1,819,802** | 2005-01-03 | 2026-07-01 | 21 years |

**Critical finding — date range discrepancy:** The research architecture assumed setup_log begins in 2020. The actual start date is **2015-01-01** — five additional years of data exist and were never accounted for in any prior planning document. `stock_signals` and `market_regime` extend to **2005**, 10 years earlier still.

---

### D2 — NULL Rates in `setup_log` (Confirmed Column List)

**Confirmed columns in setup_log: 20**
`id, symbol, setup_date, setup_type, regime, rs_rank, sector_rs_rank, rank_change, rs_score_20, base_tightness, vol_contraction, pivot_distance_pct, bos_flag, sector, fwd_return_5d, fwd_return_10d, fwd_return_20d, outcome_label, outcome_tagged_date, created_at`

| Column | NULL Count | NULL % | Status |
|---|---|---|---|
| `symbol` | 0 | 0.0% | ✅ Clean |
| `setup_date` | 0 | 0.0% | ✅ Clean |
| `setup_type` | 0 | 0.0% | ✅ Clean |
| `regime` | 0 | 0.0% | ✅ Clean — denormalized from market_regime |
| `rs_rank` | 0 | 0.0% | ✅ Clean |
| `sector_rs_rank` | 0 | 0.0% | ✅ Clean |
| `rs_score_20` | 0 | 0.0% | ✅ Clean |
| `sector` | 0 | 0.0% | ✅ Clean |
| `rank_change` | 92 | 0.0% | ✅ Negligible |
| `base_tightness` | 271 | 0.1% | ✅ Negligible |
| `vol_contraction` | 271 | 0.1% | ✅ Negligible — same 271 rows as base_tightness |
| `fwd_return_5d` | 1,964 | 1.0% | ✅ Expected (recent rows, window not closed) |
| `fwd_return_10d` | 1,964 | 1.0% | ✅ Expected |
| `fwd_return_20d` | 1,964 | 1.0% | ✅ Expected — all three horizons NULL together |
| `outcome_label` | 1,648 | 0.8% | ⚠️ Slightly fewer NULL than forward returns — investigate |
| `pivot_distance_pct` | 28,730 | **14.0%** | ⚠️ Elevated — requires investigation |
| `bos_flag` | 28,730 | **14.0%** | ⚠️ Elevated — same 28,730 rows as pivot_distance_pct |

**Finding — Elevated NULLs in pivot_distance_pct and bos_flag:** 28,730 rows (14.0%) have NULL in both columns simultaneously. These are the same rows. Since `pivot_distance_pct` requires a confirmed pivot high (10-bar left/right window), NULL means no confirmed pivot existed for that symbol on that date. These are not data errors — they are valid structural NULLs. However, they create a material asymmetry: **all 49,323 BREAKOUT rows must have bos_flag = 1 and non-NULL pivot_distance_pct, but 28,730 rows across other setup types do not.** The NULL rows are concentrated in RS_LEADER_MARKET and RS_LEADER_SECTOR (which do not require a pivot for detection).

**Finding — outcome_label NULL count (1,648) is less than fwd_return NULL count (1,964):** 316 rows have a NULL `fwd_return_10d` but a non-NULL `outcome_label`. This suggests some rows were labelled before the forward return was computed, or the labelling process and the return computation ran at different times and produced a small mismatch. Requires investigation in EXP-0002.

---

### D3 — Outcome Variable Completeness

| Outcome Variable | Populated | NULL | NULL % |
|---|---|---|---|
| `fwd_return_5d` | 203,927 | 1,964 | 1.0% |
| `fwd_return_10d` | 203,927 | 1,964 | 1.0% |
| `fwd_return_20d` | 203,927 | 1,964 | 1.0% |

All three forward return horizons have **identical NULL counts** — 1,964 rows. This is structurally correct: when the window closes, all three are computed together. There is no partial population issue.

**Finding — 1.0% NULL forward returns:** These are expected to be the most recent ~20 trading days of signals (window not yet closed as of 2026-07-01). For a dataset spanning to 2026-07-01, 1,964 rows at approximately 20 trading days × ~100 daily signals is plausible. Exact verification deferred to EXP-0002 (Outcome Validation).

---

### D3b — Outcome Label Distribution

| Label | Count | % of Total |
|---|---|---|
| `LOSER` | 108,030 | 52.5% |
| `WINNER` | 94,268 | 45.8% |
| `BREAKEVEN` | 1,945 | 0.9% |
| `NULL` | 1,648 | 0.8% |

**Raw base rate (all setup types combined, excluding NULL):** Win rate = 94,268 / (94,268 + 108,030) = **46.6%**

The evidence supports that the raw base rate across all setup types is below 50%. This is the first quantitative finding of the research program. It establishes that generating signals is not sufficient — the majority of signals in the raw population lose. Conviction Engine development is necessary to identify the subset with above-50% win rates.

---

### D4 — Setup Type Distribution

| Setup Type | Row Count | % of Total | Date Range |
|---|---|---|---|
| `RS_LEADER_SECTOR` | 94,364 | 45.8% | 2015-01-01 to 2026-07-01 |
| `RS_LEADER_MARKET` | 56,900 | 27.6% | 2015-01-01 to 2026-07-01 |
| `BREAKOUT` | 49,323 | 23.9% | 2015-01-01 to 2026-07-01 |
| `PRE_BREAKOUT` | 5,304 | 2.6% | 2015-01-01 to 2026-06-30 |

**Critical finding — PRE_BREAKOUT is severely underrepresented:** 5,304 rows is 2.6% of the population. With a strict detection condition (`pivot_distance_pct BETWEEN 0 AND 3 AND base_tightness < 8`), this setup type generates approximately 442 signals per year on average. Splitting that into factor quintiles yields ~88 rows per quintile — below the Moderate confidence threshold of 50 in most cells. **PRE_BREAKOUT factor studies will be systematically underpowered.**

**Finding — Year-by-year distribution shows temporal stability:**

| Year | BREAKOUT | PRE_BREAKOUT | RS_LEADER_MARKET | RS_LEADER_SECTOR |
|---|---|---|---|---|
| 2015 | 3,589 | 423 | 4,980 | 7,719 |
| 2016 | 5,480 | 1,067 | 4,960 | 8,155 |
| 2017 | 2,625 | 354 | 4,980 | 7,454 |
| 2018 | 2,625 | 482 | 4,920 | 7,141 |
| 2019 | 3,444 | 260 | 4,940 | 6,795 |
| 2020 | 5,468 | 258 | 5,020 | 8,429 |
| 2021 | 3,853 | 483 | 4,940 | 8,378 |
| 2022 | 2,283 | 429 | 4,960 | 7,270 |
| 2023 | 5,191 | 420 | 4,920 | 8,436 |
| 2024 | 5,982 | 423 | 4,920 | 9,431 |
| 2025 | 6,896 | 571 | 5,000 | 10,312 |
| 2026 | 1,887 | 134 | 2,360 | 4,844 |

RS_LEADER_MARKET is mechanically stable at ~4,960 signals/year (LIMIT 20 per trading day × ~248 trading days). RS_LEADER_SECTOR grows gradually, reflecting the expanding symbol universe. BREAKOUT is volatile year-to-year, ranging from 2,283 (2022) to 6,896 (2025) — likely reflecting market cycle effects. PRE_BREAKOUT is the most volatile in proportion, ranging from 258 (2020) to 1,067 (2016).

---

### D5 — Symbol and Sector Coverage

| Metric | Value |
|---|---|
| Unique symbols in `setup_log` | **252** |
| Unique symbols in `stock_signals` | **313** |
| Gap (in stock_signals but not setup_log) | **61 symbols** |
| Unique sectors in `setup_log` | **23** |

**Finding — 61 symbols present in stock_signals but absent from setup_log:** These symbols have computed signals but never met the detection conditions for any setup type across the full 11-year history. They are in the universe but have never qualified as a research signal. This is expected behaviour, not a data error, but it defines the boundary of what this research can speak to.

**Symbol coverage over time:**

| Year | Unique Symbols |
|---|---|
| 2015 | 147 |
| 2016 | 159 |
| 2017 | 155 |
| 2018 | 140 |
| 2019 | 133 |
| 2020 | 155 |
| 2021 | 171 |
| 2022 | 151 |
| 2023 | 170 |
| 2024 | 191 |
| 2025 | 213 |
| 2026 | 179 |

Symbol universe is growing: 147 symbols in 2015 vs 213 in 2025 (+45%). This growth in coverage means later years will have more diversified signals. Studies pooling all years will be influenced more by the richer later years.

**Sector concentration (top 5 by setup count):**

| Sector | Setup Count | % |
|---|---|---|
| COMMERCIAL BANKS | 19,006 | 9.2% |
| CEMENT | 16,532 | 8.0% |
| TECHNOLOGY & COMMUNICATION | 16,206 | 7.9% |
| FERTILIZER | 12,811 | 6.2% |
| POWER GENERATION & DISTRIBUTION | 12,275 | 6.0% |

Top 5 sectors account for 37.3% of all setups. The bottom 5 sectors account for approximately 7.5%. Sector-stratified studies will have materially unequal cell sizes. **Studies that pool results across sectors are implicitly overweighted toward Banks, Cement, and Technology.**

---

### D6 — Outcome Label Internal Consistency

| Check | Result | Status |
|---|---|---|
| WINNER rows with `fwd_return_10d ≤ 0` | 0 | ✅ Clean |
| LOSER rows with `fwd_return_10d ≥ 0` | 0 | ✅ Clean |
| WINNER rows with `fwd_return_10d` NULL | 0 | ✅ Clean |
| LOSER rows with `fwd_return_10d` NULL | 0 | ✅ Clean |
| BREAKEVEN rows with non-zero `fwd_return_10d` | 0 | ✅ Clean |

**Finding:** The outcome labelling is internally consistent without a single exception. Every WINNER has a strictly positive 10d return. Every LOSER has a strictly negative 10d return. Every BREAKEVEN with a populated return has exactly zero. The label computation logic is reliable.

---

### D7 — Cross-Table Join Integrity

| Check | Result | Status |
|---|---|---|
| `setup_log` dates with no `market_regime` row | **0** | ✅ Clean |
| `setup_log` rows with no matching `sector_signals` row | **1,892** | ⚠️ Requires investigation |
| `setup_log.regime` vs `market_regime.regime` mismatches | **0** | ✅ Clean |

**Finding — 1,892 setup_log rows have no matching sector_signals row:** These rows have a sector value in `setup_log` that either (a) does not appear in `sector_signals` on that date, or (b) uses a different sector label string. This affects 0.9% of all rows. For the 19,989 rows in TRENDING_DOWN regime or any sector-stratified study, these orphaned rows would be silently dropped in a join without warning. Every study using `sector_signals` must account for this 0.9% left-join gap.

**Finding — regime is perfectly denormalized:** The `regime` column in `setup_log` matches `market_regime.regime` for every row with zero exceptions. This means factor experiments that only need the regime label do not require a join — it is already available in `setup_log`.

---

### D7b — Regime Distribution

| Regime | Count | % |
|---|---|---|
| `TRENDING_UP` | 96,791 | 47.0% |
| `RANGING` | 59,627 | 29.0% |
| `VOLATILE` | 29,484 | 14.3% |
| `TRENDING_DOWN` | 19,989 | 9.7% |

**Finding — four regime labels confirmed (not three):** The research architecture assumed three regimes (TRENDING_UP, RANGING, TRENDING_DOWN). A fourth label, `VOLATILE`, accounts for **14.3% of all setups** — larger than TRENDING_DOWN (9.7%). Every experiment that stratifies by regime must include VOLATILE as a separate category, not collapse it into RANGING. All prior documentation referring to "three regimes" is materially incorrect and must be updated.

---

### D8 — Duplicate Detection

| Check | Result | Status |
|---|---|---|
| Duplicate (symbol, setup_date, setup_type) combinations | **0** | ✅ Clean |
| Excess rows from duplicates | **0** | ✅ Clean |

**Finding:** The setup_log has no exact duplicates on the (symbol, date, setup_type) key. The BREAKOUT multi-day concern remains a logical duplication issue (same economic event generating multiple rows on consecutive days), but it is not a data integrity issue — each row is genuinely a different calendar day. This is addressed in EXP-0003 (Sample Independence Assessment).

---

### D9 — Schema Gap: Columns Missing from setup_log

**Critical finding — 11 columns from `stock_signals` are not present in `setup_log`:**

| Column | In stock_signals | In setup_log | Impact |
|---|---|---|---|
| `stage2_bull` | ✅ | ❌ | All Stage 2 experiments require a join |
| `overhead_clear` | ✅ | ❌ | Overhead Clear experiment requires a join |
| `near_pivot_days` | ✅ | ❌ | Near Pivot Days experiment requires a join |
| `base_duration` | ✅ | ❌ | Base Duration experiment requires a join |
| `avg_vol_10d` | ✅ | ❌ | Volume threshold validation requires a join |
| `rs_score_50` | ✅ | ❌ | RS Acceleration experiment requires a join |
| `pivot_high` | ✅ | ❌ | Pivot level analysis requires a join |
| `close_above_ema150` | ✅ | ❌ | EMA decomposition requires a join |
| `ema150_slope_pos` | ✅ | ❌ | EMA slope experiments require a join |
| `close_above_ema50` | ✅ | ❌ | EMA decomposition requires a join |
| `ema50_slope_pos` | ✅ | ❌ | EMA slope experiments require a join |

This directly contradicts the assumption in the Study Design document that these columns were "confirmed in setup_log." The factor research plan classified experiments using these columns as "Group A — No Engineering Required." **That classification is incorrect. These are Group B experiments requiring a join to stock_signals.**

Three columns present in `setup_log` that were not documented in the research architecture:
- `regime` — denormalized from market_regime (eliminates regime join for most experiments)
- `rank_change` — present directly (no join needed for rank momentum studies)
- `vol_contraction` — present directly (no join needed for volume contraction studies)

---

## ─── BLOCK 5: INTERPRETATION ──────────────────────────────────

### 5.1 Primary Finding

```
The evidence supports H₁: the dataset contains multiple structural anomalies requiring
documentation before factor research begins. Seven findings of material consequence were
identified. No finding is severe enough to invalidate the dataset — the evidence supports
that setup_log is fundamentally usable — but three findings require corrections to the
research plan before EXP-0101 opens.
```

### 5.2 Kill Criteria Review

Not applicable to a descriptive experiment.

### 5.3 Hypothesis Verdict

| | |
|---|---|
| **H₁ supported?** | Yes |
| **Dataset structurally usable for research?** | Yes — with documented caveats |
| **Any finding severe enough to halt research?** | No |
| **Corrections required before factor research?** | Yes — three (see Block 5.4) |

### 5.4 Ranked Findings by Severity

**SEVERITY: MODERATE — Requires correction to research plan before proceeding**

1. **Date Range Assumption Wrong (D1):** All prior documentation assumed the research dataset begins in 2020. The actual start is 2015 for `setup_log` and 2005 for `stock_signals`. The in-sample / out-of-sample split, the temporal stability design, and the base rate characterisation must be redesigned to account for 11 years of data, not 6.

2. **Four Regime Labels, Not Three (D7b):** `VOLATILE` is a fourth regime covering 14.3% of setups. All documentation, governance files, and planned experiments that reference "three regimes" must be updated. Every stratification table in every future experiment must have four regime rows, not three.

3. **Schema Gap — 11 Columns Missing from setup_log (D9):** The experiment classification in the Study Design document incorrectly categorised 11 single-factor experiments as "no engineering required." Stage 2, Overhead Clear, Near Pivot Days, Base Duration, RS Score 50d, and all EMA condition experiments require a join to `stock_signals`. The Research Pipeline must be updated to reflect Group B classification for these experiments.

**SEVERITY: MINOR — Document and monitor, no plan change required**

4. **PRE_BREAKOUT Severely Underrepresented (D4):** 5,304 rows total, averaging 442 per year. Most PRE_BREAKOUT factor experiments will achieve only Weak confidence. This should be noted in the Hypotheses file for any PRE_BREAKOUT study.

5. **1,892 Orphaned Sector Rows (D7):** 0.9% of setup_log rows have no matching sector_signals entry. Every sector_signals join must use LEFT JOIN and account for the gap.

6. **Outcome Label / Forward Return Count Mismatch (D2):** 1,964 NULL forward returns vs 1,648 NULL outcome labels — a 316-row discrepancy. Mechanism unknown. Deferred to EXP-0002 for investigation.

7. **Sector Concentration (D5c):** Top 5 sectors account for 37% of setups. Pooled-sector results are implicitly weighted. All sector-stratified studies must report both pooled and per-sector results.

**SEVERITY: INFORMATIONAL — No action required**

8. **Symbol Universe Growing (D5b):** 147 symbols in 2015 vs 213 in 2025. Expected. Note in temporal studies.

9. **Raw Base Rate Below 50% (D3b):** 46.6% win rate across all setup types. Establishes that the unfiltered signal universe loses money on net. Expected and motivates the conviction engine.

10. **Outcome Labels Perfectly Consistent (D6):** Zero mismatches. No action required.

11. **Zero Exact Duplicates (D8):** No action required.

### 5.5 What This Result Does Not Establish

- The evidence does not establish whether the 2015–2019 data (pre-assumed-start) is of equal quality to the 2020–2026 data. That is the subject of EXP-0005 (Temporal Stability).
- The evidence does not establish the cause of the 1,892 orphaned sector rows or the 316-row outcome label mismatch. Those are subjects for EXP-0002.
- The evidence does not establish whether the schema gap (11 missing columns) represents an intentional design decision or an omission in the backfill pipeline. No recommendation about implementation is made here.

### 5.6 Alternative Explanations

- The 28,730 NULL values in `pivot_distance_pct` could represent either (a) stocks with no confirmed pivot in their history, or (b) a pipeline gap where pivot computation failed for some symbols. The consistency — all 28,730 NULLs are in non-BREAKOUT rows — strongly supports explanation (a), since BREAKOUT detection requires a non-NULL pivot by definition.
- The VOLATILE regime being unlisted in prior documentation may reflect documentation lag rather than a pipeline error. The data itself shows VOLATILE clearly and consistently.

---

## ─── BLOCK 6: EVIDENCE CLASSIFICATION ────────────────────────

| | |
|---|---|
| **Classification** | 🟢 Accepted |
| **Confidence Level** | Strong — exhaustive census of the full database, no sampling |

**Rationale:** This is a descriptive census experiment with no sampling uncertainty. Every number reported is exact. The evidence is accepted as the authoritative characterisation of the dataset as it exists on 2026-07-01. Future health assessments should re-run this experiment periodically to detect drift.

---

## ─── BLOCK 7: EVIDENCE MATURITY ──────────────────────────────

```
EXP-0001 — Dataset Health Assessment

  Discovery ✅  →  Observed ◉  →  Replicated ⬜  →  Validated ⬜  →  Production Ready ⬜
```

**Current Stage: Observed**

A health report requires no replication or OOS validation — it is a snapshot of a physical database state. This experiment reaches Observed and terminates the maturity pipeline at that stage by design.

---

## ─── BLOCK 8: CROSS-REFERENCES ───────────────────────────────

| Field | Value |
|---|---|
| **Evidence Register Entry** | E-0001 |
| **Evidence bucket** | 🟢 Accepted |
| **Experiments unlocked** | EXP-0002 (Outcome Validation), EXP-0003 (Sample Independence) |
| **Experiments requiring plan revision** | All Group A experiments that use stage2_bull, overhead_clear, near_pivot_days, base_duration → reclassify to Group B |
| **Documents requiring update** | All docs referencing "three regimes" → add VOLATILE; all docs referencing "2020 start date" → correct to 2015 |

---

## ─── BLOCK 9: REUSABLE ASSET ──────────────────────────────────

| Field | Value |
|---|---|
| **Asset Type** | Data quality report + Confirmed schema reference |
| **Asset Description** | The confirmed column list for setup_log (20 columns), the confirmed null rates, the confirmed regime label set (4 labels), and the confirmed date range (2015–2026) — all verified against the live database |
| **Where it lives** | This document (EXP-0001), Blocks D1–D9 |
| **How future experiments use it** | Every future experiment cites EXP-0001 for its column availability check. No experiment needs to re-verify which columns exist in setup_log — use the confirmed list in D9. Every experiment using regime stratification uses the four-label set from D7b. Every experiment citing "the IS period" now uses 2015–2023 (not 2020–2023) unless a specific rationale is given for restricting the start year. |

---

## ─── EXPERIMENT LOG ────────────────────────────────────────────

| Date | Entry |
|---|---|
| 2026-07-01 | Pre-registration completed. Seven assessment dimensions defined. |
| 2026-07-01 | Schema query executed. Discovered setup_log has 20 confirmed columns — 11 assumed columns are absent. |
| 2026-07-01 | Full health assessment executed across D1–D8. |
| 2026-07-01 | Analysis complete. H₁ supported. Three moderate findings, four minor findings, four informational findings. Classification: 🟢 Accepted. Maturity: Observed. Experiment closed. |
| 2026-07-01 | Addendum A appended. 2005–2014 coverage gap diagnosed. Root cause: stock_signals backfill was never run for the pre-2015 period. Only one symbol (MTL) exists in stock_signals before 2015, with all computed fields NULL. The 2005–2014 window is a future backlog item, not permanently out of scope. IS/OOS era boundaries (2015–19 / 2020–22 / 2023–26) are confirmed unchanged. |

---

## ─── ADDENDUM A — 2005–2014 Coverage Gap ──────────────────────

*Appended 2026-07-01. This addendum is a standalone diagnostic. No sections of the closed experiment above have been modified.*

### A.1 — Question

Why does `setup_log` begin on 2015-01-01 when `prices_adjusted` extends back to 2005-01-03?

---

### A.2 — Evidence

**Date ranges across all tables (confirmed):**

| Table | Min Date | Max Date | Rows |
|---|---|---|---|
| `prices_adjusted` | 2005-01-03 | 2026-07-01 | 1,819,802 |
| `prices` | 2005-01-03 | 2026-07-01 | 1,819,802 |
| `market_regime` | 2005-01-03 | 2026-07-01 | 5,313 |
| `stock_signals` | 2005-02-16 | 2026-07-01 | 680,340 |
| `sector_signals` | 2015-01-01 | 2026-07-01 | 63,397 |
| `setup_log` | 2015-01-01 | 2026-07-01 | 205,891 |

**`stock_signals` pre-2015 — year-by-year breakdown:**

| Year | Distinct Symbols | Rows | `avg_vol_10d` NULL | `bos_flag` NULL |
|---|---|---|---|---|
| 2005 | **1** | 189 | 189 (100%) | 189 (100%) |
| 2006 | **1** | 231 | 231 (100%) | 231 (100%) |
| 2007 | **1** | 242 | 242 (100%) | 242 (100%) |
| 2008 | **1** | 208 | 208 (100%) | 208 (100%) |
| 2009 | **1** | 246 | 246 (100%) | 246 (100%) |
| 2010 | **1** | 250 | 250 (100%) | 250 (100%) |
| 2011 | **1** | 247 | 247 (100%) | 247 (100%) |
| 2012 | **1** | 249 | 249 (100%) | 249 (100%) |
| 2013 | **1** | 247 | 247 (100%) | 247 (100%) |
| 2014 | **1** | 246 | 246 (100%) | 246 (100%) |
| **2015** | **263** | 53,485 | 9 (0.0%) | 0 |

**The single pre-2015 symbol in `stock_signals` is MTL.**

`prices_adjusted` pre-2015 contains **708 distinct symbols** and **809,846 rows** — the raw price history is substantively populated for that period.

`sector_signals` has **zero rows before 2015-01-01**.

---

### A.3 — Root Cause

The gap is a **pipeline artifact: the `stock_signals` backfill was never executed for dates prior to 2015**.

The evidence chain:

1. **`stock_signals` pre-2015 is effectively empty.** Only MTL appears, with one row per trading day, all computed fields (`avg_vol_10d`, `bos_flag`, `pivot_distance_pct`, `rs_rank`, `base_tightness`, etc.) NULL. This is a degenerate record — likely an artifact of a single-symbol test run, not a real computation pass over the universe.

2. **`stock_signals` 2015+ has full multi-symbol coverage.** From 2015-01-01, 198–313 distinct symbols appear per year with fully populated computed fields. The transition from 1 symbol (all NULLs) to 263 symbols (fully computed) at the 2015 boundary is sharp and unambiguous.

3. **Setup detection cannot fire on NULL computed fields.** All four setup types in `backfill_setup_log.py` require `avg_vol_10d > 200000` (RS and PRE_BREAKOUT types) or `bos_flag = 1` (BREAKOUT). Since every pre-2015 row in `stock_signals` has `avg_vol_10d = NULL` and `bos_flag = NULL`, none of these conditions can be satisfied. `setup_log` would receive zero rows even if `backfill_setup_log.py` were run against the full date range — which the evidence suggests it was (the script iterates all `stock_signals` dates), but with no output before 2015 for this reason.

4. **`sector_signals` was never computed for pre-2015 dates.** `sector_signals` is computed from `stock_signals` via the daily hook in `sector_signals.py`. With no valid multi-symbol `stock_signals` data before 2015, the sector aggregation produces nothing.

5. **`market_regime` and `prices_adjusted` are populated back to 2005** because they are computed directly from raw price data (the index and individual stock OHLCV), not from `stock_signals`. These two tables are the only genuine 21-year tables.

6. **`backfill_setup_log.py` contains an explicit dry-run boundary of `2015-01-31`**, confirming that 2015 was always the intended operational start date for the backfill. This is a design decision, not a technical constraint.

**Summary of root cause:** The `stock_signals` computation was backfilled starting from 2015. The 2005–2014 window in `prices_adjusted` and `market_regime` exists because those tables are sourced directly from raw prices, but the derived signal layer — RS ranks, pivot detection, volume averages, stage indicators — was never computed for the pre-2015 period. Without the signal layer, setup detection produces nothing, and `setup_log` is empty before 2015.

---

### A.4 — Is the 2005–2014 Window Recoverable?

**Technically: yes, subject to data quality constraints.**

`prices_adjusted` holds 708 symbols and 809,846 rows for 2005–2014. The same `stock_signals.py` computation pipeline that was applied from 2015 onwards could be run against this data. The output would be `stock_signals` rows for 2005–2014 with populated `rs_rank`, `bos_flag`, `avg_vol_10d`, etc. `sector_signals` could then be computed from those rows. `backfill_setup_log.py` could then generate `setup_log` entries.

**What would be required (scope only — not a commitment):**

1. Run `stock_signals.py` backfill for all dates in `prices_adjusted` before 2015-01-01 (approximately 2,475 trading days × ~200 symbols at full coverage, though symbol count in `prices_adjusted` is lower in earlier years).
2. Run `sector_signals` computation for those dates.
3. Re-run `backfill_setup_log.py` (it processes all `stock_signals` dates, so new pre-2015 rows would be picked up automatically).
4. Run `compute_forward_returns.py` to compute outcome variables for the new rows.

**Data quality cautions for the pre-2015 period:**

- Corporate action adjustment coverage is less certain for 2005–2014 than for 2015+. The `corporate_action_suspects` table and the adjustment pipeline were built around the Kiran scraper era. Pre-2015 data comes from the BI PostgreSQL source, and the completeness of corporate action records for that period has not been validated.
- Symbol universe in `prices_adjusted` for 2005–2014 is 708 symbols — substantially more than the 252 that ultimately appear in `setup_log` for 2015+. The additional symbols may include thinly traded or since-delisted securities. Volume filtering (`avg_vol_10d > 200000`) would naturally exclude many of them.
- The 2008 financial crisis and the PSX market crash of 2008 are within this window. These events would create unusual regime and signal distributions that could introduce structural breaks when data is pooled with 2015+.

---

### A.5 — Does This Change the IS/OOS Era Boundaries?

**No.**

The proposed era boundaries for `setup_log` research are:

| Era | Period | Role |
|---|---|---|
| In-Sample (IS) | 2015–2022 | Factor discovery and calibration |
| Out-of-Sample (OOS) | 2023–2026 | Validation |

These boundaries are defined on `setup_log` coverage, which begins 2015-01-01. The diagnostic confirms that 2015 is the correct and unambiguous start of the usable research dataset for setup-level research.

If the 2005–2014 backfill is ever completed, those years would extend the IS period. At that point, the era boundaries would need to be reconsidered. But that is a future decision — the current boundaries remain valid and unchanged.

---

### A.6 — Recommendation

| Question | Answer |
|---|---|
| **Root cause of the gap** | Pipeline artifact — `stock_signals` was never backfilled for 2005–2014 |
| **Is 2005–2014 permanently out of scope?** | **No** — the raw price data exists and the backfill is technically feasible |
| **Is 2005–2014 a current backlog item?** | **Yes** — classify as a future enhancement; not required before Phase 1 |
| **Does the gap affect Phase 1 readiness?** | **No** — `setup_log` is usable as-is from 2015; Phase 1 proceeds on the existing 11-year dataset |
| **IS/OOS era boundaries changed?** | **No** — 2015–2022 IS / 2023–2026 OOS remains correct |
| **Action before Phase 1** | None — this addendum documents the gap; no remediation is required before factor research begins |

**Backlog entry (for future consideration):** Extend `stock_signals` backfill to cover 2005–2014 using the existing computation pipeline on `prices_adjusted`. Validate corporate action coverage for that period before treating the resulting setup rows as research-grade data. This would expand the IS period from 8 years to 18 years, substantially increasing statistical power for factor studies.
