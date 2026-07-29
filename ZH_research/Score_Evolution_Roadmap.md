# Score Evolution Roadmap — PSX Quantitative Research Platform

> **Purpose:** Tracks how the conviction score will evolve from its first simple version to a mature calibrated system. Prevents premature complexity and ensures each version is validated before the next is built.  
> **Related:** [Conviction_Engine_Specification.md](Conviction_Engine_Specification.md) · [Model_Registry.md](Model_Registry.md) · [Research_Pipeline.md](Research_Pipeline.md)

---

## Philosophy

Build simply, validate thoroughly, extend carefully. Each version must be running in production and passing its monitoring checks before the next version's design is finalised.

---

## Version Timeline

### V0 — Heuristic Score (Current Implicit State)
**Status:** Active (informal)

The Explorer page already shows a rough signal quality classification via the color coding:
- Green (Breakout): BOS + positive RS
- Amber (Near Pivot): within 5% of pivot
- Blue (RS Positive): positive RS only
- Gray (Lagging): none of the above

This is a 4-level heuristic, not a scored system. It uses no historical validation.

**Limitations:** No probability calibration. No factor weights. No evidence that the color buckets predict different outcomes.

---

### V1 — Additive Evidence Score
**Status:** Not yet built (awaiting Phase 2–3 research)

**Design:** Weighted sum of validated factors. Score 0–100. Four conviction labels.

**Entry requirement:** All 6 gates in [Acceptance_Criteria.md](Acceptance_Criteria.md) must pass.

**Target factor set (provisional — subject to study results):**
- F-01/F-03: RS Rank (primary momentum factor)
- F-13: Stage 2 Bull (trend confirmation)
- F-07: Base Tightness (structure quality)
- F-19: Overhead Clear (supply check)
- F-37: Market Regime (environment gate)
- F-28: Sector Stage (sector context)

**Weight assignment approach:**
- Initial weights: proportional to win-rate lift from single-factor studies
- Win-rate lift = P(WIN | factor favourable) / overall base rate
- Factors with lift > 1.3 receive higher weight; factors with lift 1.0–1.1 receive low weight

**Validation target:**
- OOS win rate spread (Very High vs Low) ≥ 10 percentage points
- OOS N ≥ 200

---

### V1.1 — Regime-Weighted Score
**Status:** Design future

**Design:** Same factors as V1, but factor weights are conditioned on market regime. In TRENDING_UP, RS factors get more weight; in RANGING, base quality factors may get more weight.

**Entry requirement:** V1 has been running for ≥ 90 trading days with satisfactory monitoring metrics.

---

### V2 — Probability-Calibrated Score
**Status:** Design future

**Design:** Score is a calibrated win probability estimate rather than an arbitrary 0–100 index. The score is trained and calibrated so that a score of 65 corresponds empirically to a 65% historical win rate.

**Entry requirement:** Sufficient OOS data to calibrate across all score levels (needs ≥ 500 OOS observations).

---

### V3 — Non-Linear / Interaction-Aware Score
**Status:** Concept only

**Design:** Incorporate validated factor interactions from [Factor_Interaction_Matrix.md](Factor_Interaction_Matrix.md). Some factor combinations produce superadditive or subadditive effects that a linear model misses.

**Entry requirement:** All Tier 1 and Tier 2 interaction studies in the Factor Interaction Matrix are complete.

---

## Version Registry Summary

| Version | Design | Build | OOS Validated | Live | Retired |
|---|---|---|---|---|---|
| V0 (Heuristic) | ✓ Implicit | ✓ Deployed | ✗ | ✓ | — |
| V1 (Additive) | In progress | Not started | Not started | Not live | — |
| V1.1 (Regime) | Not started | — | — | — | — |
| V2 (Calibrated) | Not started | — | — | — | — |
| V3 (Interactions) | Not started | — | — | — | — |

---

## Transition Rules

1. A new version never replaces the live version until it has passed all acceptance gates
2. Both the old and new version may run in parallel for 30 trading days before the old version is retired
3. In parallel mode, both scores are logged but only the old version is shown to the trader
4. If the new version passes monitoring, promote it; if it fails, retire it and keep the old version
5. Every version transition is recorded in [Model_Registry.md](Model_Registry.md) with the study set that produced it

---

## Guiding Constraints

- Do not build V2 before V1 is validated
- Do not add a factor to the score without a completed study
- Do not add more than 2 new factors between versions (prevents "big bang" redesigns that are hard to diagnose)
- Never reduce the score to below-chance levels for any valid signal — the engine should identify quality differences, not make binary go/no-go calls
