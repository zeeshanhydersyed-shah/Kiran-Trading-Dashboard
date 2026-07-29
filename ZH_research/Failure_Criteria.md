# Failure Criteria — PSX Quantitative Research Platform

> **Purpose:** Defines the objective, measurable conditions that would cause a deployed conviction engine to be suspended, revised, or retired. These are the "kill switches."  
> **Related:** [Acceptance_Criteria.md](Acceptance_Criteria.md) · [Conviction_Engine_Specification.md](Conviction_Engine_Specification.md) · [Validation_Framework.md](Validation_Framework.md)

---

## Principle

A system that no longer works should not continue to be used. These failure criteria define when the conviction engine has demonstrably failed and must be taken offline for revision. They are set before deployment so that the decision to suspend is objective, not emotional.

---

## Pre-Deployment Failure Criteria (Prevent Launch)

If any of the following are observed during validation, the engine cannot be launched:

| Condition | Threshold | Action |
|---|---|---|
| OOS win rate for Very High scores is lower than for Low scores | Any inversion | Do not launch; redesign factor weights |
| Any factor has opposite directional effect OOS vs IS | Any reversal | Remove that factor from the engine; re-validate |
| Score distribution is degenerate | > 90% of signals fall into a single score bin | Recalibrate score mapping |
| Gate 3 N thresholds not met | OOS N < 200 total | Wait for more OOS data; do not launch early |

---

## Post-Deployment Failure Criteria (Trigger Suspension)

Monitor these on a rolling 90-day basis after deployment:

### FC-01 — Win Rate Inversion
**Trigger:** The rolling 90-day win rate for Very High conviction signals drops below the win rate for Moderate or Low conviction signals.

**Action:** Suspend the engine immediately. Open a diagnostic study. Do not resume until the cause is identified and addressed.

---

### FC-02 — Overall Win Rate Collapse
**Trigger:** The rolling 90-day overall win rate (all signals combined) drops more than 15 percentage points below the historical in-sample base rate.

**Action:** Suspend the engine. Evaluate whether the market regime has changed in a way that makes the model's factors non-predictive.

**Note:** A 15pp decline is a large and material move. A modest decline of 3–5pp during a regime transition is normal and does not trigger this criterion.

---

### FC-03 — Score Calibration Drift
**Trigger:** Two consecutive 90-day windows show that the score is no longer monotonically increasing in win rate (middle score bins outperform Very High bins).

**Action:** Recalibrate score-to-probability mapping. If recalibration is insufficient, rebuild the engine with a revised factor set.

---

### FC-04 — Factor Sign Reversal
**Trigger:** A factor that was validated as positively predictive (higher factor = better outcome) shows a negative effect (higher factor = worse outcome) in two consecutive 90-day windows.

**Action:** Remove the factor from the engine immediately. Open a study to investigate the reversal. Consider whether a market structural change has occurred.

---

### FC-05 — Regime Shift
**Trigger:** Market regime changes to TRENDING_DOWN and remains there for more than 60 trading days.

**Action:** This is not automatic failure, but the engine should be flagged as "Under Review — Regime Shift." All IS training data was predominantly TRENDING_UP; the engine's performance in sustained downtrends is not well-validated. Trade with reduced conviction weighting during this period.

---

## Retirement Criteria

The conviction engine (a specific version) is retired when:

1. A successor version (with better acceptance test results) is ready for deployment AND
2. The successor version has been validated on at least 90 days of OOS data

A retired version's study set is preserved in [Model_Registry.md](Model_Registry.md).

---

## Failure Log

| Date | Criterion | Observed Value | Decision | Resolution |
|---|---|---|---|---|
| — | — | — | — | — |

*Record all FC triggers here, even if the decision is to continue operating with modifications.*
