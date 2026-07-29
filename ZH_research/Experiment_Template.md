# Experiment Execution Template
## PSX Quantitative Research Platform

---

> ### ⚑ IMMUTABLE RESEARCH PHILOSOPHY
>
> **The purpose of this experiment is to reduce uncertainty — not to confirm a trading belief.**
>
> **Negative results are considered equally valuable as positive results.**
>
> A hypothesis that survives this template is stronger. A hypothesis that dies here saves months of misallocated capital. Both outcomes are success.
>
> ---
>
> **Reproducibility Standard:** An experiment is complete only when a future researcher can independently reproduce the conclusion from the documented methodology and the same underlying data. If the methodology cannot be followed without the original researcher present, the experiment is not complete.
>
> **Proportional Burden of Proof:** The burden of proof must increase with the influence a factor has on the engine. A minor factor (≤5% engine weight) requires one validated experiment. A core factor (≥20% engine weight) requires replication, regime stability testing, out-of-sample validation, and interaction testing before it is considered for production.
>
> **Compounding Capability:** Every experiment must leave behind a concrete, reusable asset that future experiments can inherit — a validated dataset, a documented query, a data quality report, a reusable filter definition, or a visualization standard. An experiment that produces only a conclusion but no inheritable asset is incomplete.
>
> **Linguistic Rigor:** The phrase "the data proves" is prohibited. Permitted language: "The evidence supports…" / "The evidence does not support…" / "The evidence is inconclusive…" Science is provisional. Every finding is held until better evidence supersedes it.

---

> **This template is the contract.** Every experiment, without exception, follows this structure in this order. Fields marked `[PRE-REG]` must be completed before any data is examined. Fields marked `[POST]` are completed after analysis. No exceptions. No shortcuts.

---

## ─── BLOCK 1: IDENTITY ────────────────────────────────────────

| Field | Value |
|---|---|
| **Experiment ID** | EXP-XXXX |
| **Title** | One descriptive sentence |
| **Phase** | 0.5 Dataset Validation / 1 Single Factor / 2 Interaction / 3 Regime / 4 Engine |
| **Status** | `OPEN` → `ANALYSIS` → `REVIEW` → `CLOSED` |
| **Opened** | YYYY-MM-DD |
| **Closed** | YYYY-MM-DD |
| **Experiment Type** | Descriptive / Hypothesis Test / Robustness Check / Replication |
| **Evidence Maturity** | Discovery → Observed → Replicated → Validated → Production Ready / Terminated |

---

## ─── BLOCK 2: PRE-REGISTRATION `[PRE-REG]` ───────────────────

> Complete this block in full before querying any data. Date and sign off before proceeding. The pre-registration is the only protection against unconscious result-seeking.

### 2.1 Research Question
*One sentence. Answerable with a number.*

```
[Write here]
```

### 2.2 Hypotheses

| | Statement |
|---|---|
| **Null (H₀)** | There is no difference in [outcome] between [condition A] and [condition B] |
| **Alternative (H₁)** | [Direction and nature of expected difference] |
| **Expected Direction** | Positive / Negative / Non-directional |

### 2.3 Primary Outcome Variable

| Field | Value |
|---|---|
| **Outcome Variable** | OV-XX — [name] |
| **Column** | `column_name` in `table_name` |
| **Metric** | Win rate (%) / Mean return (%) / Both |

### 2.4 Independent Variable

| Field | Value |
|---|---|
| **Factor** | F-XX — [name] |
| **Column** | `column_name` in `table_name` |
| **Form** | Binary / Ordinal (how many groups?) / Continuous (how binned?) |
| **Group definitions** | [Exact thresholds or bin edges — stated now, not after seeing data] |

### 2.5 Required Data

| Table | Columns Used | Join Condition |
|---|---|---|
| `setup_log` | [list columns] | Primary table |
| `[other table]` | [list columns] | `[join condition]` |

### 2.6 Population Filter

```
setup_type = [value or ALL]
setup_date BETWEEN [IS start] AND [IS end]
fwd_return_10d IS NOT NULL
[any additional filters — state them now, before looking at results]
```

### 2.7 Minimum Sample Size

| Group | Required N | Confidence Level if Met |
|---|---|---|
| Per group minimum | ≥ 30 | Weak |
| Per group target | ≥ 50 | Moderate |
| Per group strong | ≥ 200 | Strong |

*Expected N per group (estimate):* ___

### 2.8 Pre-Defined Success Threshold
*What result would constitute evidence for H₁? This cannot be changed after data is examined.*

```
Evidence for H₁ requires ALL of the following:
- Win rate difference ≥ [X] percentage points between best and worst group
- Effect is practically significant (see Block 5.3 — state the minimum meaningful size now)
- Direction consistent across ≥ [Y] of [Z] subgroups
- p < 0.05 on primary metric
```

### 2.9 Pre-Defined Kill Criteria `[PRE-REG]`
*What result would require us to terminate this hypothesis? A dead hypothesis is a completed experiment.*

```
This hypothesis is TERMINATED if ANY of the following are observed:

☐  Effect size falls below minimum practical threshold: win rate spread < [X] pp
      AND the 95% confidence interval includes zero difference

☐  Direction reverses across majority of subgroups (< [Y] of [Z] consistent)

☐  Result disappears entirely when BREAKOUT signals are deduplicated
      (applies only to BREAKOUT experiments)

☐  Evidence classification is 🔴 Rejected AND the result is replicated in
      at least one robustness check with the same null outcome

☐  [Experiment-specific kill criterion: state one additional condition
      that would uniquely invalidate this particular hypothesis]
```

**If terminated:** Classification is 🔴 Rejected. Maturity advances to **Terminated** (not discarded — retained as institutional memory). Document the termination reason in the Evidence Register.

### 2.10 Stratification Plan
*How will results be broken down beyond the primary comparison?*

| Stratifier | Included? | Rationale |
|---|---|---|
| `setup_type` | Always | Verify effect is not driven by one type |
| `market_regime` | Yes / Defer | [Reason] |
| Year (from setup_date) | Yes / Defer | [Reason] |
| `sector` | Yes / Defer | [Reason] |

### 2.11 Pre-Registration Sign-Off

| | |
|---|---|
| **Registered by** | [Name] |
| **Date registered** | YYYY-MM-DD |
| **Data examined before registration?** | No / Yes — if Yes, explain deviation below |

*Deviation explanation (if applicable):*

---

## ─── BLOCK 3: DATA QUALITY CHECK `[POST]` ────────────────────

> Complete before proceeding to analysis. If any item fails, document the decision made before opening the results.

| Check | Result | Pass / Warn / Fail |
|---|---|---|
| Total N in population (before filters) | | |
| Total N after all filters applied | | |
| NULL rate in outcome variable | | |
| NULL rate in independent variable | | |
| N per group (verify against Block 2.7) | | |
| Date range actually covered | | |
| Any PENDING corporate action suspects affecting study symbols? | | |
| Deduplication applied (if BREAKOUT setup type)? | | |

**Data quality decision:** `Proceed` / `Proceed with caveats` (list below) / `Halt` (explain why)

*Caveats or halt reason:*

---

## ─── BLOCK 4: RESULTS `[POST]` ───────────────────────────────

### 4.1 Primary Result Table

| Group | N | Win Rate % | Mean 10d Return % | Median 10d Return % | 95% CI (win rate) |
|---|---|---|---|---|---|
| [Group 1] | | | | | |
| [Group 2] | | | | | |
| [Group 3 if applicable] | | | | | |
| **Overall** | | | | | |

### 4.2 Statistical Significance

| Field | Value |
|---|---|
| **Test used** | [chi-square / t-test / Mann-Whitney / ANOVA] |
| **Test statistic** | |
| **p-value** | |
| **Significant at p < 0.05?** | Yes / No |
| **Effect size (win rate spread)** | [X] pp |
| **Effect size (return delta)** | [X]% |
| **95% CI on the primary effect** | [ lower , upper ] |

### 4.3 Practical Significance

> A result can be statistically significant and practically irrelevant. Answer both questions.

| Question | Answer | Reasoning |
|---|---|---|
| **Is the effect practically significant?** | Yes / No | |
| **Minimum threshold (from Block 2.8):** | [X] pp | |
| **Observed effect:** | [X] pp | |
| **Threshold met?** | Yes / No | |

**Practical significance decision:**

```
[ ] YES — This result would materially change at least one of the following:
          capital allocation / position sizing / conviction scoring / risk management.
          Reason: [explain which decision changes and how]

[ ] NO  — The effect is statistically detectable but too small to change
          any real-world decision on this platform.
          Reason: [explain why the observed magnitude is insufficient]

[ ] BORDERLINE — Effect is above the minimum threshold but below the target threshold.
          Proceed with explicit caveat that magnitude requires replication.
```

### 4.4 Stratified Results

*(Complete for each stratifier declared in Block 2.10.)*

**By Setup Type:**

| Setup Type | N | Win Rate % | Direction Consistent with H₁? |
|---|---|---|---|
| BREAKOUT | | | |
| PRE_BREAKOUT | | | |
| RS_LEADER_MARKET | | | |
| RS_LEADER_SECTOR | | | |

**By Year (IS period):**

| Year | N | Win Rate % | Direction Consistent? |
|---|---|---|---|
| 2020 | | | |
| 2021 | | | |
| 2022 | | | |
| 2023 | | | |

**By Regime (if included in Block 2.10):**

| Regime | N | Win Rate % | Direction Consistent? |
|---|---|---|---|
| TRENDING_UP | | | |
| RANGING | | | |
| TRENDING_DOWN | | | |

---

## ─── BLOCK 5: INTERPRETATION `[POST]` ────────────────────────

### 5.1 Primary Finding
*One sentence. Precise. Quantified. No hedging.*

```
[Write here. Example: "Stocks in RS rank quintile 1 (best) produced a 10-day win rate
of 58.3% vs 44.1% for quintile 5 (worst), a spread of 14.2pp (N=6,841, p=0.003,
95% CI on spread: [9.1pp, 19.3pp])."]
```

### 5.2 Kill Criteria Review
*Check each criterion from Block 2.9 against the observed result.*

| Kill Criterion | Triggered? | Evidence |
|---|---|---|
| Effect size below minimum AND CI includes zero | Yes / No | |
| Direction reverses across majority of subgroups | Yes / No | |
| Result disappears on deduplication (if applicable) | Yes / No | |
| Replicated null result (if this is a robustness check) | Yes / No | |
| Experiment-specific criterion | Yes / No | |

**Kill criteria verdict:** `No criteria triggered — hypothesis survives` / `[X] criterion triggered — hypothesis TERMINATED`

### 5.3 Hypothesis Verdict

| | |
|---|---|
| **H₁ supported?** | Yes / No / Partially |
| **Pre-defined success threshold met?** | Yes / No |
| **Practical significance confirmed?** | Yes / No / Borderline |
| **Direction as predicted?** | Yes / No / Reversed |
| **Hypothesis status after this experiment** | Active / Terminated |

### 5.4 Caveats Specific to This Experiment
*What limitations apply specifically here? Do not repeat platform-wide limitations — reference by ID.*

- [Caveat 1]
- [Caveat 2]
- Inherited platform limitations: L-XX, L-XX

### 5.5 What This Result Does Not Establish
*Explicitly state what cannot be concluded from this experiment alone. This section is mandatory.*

- This experiment does not establish that [factor] **causes** better outcomes — only that it is **associated** with them in this dataset.
- This experiment does not test [closely related question that might seem implied].
- This result applies to the in-sample period (2020–2023) and has not been tested on OOS data.
- [Other explicit non-conclusions specific to this experiment]

### 5.6 Alternative Explanations
*What else could explain this result? A finding that has no plausible alternative explanation is stronger.*

- [Alternative 1: e.g., "The observed RS effect may reflect the bull market period of 2020–2021 rather than RS as a persistent factor."]
- [Alternative 2]
- [Alternative 3 or "No plausible alternative identified — explain why"]

---

## ─── BLOCK 6: EVIDENCE CLASSIFICATION `[POST]` ───────────────

### 6.1 Classification

| | |
|---|---|
| **Classification** | 🟢 Accepted / 🟡 Conditional / 🔴 Rejected |
| **Confidence Level** | Strong (N≥200/group) / Moderate (N≥50) / Weak (N≥30) |

**Rationale:**

```
[Write here.
 For 🟢: state why the result meets all five criteria below.
 For 🟡: state the exact conditions under which the result holds and those under which it does not.
 For 🔴: state which criterion failed and what the null result means for the hypothesis.]
```

**Classification criteria:**

| Criterion | Met? |
|---|---|
| Pre-defined N threshold met | Yes / No |
| Pre-defined success threshold met | Yes / No |
| Practically significant (Block 4.3) | Yes / No |
| Direction consistent across ≥ 3 of 4 subgroups | Yes / No |
| Result not driven by a single year or outlier period | Yes / No |

> **Mandatory rule:**
> - All five criteria Yes → 🟢 Accepted
> - Criteria 1 and 3 Yes, at least one other No → 🟡 Conditional
> - Criteria 1 or 3 fails → 🔴 Rejected
> - Any kill criterion triggered (Block 5.2) → 🔴 Rejected, Maturity = Terminated

---

## ─── BLOCK 7: EVIDENCE MATURITY `[POST]` ─────────────────────

```
EXP-XXXX — [Title]

  Discovery  →  Observed  →  Replicated  →  Validated  →  Production Ready
                                                              or
                                                           Terminated
  [mark current stage with ◉]
```

### Stage Definitions

| Stage | Meaning | Requirement to Advance |
|---|---|---|
| **Discovery** | Experiment opened; pre-registration complete | Block 2 signed off |
| **Observed** | First result obtained; classified 🟢 or 🟡 | This experiment closed |
| **Replicated** | Same direction confirmed in ≥ 1 independent context (different setup type, time window, or population subset) | Replication experiment closed |
| **Validated** | OOS result (2024+) confirms direction; effect size within 50% of IS | OOS experiment closed |
| **Production Ready** | Multi-factor study confirms marginal value; weight assigned; calibration passed | Engine acceptance gates passed |
| **Terminated** | ≥ 1 kill criterion triggered, OR 🔴 Rejected in both IS and replication | Kill criterion documented |

### Current Stage: **Discovery** *(advance to Observed when this experiment closes)*

### What Is Required to Advance from Observed to Replicated

- [ ] At least one replication experiment (EXP-XXXX) is open or planned
- [ ] Replication uses a different population, time window, or setup type than this experiment
- [ ] Replication pre-registered independently (not designed after seeing this result)

### What Is Required to Advance from Replicated to Validated

- [ ] OOS experiment (2024+ data) opened and closed
- [ ] OOS direction matches IS direction
- [ ] OOS effect size ≥ 50% of IS effect size

### What Is Required for Production Ready

- [ ] Multi-factor experiment confirms marginal predictive value
- [ ] Weight assigned proportional to effect size
- [ ] IS calibration check passed
- [ ] All acceptance gates in Acceptance_Criteria.md: Pass

### Termination Record *(if applicable)*

| Field | Value |
|---|---|
| **Terminated on** | YYYY-MM-DD |
| **Kill criterion triggered** | [state which one] |
| **Institutional memory note** | [What should future researchers know? Why is this hypothesis dead?] |
| **Re-test permitted?** | No — unless new data or materially different methodology / Yes — under condition: [state condition] |

---

## ─── BLOCK 8: CROSS-REFERENCES `[POST]` ──────────────────────

| Field | Value |
|---|---|
| **Hypothesis ID** | H-XXX |
| **Factor ID(s)** | F-XX |
| **Evidence Register Entry** | E-XXXX |
| **Evidence bucket** | 🟢 Accepted / 🟡 Conditional / 🔴 Rejected |
| **Experiments this result depends on** | EXP-XXXX, EXP-XXXX |
| **Experiments this result unlocks** | EXP-XXXX, EXP-XXXX |
| **Experiments required for replication** | EXP-XXXX |
| **Factor Catalog update** | F-XX: Predictive Value → [value] |
| **Assumption Register update** | A-XX: Status → [new status] |

---

## ─── BLOCK 9: REUSABLE ASSET `[POST]` ────────────────────────

*Every experiment must leave behind at least one inheritable asset. This block is mandatory. An experiment with no documented asset is not closed.*

| Field | Value |
|---|---|
| **Asset Type** | Validated dataset / Documented query / Data quality report / Filter definition / Visualization standard / Statistical test result / Other |
| **Asset Description** | [What is it? One sentence.] |
| **Where it lives** | [File name, table name, or document section] |
| **How future experiments use it** | [Concrete inheritance instruction — what can a future researcher skip because this experiment already did it?] |

---

## ─── EXPERIMENT LOG `[RUNNING]` ──────────────────────────────

*One line per session. Mandatory entry at pre-registration and at close. Captures deviations, decisions, and unexpected findings in real time — not reconstructed after the fact.*

| Date | Entry |
|---|---|
| YYYY-MM-DD | Pre-registration completed. Kill criteria set. |
| YYYY-MM-DD | [Any deviation from pre-registered plan — state what changed and why] |
| YYYY-MM-DD | Data quality check complete. Decision: [Proceed / Halt]. |
| YYYY-MM-DD | Analysis complete. Kill criteria: [triggered / not triggered]. Classification: [🟢/🟡/🔴]. Maturity: Observed. |
