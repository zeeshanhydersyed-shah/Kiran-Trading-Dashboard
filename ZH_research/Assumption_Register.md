# Assumption Register — PSX Quantitative Research Platform

> **Purpose:** Records every assumption this research platform depends on. Assumptions are validated before being relied upon; unvalidated assumptions are flagged. If an assumption is violated, all studies that depend on it must be reviewed.  
> **Related:** [Known_Limitations.md](Known_Limitations.md) · [Data_Quality_Policy.md](Data_Quality_Policy.md) · [Research_Standards.md](Research_Standards.md)

---

## Assumption Classification

| Class | Meaning |
|---|---|
| **Data** | Assumption about the database, data pipeline, or data quality |
| **Market** | Assumption about how PSX markets behave |
| **Methodology** | Assumption about how research is conducted |
| **Model** | Assumption about how factors relate to outcomes |

| Status | Meaning |
|---|---|
| **Validated** | Explicitly tested and confirmed |
| **Accepted** | Accepted without explicit validation; widely held; low risk |
| **Unvalidated** | Assumed but not tested; risk should be noted in studies |
| **Violated** | Found to be false; dependent studies must be reviewed |

---

## Data Assumptions

| ID | Assumption | Class | Status | Validation Evidence | Dependent Studies |
|---|---|---|---|---|---|
| A-01 | `prices_adjusted` contains corporate-action-adjusted prices that correctly reflect the economic experience of a stock holder (splits, dividends normalised) | Data | Accepted | Corporate action pipeline reviewed in code audit; `apply_price_adjustments.py` applies factors to pre-event rows | All studies using price-derived factors |
| A-02 | `stock_signals` factors are computed without look-ahead bias (all calculations at T use only data available before or at T) | Data | Accepted | Traced from `stock_signals.py`; EMA uses historical lookback with 3× warmup; pivot requires `right=10` confirmation lag | All factor studies |
| A-03 | `setup_log` forward returns are computed correctly: `(close[T+N] − close[T]) / close[T] × 100` using adjusted prices | Data | Accepted | Traced from `compute_forward_returns.py` design | All outcome studies |
| A-04 | The sector assignment of each stock is stable enough for sector-level analysis (i.e., sector reclassifications are rare) | Data | Unvalidated | Not explicitly tested | All sector-stratified studies |
| A-05 | `active_stocks_on_date` correctly identifies which stocks were traded on each date (preventing survivorship-biased universe selection) | Data | Accepted | Table confirmed; noted in PSX DB Schema Notes | Universe construction for all studies |

---

## Market Assumptions

| ID | Assumption | Class | Status | Validation Evidence | Dependent Studies |
|---|---|---|---|---|---|
| A-06 | PSX price action exhibits momentum and trend characteristics similar to other equity markets (i.e., Weinstein-style stage analysis is applicable) | Market | Unvalidated | Strategic rationale exists; formal validation pending (this is a primary research question) | Entire conviction engine framework |
| A-07 | The KSE-100 index is a valid benchmark for computing relative strength for individual stocks | Market | Accepted | Standard practice; KSE-100 is the primary PSX index | All RS-based factors (F-01 through F-06) |
| A-08 | A breakout above a pivot high with volume confirms institutional demand (price-volume relationship) | Market | Unvalidated | No formal study on PSX yet; imported from developed market evidence | BREAKOUT setup logic |
| A-09 | Market regime at the signal date is predictive of the environment for the signal's forward return window (i.e., regime is stable enough across 10–20 days) | Market | Unvalidated | Regime duration data available (F-38) but not studied | All regime-stratified studies |
| A-10 | PSX liquidity is sufficient for the studied setup types when `avg_vol_10d > 200000` | Market | Accepted | Chosen as minimum liquidity filter; not formally validated for slippage effects | All studies using `setup_log` (filter already applied) |

---

## Methodology Assumptions

| ID | Assumption | Class | Status | Validation Evidence | Dependent Studies |
|---|---|---|---|---|---|
| A-11 | 2023-12-31 is an appropriate in-sample / out-of-sample cutoff (not chosen to optimise OOS performance) | Methodology | Validated | Cutoff chosen before any OOS analysis; consistent with platform build timeline | All studies reporting OOS results |
| A-12 | Minimum N thresholds (N≥200 Strong, N≥50 Moderate, N≥30 Weak) are appropriate for this dataset | Methodology | Accepted | Derived from standard statistical practice; specific to this platform's effect sizes | All confidence assessments |
| A-13 | The `setup_log` is a sufficient representation of the breakout-type signal universe (i.e., there are no major signal types that are absent) | Methodology | Accepted | Four setup types implemented; rationale documented in platform design | All studies using `setup_log` |
| A-14 | Studies conducted on in-sample data (2020–2023) will generalise to post-2024 conditions on PSX | Methodology | Unvalidated | This is the core hypothesis of the entire research program; OOS validation is how it will be tested | Every study with OOS phase |

---

## Model Assumptions

| ID | Assumption | Class | Status | Validation Evidence | Dependent Studies |
|---|---|---|---|---|---|
| A-15 | The conviction engine score can be meaningfully constructed from a weighted sum of factor scores (linearity assumption) | Model | Unvalidated | Implicit in the design; non-linear factor interactions not yet studied | Conviction Engine Specification |
| A-16 | Higher RS scores at time of signal predict better forward returns (monotonic positive relationship) | Model | Unvalidated | Primary hypothesis H-01 (proposed); not yet studied | All RS factor studies |
| A-17 | Stage 2 classification provides additive signal on top of RS rank (not fully redundant) | Model | Unvalidated | Stage 2 includes EMA conditions beyond RS; correlation risk noted in taxonomy | Factor Interaction Studies |
| A-18 | The factor importance rankings from `kiran_model.pkl` (LightGBM) are informative for prioritising research questions | Model | Accepted with caution | The ML model is trained on `backtest_setups` (4,344 rows), a different and smaller population than `setup_log`. Rankings may differ on the larger dataset. | Research prioritisation only |

---

## Managing Violated Assumptions

If an assumption is found to be violated (status → Violated):

1. Record the violation date and the evidence
2. List all studies that were conducted under the violated assumption
3. For each dependent study: assess whether the violation materially changes the finding
4. Mark findings as **Under Review** in the Evidence Register until reassessment is complete
5. Open a correction study if the violation is material

---

*Update status column as assumptions are validated or violated. Add new assumptions as they are identified.*
