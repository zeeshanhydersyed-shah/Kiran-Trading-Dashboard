# Bias Checklist — PSX Quantitative Research Platform

> **Purpose:** A mandatory checklist to be reviewed before beginning any study and again before closing it.  
> **Usage:** Copy into the study entry or complete independently and mark the study entry as "Bias checklist reviewed: Yes"  
> **Related:** [Research_Standards.md](Research_Standards.md) · [Statistical_Guidelines.md](Statistical_Guidelines.md) · [Known_Limitations.md](Known_Limitations.md)

---

## Instructions

Run this checklist **twice** per study:
1. **Before** executing any query (Pre-Study Review)
2. **Before** writing Conclusions (Pre-Close Review)

Mark each item: ✅ Clear · ⚠️ Risk present (document mitigation) · ❌ Unresolved (do not proceed)

---

## Section A — Look-Ahead Bias

| # | Check | Status | Notes |
|---|---|---|---|
| A1 | All signal factors were computable on the signal date using only prior data | | |
| A2 | `pivot_high` values used are confirmed pivots (10-bar confirmation) — not same-day highs | | |
| A3 | Market regime label on signal date does not require any data from after that date | | |
| A4 | `prices_adjusted` adjustment factors applied on signal dates were available at that time (corporate action risk) | | |
| A5 | No factor in the study implicitly requires knowledge of the outcome | | |

---

## Section B — Survivorship Bias

| # | Check | Status | Notes |
|---|---|---|---|
| B1 | Study includes all symbols active on the signal date, not only those still active today | | |
| B2 | Delisted symbols are included in the study with their available outcomes (or explicitly excluded with justification) | | |
| B3 | For long forward horizons (> 20d), symbols that were halted or delisted during the window are accounted for | | |
| B4 | The universe on the signal date is reconstructed from `symbol_active_dates`, not from today's active symbol list | | |

---

## Section C — Data Leakage

| # | Check | Status | Notes |
|---|---|---|---|
| C1 | No outcome variable is used as an input feature | | |
| C2 | `outcome_label` is not used as a feature anywhere in the study | | |
| C3 | Features are computed using only data up to (not including) the forward return window | | |
| C4 | No "future" sector or regime data is joined to signal-date rows | | |

---

## Section D — Selection Bias

| # | Check | Status | Notes |
|---|---|---|---|
| D1 | Setup type filter is applied consistently (not changed based on preliminary results) | | |
| D2 | Date range covers a representative mix of market regimes | | |
| D3 | Volume/liquidity filter is applied to exclude illiquid symbols, not to cherry-pick favourable ones | | |
| D4 | Sector filter (if any) is justified by the hypothesis, not applied to improve results | | |

---

## Section E — Overlapping Windows / Non-Independence

| # | Check | Status | Notes |
|---|---|---|---|
| E1 | Deduplication rule is stated and applied: one observation per (symbol, streak) | | |
| E2 | Consecutive-day signals for the same stock in the same setup type are collapsed to first day | | |
| E3 | Forward return windows do not overlap in a way that creates spurious correlation between observations | | |
| E4 | If windows do overlap (cannot be avoided), this limitation is stated and its effect on conclusions is discussed | | |

---

## Section F — Multiple Testing

| # | Check | Status | Notes |
|---|---|---|---|
| F1 | Primary hypothesis and primary outcome variable were stated before data was examined | | |
| F2 | Number of tests run in this study is documented | | |
| F3 | If > 5 tests were run, Bonferroni correction or equivalent was applied | | |
| F4 | Exploratory analyses are clearly labelled as exploratory, not confirmatory | | |

---

## Section G — Overfitting / Threshold Mining

| # | Check | Status | Notes |
|---|---|---|---|
| G1 | Threshold values were pre-specified in the hypothesis, not selected after seeing the data | | |
| G2 | If threshold was selected empirically, out-of-sample validation is required before elevation to evidence | | |
| G3 | Results are not reported only for the specific threshold that produced the best result | | |
| G4 | The number of threshold variants tested is disclosed | | |

---

## Section H — Regime / Non-Stationarity

| # | Check | Status | Notes |
|---|---|---|---|
| H1 | Results are stratified by market regime (TRENDING_UP / RANGING / TRENDING_DOWN) | | |
| H2 | The study does not treat 2020–2026 as a single homogeneous period without checking for temporal breaks | | |
| H3 | Date range includes at least one full regime cycle if possible | | |
| H4 | If results differ substantially by time period, this is reported | | |

---

## Section I — Reporting Bias

| # | Check | Status | Notes |
|---|---|---|---|
| I1 | All groups are reported, including those with unfavourable results | | |
| I2 | Null results are documented in the Conclusions section | | |
| I3 | The baseline win rate is reported alongside the factor-conditioned win rate | | |
| I4 | Effect size is reported; statistical significance alone is not used to declare success | | |

---

## Sign-Off

| Review | Date | Status |
|---|---|---|
| Pre-Study Review | | |
| Pre-Close Review | | |

**Any ❌ items must be resolved before the study proceeds or closes.**  
**⚠️ items must be documented in the study's Limitations section.**
