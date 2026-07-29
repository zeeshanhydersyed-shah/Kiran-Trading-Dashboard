# Documentation Style Guide — PSX Quantitative Research Platform

> **Purpose:** Standards for writing all documents in this research workspace. Ensures consistency, reduces ambiguity, and makes documents easy to navigate after long periods away.  
> **Related:** [Naming_Conventions.md](Naming_Conventions.md) · [Research_Governance.md](Research_Governance.md)

---

## Tone and Voice

- Write in plain declarative English. State what is, not what might be.
- Use active voice: "The factor predicts outcomes" not "Outcomes are predicted by the factor."
- Be precise: "N = 342, win rate = 61.4%" not "a few hundred observations, win rate around 60%."
- Do not hedge with "perhaps" or "may" when data is available. Hedge only when uncertainty is real.
- Do not editorialize: "surprisingly," "interestingly," and "notably" add no information.

---

## Structure

### Every document must have:
1. A title (H1, `# Title`)
2. A purpose statement and cross-references block (blockquote under the title)
3. Content sections (H2, `## Section`)
4. Subsections where needed (H3, `### Subsection`)

### Headers
- H1: Document title only (one per document)
- H2: Major sections
- H3: Subsections within a section
- H4: Used sparingly, only for nested subsections
- Do not skip heading levels

---

## Tables

Use tables for:
- Factor definitions, column mappings, and field schemas
- Comparison of conditions, outcomes, or options
- Status tracking (pipelines, registries, logs)

Table rules:
- Header row is always present
- Use `|---|` alignment row
- Align columns consistently (left align is default)
- Every cell should have content; use `—` for empty cells, not blank

Example:
```markdown
| ID | Name | Status |
|---|---|---|
| S-001 | Base Rate Study | Open |
| S-002 | RS Rank Study | Design |
```

---

## Code and Column Names

- Use `backtick` format for all column names, table names, file names, function names, and SQL keywords
- Examples: `setup_log`, `fwd_return_10d`, `prices_adjusted`, `bos_flag`
- Use code fences (triple backticks) for multi-line code, formulas, and SQL queries

---

## Cross-References

- Link to related documents using Markdown syntax: `[Document Name](FileName.md)`
- Cross-references go in the blockquote at the top of the document and inline where the related concept first appears
- Do not use bare filenames without link text

---

## Status Indicators

| Symbol | Meaning |
|---|---|
| ✅ | Passed, complete, or confirmed |
| ⚠️ | Warning, review required, or uncertain |
| ❌ | Failed, missing, or blocked |
| — | Not applicable or not yet assessed |

---

## Numbers and Statistics

- Always report N alongside percentages: "61.4% (N=342)" not just "61.4%"
- Use two decimal places for percentages and return figures: "4.32%" not "4.3%" or "4.3213%"
- Report confidence intervals as `[lower, upper]` with 95% CI specified
- Use plain language for p-values: "p < 0.05" not "0.0000431"
- State the test used: "chi-square test" or "t-test on means"

---

## Dates

- ISO 8601 for all dates: `YYYY-MM-DD` (e.g., `2026-07-01`)
- Never use relative dates in documents: not "last week" or "recently"; always the actual date
- When referring to the in-sample period, write `2020-01-01 to 2023-12-31`
- When referring to the out-of-sample period, write `2024-01-01 onwards`

---

## IDs and Naming

All IDs follow the conventions in [Naming_Conventions.md](Naming_Conventions.md):
- Research Questions: `RQ-001`
- Hypotheses: `H-001`
- Studies: `S-001`
- Evidence entries: `E-001`
- Factors: `F-01`
- Outcome Variables: `OV-01`
- Assumptions: `A-01`
- Limitations: `L-01`
- Backlog items: `BL-S-01`, `BL-M-01`, etc.

---

## Document Maintenance

- Date of last update: include at the bottom of active tracking documents (pipeline, backlog, evidence register)
- Do not delete content — mark superseded rows as `Superseded` or add a strike and keep the record
- Version numbers: use `V1.0`, `V1.1`, `V2.0` format for versioned artefacts (models, engine specs)

---

## What Not to Include

- Do not include speculative content that is not labelled as speculative
- Do not paste raw SQL query results (summarise them instead)
- Do not include personal commentary or informal asides
- Do not duplicate content from another document; instead, cross-reference it
- Do not write implementation instructions in research documents (those belong in CLAUDE.md or the application codebase)
