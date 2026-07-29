# Outcome Definitions — PSX Quantitative Research Platform

> **Purpose:** Authoritative definitions of every outcome variable available for research. Only variables defined here may be used as study outcomes.  
> **Related:** [Data_Quality_Policy.md](Data_Quality_Policy.md) · [Statistical_Guidelines.md](Statistical_Guidelines.md) · [Factor_Catalog.md](Factor_Catalog.md)

---

## Primary Outcome Variables

### OV-01 — 10-Day Forward Return

| Field | Value |
|---|---|
| **Source table** | `setup_log` |
| **Column** | `fwd_return_10d` |
| **Type** | REAL (percentage) |
| **Definition** | `(close[signal_date + 10 trading_days] − close[signal_date]) / close[signal_date] × 100` |
| **Window** | 10 trading days (calendar-day equivalent: ~14 days) |
| **Horizon type** | Fixed-exit, passive hold (no stop-loss applied) |
| **NULL handling** | Rows with NULL `fwd_return_10d` are excluded from outcome studies; they represent signals whose window has not yet closed |
| **Suitability** | Primary outcome for short-term factor studies; baseline for `outcome_label` |
| **Limitation** | Passive hold only. Does not reflect what a trader with a stop-loss would have experienced. A stock that hit −8% on day 5 then recovered to +3% on day 10 shows as +3%. |

---

### OV-02 — 20-Day Forward Return

| Field | Value |
|---|---|
| **Source table** | `setup_log` |
| **Column** | `fwd_return_20d` |
| **Type** | REAL (percentage) |
| **Definition** | `(close[signal_date + 20 trading_days] − close[signal_date]) / close[signal_date] × 100` |
| **Window** | 20 trading days (~one calendar month) |
| **Horizon type** | Fixed-exit, passive hold |
| **NULL handling** | Exclude; window not yet closed |
| **Suitability** | Primary outcome for medium-term and multi-factor studies |
| **Limitation** | Same passive-hold limitation as OV-01. Greater regime-shift risk over 20 days. |

---

### OV-03 — 5-Day Forward Return

| Field | Value |
|---|---|
| **Source table** | `setup_log` |
| **Column** | `fwd_return_5d` |
| **Type** | REAL (percentage) |
| **Definition** | `(close[signal_date + 5 trading_days] − close[signal_date]) / close[signal_date] × 100` |
| **Window** | 5 trading days (one calendar week) |
| **Horizon type** | Fixed-exit, passive hold |
| **NULL handling** | Exclude |
| **Suitability** | Short-term momentum studies; initial breakout reaction |
| **Limitation** | Too short for Stage 2 position trade assessment. Vulnerable to noise. |

---

### OV-04 — Outcome Label (Binary)

| Field | Value |
|---|---|
| **Source table** | `setup_log` |
| **Column** | `outcome_label` |
| **Type** | TEXT: `WINNER` / `LOSER` / `BREAKEVEN` |
| **Definition** | `WINNER` if `fwd_return_10d > 0`; `LOSER` if `< 0`; `BREAKEVEN` if `= 0` or `NULL` |
| **Derived from** | OV-01 (sign only; magnitude is lost) |
| **Suitability** | Win rate studies. Binary classification research. |
| **Limitation** | No magnitude information. A +0.1% return is WINNER same as +30%. In studies, prefer OV-01 or OV-02 alongside this variable. |
| **Note** | `BREAKEVEN` at insert = outcome not yet computed. Rows with `fwd_return_10d IS NOT NULL` will have a definitive label. Always filter to rows where `fwd_return_10d IS NOT NULL`. |

---

### OV-05 — Realized R (Risk-Adjusted)

| Field | Value |
|---|---|
| **Source table** | `backtest_setups` |
| **Column** | `realized_r` |
| **Type** | REAL |
| **Definition** | `(exit_price − entry_price) / (entry_price − stop_loss_price)`. Positive = profitable, negative = loss. `realized_r = 1.0` means exit was at 1× initial risk in profit. |
| **Horizon type** | Event-driven exit (stop hit, target hit, or time limit) |
| **Suitability** | Risk-adjusted quality assessment. Best single metric for evaluating trading-quality signal. |
| **Limitation** | Only available in `backtest_setups` (4,344 rows vs 205,821 in `setup_log`). The backtest methodology must be understood before interpreting this variable. |

---

### OV-06 — Custom Forward Return (Non-Standard Horizon)

For research requiring horizons not pre-computed in `setup_log` (e.g., 30d, 60d, 90d):

| Field | Value |
|---|---|
| **Source table** | `prices_adjusted` (computed by joining) |
| **Column** | N/A — computed at research time |
| **Definition** | `(close[signal_date + N] − close[signal_date]) / close[signal_date] × 100` where N is the trading-day offset |
| **Construction** | Join `setup_log` signal dates to `prices_adjusted` on symbol; find the row at offset N using date ranking within the symbol's price series |
| **Suitability** | Weinstein Stage 2 studies (90d horizon); long-term outcome validation |
| **Limitation** | Higher corporate-action risk over longer windows. More NULL values (delisted symbols). Must be constructed carefully. |

---

## Secondary Outcome Variables

### OV-07 — Actual P&L % (Executed Trades)

| Field | Value |
|---|---|
| **Source table** | `trade_setups` |
| **Column** | `actual_pl_pct` |
| **Suitability** | Validation against live execution. Too small (240 rows) for factor studies. |

---

## Outcome Variable Selection Guide

| Research Objective | Recommended Primary OV | Secondary OV |
|---|---|---|
| Quick factor screening | OV-04 (win rate) | OV-01 (mean return) |
| Factor magnitude study | OV-01 + OV-02 | OV-04 |
| Weinstein / Stage 2 study | OV-06 (90d) | OV-02 |
| Risk-adjusted quality | OV-05 | OV-01 |
| Short-term momentum | OV-03 | OV-04 |
| Live validation | OV-07 | OV-01 |

---

## Rules

1. The outcome variable must be selected before the study begins and not changed after data is examined
2. Multiple outcome variables may be used but one must be declared primary
3. Never use `outcome_label` without also checking `fwd_return_10d IS NOT NULL`
4. Custom forward returns (OV-06) must have their construction methodology fully documented in the study entry
