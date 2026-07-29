# Research Review Checklist — PSX Quantitative Research Platform

> **Purpose:** A final review gate before a study's findings are accepted into the Evidence Register. Every completed study must pass this checklist.  
> **Related:** [Research_Workflow.md](Research_Workflow.md) · [Bias_Checklist.md](Bias_Checklist.md) · [Evidence_Standards.md](Evidence_Standards.md)

---

## How to Use

When a study reaches the **Review** state in [Research_Pipeline.md](Research_Pipeline.md):

1. Open this checklist and the study's draft findings
2. Work through every section below
3. Record any failures or concerns alongside the relevant item
4. If all items pass: promote to **Closed** and write the Evidence Register entry
5. If any items fail: return to Analysis or flag for revision

---

## Section A — Pre-Registration Integrity

| # | Check | Pass / Fail / N/A |
|---|---|---|
| A-1 | The hypothesis was registered in [Hypotheses.md](Hypotheses.md) before data was examined | |
| A-2 | The primary outcome variable was declared before analysis (not chosen after seeing results) | |
| A-3 | The study design (filters, date range, factor definition) matches what was pre-registered | |
| A-4 | Any deviations from the registered design are documented and justified | |

---

## Section B — Data Quality

| # | Check | Pass / Fail / N/A |
|---|---|---|
| B-1 | Row counts match the expected counts from [Data_Quality_Policy.md](Data_Quality_Policy.md) | |
| B-2 | NULL rates were checked for all variables; high NULL rates are explained | |
| B-3 | `fwd_return_10d IS NOT NULL` filter was applied before computing win rates | |
| B-4 | No corporate action suspects (PENDING) for study symbols affect the results | |
| B-5 | `prices_adjusted` was used (not `prices`) for any price-derived joins | |
| B-6 | The study exclusively uses in-sample data (2020–2023) unless explicitly OOS | |

---

## Section C — Sample Size

| # | Check | Pass / Fail / N/A |
|---|---|---|
| C-1 | Total N is reported and meets minimum thresholds per [Statistical_Guidelines.md](Statistical_Guidelines.md) | |
| C-2 | N per subgroup (regime, sector, setup type) is reported and confidence level is appropriate | |
| C-3 | Any subgroup with N < 30 is flagged as Weak and no conclusion is drawn from it | |
| C-4 | BREAKOUT signals were deduplicated if the study requires transition-day-only analysis | |

---

## Section D — Statistical Correctness

| # | Check | Pass / Fail / N/A |
|---|---|---|
| D-1 | The primary metric is win rate (OV-04) and/or mean return (OV-01 or OV-02) | |
| D-2 | Confidence intervals are reported for the primary finding | |
| D-3 | If multiple factors or subgroups were tested, a multiple-testing correction was applied | |
| D-4 | The claimed p-value threshold matches the declared standard (p < 0.05) | |
| D-5 | Effect size is reported (win-rate difference in pp, or mean return difference in %) | |
| D-6 | The result is not described as "statistically significant" without also reporting effect size | |

---

## Section E — Bias Assessment

| # | Check | Pass / Fail / N/A |
|---|---|---|
| E-1 | The Bias Checklist (Section A–I in [Bias_Checklist.md](Bias_Checklist.md)) was run and all items passed | |
| E-2 | No look-ahead bias: all factors use only data available at or before the signal date | |
| E-3 | No survivorship bias: the study universe matches the available universe at signal date | |
| E-4 | No selection bias from studying only a subset chosen after seeing the results | |
| E-5 | The in-sample / out-of-sample boundary was not crossed | |

---

## Section F — Interpretive Soundness

| # | Check | Pass / Fail / N/A |
|---|---|---|
| F-1 | The finding is stated precisely (what was measured, in what population, over what period) | |
| F-2 | The conclusion matches the evidence (no overclaiming, no underclaiming) | |
| F-3 | Limitations specific to this study are stated in the finding | |
| F-4 | If a null result: it is documented with the same precision as a positive finding | |
| F-5 | The finding references any known limitations from [Known_Limitations.md](Known_Limitations.md) that are relevant | |

---

## Section G — Reproducibility

| # | Check | Pass / Fail / N/A |
|---|---|---|
| G-1 | The exact SQL or analysis steps are recorded in the study entry | |
| G-2 | Table row counts, date ranges, and column names are recorded at time of study | |
| G-3 | Any custom filters applied beyond the standard exclusions are documented | |
| G-4 | Another researcher could reproduce the result from the documented steps alone | |

---

## Section H — Evidence Register Integration

| # | Check | Pass / Fail / N/A |
|---|---|---|
| H-1 | The Evidence Register entry is written and matches the finding | |
| H-2 | Confidence level is assigned (Strong / Moderate / Weak / Inconclusive) | |
| H-3 | The study ID is linked from the relevant hypothesis in [Hypotheses.md](Hypotheses.md) | |
| H-4 | If applicable, the Factor Catalog predictive value column has been updated | |
| H-5 | If the finding affects an existing assumption, [Assumption_Register.md](Assumption_Register.md) has been updated | |

---

## Review Decision

| Field | Value |
|---|---|
| Study ID | |
| Reviewer | |
| Review date | |
| Outcome | ☐ Accepted ☐ Returned for revision ☐ Rejected |
| Conditions (if returned) | |
