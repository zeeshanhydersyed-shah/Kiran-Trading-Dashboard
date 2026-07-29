# Statistical Guidelines — PSX Quantitative Research Platform

> **Purpose:** Defines the statistical methods, thresholds, and interpretation standards for all studies on this platform.  
> **Related:** [Research_Standards.md](Research_Standards.md) · [Bias_Checklist.md](Bias_Checklist.md) · [Validation_Framework.md](Validation_Framework.md) · [Outcome_Definitions.md](Outcome_Definitions.md)

---

## Section 1 — Minimum Sample Sizes

Minimum N per group before a finding is reportable:

| Analysis Type | Min N per Group | Confidence Available |
|---|---|---|
| Binary group comparison (win rate) | 50 | Moderate or Strong |
| Quintile/decile analysis | 30 per bucket | Moderate |
| 2-factor interaction (2×2 table) | 30 per cell | Moderate |
| Regime-stratified subgroup | 30 per cell | Moderate |
| Out-of-sample validation | 30 per group | Required for Strong |
| Win rate with N < 30 | Reportable but flagged | Weak only |
| Win rate with N < 15 | Do not report | Not reportable |

---

## Section 2 — Outcome Metrics

Report all of the following for every group comparison. Never report only win rate or only mean return.

| Metric | Definition | Why Required |
|---|---|---|
| N | Row count (after deduplication) | Assesses reliability |
| Win Rate | % of rows with positive outcome | Primary binary metric |
| Mean Return | Average forward return (%) | Captures magnitude |
| Median Return | Median forward return (%) | Robust to outliers |
| Standard Deviation | Std of forward returns | Measures consistency |
| Win Rate Delta | Win rate (group) − Win rate (baseline) | Measures incremental value |
| Mean Return Delta | Mean (group) − Mean (baseline) | Measures magnitude increment |

---

## Section 3 — Baseline Comparison

Every group result must be compared to the unconditional baseline for the same setup type and regime.

**Baseline = all rows of that setup type in that regime, before any factor filter.**

A factor adds value only if:
- Win rate delta > +5 percentage points, **AND**
- Mean return delta > +1.0%, **AND**
- N ≥ 50

Meeting only one criterion is not sufficient.

---

## Section 4 — Statistical Significance

This platform does **not** rely on p-values as the primary decision criterion. Effect size and economic significance are prioritised. However, significance testing is used as a supporting check.

**Recommended test for win rate comparison:** Two-proportion z-test  
**Recommended test for return comparison:** Mann-Whitney U (non-parametric; return distributions are typically non-normal)  
**Significance threshold:** p < 0.05 (two-tailed)  
**Adjustment for multiple comparisons:** Apply Bonferroni correction when testing > 5 hypotheses in the same study

**Interpretation rule:**
- A statistically significant result with small effect size (e.g., Δwin rate < 3pp) is noted but not acted on
- A large effect size (Δwin rate ≥ 8pp) with marginal significance (p ≈ 0.07) is noted and flagged for replication

---

## Section 5 — Distribution Considerations

PSX forward returns are typically:
- Right-skewed (large gains are rarer but more extreme than large losses)
- Regime-dependent (volatility differs significantly across TRENDING_UP vs RANGING)
- Not normally distributed

**Implications:**
- Always report median alongside mean
- Do not assume normality in significance tests → use non-parametric alternatives
- Be cautious of studies where a small number of large positive outliers drive the mean

---

## Section 6 — Multiple Testing

**Problem:** Testing 20 factors on the same dataset produces ~1 false positive at p < 0.05 by chance.

**Policy:**
- Pre-specify the primary hypothesis and primary outcome variable per study
- Secondary analyses (additional factors, horizons) are reported as exploratory, not confirmatory
- Bonferroni correction: when running K tests in one study, require p < 0.05/K for any single test to be considered significant
- Findings from exploratory analyses require independent replication (a separate study) before elevation to evidence

---

## Section 7 — Effect Size Interpretation

For win rate differences:

| Delta (pp) | Interpretation |
|---|---|
| < 3 | Negligible — not actionable |
| 3–5 | Small — monitor; not alone sufficient |
| 5–10 | Moderate — material if consistent across regimes |
| > 10 | Large — strong candidate for conviction factor |

For mean return differences:

| Delta (%) | Interpretation |
|---|---|
| < 0.5 | Negligible |
| 0.5–1.5 | Small |
| 1.5–3.0 | Moderate |
| > 3.0 | Large |

---

## Section 8 — Correlation Between Factors

Before studying a factor combination, check for correlation with already-studied factors.

**Guideline:** If two factors have Pearson r > 0.7 across the study population, treat them as correlated. Report this. Do not count them as independent predictors.

Correlation does not mean one factor is redundant — they may each carry distinct information. But they may not be treated as adding 2× the predictive power of one.

---

## Section 9 — Out-of-Sample Validation Protocol

See [Validation_Framework.md](Validation_Framework.md) for full detail.

**Minimum requirement:**
- Study dataset split: 70% in-sample, 30% out-of-sample (or chronological split if data quantity allows)
- In-sample: identification and threshold selection
- Out-of-sample: apply thresholds without re-optimisation; report result
- A finding drops from `Moderate` to `Weak` if it fails out-of-sample validation

---

## Section 10 — Confidence Level Assignment

| Criteria | Level |
|---|---|
| N ≥ 200/group · Consistent across ≥ 2 regimes · OOS validated · Large effect size | Strong |
| N ≥ 50/group · Directionally consistent · Not OOS validated · Moderate effect size | Moderate |
| N < 50/group · Or single-regime · Or small effect size | Weak |
| Any study with undisclosed methodology deviation | Weak (regardless of other criteria) |

---

*Methodology questions not answered here should be resolved by consultation with [Research_Standards.md](Research_Standards.md) before proceeding.*
