# PSX Intelligence Platform — Full System Audit
**Date:** 2026-05-29  
**Auditor:** Senior Quantitative Systems Auditor  
**Scope:** Full codebase — data pipeline, screener, backtest, ML, dashboard, agent, import

---

## SEVERITY CLASSIFICATION

| Level | Meaning |
|-------|---------|
| 🔴 CRITICAL | Live system is silently broken or data is corrupted |
| 🟠 HIGH | Significant logic error; affects real outputs but not immediately obvious |
| 🟡 MODERATE | Inconsistency that can cause wrong numbers under specific conditions |
| 🔵 LOW | Technical debt, maintenance risk, or silent fail-safe behaviour |

---

## 🔴 CRITICAL FINDINGS

### CRITICAL-1: Live screener generates ZERO setups (processor.py vs generate_trade_setups)

**File:** `processor.py`  
**What happened:** `compute_sector_rankings()` was updated to return Weinstein Stage labels:
```
"Stage 2: Advancing", "Stage 3: Topping", "Stage 4: Declining", "Stage 1: Basing"
```

But `generate_trade_setups()` in the same file still filters using the **old** label set:
```python
SHORT_MOM = {"Rolling Over", "Falling"}
LONG_MOM  = {"Heating Up", "Cooling Down"}
```

These sets will never match the Stage labels. As a result, `s_mom in LONG_MOM` is always `False` and `s_mom in SHORT_MOM` is always `False`.

**Consequence:** Every call to `generate_trade_setups()` returns an empty list. The GitHub Actions `daily_scraper.yml` has been saving zero setups to Supabase since the label change was made. No new System setups have been auto-generated.

**Evidence:**  
- `processor.py` lines 97–108: Stage labels returned  
- `processor.py` lines 391–392: LONG_MOM / SHORT_MOM still use old labels  
- `backtest.py` lines 55–56 and 247–254: Backtest still uses old labels correctly — backtest is unaffected

**Docstring lie:** The docstring of `compute_sector_rankings()` in `processor.py` still documents the old label names ("Heating Up", "Cooling Down", etc.), contradicting the actual code. The function comment and its caller are now fully out of sync.

---

### CRITICAL-2: Backtest sector ranking uses mean(); live screener uses median()

**Files:** `backtest.py` (line 243: `mean()`), `processor.py` (line 91: `median()`)

The backtest replicates the screener logic inside `_sector_rankings()` but uses `mean()` to compute sector performance. The live screener's `compute_sector_rankings()` uses `median()`.

**Consequence:** The ML model (`kiran_model.pkl`) was trained on backtest data where sector rankings were computed with `mean()`. Live inference (`get_ml_confidence()` in `dashboard.py`) uses `sector_rank` derived from `median()`-based rankings. The `sector_rank` feature passed to the model is on a different distribution than the training data. Model predictions are therefore slightly miscalibrated — particularly for sectors with outlier stocks that pull mean away from median.

This is a systematic train/serve skew.

---

## 🟠 HIGH FINDINGS

### HIGH-1: KSE100Filter crashes on PostgreSQL (Supabase/Cloud)

**File:** `kse100_filter.py` lines 47–53

```python
from database import get_conn
with get_conn() as conn:
    rows = conn.execute("""SELECT date, close FROM index_prices ...""").fetchall()
```

When `DATABASE_URL` is set, `get_conn()` yields a **psycopg2 connection**. psycopg2 connections do not have `.execute()` — only cursors do. This raises `AttributeError`, which is caught by the `except Exception` wrapper, and the function returns an empty DataFrame.

**Two opposite consequences on Cloud:**

1. **In `generate_trade_setups()`**: `kse_filter.long_allowed()` falls back to `True` (no suppression). LONGs are always permitted regardless of the index being below its 50-day MA. The KSE-100 trend gate is silently disabled.

2. **In `_run_stm_screener()`**: `kse100_d.get("above_ma50", False)` → `False` because `kse100_summary()` returns `{"available": False}` with no `above_ma50` key. `gate_kse` is always `False`. The STM LONG gate **never passes** on Cloud.

The same underlying bug causes opposite failures in two different features.

---

### HIGH-2: `evaluate_paper_trades()` writes wrong outcome/status values

**Files:** `database.py` lines 769, 778, 791, 797; `database_pg.py` lines 789, 796, 805, 811

Both versions set:
```python
outcome = "LOSS"   # or "WIN"
status  = "Hit SL" # or "Hit Target"
```

But the data migrations in both files explicitly normalize these:
```sql
UPDATE trade_setups SET outcome='Loss' WHERE outcome='LOSS'
UPDATE trade_setups SET outcome='Win'  WHERE outcome IN ('WIN', 'win')
UPDATE trade_setups SET status='Closed' WHERE status IN ('Hit Target', 'Hit SL')
```

Any trade evaluated by `evaluate_paper_trades()` would be stored with:
- `outcome='WIN'` or `'LOSS'` (uppercase)
- `status='Hit SL'` or `'Hit Target'`

The dashboard outcome filters check for `'Win'`, `'Loss'`, `'Breakeven'` (proper case). These trades would be **invisible** to all dashboard analytics and trade log filters.

**Additional issue in SQLite version:** The `results["evaluated"]` counter is never incremented in `database.py`'s `evaluate_paper_trades()` (the counter logic is missing — it exists in `database_pg.py` but was not copied to the SQLite version). The function always returns `{"evaluated": 0}` regardless of what it actually processed.

**Dormant but dangerous:** `evaluate_paper_trades` is imported in `dashboard.py` line 58 but is never called anywhere in the dashboard. If ever wired up, it will corrupt outcome data.

---

### HIGH-3: `evaluate_paper_trades()` queries non-existent SQLite column

**File:** `database.py` lines 727–734; `database_pg.py` lines 747–750

The query uses `WHERE trade_execution='Paper'`. The `trade_execution` column is added in `database_pg.py` migrations (line 226) but is **absent from `database.py`'s SQLite migrations** (lines 112–130). On SQLite, this query raises `OperationalError: no such column: trade_execution`, which propagates uncaught through `get_conn()`.

---

### HIGH-4: `import_actual_trades.py` uses SQLite placeholders on PostgreSQL

**File:** `import_actual_trades.py` lines 179–184, 217–231, 253–276

All queries use `?` placeholders (SQLite syntax). When `DATABASE_URL` is set and `get_conn()` returns a psycopg2 connection, these queries will fail with `ProgrammingError: syntax error at or near "?"`. psycopg2 requires `%s` placeholders.

The script runs locally via `run_update.bat` and typically does NOT have `DATABASE_URL` set, so this has been silently safe. But anyone who runs it in an environment where `DATABASE_URL` is set (e.g., during a migration or on a server) will get errors on every row.

---

## 🟡 MODERATE FINDINGS

### MODERATE-1: Support Reversal setups have no deduplication guard

**File:** `database.py` line 563; `database_pg.py` line 610

`setup_already_saved()` only checks `source='System'`. There is no equivalent guard for `source='Support Reversal'` or `source='STM'` (the STM dedup uses a separate `stm_pick_already_saved()` function). The `generate_support_reversal_setups()` in `processor.py` has no dedup call. Each daily run by the GitHub Action could re-insert the same support reversal setup if the candle pattern repeats on the same day.

---

### MODERATE-2: Support reversal setups store target_1r = target_2r = 0.0

**File:** `processor.py` lines 757–758; `database.py` line 422

The setup dict is created with `"target_1r": None, "target_2r": None`. The `save_trade_setup()` functions fall back to `s.get("target_1r", 0.0)` → stores 0.0. The setup has no valid profit targets. Any code computing RR ratio from `(target_2r - entry_price) / (entry_price - stop_loss)` would get `(0 - entry) / (entry - sl)` — a large negative number. Dashboard columns that display R:R from stored target prices will show garbage for this source.

---

### MODERATE-3: execution_type logic differs between dashboard and agent

**Files:** `dashboard.py` line 1936; `agent.py` line 2089

Dashboard:
```python
row.get("actual_entry") is not None and row.get("actual_entry") > 0
```

Agent:
```python
s.get("actual_entry") is not None
```

If `actual_entry = 0` (a data anomaly — zero fill price), the dashboard classifies the trade as "Paper" while the agent classifies it as "Paper & Actual". Trade counts in agent performance reports and dashboard analytics will diverge for these edge cases.

Also: `agent.py` line 2092 has `"Support Reversal"` listed **twice** in the source check:
```python
src in ("System", "STM", "Support Reversal", "Support Reversal")
```
Harmless but indicates copy-paste error.

---

### MODERATE-4: `generate_support_reversal_setups()` has no "open" column — wick calculation is wrong

**File:** `processor.py` lines 663–690

The function accesses `latest.get("open", close)` but the `raw_prices` DataFrame (from `get_sector_price_data()`) has columns: `symbol, sector, date, high, low, close, volume`. There is no `open` column in the database schema. Therefore `open_p` always equals `close`.

This means:
- `wick_bottom = min(open_p, close) = min(close, close) = close`
- `lower_wick_ratio = (close - low) / (high - low)`

Which is algebraically identical to `recovery_ratio = (close - low) / (high - low)`.

Both quality checks in the score are computing the same thing. The "lower_wick_ratio" filter at 60% and "recovery_ratio" filter at 75% are nearly the same condition. The pattern effectively has only two truly independent checks out of three.

---

### MODERATE-5: ATR calculation in support reversal screener is broadcast incorrectly

**File:** `processor.py` line 657

```python
grp["atr"] = compute_atr_pct(grp["close"].tolist())
```

`compute_atr_pct()` returns a single scalar (average ATR over the full price history). This scalar is broadcast to the entire column. `latest.get("atr", 0)` then retrieves this single number as if it were the candle's ATR. The ATR shown in setup notes is for the entire symbol history, not the recent volatility. For long-history symbols, this could be very different from the current ATR.

---

### MODERATE-6: Monthly P&L table buckets by created_date when exit_date is missing

**File:** `dashboard.py` lines 2112–2113

```python
ref_date = pd.to_datetime(
    closed["exit_date"].fillna(closed["created_date"]), errors="coerce"
)
```

For "Actual" source trades where `exit_date` is null (Active/still-open), the code falls back to `created_date` (entry date). These trades are excluded from `closed` (filtered by outcome IN Win/Loss/Breakeven), so in practice this is safe for closed trades. However, if any trade is classified as "Closed" but missing `exit_date` (possible data anomaly), it would be bucketed in the wrong month.

---

### MODERATE-7: `phase4_train.py` hardcodes SQLite DB path and ignores DATABASE_URL

**File:** `phase4_train.py` line 56

```python
DB_PATH = "psx_data.db"
```

This bypasses `config.DB_PATH` and always reads from a local SQLite file using a relative path. This is intentional (training is local-only), but if the working directory differs from the repo root, training fails silently with an empty dataset.

---

## 🔵 LOW FINDINGS

### LOW-1: `database.py` PG override list is incomplete

**File:** `database.py` lines 827–861

The following functions are defined in both `database.py` and `database_pg.py` but are **not in the PG override import list**:
- `get_prices_for_breadth`
- `get_latest_prices`
- `cleanup_ghost_dates`
- `auto_save_setups_with_source` (also not defined in `database_pg.py` at all)

These work correctly on PG only because the functions they call internally (`get_conn`, `save_trade_setup`, etc.) are overridden. This is "works by accident" — any future change to these functions could break PG behaviour without any obvious signal.

---

### LOW-2: `evaluate_paper_trades` imported but never called

**File:** `dashboard.py` line 58

`evaluate_paper_trades` is imported at the top of `dashboard.py` but there is no call site anywhere in the file. It is dead code. Combined with HIGH-2 and HIGH-3, this is fortunate — calling it would corrupt data.

---

### LOW-3: `backtest.py` uses SQLite PRAGMA — would fail on PG

**File:** `backtest.py` lines 63–88

```python
existing = [
    r[1] for r in conn.execute("PRAGMA table_info(backtest_setups)").fetchall()
]
```

`PRAGMA` is SQLite-only. If `backtest.py` is ever run in an environment where `DATABASE_URL` is set, this will fail. Currently it reads `backtest_setups` from local SQLite only, so this is safe in practice.

---

### LOW-4: CLAUDE.md page index is significantly outdated

**File:** `CLAUDE.md`

The CLAUDE.md documents 13 pages (indices 0–12). The current `dashboard.py` has 17 pages (indices 0–16). Discrepancies:

| CLAUDE.md | dashboard.py |
|-----------|-------------|
| Page 0: 🧭 Regime | Page 0: **🎯 Market Gates Dashboard** (NEW) |
| Page 5: 🎖️ The Audit | **Does not exist** — removed from PAGES list |
| — | Pages 13–16: Model Health, Agent, Valuation, Flows (NEW) |

"The Audit" page referenced in CLAUDE.md's "Known Issues" section no longer exists in the deployed dashboard. The known issues remain outstanding with no page to address them.

---

### LOW-5: `subprocess` call inside `dashboard.py` violates Streamlit Cloud constraints

**File:** `dashboard.py` lines 914–922

```python
_auto_sp.run([_auto_sys.executable, _log_script, "log-today"], ...)
```

CLAUDE.md explicitly states: "No subprocess calls — cannot run Python scripts via subprocess" as a Streamlit Cloud constraint. This is wrapped in try/except and silently fails on Cloud, but it means `part7_prediction_log.py` is never executed on Cloud, and prediction logs are never updated from the live deployment.

---

### LOW-6: Capital flows hardcoded in dashboard.py

**File:** `dashboard.py` lines 2757–2766

```python
CAPITAL_FLOWS = [
    ("2024-10-01", -498_767),
    ...
    ("2026-03-31", -1_000_000),
]
```

Capital injection/withdrawal history is embedded as code. Adding new transactions requires a code deployment. Given the portfolio is active, this will drift over time. This data belongs in the `portfolio_transactions` table (which exists and is already populated via the Portfolio page) — but the equity curve calculation doesn't use that table.

---

### LOW-7: Duplicate label mapping — `compute_sector_rankings` docstring vs code

**File:** `processor.py` lines 71–77 (docstring) vs lines 97–108 (code)

The docstring documents the six original labels:
> "Heating Up", "Cooling Down", "Recovering", "Rolling Over", "Falling", "Stabilising"

The actual code produces four Stage labels:
> "Stage 2: Advancing", "Stage 3: Topping", "Stage 4: Declining", "Stage 1: Basing"

The docstring has not been updated since the label change. Anyone reading the docstring to understand the function's output will be misled.

---

### LOW-8: `import_actual_trades.py` drops `quantity` from insert

**File:** `import_actual_trades.py` lines 253–276

The script reads `qty` from the Excel column (line 154) but never includes it in the INSERT statement. The `quantity` column exists in the PG schema (database_pg.py migration line 225). Actual trade quantities are never persisted.

---

### LOW-9: P&L percentage scaling heuristic is ambiguous

**File:** `import_actual_trades.py` lines 162–163

```python
pl_pct = float(raw) * 100 if abs(float(raw)) < 5 else float(raw)
```

This assumes: if |value| < 5, it is a decimal fraction (e.g., 0.03 = 3%); otherwise it is already a percentage. A trade with a 2% P&L stored as `2.0` (not 0.02) in Excel would be misinterpreted as 0.02 → scaled to 200%. The heuristic is correct for the current Excel layout but is fragile and undocumented.

---

### LOW-10: `backtest_setups` has no corresponding table in PostgreSQL schema

**File:** `database_pg.py` `init_db()`

The `backtest_setups` table is created in `database.py` SQLite via `backtest.py`'s `init_backtest_table()`. However, `database_pg.py`'s `init_db()` does NOT create `backtest_setups`. The `get_backtest_summary()` function in both files queries this table with a try/except that silently returns `[]` if it doesn't exist. The Backtest page on Supabase would always show empty unless the table was manually created.

---

## SUMMARY TABLE

| ID | Severity | Module | Description |
|----|----------|--------|-------------|
| CRITICAL-1 | 🔴 | processor.py | Live screener NEVER generates setups — label mismatch |
| CRITICAL-2 | 🔴 | backtest.py vs processor.py | mean() vs median() in sector ranking → train/serve skew |
| HIGH-1 | 🟠 | kse100_filter.py | psycopg2 connection has no .execute() → KSE gate broken on Cloud |
| HIGH-2 | 🟠 | database.py / _pg.py | evaluate_paper_trades writes LOSS/WIN (wrong case) + Hit SL/Target (wrong status) |
| HIGH-3 | 🟠 | database.py | evaluate_paper_trades queries non-existent SQLite column trade_execution |
| HIGH-4 | 🟠 | import_actual_trades.py | SQLite ? placeholders will fail if DATABASE_URL is set |
| MODERATE-1 | 🟡 | processor.py / database | Support Reversal setups have no dedup guard |
| MODERATE-2 | 🟡 | processor.py | Support Reversal target_1r/2r stored as 0.0 → wrong RR display |
| MODERATE-3 | 🟡 | dashboard.py vs agent.py | execution_type differs: actual_entry > 0 vs is not None |
| MODERATE-4 | 🟡 | processor.py | No "open" column → lower_wick_ratio = recovery_ratio (duplicate check) |
| MODERATE-5 | 🟡 | processor.py | ATR broadcast to full column instead of per-candle computation |
| MODERATE-6 | 🟡 | dashboard.py | Monthly P&L uses created_date fallback if exit_date missing |
| MODERATE-7 | 🟡 | phase4_train.py | Hardcoded relative DB path ignores config.DB_PATH |
| LOW-1 | 🔵 | database.py | PG override list missing 4 functions (work by delegation) |
| LOW-2 | 🔵 | dashboard.py | evaluate_paper_trades imported but never called |
| LOW-3 | 🔵 | backtest.py | PRAGMA table_info would fail on PG |
| LOW-4 | 🔵 | CLAUDE.md | Page index 6 pages out of date; Audit page deleted |
| LOW-5 | 🔵 | dashboard.py | subprocess violates Streamlit Cloud constraints |
| LOW-6 | 🔵 | dashboard.py | Capital flows hardcoded, not using portfolio_transactions table |
| LOW-7 | 🔵 | processor.py | Docstring documents old labels, code uses Stage labels |
| LOW-8 | 🔵 | import_actual_trades.py | quantity read but never saved to DB |
| LOW-9 | 🔵 | import_actual_trades.py | P&L % scaling heuristic is ambiguous and undocumented |
| LOW-10 | 🔵 | database_pg.py | backtest_setups table not created in PG init_db() |

---

## RECOMMENDED PRIORITY ORDER (for fixing)

1. **CRITICAL-1** — Fix momentum label constants in `generate_trade_setups`. Either revert `compute_sector_rankings` labels to old names, or update `LONG_MOM`/`SHORT_MOM` to the Stage labels. The backtest is using old names correctly — decide on one canonical set and apply consistently.

2. **HIGH-1** — Fix `kse100_filter.py` to use a cursor instead of `conn.execute()` on PG. Use `database_pg._fetchall()` pattern or detect backend.

3. **CRITICAL-2** — Align `backtest.py`'s `_sector_rankings()` to use `median()` (matching processor) or vice versa. Retrain the model after aligning.

4. **HIGH-2/HIGH-3** — Fix `evaluate_paper_trades` outcome/status casing, or remove it (it is never called).

5. **MODERATE-1** — Add a dedup check for `source='Support Reversal'` before saving support reversal setups.

6. **HIGH-4** — Wrap `import_actual_trades.py` to use PG-compatible placeholders when DATABASE_URL is set, or add a guard that prevents running it against PG.

---

*This report is read-only. No code was modified during this audit.*
