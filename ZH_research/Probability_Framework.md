# Probability Framework — PSX Quantitative Research Platform

> **Purpose:** Defines how probability estimates are derived, communicated, and used in this platform. Ensures that "probability" means something specific and measurable, not a vague qualitative label.  
> **Related:** [Conviction_Engine_Specification.md](Conviction_Engine_Specification.md) · [Statistical_Guidelines.md](Statistical_Guidelines.md) · [Evidence_Standards.md](Evidence_Standards.md)

---

## What Probability Means Here

In this platform, all probabilities are **empirical frequencies** — they are derived from observed win rates in historical data, not from theoretical distributions or subjective beliefs.

When the conviction engine says a setup has "70% probability of a positive outcome," it means:

> "In historical data matching this factor profile, approximately 70 out of 100 similar setups had a positive 10-day forward return."

This is a **frequentist interpretation**, not a Bayesian credibility interval or a theoretical model prediction.

---

## Base Rate (Prior Probability)

Before any factors are applied, the base rate is the overall win rate across all setups of the same type.

**Required base rates (to be established by formal study):**

| Setup Type | N (approx) | Base Rate Win% | Study |
|---|---|---|---|
| BREAKOUT | ~37,000 | Unknown | Pending |
| PRE_BREAKOUT | ~XX,XXX | Unknown | Pending |
| RS_LEADER_MARKET | ~XX,XXX | Unknown | Pending |
| RS_LEADER_SECTOR | ~XX,XXX | Unknown | Pending |

> Base rates must be computed from the deduplicated, properly filtered `setup_log` population (see [Data_Quality_Policy.md](Data_Quality_Policy.md)). They become the reference point for all factor effect-size calculations.

**Using base rate in the engine:**

The conviction score starts at the base rate and adjusts up or down based on factor evidence. A factor that has no predictive value keeps the score at the base rate. A factor that doubles the win rate over the base adds positive weight.

---

## Factor-Conditional Probability

For a binary factor (e.g., F-12 BOS Flag = 1 vs 0):

```
P(WIN | factor = 1) = observed wins among setups where factor = 1 / total setups where factor = 1
P(WIN | factor = 0) = observed wins among setups where factor = 0 / total setups where factor = 0
```

The factor effect is measured as:

```
lift = P(WIN | factor = 1) / base_rate_WIN
```

A lift of 1.2 means the factor raises the win rate by 20% relative to the base rate.

For a continuous factor (e.g., F-07 Base Tightness), the factor is binned into quantiles (typically quartiles or deciles) and the win rate is computed per bin.

---

## Probability Estimation Rules

### Rule 1 — Minimum N
Probability estimates require at least N=30 observations per cell to report as any confidence level. Below 30, report "Insufficient data" rather than a probability.

### Rule 2 — Confidence Intervals
All reported probabilities must include a 95% confidence interval. For a binary outcome with N observations and k wins:

```
p_hat = k / N
margin = 1.96 × sqrt(p_hat × (1 − p_hat) / N)
CI = [p_hat − margin, p_hat + margin]
```

A probability of 0.65 with N=40 has CI [0.50, 0.80] — wide. A probability of 0.65 with N=400 has CI [0.60, 0.70] — narrow and reliable.

### Rule 3 — OOS Confirmation
A probability estimate from in-sample data is provisional until confirmed in OOS data. The direction of the OOS estimate must agree with the IS estimate (even if the magnitude differs) before the factor is considered validated.

### Rule 4 — No Probability < 0 or > 1
This is trivial but enforced. Do not report "120% win rate" or negative probabilities from edge case calculations.

### Rule 5 — Report Absolute, Not Just Relative
Always state the absolute win rate alongside any relative measure (lift). Saying "factor X doubles the win rate" is misleading without knowing the base rate.

---

## From Probabilities to Conviction Score

The conviction score translates factor-conditional probabilities into an integer 0–100. The exact mapping will be determined during Phase 4 (engine construction), but the design intent is:

| Estimated P(WIN) | Target Score Range |
|---|---|
| < 40% | 0–24 (Low) |
| 40%–55% | 25–49 (Moderate) |
| 55%–70% | 50–74 (High) |
| > 70% | 75–100 (Very High) |

> These thresholds are provisional. They will be calibrated against the base rates computed from `setup_log`.

**Calibration requirement:** After V1 engine construction, run a calibration check:
- Group all in-sample setups by their assigned conviction score (binned into 10-point ranges)
- For each bin, compute the actual observed win rate
- A well-calibrated engine should show a monotonically increasing win rate as the score increases
- If calibration fails, recalibrate the score-to-probability mapping before deployment

---

## What Probability Cannot Tell Us

1. **It cannot predict the future.** A 70% win rate means 30% of the time the setup fails. Even the highest-scoring setups lose.

2. **It cannot size positions.** Higher probability does not automatically mean larger position size. Position size is determined by the 1% risk rule, not by conviction score.

3. **It cannot replace judgment.** The trader may have context (news, sector events, earnings upcoming) that the score cannot see. Override is always permitted, but should be logged.

4. **It cannot tell you when to exit.** The conviction engine is an entry-quality filter only. Exit rules (stop-loss, trailing stop, target) are separate.
