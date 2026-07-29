# Conviction Engine Specification — PSX Quantitative Research Platform

> **Purpose:** Authoritative specification for the Conviction Engine — the end product of this research platform. Defines what it must do, how it will be built, and what evidence it requires.  
> **Related:** [Score_Evolution_Roadmap.md](Score_Evolution_Roadmap.md) · [Probability_Framework.md](Probability_Framework.md) · [Acceptance_Criteria.md](Acceptance_Criteria.md) · [Model_Registry.md](Model_Registry.md)

---

## What the Conviction Engine Is

The Conviction Engine is a scoring system that assigns each stock a **conviction score** at the time of a breakout or pre-breakout signal. The score represents the evidence-weighted probability that the signal will produce a positive outcome, given the current factor profile of the stock, its sector, and the market regime.

It is displayed on the Explorer page of the PSX dashboard to help the trader prioritise which signals to act on.

---

## What It Is Not

- It is **not** a trading system. It does not enter, size, or exit trades.
- It is **not** a black box. Every component of the score must have a supporting study.
- It is **not** a buy recommendation. The score reflects signal quality; the final decision is the trader's.
- It is **not** a substitute for stop-loss discipline or position sizing rules.

---

## Design Principles

1. **Evidence-first:** No factor enters the conviction engine without at least Moderate confidence evidence from a completed study.
2. **Explainable:** The score can be decomposed — the trader can see which factors drove it up or down.
3. **Updatable:** New studies can raise or lower a factor's weight or remove it entirely.
4. **Conservative:** When evidence is weak or conflicting, default to lower scores, not higher.
5. **Calibrated:** Score levels should correspond to empirically derived win-rate ranges, not arbitrary labels.

---

## Score Architecture

### Version 1 — Additive Weighted Score (Initial)

The first version is a simple weighted additive score:

```
conviction_score = Σ (factor_score_i × weight_i)
```

Where:
- Each `factor_score_i` is normalised to a common scale (e.g., 0–1 or 0–10)
- `weight_i` is derived from the factor's validated predictive power
- The sum is rescaled to 0–100 for display

**Score levels (V1):**

| Score Range | Label | Interpretation |
|---|---|---|
| 75–100 | Very High | Multiple strong factors aligned; historically high win rate |
| 50–74 | High | Most factors positive; above-average expectancy |
| 25–49 | Moderate | Mixed factors; near-average expectancy |
| 0–24 | Low | Weak factor profile; below-average expectancy |

> These ranges are provisional. They will be calibrated empirically once the engine is built and validated against OOS data.

### Version 2 — Regime-Conditional Score (Later)

After V1 is validated, extend to regime-conditional weights:

```
conviction_score = Σ (factor_score_i × weight_i × regime_adjustment_i)
```

Where `regime_adjustment_i` modifies the weight of factor `i` based on market regime. Some factors may be predictive only in TRENDING_UP; others only in RANGING.

---

## Required Evidence Before Each Component is Added

Each factor included in the conviction engine requires:

| Requirement | Standard |
|---|---|
| Completed study (single-factor) | Minimum Moderate confidence per [Evidence_Standards.md](Evidence_Standards.md) |
| OOS validation | At least 30 OOS observations confirming the direction of effect |
| Factor independence checked | Not fully redundant with an already-included factor (correlation assessed) |
| Weight justification | Weight is proportional to effect size, not arbitrary |
| Documentation | Study ID and evidence record linked in [Model_Registry.md](Model_Registry.md) |

---

## Build Phases

### Phase 1 — Foundation (Current)
- Define all factors, outcomes, and methodology (this document layer)
- No engine exists yet
- Output: complete documentation architecture

### Phase 2 — Single-Factor Studies
- Run individual factor studies (RS rank, base tightness, overhead clear, stage, regime)
- Identify which factors have Moderate or High confidence predictive value
- Output: prioritised list of validated factors

### Phase 3 — Multi-Factor Studies
- Test factor combinations identified in [Factor_Interaction_Matrix.md](Factor_Interaction_Matrix.md)
- Identify additive vs. redundant combinations
- Output: validated factor set for V1 engine

### Phase 4 — V1 Engine Construction
- Assign provisional weights based on effect sizes
- Build score computation logic
- Validate on OOS (2024+) data
- Output: V1 conviction engine, calibrated

### Phase 5 — V1 Dashboard Integration
- Display conviction score on Explorer page
- Show factor breakdown (explainability layer)
- Monitor score distribution and drift
- Output: live conviction engine in production

### Phase 6 — V2 Regime-Conditional
- After 12+ months of V1 operation with live data
- Extend to regime-conditional weights
- Output: V2 engine

---

## Output Specification

For each signal in `setup_log`, the engine produces:

| Field | Description |
|---|---|
| `conviction_score` | Integer 0–100 |
| `conviction_label` | Very High / High / Moderate / Low |
| `score_version` | Which engine version produced this score |
| `factor_scores` | JSON: factor_id → normalised score |
| `top_positive_factors` | Top 3 factors driving the score up |
| `top_negative_factors` | Top 3 factors driving the score down |
| `regime_at_signal` | Market regime on signal date |
| `computed_at` | Timestamp |

---

## Acceptance Gate

The conviction engine must not be deployed to the dashboard until it passes the acceptance criteria defined in [Acceptance_Criteria.md](Acceptance_Criteria.md). These include:

- OOS win rate for scores ≥ 75 must exceed OOS win rate for scores ≤ 25 by a statistically significant margin
- The score must be calibrated: scores in the 50–74 range must correspond to observed win rates between 50–74%
- No factor in the engine is sourced from in-sample data only

---

## Version Control

| Version | Status | Date | Changes |
|---|---|---|---|
| V0.1 | Draft | 2026-07-01 | Initial specification |
| V1.0 | Not built | — | Additive score; pending Phase 2–4 |
| V2.0 | Not designed | — | Regime-conditional; pending V1 validation |
