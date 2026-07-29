# Decisions — PSX Breakout Research Project

> **Purpose:** Permanent record of significant project decisions.  
> **Rule:** Every decision that affects research methodology, system design, or project direction is recorded here. Minor implementation choices do not need an entry.

---

## Decision Template

```
---

## Decision [NUMBER] — [SHORT TITLE]

| Field | Value |
|---|---|
| **Date** | |
| **Status** | Active / Superseded / Reversed |

### Context

> _Why was this decision needed? What problem or question prompted it?_

### Decision

> _What was decided, stated clearly and unambiguously._

### Reasoning

> _Why this option over alternatives?_

### Evidence

> _What data, research, or analysis supported this decision? (Reference Research_Log entries where applicable.)_

### Consequences

> _What does this decision enable? What does it rule out?_

### Superseded By

> _If this decision was later reversed or replaced, reference the new decision here._

---
```

---

## Decisions

---

## Decision D-001 — Mandatory Multiple-Comparison Disclosure for Threshold/Quintile Selection Studies

| Field | Value |
|---|---|
| **Date** | 2026-07-03 |
| **Status** | Active |

### Context

> S-001 (pivot-distance-pct band for BREAKOUT) selected its band by testing 5 quintiles on Development data and picking the best-performing one (Q4), then reported that quintile's p-value against its complement without any correction for having tested 5 candidates. The S-001 Diagnostic Addendum (Section 11, Task 1) applied a Bonferroni correction after the fact (adjusted α = 0.05/5 = 0.01) and found that the Development-era result, reported as significant at p≈0.02, does NOT survive correction — it was only the reviewer's explicit request that surfaced this. This should not depend on the reviewer noticing and asking each time.

### Decision

> Any future factor study that compares 3 or more groups (quintiles, deciles, candidate bands, candidate cutoffs, etc.) in order to select a "best" band, cutoff, or threshold must report a multiple-comparison-corrected significance level (e.g., Bonferroni: α_adjusted = 0.05 / number_of_candidates_tested) **alongside** the raw, uncorrected p-value, as standard output in the study's methodology/results section — not only when a reviewer requests it.

### Reasoning

> Selecting the best-performing group out of N candidates and then testing only that group against a single-comparison threshold systematically inflates the apparent significance of the selected group (the "look-elsewhere effect" / multiple-comparisons problem). Without disclosing the corrected threshold, a study can present a selection artifact as if it were a pre-registered, single-hypothesis result. Making the correction a standard, always-reported output (rather than a reviewer-triggered follow-up) catches this at first submission instead of requiring a second pass.

### Evidence

> S-001 Diagnostic Addendum, Section 11 (Task 1): Development-era Q4-vs-complement result (MWU p=0.0216, t-test p=0.0162) fails Bonferroni-corrected α=0.01 for 5 quintiles tested; only Validation's independently-strong result (p<0.001, p=0.0012) cleared the corrected bar on its own.

### Consequences

> Enables: earlier, self-service detection of selection-effect inflation before a study reaches reviewer sign-off; consistent, comparable disclosure across all future quintile/threshold-selection studies.
> Rules out: reporting a "best of N" comparison's raw p-value as if it were a single pre-registered test without also showing the corrected view.

### Superseded By

> —

---

## Decision D-002 — Minimum Minority-Class Share for Standalone Binary Flag Testing

| Field | Value |
|---|---|
| **Date** | 2026-07-03 |
| **Status** | Active |

### Context

> H-003's six-flag Development screen (S-003) included `close_above_ema50` (flag=0 population: 66 of 17,749 rows, 0.37%) and `ema50_slope_pos` (flag=0 population: 189 of 17,744 rows, 1.07%). Both were terminated on statistical grounds (Bonferroni-corrected MWU p=0.28 and p=0.67 respectively), but even a hypothetically low p-value from a ~0.4–1% minority cell would be a fragile basis for a factor decision — a handful of rows can swing the comparison group's mean/median substantially, and the result would not generalize.

### Decision

> Binary flags with a minority-class population share below roughly 5% (of the relevant setup-type population) should be **excluded from standalone hypothesis testing** in future candidate factor pools. This is a screening rule applied before a hypothesis is even pre-registered, not a post-hoc statistical correction — thin-minority flags are excluded from the candidate list on population-share grounds, independent of whatever p-value they might produce.

### Reasoning

> A statistical test's p-value does not certify that a comparison is trustworthy when one side of it is built from a very small number of rows — regardless of how many rows are on the other side. Below roughly 5% minority share, any result (significant or not) is disproportionately sensitive to a handful of observations and does not constitute a reliable basis for a factor decision. Excluding these flags from the candidate pool up front is simpler and more honest than testing them and later discounting a "significant" result for the same reason.

### Evidence

> S-003 Development screen (H-003): `close_above_ema50` (0.37% minority share) and `ema50_slope_pos` (1.07% minority share) were among the candidate pool; both were independently terminated on statistical grounds, but their thin minority cells would have warranted exclusion or heavy discounting regardless of the p-value obtained.

### Consequences

> Enables: a simple, checkable pre-registration screen (compute the minority-class share before drafting the hypothesis) that prevents fragile-cell factors from consuming a Bonferroni correction slot or a Development-era test cycle.
> Rules out: standalone testing of a binary flag whose rarer class falls below ~5% of the population; such a flag may still be used as a **stratifier/control** (as `regime` and `sector` are used elsewhere) where thin cells are simply reported as underpowered rather than treated as a standalone hypothesis outcome.

### Superseded By

> —

---

## Decision D-003 — Candidate 4 (Gap-at-Breakout) Shelved

| Field | Value |
|---|---|
| **Date** | 2026-07-03 |
| **Status** | Active |

### Context

> Candidate 4 (Gap-at-Breakout, a binary flag comparing `open[setup_date] > pivot_high` gap breakouts vs. intraday grind-through breakouts) was proposed as a candidate factor. A feasibility check (2026-07-03) found `open` price data has 0.00% coverage for the entire Development era (2015-01-01 to 2019-12-31) in `prices`, `prices_adjusted`, and the merged BI source — confirmed by direct query, not assumed. A follow-up scoping check found this is a build-time/parser gap rather than a source limitation (the live and historical scrapers all receive an `Open` column from `ksestocks.com` but none of the four parser implementations in this codebase extracts it), and that a backfill is technically feasible but is a multi-session data engineering project (full historical re-scrape of ~3,700+ dates, new corporate-action-adjustment logic for the new column, and an EXP-0001/EXP-0002-style validation pass).

### Decision

> Candidate 4 (Gap-at-Breakout) is **shelved** — not registered as a hypothesis, not pursued further under the current research protocol. It is not revisited without a specific, separate PI decision to either (a) commission the Open-price backfill described in the 2026-07-03 scoping report, or (b) explicitly authorize a non-standard, Validation-start protocol that does not begin with a Development-era test.

### Reasoning

> This project's standing discipline requires every hypothesis to test Development first, sequentially, before Validation or OOS is opened (see Section 9, Certified_Dataset_v1.0.md). A factor with 0% data coverage in Development cannot be tested under this discipline at all — not "tested and found weak," but structurally impossible to evaluate under the pre-registration rule every other hypothesis in this project (H-001 through H-007) has been held to. Proceeding directly to Validation for this one factor, while every other candidate is required to clear Development first, would be a silent protocol exception — exactly the kind of undisclosed methodology drift the project's guardrails (see Addendum C, S-001) exist to prevent.

### Evidence

> Feasibility check (2026-07-03): 0/17,763 Development-era BREAKOUT rows joinable to a non-NULL `open` value (0.00%), vs. 30,170/48,776 (61.85%) for the full BREAKOUT certified population across all eras — the gap is specific to the pre-2020 span. Scoping check (2026-07-03): confirmed via direct inspection of `scraper.py`, `scrape_2005_2010.py`, `scrape_2010_2015.py`, and `scrape_historical_2015_2020.py` that `Open` is present in the scraped HTML source (column index 2 of the 8-column table) but is never parsed by any of the four scripts.

### Consequences

> Enables: the research program continues without carrying an untestable candidate in the active pool, and without creating a one-off exception to the Development-first rule.
> Rules out: any further work on Gap-at-Breakout under the current protocol until the PI makes an explicit, separate resourcing/protocol decision. Does not rule out revisiting this once (if) the Open-price backfill is completed — at that point it would be a normal Development-first pre-registration like any other candidate, not a special case.

### Superseded By

> —

---

_No further decisions recorded yet. Add entries above this line._
