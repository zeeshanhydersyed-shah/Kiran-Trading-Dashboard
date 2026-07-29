# Factor Interaction Matrix — PSX Quantitative Research Platform

> **Purpose:** Tracks all factor combinations that have been proposed, studied, or validated. Prevents duplication and guides multi-factor research sequencing.  
> **Related:** [Factor_Catalog.md](Factor_Catalog.md) · [Factor_Taxonomy.md](Factor_Taxonomy.md) · [Research_Backlog.md](Research_Backlog.md)

---

## How to Use This Document

When proposing a new multi-factor study:
1. Check this matrix to see if the combination has already been studied or is in progress
2. If not studied: add it to the Proposed section with priority and rationale
3. When a study opens: move the row to Active and add the study ID
4. When a study closes: move to Completed and record the finding

---

## Tier 1 — Highest Priority Combinations

These are the combinations most likely to drive the conviction engine design. Study these first.

| ID | Factor A | Factor B | Scope | Priority | Status | Study | Finding |
|---|---|---|---|---|---|---|---|
| IX-01 | F-03 (RS Rank) | F-37 (Market Regime) | Stock × Market | High | Proposed | — | — |
| IX-02 | F-13 (Stage 2 Bull) | F-19 (Overhead Clear) | Stock × Stock | High | Proposed | — | — |
| IX-03 | F-07 (Base Tightness) | F-20 (Near Pivot Days) | Stock × Stock | High | Proposed | — | — |
| IX-04 | F-28 (Sector Stage) | F-03 (RS Rank) | Sector × Stock | High | Proposed | — | — |
| IX-05 | F-01 (RS Score 20d) | F-37 (Market Regime) | Stock × Market | High | Proposed | — | — |

---

## Tier 2 — Structural Combinations

| ID | Factor A | Factor B | Scope | Priority | Status | Study | Finding |
|---|---|---|---|---|---|---|---|
| IX-06 | F-18 (Base Duration) | F-08 (Vol Contraction) | Stock × Stock | Medium | Proposed | — | — |
| IX-07 | F-16 (Close Above EMA150) | F-20 (Near Pivot Days) | Stock × Stock | Medium | Proposed | — | — |
| IX-08 | F-01 (RS Score 20d) | F-02 (RS Score 50d) | Stock × Stock | Medium | Proposed | — | — |
| IX-09 | F-05 (Rank Change) | F-22 (Sector RS Rank) | Stock × Sector | Medium | Proposed | — | — |
| IX-10 | F-03 (RS Rank) | F-28 (Sector Stage) | Stock × Sector | Medium | Proposed | — | — |

---

## Tier 3 — Refinement Combinations

| ID | Factor A | Factor B | Scope | Priority | Status | Study | Finding |
|---|---|---|---|---|---|---|---|
| IX-11 | F-19 (Overhead Clear) | F-11 (Pivot Distance %) | Stock × Stock | Low | Proposed | — | — |
| IX-12 | F-23 (Sector Breadth) | F-37 (Market Regime) | Sector × Market | Low | Proposed | — | — |
| IX-13 | F-08 (Vol Contraction) | F-42 (BOS Day Volume) | Stock × Stock | Low | Proposed | — | — |
| IX-14 | F-18 (Base Duration) | setup_type | Stock × Setup | Low | Proposed | — | — |
| IX-15 | F-13 (Stage 2 Bull) | F-28 (Sector Stage) | Stock × Sector | Low | Proposed | — | — |

---

## Triple-Factor Combinations (Phase 4+)

To be populated after Tier 1 and Tier 2 studies are complete.

| ID | Factor A | Factor B | Factor C | Status | Study | Finding |
|---|---|---|---|---|---|---|
| IX-T01 | F-03 | F-13 | F-19 | Proposed | — | — |
| IX-T02 | F-07 | F-20 | F-08 | Proposed | — | — |
| IX-T03 | F-28 | F-16 | F-05 | Proposed | — | — |

---

## Completed Combinations

_Moved here when a study closes._

| ID | Factors | Study | Confidence | Finding Summary |
|---|---|---|---|---|
| | | | | |

---

## Status Key

| Status | Meaning |
|---|---|
| `Proposed` | Combination identified; no study opened yet |
| `Active` | Study is open |
| `Complete` | Study closed; finding recorded |
| `Abandoned` | Decided not to study (reason in Notes) |

---

## Constraints

- Combinations involving two factors from the same derivation chain (see [Factor_Taxonomy.md](Factor_Taxonomy.md)) should be studied as robustness checks only, not as independent factors
- Triple-factor combinations should not be studied until the constituent pair combinations are complete
- Do not add combinations involving factors with `Predictive Value = None` to the active research queue
