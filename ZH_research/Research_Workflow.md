# Research Workflow — PSX Quantitative Research Platform

> **Purpose:** The definitive step-by-step process for conducting research from idea to decision. Follow this for every study.  
> **Related:** [Research_Governance.md](Research_Governance.md) · [Research_Standards.md](Research_Standards.md) · [Naming_Conventions.md](Naming_Conventions.md) · [Bias_Checklist.md](Bias_Checklist.md)

---

## Overview

```
IDEA
 └─ Step 1: Register Research Question (RQ-xxx)
     └─ Step 2: Write Hypothesis (H-xxx)
         └─ Step 3: Design Study (S-xxx) — BEFORE touching data
             └─ Step 4: Execute Study
                 └─ Step 5: Record Results
                     └─ Step 6: Close Study
                         └─ Step 7: Register Evidence (E-xxx) [if finding is positive]
                             └─ Step 8: Record Decision (D-xxx) [when acted on]
```

---

## Step 1 — Register the Research Question

**Where:** [Questions.md](Questions.md) → Open Questions section

**Do:**
- Write one specific, measurable question
- Use the naming prefix `RQ-xxx` (next sequential number)
- Set status: `Open`

**Check:**
- Is this question already in the register (open, under investigation, or answered)?
- If answered: read the finding; do not re-open unless explicitly contradicting new data

**Example:**
> `RQ-001: Does rs_rank ≤ 20 produce a higher 20d win rate than rs_rank 21–100 for BREAKOUT setups in TRENDING_UP regime?`

---

## Step 2 — Write the Hypothesis

**Where:** [Hypotheses.md](Hypotheses.md)

**Do:**
- State the specific prediction, not the general question
- Use prefix `H-xxx`
- Fill all fields in the template: Motivation, Related Factors, Expected Outcome (Confirmed if / Rejected if)
- Link to the parent RQ: `Related RQ: RQ-001`
- Set status: `Untested`

**Do not:**
- Examine any data before completing this step
- Write vague hypotheses ("RS matters")
- Combine multiple predictions in one hypothesis entry

---

## Step 3 — Design the Study

**Where:** [Research_Log.md](Research_Log.md) → new study entry

**Do:**
- Assign study ID: `S-xxx`
- Link to parent hypothesis: `Related Hypothesis: H-xxx`
- Complete the full Methodology section **before any queries are run:**
  - Dataset and table(s)
  - Date range
  - Setup type filter
  - Outcome variable and forward horizon
  - Factor being tested and how it is split (binary / quintile / threshold)
  - Deduplication rule
  - Filters applied (regime, volume, etc.)
  - Statistical test to be used (if any)
  - In-sample vs out-of-sample split (if applicable)
- Set status: `In Progress`
- Run [Bias_Checklist.md](Bias_Checklist.md) before proceeding

**Do not:**
- Modify the methodology after examining any results
- Add factors to the analysis that were not pre-specified (run a separate study if needed)

---

## Step 4 — Execute the Study

**Rules during execution:**
- Use only the data sources specified in Step 3
- Apply the deduplication rule exactly as written
- Do not adjust filters, thresholds, or horizons mid-run
- If a data issue is discovered, pause and document it before proceeding
- Record any unexpected findings as follow-up questions, not primary results

---

## Step 5 — Record Results

**Where:** Research_Log.md, in the open study entry

**Do:**
- Record all groups, not only favourable ones
- Record N, win rate, mean return, standard deviation for every group
- Record the comparison metric (e.g., difference in win rates, percentage point delta)
- Record statistical test result if applicable
- Record any data quality observations

**Do not:**
- Summarise before recording raw results
- Adjust wording based on what would sound better
- Omit groups with small N (flag them instead)

---

## Step 6 — Close the Study

**Where:** Research_Log.md, in the study entry

**Do:**
- Complete the Conclusions section — state specifically whether the hypothesis was supported, rejected, or inconclusive
- Complete the Statistical Confidence section
- Document limitations of this specific study
- List follow-up questions in the designated section
- Set study status: `Complete`
- Update [Questions.md](Questions.md): move RQ to `Answered`
- Update [Hypotheses.md](Hypotheses.md): set H status to `Confirmed`, `Rejected`, or `Inconclusive`

---

## Step 7 — Register Evidence (if applicable)

**Where:** [Evidence_Register.md](Evidence_Register.md)

**Criteria for registration:**
- Study status must be `Complete`
- Finding must be a positive association (null results do not receive evidence entries)
- Confidence level assigned per [Evidence_Standards.md](Evidence_Standards.md)

**Do:**
- Assign next `E-xxx` number
- Write a precise, quantified finding statement
- Link to study: `Supporting Study: S-xxx`
- Set status: `Active`

---

## Step 8 — Record Decision (when acted on)

**Where:** [Decisions.md](Decisions.md)

**Criteria for a decision entry:**
- The evidence will be used to change something (conviction engine, screener, threshold, policy)
- The decision must cite at least one `E-xxx` entry

**Do:**
- Assign next `D-xxx` number
- Link back: `Based on: E-xxx`
- Record reasoning, alternatives considered, and consequences

---

## When to Deviate

If data conditions require a methodology change after the study has begun:

1. Do not modify the original methodology section
2. Add an explicit `## Methodology Amendment` subsection
3. State what changed, why, and when
4. Re-run the analysis under the original methodology if possible (for comparison)
5. Note the deviation in the Limitations section

---

## Workflow Reference Card

| Step | Document | Action |
|---|---|---|
| 1 | Questions.md | Register RQ-xxx |
| 2 | Hypotheses.md | Write H-xxx |
| 3 | Research_Log.md | Design S-xxx methodology |
| 3b | Bias_Checklist.md | Run pre-study checklist |
| 4 | — | Execute |
| 5 | Research_Log.md | Record results |
| 6 | Research_Log.md + Questions.md + Hypotheses.md | Close study |
| 7 | Evidence_Register.md | Register E-xxx (if positive) |
| 8 | Decisions.md | Record D-xxx (when acted on) |
