# PSX Quantitative Research Platform — Documentation Index

> **Mission:** Build a data-driven Conviction Engine for the PSX Explorer page that assigns evidence-based probability scores to breakout and pre-breakout signals.  
> **Principle:** Every enhancement to the system must be supported by documented historical evidence. Intuition, convention, and borrowed rules from other markets are not sufficient.  
> **Scope:** Documentation only. No application code, no database modifications, no Python, no SQL.

---

## Start Here

**[Master_Research_Plan.md](Master_Research_Plan.md)** — The primary governing document. Read this first. It defines what will be studied, in what order, and what the program will produce over the next 12–24 months.

---

## Quick Navigation

- Starting research? → [Master_Research_Plan.md](Master_Research_Plan.md) · [Research_Workflow.md](Research_Workflow.md) · [Research_Pipeline.md](Research_Pipeline.md)
- Need a definition? → [Research_Glossary.md](Research_Glossary.md) · [Data_Dictionary.md](Data_Dictionary.md)
- Opening a study? → [Hypotheses.md](Hypotheses.md) · [Bias_Checklist.md](Bias_Checklist.md)
- Closing a study? → [Research_Review_Checklist.md](Research_Review_Checklist.md) · [Evidence_Register.md](Evidence_Register.md)
- Understanding the engine? → [Conviction_Engine_Specification.md](Conviction_Engine_Specification.md)

---

## Section 1 — Project Foundation

Strategic direction, charter, and high-level plan.

| Document | Purpose |
|---|---|
| [Vision.md](Vision.md) | Permanent project charter: objective, principles, success criteria, what we will not do |
| [Build_Roadmap.md](Build_Roadmap.md) | Phase-by-phase research and build plan; current status of each phase |
| [Decisions.md](Decisions.md) | Record of significant project decisions with reasoning and evidence |
| [Change_Log.md](Change_Log.md) | Audit trail of all document changes and additions |

---

## Section 2 — Governance and Standards

How this research is conducted and what standards it must meet.

| Document | Purpose |
|---|---|
| [Research_Governance.md](Research_Governance.md) | Decision authority table, 4-gate research process, prohibited practices |
| [Research_Standards.md](Research_Standards.md) | 10 standards governing all research on this platform |
| [Research_Workflow.md](Research_Workflow.md) | 8-step end-to-end research process with reference card |
| [Naming_Conventions.md](Naming_Conventions.md) | ID systems, prefixes, and status values for all platform artefacts |
| [Documentation_Style_Guide.md](Documentation_Style_Guide.md) | Writing standards for all documents in this workspace |

---

## Section 3 — Statistical Methodology

How data is analysed, how findings are evaluated, and how bias is prevented.

| Document | Purpose |
|---|---|
| [Statistical_Guidelines.md](Statistical_Guidelines.md) | Sample sizes, metrics, significance standards, multiple testing, effect sizes |
| [Validation_Framework.md](Validation_Framework.md) | 4-tier validation architecture; IS=2020–2023, OOS=2024+ |
| [Evidence_Standards.md](Evidence_Standards.md) | Confidence level criteria (Strong/Moderate/Weak/Inconclusive) |
| [Probability_Framework.md](Probability_Framework.md) | How probability estimates are derived, reported, and used |
| [Bias_Checklist.md](Bias_Checklist.md) | Pre-study bias review protocol (Sections A–I) |
| [Research_Review_Checklist.md](Research_Review_Checklist.md) | 8-section gate before closing a study |
| [Reproducibility_Policy.md](Reproducibility_Policy.md) | What must be recorded to make a study reproducible |

---

## Section 4 — Data Reference

What data exists, where it lives, and what it means.

| Document | Purpose |
|---|---|
| [Data_Dictionary.md](Data_Dictionary.md) | Database schema, column definitions, table row counts |
| [Data_Quality_Policy.md](Data_Quality_Policy.md) | Pre-study quality gates, known data issues, required checks |
| [Known_Limitations.md](Known_Limitations.md) | L-01 through L-13 standing limitations of the platform and data |
| [Assumption_Register.md](Assumption_Register.md) | A-01 through A-18 assumptions: validated, accepted, unvalidated, or violated |
| [Market_Regime_Framework.md](Market_Regime_Framework.md) | Regime classification, distribution, and research usage rules |
| [Sector_Framework.md](Sector_Framework.md) | Sector data structure, composite score formula, Weinstein sector stages |

---

## Section 5 — Research Domain

Factors, outcomes, and their relationships.

| Document | Purpose |
|---|---|
| [Factor_Catalog.md](Factor_Catalog.md) | F-01 through F-42: every factor with column, source, formula, and predictive value |
| [Factor_Taxonomy.md](Factor_Taxonomy.md) | 4-dimension classification: scope, type, form, independence; correlation risk map |
| [Factor_Interaction_Matrix.md](Factor_Interaction_Matrix.md) | IX-01 through IX-T03: proposed and completed factor combinations |
| [Outcome_Definitions.md](Outcome_Definitions.md) | OV-01 through OV-07: authoritative outcome variable specifications |

---

## Section 6 — Research Tracking

Living documents tracking current and future work.

| Document | Purpose |
|---|---|
| [Hypotheses.md](Hypotheses.md) | All registered hypotheses following the RQ→H traceability chain |
| [Research_Pipeline.md](Research_Pipeline.md) | Currently active, queued, and completed studies |
| [Research_Backlog.md](Research_Backlog.md) | Proposed studies not yet scheduled |
| [Evidence_Register.md](Evidence_Register.md) | All closed study findings: E-xxx entries with confidence ratings |
| [Research_Log.md](Research_Log.md) | Session journal and working notes |
| [Questions.md](Questions.md) | Living catalogue: Open → Under Investigation → Answered |

---

## Section 7 — Conviction Engine

Design specifications for the end product.

| Document | Purpose |
|---|---|
| [Conviction_Engine_Specification.md](Conviction_Engine_Specification.md) | Full engine architecture, build phases, output specification |
| [Score_Evolution_Roadmap.md](Score_Evolution_Roadmap.md) | V0 through V3 engine versions; transition rules |
| [Model_Registry.md](Model_Registry.md) | Version registry: each engine version tied to its study set and validation results |
| [Acceptance_Criteria.md](Acceptance_Criteria.md) | 6-gate deployment acceptance test |
| [Failure_Criteria.md](Failure_Criteria.md) | FC-01 through FC-05 post-deployment kill switches |
| [Historical_Similarity_Design.md](Historical_Similarity_Design.md) | Design specification for the analogous-setup lookup feature |

---

## Section 8 — Discovery and Ideas

Research knowledge base and long-horizon ideas.

| Document | Purpose |
|---|---|
| [Claude_Findings.md](Claude_Findings.md) | Facts discovered from code reviews and database investigations |
| [Future_Research_Ideas.md](Future_Research_Ideas.md) | Speculative ideas requiring data or capability not yet available |
| [Research_Glossary.md](Research_Glossary.md) | Authoritative definitions of all technical terms used on this platform |

---

## Document Count

**Total documents: 32** (as of 2026-07-01)
- Section 1 (Foundation): 4
- Section 2 (Governance): 5
- Section 3 (Methodology): 7
- Section 4 (Data Reference): 6
- Section 5 (Domain): 4
- Section 6 (Tracking): 6
- Section 7 (Engine): 6
- Section 8 (Discovery): 3 + this README = 4

---

## RQ → H → S → E → D Traceability Chain

All research on this platform follows a strict traceability chain:

```
RQ (Research Question)
  └── H (Hypothesis)
        └── S (Study)
              └── E (Evidence entry)
                    └── D (Decision / engine change)
```

IDs: `RQ-001` → `H-001` → `S-001` → `E-001` → `D-001`

A conviction engine change (D) can only be made if it links to Evidence (E), which links to a Study (S), which links to a Hypothesis (H). No hypothesis = no study. No study = no evidence. No evidence = no engine change.
