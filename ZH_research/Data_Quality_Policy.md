# Data Quality Policy — PSX Quantitative Research Platform

> **Purpose:** Defines data quality standards, known data issues, and required checks before any study proceeds.  
> **Related:** [Known_Limitations.md](Known_Limitations.md) · [Reproducibility_Policy.md](Reproducibility_Policy.md) · [Assumption_Register.md](Assumption_Register.md)

---

## Principle

Every study begins with a data quality assessment. Results derived from unclean data are not accepted into the Evidence Register, regardless of their statistical significance.

---

## Primary Data Sources

| Source | Table | Row Count | Notes |
|---|---|---|---|
| Adjusted prices | `prices_adjusted` | 1,819,212 | Corporate-action adjusted OHLCV. Primary price source for all research. |
| Raw prices | `prices` | ~581K | Unadjusted OHLCV. Not for research calculations — use `prices_adjusted`. |
| Stock signals | `stock_signals` | 680,047 | Pre-computed technical indicators per symbol per date. |
| Setup log | `setup_log` | 205,821 | Pre-classified signals with forward returns. Primary research table. |
| Sector signals | `sector_signals` | 63,374 | Sector-level aggregates. |
| Market regime | `market_regime` | 5,312 | Daily market classification. |
| Backtest setups | `backtest_setups` | 4,344 | Historically backtested entries with exit outcomes. |

---

## Pre-Study Data Quality Checklist

Before opening a study, verify all applicable items:

### 1. Row Count Check
- Confirm the row count of the primary table being queried
- If the count differs from the reference above by more than 5%, investigate before proceeding
- Document the actual count in the study entry

### 2. NULL Rate Check
For every factor and outcome variable in the study:
- Check the NULL rate per column
- If NULL rate > 10% for a key factor: investigate the cause before including the factor
- If NULL rate > 10% for the outcome variable (OV-01/02/03): the study should not proceed until the cause is understood
- Forward return NULLs for recent dates (window not yet closed) are expected and should be filtered out with `WHERE fwd_return_10d IS NOT NULL`

### 3. Date Range Check
- Confirm the date range of data available: `SELECT MIN(setup_date), MAX(setup_date) FROM setup_log`
- Confirm the in-sample split date: data from 2020-01-01 to 2023-12-31
- Confirm the out-of-sample split date: data from 2024-01-01 onwards
- Never mix in-sample and out-of-sample without clearly marking each

### 4. Corporate Action Suspects Check
- Query `corporate_action_suspects` for any PENDING rows affecting symbols in the study universe
- If PENDING suspects exist for a study symbol: exclude that symbol from the study until the suspect is resolved, OR document the inclusion with a caveat
- A CONFIRMED corporate action with a corrected `prices_adjusted` series is acceptable to include

### 5. Forward Return Completeness
- Forward returns for the last 20 trading days in the study period will be NULL (window not yet closed)
- Filter: `WHERE setup_date <= MAX(setup_date) - 20 trading days` for studies using OV-01 (10d)
- Filter more conservatively for OV-02 (20d horizon)

### 6. Setup Type Representativeness
- Confirm N per setup type before stratifying:
  - `SELECT setup_type, COUNT(*) FROM setup_log WHERE fwd_return_10d IS NOT NULL GROUP BY setup_type`
- Apply minimum N thresholds from [Statistical_Guidelines.md](Statistical_Guidelines.md)

### 7. Prices-Adjusted vs Raw Prices
- All pivot calculations in `stock_signals` use `prices_adjusted`
- All factor values in `stock_signals` are derived from `prices_adjusted`
- Studies joining to price data must use `prices_adjusted`, not `prices`
- One exception: recent dates where `prices_adjusted` incremental append has not yet been run

---

## Known Data Issues

### Issue 1 — BREAKOUT Backfill vs Daily Hook Inconsistency
**What:** Historical `setup_log` BREAKOUT rows include all `bos_flag = 1` days (multi-day holding). The daily hook (`append_setup_log_today`) inserts BREAKOUT only on the transition day (`prev bos_flag = 0`).

**Research implication:** Studies on `setup_type = 'BREAKOUT'` will include duplicate-signal rows for the same breakout event (day 1, day 2, day 3 of the same breakout all have rows). Raw win-rate calculations are overstated for multi-day breakouts because the easy subsequent days are counted as separate setups.

**Required mitigation:** For BREAKOUT studies, deduplicate using `MIN(setup_date)` per (`symbol`, breakout event start). An alternative is to study only the first occurrence per symbol per 20-day window.

### Issue 2 — outcome_label Default at Insert
**What:** `outcome_label` is set to `BREAKEVEN` at insert time as a default. Only after `compute_forward_returns.py` fills `fwd_return_10d` and the label update runs is the outcome WINNER/LOSER.

**Research implication:** Never filter on `outcome_label = 'BREAKEVEN'` to find genuinely flat trades. Always check `fwd_return_10d IS NOT NULL` and `ABS(fwd_return_10d) < threshold` instead.

### Issue 3 — Small Sector Breadth Instability
**What:** Sectors with fewer than 5 stocks produce unstable `breadth_score` values. A single stock moving its price by 1% can flip the breadth score from 0% to 25%.

**Research implication:** Exclude sectors with fewer than 5 stocks from breadth-based studies, or flag their breadth scores as unreliable.

### Issue 4 — TRENDING_DOWN Regime Rarity
**What:** TRENDING_DOWN regime represents approximately 10–11% of the historical trading days. Most PSX bear markets are brief.

**Research implication:** Studies stratified by TRENDING_DOWN will consistently have sub-50 cells for most setup types. Report these as Weak confidence and do not draw firm conclusions.

### Issue 5 — KSE-100 Symbol Hyphen
**What:** The KSE-100 index is stored with a hyphen in symbol format (`KSE-100`, not `KSE100`). Joins that use the index symbol must use the exact stored format.

**Research implication:** Queries filtering on `symbol = 'KSE100'` will return zero rows. Always use `symbol = 'KSE-100'`.

### Issue 6 — Pivot Price Source
**What:** Pivot prices in `stock_signals` are computed from `prices_adjusted`, not from `prices`. The pivot level for a stock reflects the adjusted price history, not the raw price as seen on a live screen.

**Research implication:** When comparing pivot levels from `stock_signals` to current live prices, ensure the live price is also on an adjusted basis.

---

## Data Version Tracking

For reproducibility, record with every study:

| Field | Value |
|---|---|
| `prices_adjusted` row count | [record at time of study] |
| `setup_log` row count | [record at time of study] |
| `stock_signals` row count | [record at time of study] |
| MAX date in `stock_signals` | [record] |
| MAX date in `setup_log` | [record] |
| Any PENDING corporate action suspects | [list symbol and date, or "None"] |

---

## Data Exclusions — Automatic

The following are automatically excluded from all studies unless a specific study specifically includes them:

- Symbols in `EXCLUDED_SECTORS` (from `config.py`): Textile Spinning, Modarabas, Sugar & Allied Industries, and others
- Futures symbols matching regex `-JAN/-FEB/-MAR/...`
- Rows where `avg_vol_10d < 200000` (minimum liquidity threshold already applied in `setup_log` construction for most types)
- Rows where `fwd_return_10d IS NULL` when OV-01 is the outcome
- Rows where `setup_date > [study close date]`

---

*Update the Known Data Issues section when new data problems are discovered. Tag with discovery date.*
