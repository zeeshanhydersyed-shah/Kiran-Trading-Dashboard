# Certified Dataset — v1.0
## PSX Quantitative Research Platform

---

> **Purpose:** Single authoritative reference for the research dataset as validated by Phase 0.5 experiments. Future experiments cite this document instead of re-deriving dataset facts. All facts here are sourced from completed, accepted experiments — not from assumptions.
>
> **Supersedes:** All prior informal descriptions of the dataset in planning documents, strategy notes, or session context.
>
> **How to use:** At the opening of any experiment, cite "Certified Dataset v1.0" and state which facts are inherited from this document. Do not re-verify inherited facts unless a new health assessment has been run.
>
> **Versioning rule:** "Certified Dataset v1.0" refers to the frozen snapshot taken on 2026-07-02 (see Section 0). The live database grows nightly. Two researchers running `SELECT COUNT(*) FROM setup_log WHERE fwd_return_10d IS NOT NULL` on different dates will get different numbers. The frozen snapshot — not a live query — is the reproducible reference. Any re-certification (new row counts, new limitations, new approved population) must be versioned as v1.1 or v2.0 with a new snapshot date. Do not silently redefine v1.0.

---

## ─── CERTIFICATION STATUS ──────────────────────────────────────

| Field | Value |
|---|---|
| **Dataset Version** | v1.0 |
| **Approved For Research** | **Yes — Phase 1 factor research approved** |
| **Approved On** | 2026-07-01 |
| **Snapshot Frozen On** | **2026-07-02** — see Section 0 |
| **Approved By** | Phase 0.5 experiment series (EXP-0001, EXP-0001-Addendum-A, EXP-0002) |
| **Primary Research Table** | `setup_log` |
| **Valid Research Population** | **203,996 rows** — frozen count as of 2026-07-02 snapshot (see Section 0) |
| **Valid Date Range** | 2015-01-01 to 2026-06-02 (most recent non-NULL setup date at snapshot) |
| **Pre-Phase-1 Remediation** | **Complete** — 1,009-row label fix committed 2026-07-02; source bug fixed in `backfill_setup_log.py` |
| **Next Scheduled Review** | Before Phase 2 opens, or upon any structural pipeline change |

---

## ─── SECTION 0: FROZEN SNAPSHOT — 2026-07-02 ──────────────────

> This section is immutable. It records the exact state of the database at the moment Certified Dataset v1.0 was finalized. All row counts and population figures cited in future experiments must use these numbers, not live queries. If the live database has grown or changed, that growth is not part of v1.0.

### Snapshot Date: 2026-07-02

**Taken after:**
- EXP-0001 (Dataset Health Assessment) — closed 2026-07-01
- EXP-0001-Addendum-A (Coverage Gap Diagnostic) — closed 2026-07-01
- EXP-0002 (Outcome Variable Validation) — closed 2026-07-01
- EXP-0002-Addendum-2 (Label fix committed, source bug patched) — 2026-07-02

**Table row counts at snapshot:**

| Table | Row Count | Date Min | Date Max |
|---|---|---|---|
| `setup_log` | **205,964** | 2015-01-01 | 2026-07-02 |
| `stock_signals` | 680,340 | 2005-02-16 | 2026-07-01 |
| `sector_signals` | 63,397 | 2015-01-01 | 2026-07-01 |
| `market_regime` | 5,313 | 2005-01-03 | 2026-07-01 |
| `prices_adjusted` | 1,819,802 | 2005-01-03 | 2026-07-01 |

**Certified research population at snapshot:**

| Metric | Count |
|---|---|
| `setup_log` total rows | 205,964 |
| Excluded — NULL `fwd_return_10d` | 1,968 |
| **Certified population** (`fwd_return_10d IS NOT NULL`) | **203,996** |
| Of certified: `outcome_label` NULL | **0** (label fix applied 2026-07-02) |
| Of certified: `outcome_label` = WINNER | 94,628 (approx) |
| Of certified: `outcome_label` = LOSER | 108,550 (approx) |
| Of certified: `outcome_label` = BREAKEVEN | ~818 (approx) |

**NULL `fwd_return_10d` breakdown at snapshot:**

| Category | Count | Disposition |
|---|---|---|
| Pending BREAKEVEN (open window, label set) | 1,329 | Excluded by standard filter — will populate naturally |
| Both NULL (open window, no label yet) | 639 | Excluded by standard filter — will populate naturally |
| Delisted / irrecoverable | 100 | Excluded permanently — no forward price available |
| **Total excluded** | **1,968** | |

**Reproducibility instruction:**

Any experiment that needs the v1.0 population denominator must use **203,996**, not a live `COUNT(*)`. If a study is opened after new pipeline runs have added rows, the experimenter must explicitly note the live count and state that v1.0 denominators are used for comparison.

---

## ─── SECTION 1: TABLES ─────────────────────────────────────────

### 1.1 Research Tables

| Table | Row Count | Date Min | Date Max | Role |
|---|---|---|---|---|
| `setup_log` | **205,891** | 2015-01-01 | 2026-07-01 | Primary research table — one row per (symbol, date, setup_type) |
| `stock_signals` | **680,340** | 2005-02-16 | 2026-07-01 | Signal source — RS ranks, pivot, stage, EMA, volume per symbol per day |
| `sector_signals` | **63,397** | 2015-01-01 | 2026-07-01 | Sector-level aggregates — breadth, RS, stage per sector per day |
| `market_regime` | **5,313** | 2005-01-03 | 2026-07-01 | Daily market regime classification |
| `prices_adjusted` | **1,819,802** | 2005-01-03 | 2026-07-01 | Adjusted OHLCV per symbol per day — price source for all return computations |
| `prices` | **1,819,802** | 2005-01-03 | 2026-07-01 | Raw OHLCV — mirrors `prices_adjusted` unless a corporate action has been confirmed |

### 1.2 Valid Research Population

The certified research population is not the full `setup_log` — it is the subset with a computable outcome:

```sql
-- Certified research population
SELECT *
FROM setup_log
WHERE fwd_return_10d IS NOT NULL
-- N = 202,987 rows (as of 2026-07-01)
```

**Rows excluded by this filter and why:**

| Excluded Category | Count | Reason | Recoverable? |
|---|---|---|---|
| Open forward window (recent setups) | ~1,864 | Window not yet closed as of computation date | Yes — added automatically by pipeline |
| Delisted symbols (PSMC, FFBL, PIAA, others) | 100 | Price series ended before 20d window could close | No — permanent NULL |
| **Total excluded** | **1,964** | | |

### 1.3 Setup Type Distribution (Research Population)

| Setup Type | Row Count | % | Avg Signals/Year |
|---|---|---|---|
| `RS_LEADER_SECTOR` | ~93,423 | 46.0% | ~8,311 |
| `RS_LEADER_MARKET` | ~56,489 | 27.8% | ~4,960 (mechanical — LIMIT 20/day) |
| `BREAKOUT` | ~48,765 | 24.0% | ~4,340 |
| `PRE_BREAKOUT` | ~5,250 | 2.6% | ~467 ⚠️ see Known Limitations |
| **Total** | **~202,987** | | |

*Note: Counts are approximate post-filter values. EXP-0001 reported pre-filter counts; the small difference reflects the NULL exclusions above.*

---

## ─── SECTION 2: TABLE RELATIONSHIPS ────────────────────────────

```
setup_log ──────────────────────── PRIMARY RESEARCH TABLE
    │
    ├── JOIN market_regime ON market_regime.date = setup_log.setup_date
    │       → regime column; NOT required — regime is denormalized into setup_log.regime (EXP-0001 D7)
    │
    ├── LEFT JOIN sector_signals ON sector_signals.date = setup_log.setup_date
    │                            AND sector_signals.sector = setup_log.sector
    │       → sector-level features; LEFT JOIN required — 1,892 rows have no match (0.9%)
    │
    ├── LEFT JOIN stock_signals ON stock_signals.date = setup_log.setup_date
    │                           AND stock_signals.symbol = setup_log.symbol
    │       → 11 additional factor columns not in setup_log (see Section 5)
    │       → LEFT JOIN required to avoid silent row loss
    │
    └── JOIN prices_adjusted ON prices_adjusted.symbol = setup_log.symbol
            → used to reconstruct forward returns or compute custom horizons (OV-06)
```

**Key join rules:**

1. `market_regime` join is rarely needed — `regime` is already in `setup_log` and is perfectly denormalized (EXP-0001 D7, zero mismatches).
2. `sector_signals` join must be LEFT JOIN — 1,892 setup_log rows have no matching sector_signals entry (0.9% gap).
3. `stock_signals` join must be LEFT JOIN — silent inner-join row loss is a real risk.
4. All joins use `date = setup_date` (not a date range). `setup_log` uses column name `setup_date`; all other tables use `date`.

---

## ─── SECTION 3: REGIME DEFINITIONS ────────────────────────────

**Four regime labels are present in the database.** Prior documentation that references "three regimes" is incorrect and superseded by EXP-0001 D7b.

| Regime | Count in setup_log | % | Definition Source |
|---|---|---|---|
| `TRENDING_UP` | 96,791 | 47.0% | `market_regime` table |
| `RANGING` | 59,627 | 29.0% | `market_regime` table |
| `VOLATILE` | 29,484 | 14.3% | `market_regime` table |
| `TRENDING_DOWN` | 19,989 | 9.7% | `market_regime` table |

**Important:** `VOLATILE` is larger than `TRENDING_DOWN` by signal count. Any experiment stratifying by regime must include all four labels as separate categories.

**Column availability:** `setup_log.regime` holds the regime label for every row (NULL rate = 0.0%). A join to `market_regime` is not required for regime-stratified studies.

---

## ─── SECTION 4: VALIDATED OUTCOME DEFINITIONS ─────────────────

Source: EXP-0002 (🟢 Accepted). All outcomes below have passed the reconstruction audit.

### OV-01 — 10-Day Forward Return *(Primary)*

| Property | Value |
|---|---|
| **Column** | `fwd_return_10d` in `setup_log` |
| **Formula** | `(close[setup_date + 10 trading days] − close[setup_date]) / close[setup_date] × 100` |
| **Price source** | `prices_adjusted` |
| **Trading day counting** | Positional index in symbol's `prices_adjusted` series (ordered by date) |
| **Horizon type** | Fixed-exit passive hold — no stop-loss applied |
| **NULL handling** | NULL = window not yet closed OR symbol delisted before window closed. Exclude via `WHERE fwd_return_10d IS NOT NULL` |
| **Audit result** | 0/100 reconstruction errors (0.0%) — EXP-0002 |
| **Look-ahead status** | Clean — all exit dates confirmed strictly after setup_date |
| **Practical limitation** | Passive hold. A stock that hit −8% on day 5 then recovered to +3% on day 10 is recorded as +3%. Does not reflect trading-quality outcomes. |

### OV-02 — 20-Day Forward Return

| Property | Value |
|---|---|
| **Column** | `fwd_return_20d` in `setup_log` |
| **Formula** | Same as OV-01 at positional index + 20 |
| **NULL handling** | Identical to OV-01 — all three horizons are NULL together |
| **Audit result** | 0/100 reconstruction errors (0.0%) — EXP-0002 |

### OV-03 — 5-Day Forward Return

| Property | Value |
|---|---|
| **Column** | `fwd_return_5d` in `setup_log` |
| **Formula** | Same as OV-01 at positional index + 5 |
| **NULL handling** | Identical to OV-01 |
| **Audit result** | 0/100 reconstruction errors (0.0%) — EXP-0002 |
| **Practical limitation** | Short window — more exposed to noise; not recommended as sole outcome for stage-analysis studies |

### OV-04 — Outcome Label

| Property | Value |
|---|---|
| **Column** | `outcome_label` in `setup_log` |
| **Values** | `WINNER` / `LOSER` / `BREAKEVEN` / NULL |
| **Derivation** | `WINNER` if `fwd_return_10d > 0`; `LOSER` if `< 0`; `BREAKEVEN` if `= 0` |
| **Audit result** | 0/100 label mismatches — EXP-0002 |
| **Known gap** | 940 rows (setup dates 2026-05-11 to 2026-06-01) have valid `fwd_return_10d` but NULL `outcome_label` due to a one-time backfill pipeline omission. **Requires one-time SQL fix before win rate studies.** |
| **Mandatory filter rule** | Always filter `fwd_return_10d IS NOT NULL` in addition to any `outcome_label` filter. Do not use `outcome_label` as the sole completeness gate. |
| **Insert placeholder** | Rows awaiting their forward window show `outcome_label = 'BREAKEVEN'` (pipeline insert default). These rows also have `fwd_return_10d = NULL`. The standard filter above excludes them automatically. |

### OV-05 — Realized R (backtest_setups only)

| Property | Value |
|---|---|
| **Column** | `realized_r` in `backtest_setups` |
| **Population** | 4,344 rows (not in `setup_log`) |
| **Non-NULL count** | 2,427 rows (Win_Trail=1562, Loss=776, Win_T1=89) |
| **NULL explanation** | 1,841 Stale_Setup + 76 Expired = 1,917 NULLs — these outcomes have no realized_r by design |
| **Certification status** | **Inventoried — not yet certified.** Reconstruction audit deferred; requires backtest engine validation. Do not use OV-05 in Phase 1 factor research. |

### OV-06 — Custom Forward Return (non-standard horizon)

Not stored. Must be constructed at research time from `prices_adjusted`. Construction methodology must be documented in the experiment that uses it. Not certified here.

---

## ─── SECTION 5: KNOWN MISSING FIELDS ──────────────────────────

The following 11 columns are **present in `stock_signals` but absent from `setup_log`**. Experiments requiring these columns are classified as **Group B** (require JOIN to stock_signals). No experiment may treat them as Group A (no engineering required). Source: EXP-0001 D9.

| Column | In `stock_signals` | In `setup_log` | Experiments Affected |
|---|---|---|---|
| `stage2_bull` | ✅ | ❌ | Stage 2 condition experiments |
| `overhead_clear` | ✅ | ❌ | Overhead Clear experiment |
| `near_pivot_days` | ✅ | ❌ | Near Pivot Days experiment |
| `base_duration` | ✅ | ❌ | Base Duration experiment |
| `avg_vol_10d` | ✅ | ❌ | Volume threshold validation |
| `rs_score_50` | ✅ | ❌ | RS Acceleration (50d) experiment |
| `pivot_high` | ✅ | ❌ | Pivot level analysis |
| `close_above_ema150` | ✅ | ❌ | EMA150 decomposition |
| `ema150_slope_pos` | ✅ | ❌ | EMA150 slope experiments |
| `close_above_ema50` | ✅ | ❌ | EMA50 decomposition |
| `ema50_slope_pos` | ✅ | ❌ | EMA50 slope experiments |

**Columns confirmed directly in `setup_log` (no JOIN needed):**

| Column | Notes |
|---|---|
| `regime` | Denormalized from `market_regime` — zero mismatches confirmed (EXP-0001 D7) |
| `rank_change` | Present directly |
| `rs_score_20` | Present directly |
| `vol_contraction` | Present directly |
| `base_tightness` | Present directly |
| `rs_rank` | Present directly |
| `sector_rs_rank` | Present directly |
| `pivot_distance_pct` | Present — 14.0% NULL for non-BREAKOUT rows (structural, not errors) |
| `bos_flag` | Present — 14.0% NULL for non-BREAKOUT rows (same 28,730 rows as pivot_distance_pct) |

---

## ─── SECTION 6: KNOWN LIMITATIONS ─────────────────────────────

All limitations below are sourced from completed experiments. Source is cited for each.

### L-01 — 2005–2014 Coverage Gap (EXP-0001 Addendum A)

`setup_log` and `sector_signals` contain no data before 2015-01-01. `stock_signals` contains only one symbol (MTL) with all computed fields NULL for 2005–2014. This is a **pipeline artifact**: the `stock_signals` backfill was never executed for the pre-2015 period. Raw price data (`prices_adjusted`) exists for 708 symbols from 2005. The gap is technically recoverable but is a future backlog item — it does not affect current research.

**Impact on IS/OOS design:** The IS period begins 2015-01-01. There is no recoverable pre-2015 setup-level data.

### L-02 — PRE_BREAKOUT Severely Underpowered (EXP-0001 D4)

PRE_BREAKOUT accounts for only 2.6% of the research population (~5,250 rows post-filter, ~467 signals/year on average). Factor quintile studies on PRE_BREAKOUT will yield ~94 rows per quintile at best — achieving only **Weak to Moderate** confidence. Any PRE_BREAKOUT factor experiment must note this limitation explicitly.

### L-03 — 1,892 Orphaned Sector Rows (EXP-0001 D7)

1,892 `setup_log` rows (0.9%) have no matching row in `sector_signals` on the same date with the same sector label. Root cause: sector label string mismatch or sector not present in `sector_signals` for that date. **Every experiment joining `setup_log` to `sector_signals` must use LEFT JOIN** and must account for the 0.9% gap in any completeness analysis.

### L-04 — 940-Row Outcome Label Gap (EXP-0002 Step 3b)

940 `setup_log` rows (setup dates 2026-05-11 to 2026-06-01) have valid `fwd_return_10d` but NULL `outcome_label`. These rows were inserted by a backfill run on 2026-06-13 without the pipeline's BREAKEVEN insert default, causing the labelling step to skip them. Forward returns are correct. Labels are missing. **Requires one-time SQL fix before Phase 1 win rate studies** (see Section 7). After the fix, these rows are fully usable.

### L-05 — 100 Permanent-NULL Rows — Delisted Symbols (EXP-0002 Step 3a)

100 `setup_log` rows have NULL `fwd_return_10d` permanently because the underlying symbol delisted before the 20-trading-day window could close. These rows span 2024-04-16 to 2025-03-17 and include PSMC, FFBL, PIAA, and others. The standard filter `WHERE fwd_return_10d IS NOT NULL` excludes them automatically. No action required — they are correctly NULL.

### L-06 — Sector Concentration (EXP-0001 D5)

The top 5 sectors (COMMERCIAL BANKS, CEMENT, TECHNOLOGY & COMMUNICATION, FERTILIZER, POWER GENERATION & DISTRIBUTION) account for 37.3% of all setups. The bottom 5 sectors account for ~7.5%. Studies pooling all sectors are implicitly overweighted toward the top 5. Pooled results must be reported alongside per-sector breakdowns in any sector-stratified analysis.

### L-07 — Symbol Universe Growth (EXP-0001 D5)

The number of distinct symbols in `setup_log` grew from 147 (2015) to 213 (2025), a 45% increase. Studies that pool all years weight later years more heavily due to the larger symbol universe. Temporal stratification by year-block is recommended for any study sensitive to universe composition.

### L-08 — Passive Hold Limitation on OV-01 through OV-03 (EXP-0002 Step 2)

All three certified forward return variables are **passive fixed-exit** returns. A position that hit a −8% stop on day 5 but recovered to +3% by day 10 is recorded as +3%. Studies using these outcomes cannot speak to the trading-quality of a setup (stop-hit frequency, intra-hold drawdown). OV-05 (`realized_r`) addresses this but is not yet certified.

---

## ─── SECTION 7: KNOWN BIASES ────────────────────────────────────

### B-01 — Survivorship Bias (partial)

`prices_adjusted` includes delisted symbols (PSMC, FFBL, PIAA, and others), and these symbols do appear in `setup_log`. However, setups for symbols that delisted before their 20-day window closed result in NULL `fwd_return_10d` and are excluded by the standard filter. This introduces a mild survivorship bias: only symbols that remained listed for at least 20 trading days after each signal date are included in the outcome population. The effect is small (100 rows, 0.05% of the research population) but is not zero.

### B-02 — Data Snooping Risk (regime and sector labels)

The `regime` column in `setup_log` and the `sector` column were computed by the same pipeline that generated setups, using the same price history. Factor studies that use regime or sector as conditioning variables are not independent of the signal generation process. This is an inherent property of denormalized signal tables and is noted here as a bias caveat, not a correctable error.

### B-03 — Corporate Action Adjustment Incompleteness

`prices_adjusted` is initialized as a copy of `prices`. Divergence occurs only when a corporate action is confirmed via `rebuild_symbol_adjusted()`. Symbols with undetected or unconfirmed corporate actions have identical values in both tables. If a stock underwent a split or bonus issue that was not captured in the `corporate_action_suspects` workflow, its pre-event prices in `prices_adjusted` are incorrect, and all forward returns for that symbol across the affected period are silently wrong. The reconstruction audit (EXP-0002) cannot detect this class of error because it uses the same `prices_adjusted` series for both reconstruction and storage. Scope and frequency of this bias is unknown.

---

## ─── SECTION 8: REMEDIATION REQUIRED BEFORE PHASE 1 ───────────

One action is required before any Phase 1 experiment that uses `outcome_label`:

**Fix the 940 NULL outcome_label rows**

```sql
UPDATE setup_log
SET outcome_label = CASE
    WHEN fwd_return_10d > 0  THEN 'WINNER'
    WHEN fwd_return_10d < 0  THEN 'LOSER'
    ELSE                          'BREAKEVEN'
END
WHERE fwd_return_10d IS NOT NULL
  AND outcome_label IS NULL;
-- Expected: 940 rows updated. No recomputation required.
-- Verify: SELECT COUNT(*) FROM setup_log WHERE fwd_return_10d IS NOT NULL AND outcome_label IS NULL;
-- Expected result after fix: 0
```

**Verification query after running the fix:**

```sql
SELECT
    SUM(CASE WHEN fwd_return_10d IS NULL AND outcome_label IS NULL         THEN 1 ELSE 0 END) AS both_null,
    SUM(CASE WHEN fwd_return_10d IS NULL AND outcome_label = 'BREAKEVEN'   THEN 1 ELSE 0 END) AS pending_label,
    SUM(CASE WHEN fwd_return_10d IS NOT NULL AND outcome_label IS NULL      THEN 1 ELSE 0 END) AS label_gap_SHOULD_BE_ZERO,
    SUM(CASE WHEN fwd_return_10d IS NOT NULL AND outcome_label IS NOT NULL  THEN 1 ELSE 0 END) AS clean_rows,
    COUNT(*) AS total
FROM setup_log;
```

Expected post-fix state: `label_gap_SHOULD_BE_ZERO = 0`.

---

## ─── SECTION 9: ERA DESIGN ──────────────────────────────────────

*Supersedes the two-era draft (IS / OOS) from the original Section 9. PI decision recorded 2026-07-02.*

Three eras are defined. Row counts are from the v1.0 frozen snapshot (203,996 certified rows, `fwd_return_10d IS NOT NULL`, snapshot date 2026-07-02 — see Section 0).

| Era | Period | Row Count | % of Total | Role |
|---|---|---|---|---|
| **Development (Dev)** | 2015-01-01 to 2019-12-31 | **82,393** | 40.4% | Factor discovery, quintile analysis, threshold selection |
| **Validation** | 2020-01-01 to 2022-12-31 | **51,771** | 25.4% | Out-of-development checkpoint — a factor must pass here before OOS is touched |
| **Out-of-Sample (OOS)** | 2023-01-01 to 2026-06-02 | **69,832** | 34.2% | Final validation only — opened once per hypothesis, no calibration permitted |
| **Total** | 2015-01-01 to 2026-06-02 | **203,996** | 100% | |

**Rationale:**

The three-era structure introduces a mandatory intermediate checkpoint between discovery and final validation. A factor that appears significant in Development may be overfit to the 2015–2019 regime. Running it against Validation (2020–2022) — a structurally different period that includes COVID onset, a crash, and the recovery — provides a low-cost overfitting screen before the OOS period is ever committed.

*Era characteristics:*
- **Development (2015–2019):** Pre-COVID market. Covers two PSX bull cycles and one significant bear phase (2017–2019 decline). Regime distribution is weighted toward TRENDING_UP and RANGING. Cleanest period for initial factor screening — no structural shock in the middle of the window.
- **Validation (2020–2022):** COVID crash (March 2020), recovery rally (2020–2021), post-recovery consolidation. Highest concentration of VOLATILE regime. A factor whose Development-era edge disappears in Validation is a candidate for revision or termination before OOS is opened.
- **OOS (2023–2026):** Most recent and most relevant regime for forward deployment. Contains the 2023–2024 PSX bull run and partial 2025–2026. This era is opened once and only once per hypothesis. Any analysis of OOS data constitutes a permanent consumption of that hypothesis's holdout.

**Rules for era discipline:**

1. **Development only for discovery.** All factor quintile analysis, threshold selection, interaction testing, and parameter tuning happens on the Development era only (`setup_date BETWEEN '2015-01-01' AND '2019-12-31'`). No exceptions.

2. **Validation is the first out-of-development test.** After a factor survives Development, it is tested on Validation (`setup_date BETWEEN '2020-01-01' AND '2022-12-31'`). A factor that fails Validation — direction reverses, effect size collapses below the minimum practical threshold, or kill criteria are triggered — must be revised or dropped before OOS is ever opened for it.

3. **OOS is opened once per hypothesis and only after passing Validation.** Opening OOS (`setup_date BETWEEN '2023-01-01' AND '2026-06-02'`) on a hypothesis that has not yet passed Validation constitutes a protocol violation and must be documented as an explicit deviation with justification.

4. **No calibration on Validation or OOS.** If a researcher observes a Validation result and adjusts the factor definition, threshold, or group boundaries to improve it, those adjusted parameters must be re-tested on a fresh Development run before Validation is repeated. Validation is not a tuning set.

5. **Deviation documentation.** Any experiment that uses Validation or OOS data for calibration, or opens OOS before Validation has passed, must record this explicitly in Block 2 (pre-registration deviation note) and Block 5 (caveats) of the experiment file.

---

## ─── SECTION 10: EXPERIMENT REFERENCES ────────────────────────

| Experiment | Title | Status | Key Finding |
|---|---|---|---|
| EXP-0001 | Dataset Health Assessment | 🟢 Accepted / Closed | Dataset structurally usable; 11 moderate/minor/informational findings; four regimes confirmed; schema gap documented |
| EXP-0001-Addendum-A | 2005–2014 Coverage Gap Diagnostic | 🟢 Accepted / Closed | Gap is a pipeline artifact; pre-2015 window recoverable but out of scope for now; IS/OOS era boundaries unchanged |
| EXP-0002 | Outcome Variable Validation | 🟢 Accepted / Closed | 0/100 audit errors; no look-ahead bias; EXP-0001 discrepancy resolved; 940-row label fix required; Phase 1 cleared |

---

## ─── SECTION 11: APPROVED POPULATION QUERY ────────────────────

The following query defines the certified research population for Phase 1. All Phase 1 experiments use this as their base filter, citing "Certified Dataset v1.0."

```sql
-- Certified Research Population — v1.0
-- N ≈ 202,987 rows (after 940-row label fix is applied)
-- Cite: Certified_Dataset_v1.0.md, EXP-0001, EXP-0002

SELECT
    sl.id,
    sl.symbol,
    sl.setup_date,
    sl.setup_type,
    sl.regime,                -- four values: TRENDING_UP, RANGING, VOLATILE, TRENDING_DOWN
    sl.rs_rank,
    sl.sector_rs_rank,
    sl.rank_change,
    sl.rs_score_20,
    sl.base_tightness,
    sl.vol_contraction,
    sl.pivot_distance_pct,    -- NULL for non-BREAKOUT rows (14% of total) — expected structural NULL
    sl.bos_flag,              -- NULL for non-BREAKOUT rows (same 14%)
    sl.sector,
    sl.fwd_return_5d,
    sl.fwd_return_10d,
    sl.fwd_return_20d,
    sl.outcome_label          -- WINNER / LOSER / BREAKEVEN after the 940-row fix
FROM setup_log sl
WHERE sl.fwd_return_10d IS NOT NULL
  AND sl.outcome_label IS NOT NULL   -- add this line only after 940-row fix is confirmed applied
ORDER BY sl.setup_date, sl.symbol
;
```

**For Group B factors** (requiring stock_signals JOIN — see Section 5):

```sql
-- Add to the query above:
LEFT JOIN stock_signals ss
    ON ss.symbol = sl.symbol
    AND ss.date  = sl.setup_date
-- Then reference: ss.stage2_bull, ss.overhead_clear, ss.near_pivot_days, etc.
```

**For sector-level factors** (requiring sector_signals JOIN):

```sql
-- Add to the query above (LEFT JOIN — never INNER):
LEFT JOIN sector_signals sec
    ON sec.sector = sl.sector
    AND sec.date  = sl.setup_date
-- 1,892 rows will have sec.* = NULL — this is expected and documented (L-03)
```

---

*This document is the ground truth for the dataset as of 2026-07-01. It will be versioned (v1.1, v2.0, etc.) when a new health assessment produces material changes to any section.*
