# Acceptance Criteria — PSX Quantitative Research Platform

> **Purpose:** Defines the objective, measurable gates that the Conviction Engine must pass before it can be deployed to the dashboard and used to influence trading decisions.  
> **Related:** [Conviction_Engine_Specification.md](Conviction_Engine_Specification.md) · [Failure_Criteria.md](Failure_Criteria.md) · [Validation_Framework.md](Validation_Framework.md)

---

## Principle

A system does not go live because it was built. It goes live because it passed pre-defined tests. These criteria are set before any engine construction begins so that they cannot be adjusted to make a failing system look passing.

---

## Gate 1 — Evidence Completeness

Before V1 engine construction can begin:

- [ ] At least 5 factors have completed studies with Moderate or High confidence
- [ ] At least 1 market-regime factor has completed study
- [ ] At least 1 sector-level factor has completed study
- [ ] All factors to be included have their evidence recorded in [Evidence_Register.md](Evidence_Register.md)
- [ ] No included factor has Confidence = Weak as its only study

---

## Gate 2 — In-Sample Calibration

Before OOS testing begins:

- [ ] The score is monotonically increasing in observed win rate: higher scores correspond to higher win rates across all score bins
- [ ] The score discrimination is non-trivial: the difference in win rate between the top score quartile and the bottom score quartile is at least 10 percentage points
- [ ] The score is not dominated by a single factor: if the top-weighted factor is removed, the score still shows positive discrimination

---

## Gate 3 — Out-of-Sample Validation

Before dashboard deployment:

- [ ] OOS period is 2024-01-01 onwards
- [ ] OOS N ≥ 200 total (across all score levels)
- [ ] OOS N ≥ 30 in each of the four score bands (Low / Moderate / High / Very High)
- [ ] The OOS win rate for Very High scores exceeds the OOS win rate for Low scores by a statistically significant margin (p < 0.05)
- [ ] The direction of all factor effects is preserved in OOS (no factor that was positive IS becomes negative OOS)
- [ ] OOS overall win rate is within ±10pp of IS overall win rate (no evidence of extreme overfitting)

---

## Gate 4 — Explainability

Before dashboard deployment:

- [ ] Every score can be decomposed into its contributing factors (the "why" can be shown to the trader)
- [ ] The factor decomposition agrees with the score direction (if the score is High, the top factors shown are positive; if Low, they are negative)
- [ ] The conviction label (Very High / High / Moderate / Low) is displayed alongside the numeric score

---

## Gate 5 — Practical Safety

Before dashboard deployment:

- [ ] The engine is clearly labelled as a research tool and signal quality filter, not a trading recommendation
- [ ] The explorer page shows the conviction score with a clear explanation accessible to the trader (e.g., a tooltip or expander documenting what each level means)
- [ ] A score of Very High does not override or bypass stop-loss discipline — this is documented in the UI

---

## Gate 6 — Live Monitoring Commitment

Before dashboard deployment:

- [ ] A monitoring plan exists: how often will score calibration be checked post-deployment?
- [ ] A drift detection rule is defined: what would cause the engine to be suspended? (See [Failure_Criteria.md](Failure_Criteria.md))
- [ ] The engine version is recorded and tied to the specific study set that produced it (see [Model_Registry.md](Model_Registry.md))

---

## Acceptance Decision Record

| Gate | Pass/Fail | Date | Notes |
|---|---|---|---|
| Gate 1 — Evidence Completeness | Not tested | — | Awaiting first studies |
| Gate 2 — IS Calibration | Not tested | — | Awaiting engine build |
| Gate 3 — OOS Validation | Not tested | — | Awaiting OOS data growth |
| Gate 4 — Explainability | Not tested | — | Awaiting engine build |
| Gate 5 — Practical Safety | Not tested | — | Awaiting dashboard design |
| Gate 6 — Monitoring Commitment | Not tested | — | Awaiting deployment planning |

---

*Update this record when each gate is formally tested. A gate cannot be partially passed — it is Pass or Fail.*
