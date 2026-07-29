# Research Standards — PSX Quantitative Research Platform

> **Purpose:** Defines the quality bar every study must meet. Standards apply uniformly regardless of whether the result is positive, negative, or inconclusive.  
> **Related:** [Research_Governance.md](Research_Governance.md) · [Statistical_Guidelines.md](Statistical_Guidelines.md) · [Bias_Checklist.md](Bias_Checklist.md) · [Reproducibility_Policy.md](Reproducibility_Policy.md)

---

## Standard 1 — Pre-Registration

**Rule:** Every study must document its hypothesis, methodology, and expected outcome *before* any data is examined.

- Write the hypothesis in [Hypotheses.md](Hypotheses.md) first
- Write the full methodology section of the Research_Log entry before running queries
- State what result would confirm and what would reject the hypothesis
- Changes to methodology after data has been examined must be disclosed and documented separately as a secondary analysis

---

## Standard 2 — Sample Size Minimums

See [Statistical_Guidelines.md](Statistical_Guidelines.md) for full derivations.

| Analysis Type | Minimum N per Group | Below Minimum |
|---|---|---|
| Win rate comparison | 50 | Flag as Weak confidence |
| Quintile analysis | 30 per quintile | Merge quintiles or flag |
| Regime-stratified study | 30 per regime-group cell | Flag or exclude cells |
| Interaction study (2 binary factors) | 30 per cell (4 cells) | Collapse or flag |
| Out-of-sample validation | 30 per group | Required; results invalid without it |

---

## Standard 3 — Outcome Variable Consistency

- Use only outcome variables defined in [Outcome_Definitions.md](Outcome_Definitions.md)
- Do not introduce new outcome variables mid-study
- Use the same forward horizon throughout one study (do not cherry-pick the horizon with the best result)
- If multiple horizons are reported, the primary horizon must be declared before data is examined

---

## Standard 4 — Deduplication

- Consecutive-day signals for the same symbol in the same streak count as **one** observation, not N
- Deduplication rule must be stated in the methodology section
- Default rule: first day of each qualifying streak per symbol per setup type
- Alternative rules must be justified and disclosed

---

## Standard 5 — Reporting Completeness

Every completed study must report:

- [ ] N for each group (not just total N)
- [ ] Win rate for each group
- [ ] Mean return for each group
- [ ] Standard deviation for each group
- [ ] The comparison metric (difference in means, win rate delta, etc.)
- [ ] Whether statistical significance was tested and the result
- [ ] Limitations specific to this study
- [ ] Whether null results were observed and how they were handled

Selective reporting of favourable groups without disclosing unfavourable groups is prohibited.

---

## Standard 6 — Causality

- Research on this platform establishes **association**, not causation
- Never write "Factor X causes better returns"
- Write "Factor X is associated with higher median returns in the studied period"
- Causal language is reserved for the [Decisions.md](Decisions.md) context section only, where it must be clearly qualified

---

## Standard 7 — Comparison to Baseline

Every finding must be compared to the unconditional baseline:

- What is the overall win rate for this setup type with no filter applied?
- Does the factor produce a meaningful improvement above baseline?
- A filter that produces a 52% win rate when the baseline is 51% is not material

---

## Standard 8 — Out-of-Sample Validation

- Any finding intended for use in the conviction engine must be validated on a held-out data period
- The in-sample period and out-of-sample period must be defined before the study begins
- Threshold values must not be re-optimised on the out-of-sample period
- See [Validation_Framework.md](Validation_Framework.md) for the full protocol

---

## Standard 9 — Null Results

- A null result (factor does not predict outcomes) is recorded identically to a positive result
- Null results close the research question and prevent future duplication of effort
- Null results are marked `Rejected` in [Hypotheses.md](Hypotheses.md) and do not receive an Evidence Register entry
- The completed study entry in Research_Log.md serves as the permanent record

---

## Standard 10 — Language and Precision

| Do | Do Not |
|---|---|
| "Median 20d return was +4.2% (N=187)" | "Returns were good" |
| "Win rate difference: 58% vs 49% (Δ9pp)" | "Much higher win rate" |
| "Associated with higher returns in TRENDING_UP regime" | "Works in bull markets" |
| "Confidence: Moderate (not yet OOS validated)" | "This is a reliable signal" |
| "Result is consistent with H-003" | "This proves the hypothesis" |

---

*These standards apply to all work in [Research_Log.md](Research_Log.md). Any deviation must be noted explicitly in the study entry's Limitations section.*
