# Research Pipeline — PSX Quantitative Research Platform

> **Purpose:** Tracks the current state of all open and queued research work. The living queue of what is being studied, what is next, and what is waiting.  
> **Related:** [Research_Backlog.md](Research_Backlog.md) · [Hypotheses.md](Hypotheses.md) · [Evidence_Register.md](Evidence_Register.md) · [Build_Roadmap.md](Build_Roadmap.md)

---

## Pipeline States

| State | Meaning |
|---|---|
| `Design` | RQ and hypothesis defined; methodology being designed |
| `Open` | Study is active; data being queried |
| `Analysis` | Data collected; statistical analysis in progress |
| `Review` | Findings written; under self-review or second review |
| `Closed` | Evidence recorded; finding integrated into relevant documents |
| `Blocked` | Cannot proceed until a dependency is resolved |
| `Abandoned` | Decided not to complete (reason recorded) |

---

## Currently Active (In Progress)

| Study ID | Title | State | Opened | Blocked By |
|---|---|---|---|---|
| D-001 | Dataset Health Report | Design | 2026-07-01 | — |

---

## Phase 0.5 Queue — Dataset Validation (Execute Before Any Factor Research)

**Rationale:** A dataset that has not been validated cannot produce credible findings. These studies reduce uncertainty about the research instrument itself. No factor study opens until D-001 through D-003 are complete.

| Priority | Study ID | Title | Key Question | Tables | Engineering |
|---|---|---|---|---|---|
| 1 | D-001 | Dataset Health Report | Missing values, NULL rates, symbol coverage, sector coverage, date range completeness | `setup_log`, `stock_signals`, `sector_signals`, `market_regime` | None |
| 2 | D-002 | Outcome Variable Validation | Are forward returns computed correctly? Look-ahead check? Incomplete recent rows? Holiday handling? | `setup_log`, `prices_adjusted` | None |
| 3 | D-003 | Sample Independence Assessment | How many setups are repeated observations of the same event? What is the effective independent N? | `setup_log` | None |
| 4 | D-004 | Market Coverage Analysis | What percentage of all PSX stocks ever appear as setups? Is the setup universe representative or concentrated? | `setup_log`, `stock_signals`, `stock_metadata` | None |
| 5 | D-005 | Temporal Stability Assessment | Does the dataset show consistent behaviour across time? Are there structural breaks? | `setup_log`, `market_regime` | None |

**Gate:** D-001 through D-003 must be closed before S-001 opens. D-004 and D-005 may run in parallel with S-001.

---

## Phase 1 Queue (Ready After Phase 0.5)

| Priority | Study ID | Title | Setup Type | Outcome Variable | N (est) |
|---|---|---|---|---|---|
| 1 | S-001 | Base Rate Characterisation | All | OV-01, OV-04 | 205,821 |
| 2 | S-014 | BREAKOUT Deduplication Analysis | BREAKOUT | OV-04 | ~37K |
| 3 | S-008a | Setup Type Comparison | All | OV-01, OV-04 | 205,821 |
| 4 | S-004 | Market Regime Base Rate Stratification | All | OV-01, OV-04 | 205,821 |
| 5 | S-002 | RS Rank vs Forward Return | BREAKOUT | OV-01, OV-04 | ~37K |
| 6 | S-003 | Stage 2 Condition vs Forward Return | BREAKOUT | OV-01, OV-04 | ~37K |
| 7 | S-005 | Base Tightness vs Forward Return | BREAKOUT | OV-01, OV-04 | ~37K |
| 8 | S-006 | Overhead Clear vs Forward Return | BREAKOUT | OV-01, OV-04 | ~37K |

---

## Phase 3 Queue (Depends on Phase 2 Results)

| Priority | Study ID | Title | Prerequisite |
|---|---|---|---|
| 7 | S-007 | RS × Regime Interaction | S-002 + S-006 complete |
| 8 | S-008 | Stage 2 × Overhead Clear Interaction | S-003 + S-005 complete |
| 9 | S-009 | Base Tightness × Near Pivot Days Interaction | S-004 complete |
| 10 | S-010 | Sector Stage Stratification | S-001 complete |

---

## Phase 4 Queue (Engine Construction)

| Study ID | Title | Prerequisite |
|---|---|---|
| S-030 | V1 Factor Weight Calibration | ≥5 Phase 2 studies complete |
| S-031 | V1 In-Sample Calibration Check | S-030 complete |
| S-032 | V1 OOS Validation | S-031 passes Gate 2 |

---

## Backlog (Identified But Not Scheduled)

See [Research_Backlog.md](Research_Backlog.md) for the full list of proposed studies not yet in the pipeline.

---

## Completed Studies

| Study ID | Title | Finding | Confidence | Closed |
|---|---|---|---|---|
| — | — | — | — | — |

---

## Pipeline Rules

1. Maximum 2 studies open simultaneously (to maintain focus)
2. A study cannot enter the queue without a hypothesis entry in [Hypotheses.md](Hypotheses.md)
3. A study cannot be closed without a corresponding evidence entry in [Evidence_Register.md](Evidence_Register.md)
4. Phase 3 studies cannot open until their Phase 2 prerequisites are closed
5. The pipeline document is updated at the start and end of every research session

---

*Update this document at the start of each research session.*
