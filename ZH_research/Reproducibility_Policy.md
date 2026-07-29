# Reproducibility Policy — PSX Quantitative Research Platform

> **Purpose:** Ensures that any study on this platform can be independently re-run by a future researcher and produce the same result.  
> **Related:** [Research_Standards.md](Research_Standards.md) · [Data_Quality_Policy.md](Data_Quality_Policy.md) · [Research_Log.md](Research_Log.md)

---

## Why Reproducibility Matters

A finding that cannot be reproduced is not a finding — it is a one-time observation that may reflect a data error, a methodological accident, or an undisclosed choice. Every evidence entry in [Evidence_Register.md](Evidence_Register.md) must be independently verifiable.

---

## Required Information per Study

Every study entry in [Research_Log.md](Research_Log.md) must contain enough information for an independent researcher to reconstruct the analysis exactly. This means:

### 1. Data Source
- Table name(s) used
- Column names used
- Date range (exact start and end dates, not "recent")
- Row count before filters
- Row count after each filter applied

### 2. Filters Applied
- Every filter stated explicitly in the methodology
- Order of filters applied
- How NULL values were handled for each column

### 3. Deduplication Rule
- Exact rule stated: e.g., "first date per (symbol, setup_type) per streak where bos_flag transitions from 0 to 1"
- Row count before and after deduplication

### 4. Outcome Construction
- Outcome variable: exact column name or construction rule
- Forward horizon: exact number of trading days
- How rows with NULL outcome (not yet resolved) were handled: excluded or imputed

### 5. Group Definition
- How groups were defined (binary split, quintiles, threshold)
- Threshold values stated numerically, not descriptively

### 6. Statistical Procedure
- Test used (if any)
- Software or computation method
- Significance level

### 7. Result Tables
- Raw numbers, not rounded approximations
- All groups, not a selection

---

## Database State at Study Time

Because `prices_adjusted` is periodically updated with corporate action corrections, the same query run at two different times may produce different numbers.

**Policy:**
- Record the latest date in `prices_adjusted` at the time the study was run
- Record the count of rows in `corporate_action_suspects` with status `PENDING` at study time
- If any PENDING suspects affect the symbols in the study, flag the study as potentially affected

This does not invalidate the study but provides context if results differ on a future replication.

---

## Version Pinning

When a study is closed:

- The study entry in Research_Log.md is considered final
- The methodology section must not be edited after the study is marked Complete
- If an error is discovered post-close, open a new study that replicates and corrects the original; do not edit the original
- Reference the correcting study in the original entry's Notes section

---

## Spot-Check Policy

Periodically (after every 10 completed studies), one past study should be selected at random and re-run to verify that:
- The result is reproducible using the documented methodology
- Database changes (new rows, adjustments) have not materially changed the finding

If a spot-check reveals a material discrepancy:
- Open a new study to investigate
- Update the original evidence entry's status to `Under Review`
- Document the discrepancy in [Known_Limitations.md](Known_Limitations.md)
