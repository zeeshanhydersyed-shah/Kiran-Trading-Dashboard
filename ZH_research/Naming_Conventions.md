# Naming Conventions — PSX Quantitative Research Platform

> **Purpose:** Single authoritative reference for every identifier, prefix, and naming rule used across this research platform.  
> **Applies to:** All documents in `ZH_research/`. All study IDs, evidence IDs, decision IDs, and artifact names.  
> **Related:** [Research_Workflow.md](Research_Workflow.md) · [Documentation_Style_Guide.md](Documentation_Style_Guide.md)

---

## Core Traceability Chain

Every piece of work in this platform belongs to a chain:

```
RQ-xxx  →  H-xxx  →  S-xxx  →  E-xxx  →  D-xxx
```

| Code | Meaning | Lives In |
|---|---|---|
| `RQ-xxx` | Research Question | [Questions.md](Questions.md) |
| `H-xxx` | Hypothesis | [Hypotheses.md](Hypotheses.md) |
| `S-xxx` | Study | [Research_Log.md](Research_Log.md) |
| `E-xxx` | Evidence | [Evidence_Register.md](Evidence_Register.md) |
| `D-xxx` | Decision | [Decisions.md](Decisions.md) |

One RQ may have multiple hypotheses. One hypothesis may have multiple studies. Multiple studies may produce one piece of evidence.

---

## Identifier Rules

### Format
- Always three digits, zero-padded: `RQ-001`, not `RQ-1`
- Sequential: never reuse a number, even if the entry is deleted
- Never reassign: a deleted entry retains its ID with status `Cancelled`

### Cross-referencing
- Always use the full ID: `H-003`, not "hypothesis 3"
- When referencing across documents, link: `[H-003](Hypotheses.md#h-003)`
- A study entry must cite its parent hypothesis: `Related Hypothesis: H-003`

---

## Document Naming

| Document Type | Convention | Example |
|---|---|---|
| Core governance | `Title_Case.md` | `Research_Governance.md` |
| Study outputs | Recorded inside `Research_Log.md`, not separate files | — |
| Factor analysis outputs | Recorded inside `Research_Log.md` | — |
| Temporary working notes | Prefixed `DRAFT_` | `DRAFT_RS_Analysis.md` |
| Archived documents | Prefixed `ARCHIVE_` | `ARCHIVE_Research_Log_v1.md` |

---

## Factor Naming

When referencing a factor in any document:

| Context | Convention | Example |
|---|---|---|
| Database column name | backtick, exact case | `` `rs_score_20` `` |
| Human-readable label | Title Case | RS Score 20d |
| In a table | Human-readable label | RS Score 20d |
| In methodology | Both forms, first mention | RS Score 20d (`` `rs_score_20` ``) |

---

## Outcome Variable Naming

| Context | Convention |
|---|---|
| Raw return | `fwd_return_Nd` where N = number of trading days |
| Win/loss label | `outcome_label` |
| Risk-adjusted | `realized_r` |
| Custom computed | Describe in [Outcome_Definitions.md](Outcome_Definitions.md) |

---

## Status Values

Standardised status terms used across all documents:

| Entity | Allowed Status Values |
|---|---|
| Hypothesis | `Untested` · `In Progress` · `Confirmed` · `Rejected` · `Inconclusive` · `Cancelled` |
| Study | `Planned` · `In Progress` · `Complete` · `Abandoned` |
| Evidence | `Active` · `Under Review` · `Superseded` · `Retracted` |
| Decision | `Active` · `Under Review` · `Superseded` · `Reversed` |
| Research Question | `Open` · `Under Investigation` · `Answered` · `Dropped` |
| Roadmap Phase | `Planned` · `In Progress` · `Complete` · `Blocked` |

---

## Confidence Levels

Used in [Evidence_Register.md](Evidence_Register.md):

| Level | Minimum Criteria |
|---|---|
| `Strong` | N ≥ 200 per group · Consistent across ≥ 2 regimes · Out-of-sample validated |
| `Moderate` | N ≥ 50 per group · Directionally consistent · Not yet OOS validated |
| `Weak` | N < 50 per group · Or single-regime result only |

---

## Priority Levels

Used in [Hypotheses.md](Hypotheses.md) and [Research_Backlog.md](Research_Backlog.md):

| Level | Meaning |
|---|---|
| `High` | Expected material impact on conviction engine; block further design until answered |
| `Medium` | Useful to know; research when High-priority queue is clear |
| `Low` | Interesting but low expected impact; add to backlog |

---

## Versioning

- Documents do not carry version numbers in their filenames
- Breaking changes to a document's structure are logged in [Change_Log.md](Change_Log.md)
- Superseded evidence entries are moved to the archive section in [Evidence_Register.md](Evidence_Register.md)

---

*Last updated: 2026-07-01. See [Change_Log.md](Change_Log.md) for revision history.*
