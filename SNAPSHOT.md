# Snapshot: pre_audit_stable_snapshot_2026-05-29

## What this snapshot is

This is a stable working-state snapshot of the Kiran PSX Intelligence Platform taken on **29 May 2026**, immediately after a full system audit was completed. No code was changed by the audit — this snapshot reflects the exact state of the platform as it existed when the audit ran.

## What was audited

A senior quantitative systems audit was performed across the entire codebase on 2026-05-29. The audit found 23 issues. The full report is in `AUDIT_REPORT_2026-05-29.md`.

## System state at this snapshot

| Component | Status |
|-----------|--------|
| Daily price scraper | Working |
| Trade analytics (240 closed trades) | Working — numbers verified |
| Excel journal import | Working (local only) |
| Backtest engine | Working (local SQLite) |
| Weinstein / Regime indicator | Working |
| STM screener display | Working when gates pass |
| **Live setup screener** | **Broken — produces 0 setups (CRITICAL-1)** |
| **ML confidence score** | **Miscalibrated — train/serve skew (CRITICAL-2)** |
| KSE-100 gate (cloud/Supabase) | Broken — silent crash (HIGH-1) |

## Database state at this snapshot

- `psx_data.db` — local SQLite database backed up as `backups/psx_data_backup_2026-05-29.db`
- Supabase (cloud) database is live and separate; not included in this file backup
- Analytics verified: **240 closed trades · 114 wins · 126 losses** (matches Excel JOURNAL-2)
- Schema exported to: `backups/schema_export_2026-05-29.sql`

## Key files at this snapshot

| File | Notes |
|------|-------|
| `dashboard.py` | Main Streamlit app — 17 pages |
| `processor.py` | Live screener — BROKEN (sector label mismatch, see CRITICAL-1) |
| `backtest.py` | Historical backtest engine — working locally |
| `phase4_train.py` | ML training — uses mean() vs live median() (see CRITICAL-2) |
| `kiran_model.pkl` | LightGBM model — trained on backtest data with mean() rankings |
| `kiran_model_features.pkl` | Feature list for live inference |
| `database.py` | SQLite backend — missing `trade_execution` column in migrations |
| `database_pg.py` | PostgreSQL/Supabase backend |
| `import_actual_trades.py` | Excel journal sync — uses SQLite `?` placeholders (safe locally) |
| `agent.py` | Trading desk agent — working |
| `AUDIT_REPORT_2026-05-29.md` | Full audit report with all 23 findings |

## Audit findings summary

### Critical (2)
1. Live screener generates zero setups — label mismatch in `processor.py`
2. ML model trained on `mean()` sector rankings, live inference uses `median()`

### High (4)
1. `KSE100Filter` crashes silently on PostgreSQL — `.execute()` not valid on psycopg2 connection
2. `evaluate_paper_trades()` writes wrong outcome case and status values
3. `evaluate_paper_trades()` queries non-existent SQLite column `trade_execution`
4. `import_actual_trades.py` uses `?` placeholders — would crash on PostgreSQL

### Moderate (7) / Low (10)
See `AUDIT_REPORT_2026-05-29.md` for full details.

## How to restore from this snapshot

1. Copy `backups/psx_data_backup_2026-05-29.db` to `psx_data.db` to restore local DB
2. All Python files are in git — checkout this commit hash to restore code
3. Supabase (cloud) is not affected by local restores — managed separately

## Commit

```
git checkout pre_audit_stable_snapshot_2026-05-29
```
or by commit hash shown in `git log`.
