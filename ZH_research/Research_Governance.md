# Research Governance — PSX Quantitative Research Platform

> **Purpose:** Defines how research decisions are made, who has authority over what, and what standards govern the platform.  
> **Related:** [Research_Standards.md](Research_Standards.md) · [Research_Workflow.md](Research_Workflow.md) · [Decisions.md](Decisions.md)

---

## Governance Principles

1. **Evidence over intuition.** No factor enters the conviction engine without a completed study in [Research_Log.md](Research_Log.md) and a corresponding entry in [Evidence_Register.md](Evidence_Register.md).
2. **Separation of research and implementation.** Research phases and build phases are distinct. Research produces findings; findings produce decisions; decisions produce implementation. These stages are never merged.
3. **Traceability.** Every implementation choice must trace back through the chain: `D-xxx → E-xxx → S-xxx → H-xxx → RQ-xxx`.
4. **No silent changes.** Changes to methodology, thresholds, or framework design are recorded in [Decisions.md](Decisions.md) with reasoning. Nothing changes without a record.
5. **Null results are permanent record.** A rejected hypothesis is as valuable as a confirmed one. It closes a line of inquiry and prevents revisiting dead ends.

---

## Decision Authority

| Decision Type | Authority | Record In |
|---|---|---|
| Open a new research question | Researcher | [Questions.md](Questions.md) |
| Promote RQ to Hypothesis | Researcher | [Hypotheses.md](Hypotheses.md) |
| Open a Study | Researcher | [Research_Log.md](Research_Log.md) |
| Close a Study (Complete) | Researcher | [Research_Log.md](Research_Log.md) |
| Add Evidence to Register | Researcher, after study is Complete | [Evidence_Register.md](Evidence_Register.md) |
| Make a Project Decision (D-xxx) | Project Lead | [Decisions.md](Decisions.md) |
| Modify a Governance Document | Project Lead | [Change_Log.md](Change_Log.md) + document |
| Approve a factor for conviction engine | Project Lead, requires Strong or Moderate evidence | [Decisions.md](Decisions.md) |

---

## Research Gate Process

Every study must pass through four gates before a finding is acted on:

```
GATE 1 — Pre-Study
  ✓ Research question is registered (RQ-xxx)
  ✓ Hypothesis is written (H-xxx)
  ✓ Methodology is documented BEFORE data is examined
  ✓ Bias checklist reviewed (see Bias_Checklist.md)

GATE 2 — During Study
  ✓ Data source and date range confirmed
  ✓ Deduplication rule applied
  ✓ Sample sizes recorded
  ✓ No methodology changes after data has been seen

GATE 3 — Study Completion
  ✓ Results recorded verbatim
  ✓ Statistical confidence assessed
  ✓ Limitations documented
  ✓ Conclusion does not exceed what the data supports

GATE 4 — Evidence Registration
  ✓ Study marked Complete
  ✓ Confidence level assigned per Evidence_Standards.md
  ✓ Entry added to Evidence_Register.md
  ✓ Hypothesis status updated
  ✓ Research question moved to Answered
```

A study that fails any gate is returned to the previous stage, not abandoned.

---

## Prohibited Practices

| Practice | Why Prohibited |
|---|---|
| Changing methodology after seeing results | Introduces confirmation bias |
| Reporting only favourable subgroup results | Cherry-picking |
| Treating correlated factors as independent evidence | Inflates apparent certainty |
| Optimising thresholds without out-of-sample validation | Overfitting |
| Acting on a finding before it reaches Evidence Register | Bypasses governance |
| Deleting rejected hypotheses | Destroys institutional memory |
| Recording opinions as evidence | Contaminates the evidence base |

---

## Review Cadence

| Review | Frequency | Purpose |
|---|---|---|
| Research Pipeline Review | Before each new study | Prioritise what to study next |
| Evidence Review | After every 5 completed studies | Check for contradictions or superseded findings |
| Governance Review | Annually or after major phase completion | Update standards to reflect experience |
| Roadmap Review | After each phase completion | Reprioritise remaining phases |

---

## Escalation

If a study produces results that contradict an existing evidence entry:

1. Do not delete the existing entry
2. Mark the existing entry `Under Review`
3. Open a new study specifically designed to adjudicate the contradiction
4. Record the outcome in both evidence entries
5. Supersede the weaker entry with a cross-reference

---

*This document is a governance instrument. Changes require a corresponding entry in [Change_Log.md](Change_Log.md).*
