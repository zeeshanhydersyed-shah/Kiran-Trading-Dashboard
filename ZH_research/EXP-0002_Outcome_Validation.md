# EXP-0002 — Outcome Variable Validation
## PSX Quantitative Research Platform

---

> ### ⚑ IMMUTABLE RESEARCH PHILOSOPHY
> The purpose of this experiment is to reduce uncertainty — not to confirm a trading belief.
> Negative results are equally valuable. If this experiment concludes that any outcome variable
> is materially unreliable, that is a successful experiment. Phase 1 research blocked on a
> corrupted outcome is worse than Phase 1 delayed by honest validation.

---

## ─── BLOCK 1: IDENTITY ────────────────────────────────────────

| Field | Value |
|---|---|
| **Experiment ID** | EXP-0002 |
| **Title** | Outcome Variable Validation — Forward Returns and Outcome Labels |
| **Phase** | 0.5 — Dataset Validation |
| **Status** | `CLOSED` |
| **Opened** | 2026-07-01 |
| **Closed** | 2026-07-01 |
| **Experiment Type** | Descriptive / Validation |
| **Depends On** | EXP-0001 (Dataset Health Assessment) — `CLOSED` 🟢 Accepted |
| **Evidence Maturity** | Discovery → **Observed** ◉ → [Replicated / Validated not applicable — validation experiment] |

---

## ─── BLOCK 2: PRE-REGISTRATION `[PRE-REG]` ───────────────────

### 2.1 Research Question

```
Are the forward outcome variables stored in setup_log — fwd_return_5d, fwd_return_10d,
fwd_return_20d, and outcome_label — correctly calculated, internally consistent, free from
look-ahead bias, and sufficiently complete to serve as the ground-truth outcome measure
for Phase 1 factor research?
```

### 2.2 Hypotheses

| | Statement |
|---|---|
| **Null (H₀)** | All outcome variables are correctly computed; error rate in a random audit sample is below 1%; no structural flaw blocks Phase 1 research |
| **Alternative (H₁)** | At least one outcome variable contains a material error (audit error rate ≥ 1%, systematic look-ahead bias, or unresolved structural anomaly) requiring remediation before Phase 1 begins |
| **Expected Direction** | H₀ expected — EXP-0001 D6 confirmed perfect label consistency across all non-NULL rows; however two open anomalies from EXP-0001 must be investigated before H₀ can be formally accepted |

**Known open anomalies entering this experiment (from EXP-0001):**

| Anomaly | Source | Status |
|---|---|---|
| Reported 316 rows with non-NULL `outcome_label` but NULL `fwd_return_10d` — mechanism unknown | EXP-0001 D2 | Resolved — see Block 4, Step 3b |
| 1,964 NULL forward returns assumed to be the most recent ~20 trading days — not verified | EXP-0001 D3 | Resolved — see Block 4, Step 3a |

### 2.3 Primary Outcome Variable of This Experiment

| Field | Value |
|---|---|
| **Outcome Variable** | Error rate (%) in random audit sample — count of rows where reconstructed return ≠ stored return, divided by sample size |
| **Acceptance threshold** | Error rate < 1% → H₀ supported; error rate ≥ 1% → H₁ supported |

### 2.4 Variables Under Validation

| OV ID | Column | Table | Validation Scope |
|---|---|---|---|
| OV-01 | `fwd_return_10d` | `setup_log` | Primary — reconstruct from price history; verify formula |
| OV-02 | `fwd_return_20d` | `setup_log` | Secondary — spot-check formula consistency with OV-01 |
| OV-03 | `fwd_return_5d` | `setup_log` | Secondary — spot-check formula consistency with OV-01 |
| OV-04 | `outcome_label` | `setup_log` | Verify derivation from OV-01; investigate discrepancy |
| OV-05 | `realized_r` | `backtest_setups` | Inventory and document; reconstruction audit deferred |

### 2.5 Required Data

| Table | Columns Used | Join Condition |
|---|---|---|
| `setup_log` | `id, symbol, setup_date, setup_type, fwd_return_5d, fwd_return_10d, fwd_return_20d, outcome_label, outcome_tagged_date` | Primary table |
| `prices_adjusted` | `symbol, date, close` | `prices_adjusted.symbol = setup_log.symbol` — used to reconstruct forward returns |

### 2.6 Population Filter

```
All rows in setup_log where fwd_return_10d IS NOT NULL
  → Eligible N: 202,987 rows (all four setup types, full date range 2015–2026)

The NULL rows (1,964) are analysed separately in Step 3a.
The outcome_label anomaly rows are analysed separately in Step 3b.
```

### 2.7 Audit Sample Design

Reconstruction formula:
```
fwd_return_Nd_reconstructed =
  (close on the Nth trading day after setup_date − close on setup_date)
  / close on setup_date × 100

where "Nth trading day" = positional index N in the prices_adjusted series
for that symbol, ordered by date ascending
```

Stratified sample, seed = 2002:

| Stratum | Sample Size |
|---|---|
| BREAKOUT | 25 |
| RS_LEADER_MARKET | 28 |
| RS_LEADER_SECTOR | 37 |
| PRE_BREAKOUT | 10 |
| **Total** | **100** |

Tolerance: `abs(reconstructed − stored) ≤ 0.01 percentage points`

### 2.8 Pre-Defined Kill Criteria `[PRE-REG]`

```
Phase 1 research remains BLOCKED if ANY of the following are observed:

☐  Audit error rate ≥ 1% with unresolvable root cause

☐  Look-ahead bias confirmed — any exit price from a date on or before setup_date

☐  EXP-0001 discrepancy rows are genuine labelling errors affecting > 0.1% of population

☐  NULL forward return rows exist outside the expected recent-window / delisted-symbol context

☐  Corporate action adjustment absent — raw prices used instead of prices_adjusted

☐  Unvalidated MFE/MAE fields found in active use by downstream research code
```

### 2.9 Pre-Registration Sign-Off

| | |
|---|---|
| **Registered by** | Research Platform |
| **Date registered** | 2026-07-01 |
| **Data examined before registration?** | Partial — EXP-0001 established aggregate NULL counts before registration. Row-level detail, audit results, and discrepancy root causes were not examined. |

---

## ─── BLOCK 3: DATA QUALITY CHECK `[POST]` ────────────────────

| Check | Result | Pass / Warn / Fail |
|---|---|---|
| Total N in `setup_log` | 205,891 | Pass |
| Total N with non-NULL `fwd_return_10d` | 202,987 | Pass |
| NULL rate in `fwd_return_10d` | 1,964 / 205,891 = 0.95% | Pass — expected |
| Audit sample extracted (100 rows, 4 strata, seed 2002) | 100 rows confirmed | Pass |
| `prices_adjusted` coverage for all 100 audit symbols | Full coverage confirmed for all 100 | Pass |
| Any PENDING corporate action suspects affecting audit symbols | Not checked per-symbol — global check performed instead | See Step 6 |
| Partial NULL across horizons (5d NULL but 10d not NULL) | 0 rows | Pass |

**Data quality decision:** `Proceed`

---

## ─── BLOCK 4: RESULTS `[POST]` ───────────────────────────────

### Step 1 — Full Outcome Inventory

Every table in `psx_data.db` was scanned for outcome-type columns. Results:

**In scope for factor research (setup_log population):**

| OV ID | Column | Table | Rows | NULL Count | NULL % | Research Status |
|---|---|---|---|---|---|---|
| OV-01 | `fwd_return_10d` | `setup_log` | 205,891 | 1,964 | 0.95% | **Primary — validated below** |
| OV-02 | `fwd_return_20d` | `setup_log` | 205,891 | 1,964 | 0.95% | Validated below |
| OV-03 | `fwd_return_5d` | `setup_log` | 205,891 | 1,964 | 0.95% | Validated below |
| OV-04 | `outcome_label` | `setup_log` | 205,891 | 1,648 | 0.80% | Validated below — gap documented |
| OV-05 | `realized_r` | `backtest_setups` | 4,344 | 1,917 | 44.1% | Inventoried — not audited here |

**Out of scope for setup_log factor research (different populations / purposes):**

| Column | Table | Rows | Notes |
|---|---|---|---|
| `return_20d` | `market_regime` | 5,313 | 20 NULLs; regime-level metric, not setup-level |
| `outcome`, `realized_r`, `pl_pkr` | `sim_portfolio_trades` (×3 versions) | 4,160 each | Portfolio simulation output, not research outcomes |
| `outcome`, `actual_pl_pct` | `trade_setups` | 738 | Live trade log; too small for factor research |
| `outcome`, `actual_pl_pct` | `agent_opportunities` | 31 | Agent output; not a research table |
| `fwd_return_5d/10d/20d`, `outcome_label` | `leaders_top_picks` | 12 | All NULLs (recent); not a research table |
| `actual_return` | `prediction_log` | 8 | Model prediction log; not a research table |

**MFE / MAE fields:** Not present in any table in `psx_data.db`. No MFE/MAE columns exist.

**Target hit / Stop hit indicators:** Present in `backtest_setups` (`outcome` column with values Win_T1, Win_Trail, Loss, Expired, Stale_Setup) and `sim_portfolio_trades` (`t1_hit` column). Neither is a setup_log column. No target/stop hit columns exist in setup_log.

**Finding:** The research outcome universe is exactly as documented in `Outcome_Definitions.md`. No undocumented outcome columns were discovered. No MFE/MAE, target hit, or stop hit fields exist in `setup_log`. Kill criterion 6 (undocumented fields in active use) is not triggered.

---

### Step 2 — Formula Verification

Source: `compute_forward_returns.py`

```python
# Price series: prices_adjusted, ordered by date ascending
price_seq = [(date, close), ...]
date_index = {date: (positional_index, close)}

idx, close_0 = date_index[setup_date]

# Window closure check: skip if fewer than 20 prices follow setup_date
if idx + 20 >= len(price_seq):
    skipped += 1  # correctly marks row as NULL
    continue

close_5  = price_seq[idx + 5][1]
close_10 = price_seq[idx + 10][1]
close_20 = price_seq[idx + 20][1]

fwd10 = (close_10 - close_0) / close_0 * 100
```

**Formula confirmed:**

| Property | Verified |
|---|---|
| Price source | `prices_adjusted` (not raw `prices`) |
| Entry price | `close` on `setup_date` |
| Exit price | `close` at positional index + N (trading days, not calendar days) |
| Null handling | Row is left NULL if fewer than 20 prices follow setup_date in the symbol's series |
| Division by zero guard | `if close_0 == 0: skipped` |
| All three horizons computed together | Yes — 5d, 10d, 20d are either all populated or all NULL |

The formula is correct. No look-ahead elements are present in the computation logic.

---

### Step 3a — NULL Characterisation

**Overall NULL breakdown:**

| Condition | Count |
|---|---|
| `fwd_return_10d` NULL AND `outcome_label` NULL | 708 |
| `fwd_return_10d` NULL AND `outcome_label` = 'BREAKEVEN' (insert default) | 1,256 |
| `fwd_return_10d` NOT NULL AND `outcome_label` NULL | **940** ← see Step 3b |
| Both populated (normal) | 202,987 |
| **Total** | **205,891** |

**Null date range:** 64 distinct dates with NULL `fwd_return_10d`, spanning 2024-04-16 to 2026-07-01.

**Last non-NULL setup_date:** 2026-06-01

**Two distinct populations within the 1,964 NULL rows:**

**Population A — Delisted symbols (100 rows, 2024-04-16 to 2025-03-17):**
These symbols had their PSX listing terminate before the 20-trading-day window could close. The algorithm correctly leaves them NULL — the required future price does not exist. Confirmed examples:
- PSMC: 8 setups (2024-04-16 to 2024-04-25); last price in `prices_adjusted` = 2024-04-25
- FFBL: multiple setups (Nov–Dec 2024); last price = 2024-12-20
- PIAA: 1 setup (2024-04-26); last price = 2024-05-24

These are **permanent NULLs** — no forward return is recoverable. These 100 rows must be excluded from outcome studies permanently.

**Population B — Open window (1,864 rows, approx. 2026-04 to 2026-07-01):**
These are recent setups whose 20-trading-day forward window had not closed as of the computation date. They will be filled in naturally as the pipeline runs on future dates.

**Finding:** All 1,964 NULL forward returns are structurally explained. There is no computation failure. The NULL rows fall into two documented categories: permanently irrecoverable (delisted, 100 rows) and temporarily open (recent window, ~1,864 rows).

---

### Step 3b — Discrepancy Investigation: Outcome Label vs Forward Return

**EXP-0001 reported "316-row discrepancy."** That number was an arithmetic artifact: it subtracted total NULL outcome_label count (1,648) from total NULL return count (1,964) and assumed the difference (316) represented rows with non-NULL labels but NULL returns. This calculation is only valid if every NULL-label row also has a NULL return, which is false. The actual matrix is in Step 3a above.

**Two genuine anomalies exist, both fully explained:**

**Anomaly 1 — 1,256 rows: NULL return + `outcome_label` = 'BREAKEVEN'**

These are setups inserted by `append_setup_log_today()` (Phase 7.3 pipeline). The insert SQL sets `outcome_label = 'BREAKEVEN'` as the default for every new row. When `compute_forward_returns.py` later runs, these rows remain NULL if their window hasn't closed. The BREAKEVEN label is a pipeline placeholder, not a genuine classification.

All 1,256 rows have `outcome_tagged_date = NULL`, confirming no labelling step has run for them.

**Classification: Expected pipeline behavior. Not an error.**

**Anomaly 2 — 940 rows: Populated return + `outcome_label` = NULL**

These 940 rows were all created at `2026-06-13 17:43:52–17:43:53` (one-second batch) with setup dates spanning 2026-05-11 to 2026-06-01. They were inserted by a backfill run that used the historical `backfill_setup_log.py` INSERT SQL, which does **not** set `outcome_label`. When the forward window closed and `compute_forward_returns.py` ran, the returns were correctly populated. However, `append_setup_log_today` Step 3 (the labelling update) contains the filter `WHERE fwd_return_10d IS NOT NULL AND outcome_label = 'BREAKEVEN'`. Since these rows have `outcome_label = NULL`, the WHERE clause excludes them — the labelling step never fires.

These 940 rows have **correct forward returns** but **missing outcome labels**.

**Classification: Labelling gap — minor pipeline defect. Returns are correct. Labels are derivable from the stored return. Not a data error — a pipeline omission.**

**Remediation required:** A one-time UPDATE will resolve this before Phase 1:
```sql
UPDATE setup_log
SET outcome_label = CASE
    WHEN fwd_return_10d > 0 THEN 'WINNER'
    WHEN fwd_return_10d < 0 THEN 'LOSER'
    ELSE 'BREAKEVEN'
END
WHERE fwd_return_10d IS NOT NULL
  AND outcome_label IS NULL;
```
This does not require any recomputation — it derives labels from already-validated stored returns. Until this is run, factor studies must not filter on `outcome_label` alone; they must filter on `fwd_return_10d IS NOT NULL` and derive the label from the return value directly, or use both filters.

---

### Step 4 — Look-Ahead Bias Check

All 100 audit rows were checked: for each sampled setup, the exit date (positional index + 10 in the symbol's price series) was compared against the entry date (setup_date).

**Result: 100/100 exit dates are strictly after setup_date. Zero look-ahead violations.**

The formula uses positional indexing within the symbol's `prices_adjusted` series, not calendar date arithmetic. The entry price is always the close on the setup_date itself (index 0). The exit price is always a strictly later date (index 10). No mechanism for look-ahead exists in the computation.

---

### Step 5 — Random Audit Results (100 rows, seed 2002)

Pool sizes at time of sampling:

| Stratum | Pool Size | Sampled |
|---|---|---|
| BREAKOUT | 48,765 | 25 |
| RS_LEADER_MARKET | 56,489 | 28 |
| RS_LEADER_SECTOR | 93,423 | 37 |
| PRE_BREAKOUT | 5,250 | 10 |
| **Total** | **203,927** | **100** |

**Reconstruction audit results:**

| Stratum | N | 5d Matches | 10d Matches | 20d Matches | Label Matches |
|---|---|---|---|---|---|
| BREAKOUT | 25 | 25/25 | 25/25 | 25/25 | 25/25 |
| RS_LEADER_MARKET | 28 | 28/28 | 28/28 | 28/28 | 28/28 |
| RS_LEADER_SECTOR | 37 | 37/37 | 37/37 | 37/37 | 37/37 |
| PRE_BREAKOUT | 10 | 10/10 | 10/10 | 10/10 | 10/10 |
| **Total** | **100** | **100/100** | **100/100** | **100/100** | **100/100** |

**Error rate: 0.0% across all horizons and all strata.**

No discrepancies were observed at the 0.01 percentage-point tolerance threshold. Every reconstructed return matched the stored return exactly within tolerance. Every outcome label matched the sign of the stored `fwd_return_10d`.

---

### Step 6 — Corporate Action Adjustment Check

`prices_adjusted` and `prices` contain identical row counts: **1,819,802 rows each**. The tables are initialized as mirrors. Divergence only occurs when `rebuild_symbol_adjusted()` is called with a confirmed corporate action factor — at that point, pre-event rows for the affected symbol in `prices_adjusted` are multiplied by the adjustment factor.

`compute_forward_returns.py` uses `prices_adjusted` exclusively (confirmed in the `load_price_sequence()` function). Both the entry price and the exit price for any given setup are drawn from the same table and the same symbol's series, ensuring corporate action adjustments are applied consistently to both legs of the return calculation.

**Finding:** No cross-table contamination. If a symbol has an unconfirmed corporate action, both entry and exit prices are unadjusted equally — the return is internally consistent even if not adjusted, because the same unadjusted series is used throughout. The `corporate_action_suspects` table manages pending reviews.

---

### Step 7 — Outcome Label Derivation Audit

For all 100 audit rows, the expected label was derived from the stored `fwd_return_10d` sign (WINNER if > 0, LOSER if < 0, BREAKEVEN if = 0) and compared against the stored `outcome_label`.

**Result: 0/100 label mismatches.**

This confirms that for rows where the labelling pipeline ran (i.e., `outcome_label` is not NULL), the derivation from `fwd_return_10d` is perfectly consistent. The 940-row labelling gap (Step 3b) is not a mislabelling problem — it is the absence of a label where one was never written, not a wrong label.

---

### Step 8 — Backtest Outcome Inventory (OV-05)

| Field | Value |
|---|---|
| **Table** | `backtest_setups` |
| **Column** | `realized_r` |
| **Total rows** | 4,344 |
| **NULL realized_r** | 1,917 (44.1%) |
| **Non-NULL realized_r** | 2,427 |
| **Range (non-NULL)** | −1.000 to +11.112 |
| **Mean (non-NULL)** | +0.619 |

**Outcome distribution:**

| Outcome | Count | `realized_r` |
|---|---|---|
| `Win_Trail` | 1,562 | Populated |
| `Loss` | 776 | Populated (= −1.000 by construction: stop hit) |
| `Win_T1` | 89 | Populated |
| `Stale_Setup` | 1,841 | NULL — setup never triggered |
| `Expired` | 76 | NULL — triggered but no target/stop reached within time limit |

The 1,917 NULL `realized_r` values are fully explained by the 1,841 + 76 = 1,917 Stale_Setup and Expired outcomes. No genuine computation gaps exist.

**Reconstruction audit for OV-05 is deferred.** The backtest engine applies entry trigger logic, trailing stop logic, and time-limit exits — auditing these requires a separate experiment validating the backtest methodology, not just the forward return formula. OV-05 is documented here but not certified for Phase 1 factor research. Phase 1 uses OV-01 through OV-04 only.

---

## ─── BLOCK 5: INTERPRETATION `[POST]` ────────────────────────

### 5.1 Primary Finding

```
The evidence supports H₀. The 100-row stratified reconstruction audit produced a 0.0%
error rate across all three forward return horizons (5d, 10d, 20d) and all four setup
types. No look-ahead bias was detected (100/100 exit dates strictly post-entry). The
forward return formula in compute_forward_returns.py is correctly implemented and uses
prices_adjusted consistently. The EXP-0001 "316-row discrepancy" was a mis-characterized
arithmetic artifact; the underlying anomalies are fully explained and neither constitutes
a data error. One minor pipeline defect exists (940 rows with valid returns but NULL
outcome labels) requiring a one-time SQL fix before Phase 1 win rate studies.
Phase 1 research is cleared to proceed on OV-01, OV-02, OV-03, and OV-04.
```

### 5.2 Kill Criteria Review

| Kill Criterion | Triggered? | Evidence |
|---|---|---|
| Audit error rate ≥ 1% with unresolvable root cause | **No** | 0/100 errors (0.0%) |
| Look-ahead bias confirmed | **No** | 100/100 exit dates strictly after entry |
| Discrepancy rows are genuine labelling errors > 0.1% | **No** | 1,256 rows = pipeline placeholder (BREAKEVEN default); 940 rows = missing label, not wrong label |
| NULL return rows outside expected context | **No** | 100 rows = delisted symbols (no price data); ~1,864 rows = open window |
| Corporate action adjustment absent | **No** | `prices_adjusted` used consistently in both entry and exit prices |
| Unvalidated MFE/MAE fields in active use | **No** | No MFE/MAE fields exist anywhere in the database |

**Kill criteria verdict:** No criteria triggered. All six criteria cleared.

### 5.3 Hypothesis Verdict

| | |
|---|---|
| **H₀ supported?** | Yes |
| **Audit error rate** | 0.0% (0/100) |
| **All kill criteria clear?** | Yes — all six |
| **Phase 1 cleared to proceed?** | **Yes — with one pre-Phase-1 remediation (940-row label fix)** |

### 5.4 Remediation Required Before Phase 1

**Action 1 — One-time SQL: Label the 940 NULL outcome_label rows** *(non-blocking for return-based studies; required before any win rate study)*

```sql
UPDATE setup_log
SET outcome_label = CASE
    WHEN fwd_return_10d > 0 THEN 'WINNER'
    WHEN fwd_return_10d < 0 THEN 'LOSER'
    ELSE 'BREAKEVEN'
END
WHERE fwd_return_10d IS NOT NULL
  AND outcome_label IS NULL;
-- Affects 940 rows. No recomputation required. Labels derived from validated stored returns.
```

**Action 2 — Filter rule (standing guidance for all Phase 1 experiments)**

Every experiment that uses `outcome_label` must also filter on `fwd_return_10d IS NOT NULL`. Never use `outcome_label` as the sole completeness filter. The safe pattern:

```sql
WHERE fwd_return_10d IS NOT NULL
  AND outcome_label IN ('WINNER', 'LOSER')   -- or BREAKEVEN if including zeros
```

**Action 3 — Permanently exclude 100 delisted-symbol rows from outcome studies**

These 100 rows (PSMC, FFBL, PIAA, and similar delisted names with setup dates 2024-04-16 to 2025-03-17) have no recoverable forward return. They are correctly NULL and will remain NULL. Any population filter using `fwd_return_10d IS NOT NULL` automatically excludes them.

### 5.5 Caveats Specific to This Experiment

- The audit sample of 100 rows cannot detect error rates below ~3% with high confidence. An error rate of, say, 0.5% across the full population would not be detectable at this sample size. The 0.0% observed result is strong evidence that the error rate is low, but does not guarantee zero errors in the full 202,987-row population.
- OV-05 (`realized_r` in `backtest_setups`) is inventoried but not audited. Its reconstruction requires a separate experiment validating the backtest engine's entry trigger and exit logic.
- The corporate action check confirms consistency (same table used for both legs) but does not certify that all corporate actions have been correctly identified and adjusted. Symbols with undetected corporate actions may have quietly incorrect returns in both `prices` and `prices_adjusted`.

### 5.6 What This Result Does Not Establish

- This experiment does not establish that the outcome variable is the right measure for trading quality. A 10-day passive hold return does not reflect stop-loss management, trailing stop exits, or realistic execution.
- This experiment does not validate OV-05 (`realized_r`) for use in factor research.
- This experiment does not validate OV-06 (custom forward returns) — those are constructed at research time and validated at construction time.
- This result does not guarantee that the corporate action adjustment records are complete. Symbols with missed corporate actions may have incorrect `prices_adjusted` values, which would silently corrupt their stored forward returns. The reconstruction audit would not detect this if the same corrupted price was used for both reconstruction and storage.

### 5.7 Alternative Explanations

- **The 0.0% audit error rate could reflect that errors are confined to a setup type or time period not represented in the sample.** With 25–37 rows per stratum, any error type affecting < 4% of a stratum could have been missed. The pre-registered tolerance of 0.01pp is narrow enough that rounding would not mask genuine errors.
- **The 940 NULL-label rows could indicate a broader pipeline sequencing risk** — if a similar backfill is run in future without the 'BREAKEVEN' default, the labelling gap would recur silently. This is a pipeline robustness issue, not a data correctness issue in the current dataset.
- No plausible alternative explanation for the 0/100 audit result: the formula is simple, the price source is consistent, and the position-index approach to counting trading days is not vulnerable to calendar/holiday variation.

---

## ─── BLOCK 6: EVIDENCE CLASSIFICATION `[POST]` ───────────────

| | |
|---|---|
| **Classification** | 🟢 Accepted |
| **Confidence Level** | Strong — census-level checks (formula, NULL structure, discrepancy root cause); reconstruction audit at N=100 across all four setup types |

**Rationale:**

```
The forward return calculation is correct, internally consistent, and free from look-ahead
bias. The reconstruction audit at N=100 returned 0 errors across 5d, 10d, and 20d horizons.
The outcome label derivation is correct for all labelled rows. The "316-row discrepancy" from
EXP-0001 is fully explained: 1,256 rows carry the pipeline's insert-default BREAKEVEN label
while awaiting return computation (expected behavior), and 940 rows have valid returns but
no label due to a one-time pipeline backfill that did not set the default (minor defect,
one-line SQL fix). No kill criteria were triggered. Phase 1 research on OV-01 through
OV-04 is cleared to proceed after the 940-row label fix.
```

**Classification criteria:**

| Criterion | Met? |
|---|---|
| Audit sample N ≥ 100 | Yes — exactly 100 |
| All kill criteria reviewed and cleared | Yes — 6 of 6 cleared |
| NULL anomaly fully resolved | Yes — both anomaly types explained and classified |
| Look-ahead bias check passed | Yes — 100/100 |
| Corporate action handling confirmed consistent | Yes |

---

## ─── BLOCK 7: EVIDENCE MATURITY `[POST]` ─────────────────────

```
EXP-0002 — Outcome Variable Validation

  Discovery ✅  →  Observed ◉  →  [Replication / OOS stages not applicable — validation experiment]
```

**Current Stage: Observed**

A validation experiment of this type — census-level formula verification plus reconstruction audit — reaches Observed on close and terminates the maturity pipeline at that stage, consistent with EXP-0001 precedent.

---

## ─── BLOCK 8: CROSS-REFERENCES `[POST]` ──────────────────────

| Field | Value |
|---|---|
| **Evidence Register Entry** | E-0002 |
| **Evidence bucket** | 🟢 Accepted |
| **Depends on** | EXP-0001 — Dataset Health Assessment (🟢 Accepted) |
| **Experiments this result unlocks** | EXP-0003 (Sample Independence), EXP-0101 (Base Rate Characterisation) |
| **Outcome Definitions update** | Add filter rule to OV-04 entry: "Always filter `fwd_return_10d IS NOT NULL` in addition to `outcome_label` filters." Add note on 940-row labelling gap and the 100 permanent-NULL delisted rows. |
| **Known_Limitations.md update** | Add: 100 delisted-symbol rows (permanent NULLs, excluded by standard filter); 940-row labelling gap (requires one-time fix); OV-05 not yet certified. |

---

## ─── BLOCK 9: REUSABLE ASSET `[POST]` ────────────────────────

| Field | Value |
|---|---|
| **Asset Type** | Validated outcome variable report + confirmed formula documentation + root-cause resolution of EXP-0001 discrepancy |
| **Asset Description** | Confirmed 0.0% reconstruction error rate across 100 stratified audit rows; confirmed look-ahead-free formula; full NULL breakdown with root cause for every category; resolved 316-row discrepancy |
| **Where it lives** | This document (EXP-0002), Blocks 4 and 5 |
| **How future experiments use it** | Cite EXP-0002 as the source of outcome variable certification. No future experiment needs to re-verify the forward return formula, re-investigate the 940/1,256/100 row categories, or repeat the look-ahead check. The standard population filter `WHERE fwd_return_10d IS NOT NULL` is certified as sufficient to produce a clean analysis population (202,987 rows after the 940-row label fix). |

---

## ─── EXPERIMENT LOG ────────────────────────────────────────────

| Date | Entry |
|---|---|
| 2026-07-01 | Pre-registration completed. Six kill criteria defined. Audit sample: 100 rows, seed = 2002, stratified by setup type. Two open anomalies from EXP-0001 formally scoped in. Experiment opened. |
| 2026-07-01 | Full outcome inventory executed across all 42 database tables. MFE/MAE fields not present. No undocumented outcome columns found in setup_log. Kill criterion 6 cleared. |
| 2026-07-01 | Formula verified from compute_forward_returns.py source code. prices_adjusted used consistently. Division-by-zero guard confirmed. Window closure logic confirmed. |
| 2026-07-01 | NULL characterisation complete. Two populations identified: 100 delisted-symbol rows (permanent NULL), ~1,864 open-window rows (temporary NULL). |
| 2026-07-01 | EXP-0001 "316-row discrepancy" fully resolved. 1,256 rows = insert-default BREAKEVEN (expected). 940 rows = backfill without default + labelling gap (minor defect, returns are correct). Not a genuine labelling error. Kill criterion 3 cleared. |
| 2026-07-01 | 100-row reconstruction audit executed. 0/100 errors at 0.01pp tolerance. 0/100 label mismatches. 100/100 look-ahead checks passed. Kill criteria 1 and 2 cleared. |
| 2026-07-01 | Corporate action check: prices_adjusted used for both entry and exit prices in every return calculation. Kill criterion 5 cleared. |
| 2026-07-01 | All six kill criteria cleared. H₀ supported. Classification: 🟢 Accepted. Phase 1 cleared pending 940-row label fix. Maturity: Observed. Experiment closed. |
