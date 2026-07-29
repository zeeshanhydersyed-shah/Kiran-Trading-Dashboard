# Validation Framework — PSX Quantitative Research Platform

> **Purpose:** Defines how findings are validated before elevation to evidence and before use in the conviction engine. Distinguishes in-sample discovery from out-of-sample confirmation.  
> **Related:** [Research_Standards.md](Research_Standards.md) · [Statistical_Guidelines.md](Statistical_Guidelines.md) · [Evidence_Standards.md](Evidence_Standards.md) · [Conviction_Engine_Specification.md](Conviction_Engine_Specification.md)

---

## The Validation Problem

Any pattern identified by examining historical data is vulnerable to being a statistical artifact of that specific period. A factor that "worked" from 2020–2023 may have done so by chance, or due to a regime that no longer exists.

Validation is the process of testing whether a discovered pattern holds on data the discovery process never saw.

---

## Validation Tiers

| Tier | What It Tests | Required For |
|---|---|---|
| 1 — In-Sample Consistency | Result holds across different regimes within the study period | Moderate confidence |
| 2 — Temporal Stability | Result holds in early half vs late half of study period | Moderate confidence |
| 3 — Out-of-Sample (OOS) | Result holds on a held-out data window never used in discovery | Strong confidence |
| 4 — Walk-Forward | Result holds on a rolling sequence of OOS windows | Strong confidence (highest standard) |

A finding must achieve at least Tier 1 and Tier 2 before reaching the Evidence Register. Tier 3 is required for Strong confidence and for any factor incorporated into the conviction engine.

---

## Data Partitioning Policy

### Chronological Split (Primary Method)

```
Full dataset: 2020-01-01 → latest date

In-Sample:     2020-01-01 → 2023-12-31   (~70% of data by time)
Out-of-Sample: 2024-01-01 → latest date  (~30% of data by time)
```

**Rules:**
- The OOS split date is fixed at 2024-01-01 for all studies to ensure consistency
- The OOS window is never examined during the discovery phase
- Findings are initially developed and thresholds selected exclusively on the in-sample window
- The OOS window is applied once, after all parameters are fixed

### When OOS Window is Too Small

If the OOS window contains < 30 observations per group for the studied setup type:

- Report Tier 2 (temporal stability within the IS period) instead
- Flag confidence as Moderate, not Strong
- Note the limitation explicitly

---

## Tier 1 — In-Sample Consistency Checks

For every study result, verify:

- [ ] Does the result hold in TRENDING_UP regime? (report N and win rate)
- [ ] Does the result hold in RANGING regime? (report N and win rate)
- [ ] Is the direction of the effect consistent across regimes, even if magnitude differs?
- [ ] Does the result hold in both the first and second halves of the in-sample period?

A result that only exists in one regime or one time sub-period is labelled `Regime-Conditional` and cannot receive Moderate confidence without explicit regime qualification.

---

## Tier 2 — Temporal Stability

Split the in-sample period approximately in half by date and compare:

| Period | N | Win Rate | Mean Return |
|---|---|---|---|
| Early IS (2020–2021) | | | |
| Late IS (2022–2023) | | | |

A result is temporally stable if the direction of the effect is the same in both halves and the magnitude is broadly similar (within ~30% of each other).

---

## Tier 3 — Out-of-Sample Validation

**Protocol:**
1. Freeze all factor definitions, thresholds, and filters from the in-sample study
2. Apply them to the OOS window (2024–present) without modification
3. Record OOS N, win rate, mean return, and standard deviation
4. Compare to IS result

| Outcome | Interpretation |
|---|---|
| OOS result within ±5pp of IS win rate | Full confirmation → Strong confidence |
| OOS result direction same but magnitude weaker (−5 to −10pp) | Partial confirmation → Moderate confidence |
| OOS result direction reversed | OOS failure → finding degraded to Weak; do not use in engine |
| OOS N too small (< 30/group) | Inconclusive → maintain Moderate, flag for future revalidation |

**OOS failure policy:** An OOS failure does not delete the in-sample finding, but demotes it. The IS pattern existed; it may be regime-specific or period-specific. Document and move on.

---

## Tier 4 — Walk-Forward Validation

Used for the conviction engine before production deployment.

**Protocol:**
- Define a training window length (e.g., 24 months) and a test window length (e.g., 6 months)
- Train on window 1, test on the following test window
- Roll forward: train on window 2, test on the next window
- Aggregate test results across all folds

This is the most rigorous test of temporal stability and is the standard required before the conviction engine enters the Explorer page.

---

## Validation Status Tracking

Each study's validation status is tracked in [Research_Log.md](Research_Log.md):

| Validation Tier | Status |
|---|---|
| Tier 1 — In-Sample Consistency | Not run / Pass / Fail / Partial |
| Tier 2 — Temporal Stability | Not run / Pass / Fail / Partial |
| Tier 3 — Out-of-Sample | Not run / Pass / Fail / Partial / Insufficient data |
| Tier 4 — Walk-Forward | Not run / Pass / Fail / N/A |

---

## Confidence Level Map

| Tiers Passed | Confidence Level |
|---|---|
| Tier 1 + Tier 2 | Moderate |
| Tier 1 + Tier 2 + Tier 3 (Pass) | Strong |
| Tier 1 or 2 only | Weak |
| Tier 3 Fail | Downgrade to Weak regardless of IS result |
