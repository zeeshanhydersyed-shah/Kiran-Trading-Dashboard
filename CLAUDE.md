# Kiran PSX Trading Dashboard — Project Reference

## Deployment
- **GitHub:** zeeshanhydersyed-shah/Kiran-Trading-Dashboard (branch: `main`)
- **Live app:** kiran-trading-dashboard-g9dfmiwilzbuef2vzlktwh.streamlit.app (Streamlit Cloud)
- **Database:** Supabase PostgreSQL — `DATABASE_URL` in Streamlit secrets
- **Python:** 3.11

## How changes go live
1. Edit files locally in `C:\Users\Lenovo\psx_pipeline\`
2. `git add` + `git commit` + `git push origin main`
3. Streamlit Cloud auto-redeploys on push — takes ~60 seconds

Local edits alone **never** update the live app.

## Key files
| File | Purpose |
|------|---------|
| `dashboard.py` | Main Streamlit app — all pages/UI |
| `processor.py` | Trade setup generation (`generate_trade_setups`, `_run_stm_screener`) |
| `database.py` | Auto-switches SQLite↔PostgreSQL based on `DATABASE_URL` env var |
| `database_pg.py` | Supabase/PostgreSQL implementation |
| `main.py` | CLI entry point (`--update` scrapes + saves setups) |
| `scraper.py` | PSX price scraper (ksestocks.com) |
| `phase4_train.py` | Kiran ML model training (reads Supabase, saves kiran_model.pkl) |
| `kiran_model.pkl` | LightGBM model — predicts Win_Trail probability (setup quality) |
| `kiran_model_features.pkl` | Ordered feature list for live inference |
| `config.py` | EXCLUDED_SECTORS, INDEX_SYMBOLS, DFC_SYMBOLS filter lists |
| `weinstein.py` | Weinstein stage analysis / regime detection |
| `backtest.py` | Backtesting engine |
| `kiran_sim.py` | Portfolio simulation — buy-on-strength rules, 1% risk, 6% max SL |
| `load_bi_history.py` | Loads merged BI CSVs into psx_data.db (run after DB restore or BI refresh) |

## Supabase tables
| Table | Contents |
|-------|---------|
| `prices` | Daily OHLCV per symbol |
| `index_prices` | KSE-100 / index daily prices |
| `sectors` | symbol → sector mapping |
| `trade_setups` | All setups (Pending/Active/Closed), source = System or STM |
| `backtest_setups` | Historical backtest results used for ML training |

## GitHub Actions (automated)
| Workflow | Schedule | What it does |
|----------|----------|-------------|
| `daily_scraper.yml` | Mon–Fri 11:35 UTC (16:35 PKT) | Scrapes PSX prices, generates trade setups |
| `weekly_backtest.yml` | Sunday | Runs backtest engine |
| `weekly_ml_retrain.yml` | Sunday 10:00 UTC | Retrains kiran_model.pkl via phase4_train.py |

## Dashboard pages (PAGES list in dashboard.py)
0. 🧭 Regime
1. 📊 Market
2. 🔍 Explorer
3. 📈 History
4. 📋 Trade Log
5. 🎖️ The Audit
6. 📉 Analytics
7. 💡 Setups
8. 🔎 STM
9. 🔄 Support Reversals
10. 🎯 Setup Perf
11. 🤖 Backtest
12. 🗂️ Portfolio

## ML model architecture
Two separate models:
- **kiran_model.pkl** — LightGBM, predicts Win_Trail probability (setup quality score). Trained on `backtest_setups`. 10 features: `log_vol`, `atr_pct`, `stock_perf_30d`, `risk_pct`, `momentum_ratio`, `dist_to_entry_pct`, `sector_rank`, `month`, `stock_perf_10d`, `breadth_score`. Retrained weekly via GitHub Actions.
- **direction_model.pkl** — Next-day market direction (from Part 3 of the 8-part pipeline, local only, not yet in Streamlit Cloud)

## Kiran filtering rules (from config.py)
Setups exclude: derivatives, futures (regex `-JAN/-FEB/...`), and 14 sectors including TEXTILE SPINNING, MODARABAS, SUGAR & ALLIED INDUSTRIES, etc. See `config.py` for full lists.

## Streamlit Cloud constraints — IMPORTANT
- **No persistent filesystem** — cannot write CSV/pkl files at runtime
- **No subprocess calls** — cannot run Python scripts via subprocess
- **No local DB** — SQLite doesn't work; must use Supabase via `database_pg.py`
- **Secrets** — all credentials in Streamlit secrets, accessed via `st.secrets`
- **Model files** — `kiran_model.pkl` and `kiran_model_features.pkl` are in the repo (committed), so they are available on Cloud

## Historical data — BI PostgreSQL merge

### Source
Local PostgreSQL at `localhost:55432` (database `postgres`, user `postgres`, password `1234`).
App folder: `D:\BUSINESS\PSX TRADING\DIL APP\RS SW\zeeshan\BI`
Tables: `company_history` (OHLCV per symbol per date), `index_history` (index OHLCV).

### Merged output files (already generated, in repo root)
| File | Rows | Symbols | Date range |
|---|---|---|---|
| `merged_psx_data.csv` | 412,207 | 409 | 2020-01-01 → 2026-05-08 |
| `merged_index_data.csv` | 1,575 | KSE-100, KSE-MIALL, KSE-MI30 | 2020-01-01 → 2026-05-08 |

Merge strategy: **Kiran scraper data wins on overlapping dates** (2024+).
BI data fills the pre-2024 historical gap. Excluded sectors and futures already filtered out.
96 BI-only symbols (no Kiran sector mapping) are included in price data but excluded from the screener (no `sectors` table entry → not picked up by the `JOIN`).

### How to (re-)load into psx_data.db
Run **once** after any refresh of the BI source or after restoring the SQLite DB:
```
python load_bi_history.py
```
Then re-run the backtest to label outcomes for the new historical dates:
```
python backtest.py
```
The backtest is resumable — `screened_dates` tracks progress, already-processed dates are skipped automatically.

### How to refresh the BI merge (full re-merge from PostgreSQL)
The BI PostgreSQL must be running (`StartDB.cmd` in the BI folder starts it).
The previous merge script is no longer in the repo; if needed, connect to `localhost:55432/postgres`,
query `company_history` (OHLCV + eventdate) and `index_history`, and write new CSVs to the repo root
following the column names in `merged_psx_data.csv`. Then run `python load_bi_history.py`.

### DB state after full load
| Table | Rows | Symbols | Date range |
|---|---|---|---|
| `prices` | ~581K | ~2,520 | 2020-01-01 → latest scrape |
| `index_prices` | ~3,910 | KSE-100 + 4 others | 2020-01-01 → latest scrape |

---

## Local-only files (not in repo, not on Cloud)
The 8-part ML pipeline scripts (`part1_` through `part8_`) are local development tools only:
- `part2_feature_engineering.py` — builds features dataset
- `part3_train_test_split.py` — trains direction_model.pkl
- `part4_monthly_retrain.py` — monthly retrain orchestrator
- `part6_predictions.py` — BUY/SELL signal translator
- `part7_prediction_log.py` — prediction logging
- `part8_model_diagnostic.py` — model diagnostic

Do NOT import these in dashboard.py — they are not available on Streamlit Cloud.

## STM quality score (added recently)
4-point score computed inline in dashboard.py for each STM row:
1. RS > 5% vs KSE-100
2. 5d range ≤ 5%
3. 0% < dist above 21 MA ≤ 5%
4. Risk ≤ 3%

---

## Recent Changes (May 2026)

### Trade Execution Tracking
**Trade Log page now tracks execution type:**

| Execution | Definition | Counted in Analytics |
|-----------|-----------|----------------------|
| **Paper** | Screener suggestion not yet traded | ❌ No |
| **Actual** | Discretionary trade (user's own call) | ✅ Yes |
| **Paper & Actual** | Screener suggestion + actually traded | ✅ Yes |

**Calculation (dynamic, based on source + actual_entry):**
```python
if source == 'Actual':
    execution_type = 'Actual'
elif source in ('System', 'STM', 'Support Reversal') and actual_entry is not None:
    execution_type = 'Paper & Actual'
else:
    execution_type = 'Paper'
```

**Trade Log Filters:**
- Status: Pending / Active / Closed
- Source: System / STM / Support Reversal / Actual
- **Execution: All / Paper / Actual / Paper & Actual** ← NEW
- Symbol search

**Performance Table (Closed Trades Only):**
Shows metrics by execution type:
- All closed trades
- Paper (closed but untouched by user)
- Actual (user's discretionary closed trades)
- Paper & Actual (screener + user actually traded)

Metrics: Trade count, Wins, Losses, Win%, Loss%, Avg P&L%

### Status Values (Simplified)
- **Pending** — Created but not executed (user hasn't entered actual fill)
- **Active** — In trade (user entered actual fill, waiting for exit)
- **Closed** — Exited (hit SL, TP, or BE) with outcome recorded

**Note:** Outcome (Win/Loss/Breakeven) is separate from Status.

### Analytics & Setup Performance Filtering
- **Analytics page:** Only shows **Actual + Paper & Actual** trades (excludes pure Paper)
- **Setup Performance page:** Only shows System setups that were **Paper & Actual** (actually traded)
- **Audit page:** Should filter same way (needs update — see below)

### Performance Optimizations
- Cache TTL increased: 30 min → 2 hours (load_data function)
- Added "⚡ Clear Cache" button in sidebar for manual refresh
- Result: Page loads <1s after initial cache load (instead of 3-4s every 30 min)

### Data Fixes
- Standardized outcome values to proper case: 'Loss', 'Win', 'Breakeven' (was mixed: 'LOSS', 'Loss', etc.)
- HBL SHORT (ID 293) marked as Active (open trade, not Pending)

### Known Issues to Address
- **Audit page** mixes all system setups with user trades. Should filter to **Actual + Paper & Actual only** (matching Trade Log)
- Manager confusion about "system trades" — Audit should clearly show only real executed trades

---

## Agent System (agent.py)

### Architecture
Four sub-agents orchestrated by `TradingDeskAgent`:
- **PatternAnalyzerAgent** — finds patterns from closed trade history, saves to `agent_patterns` table
- **RegimeDetectorAgent** — identifies market regime (trending/ranging/bear) + playbook
- **OpportunityGeneratorAgent** — independent universe scan, picks 3–5 setups, saves to `agent_opportunities`
- **PerformanceTrackerAgent** — reviews edge health, flags degradation

### Key agent files
| File | Purpose |
|------|---------|
| `agent.py` | Main orchestrator + all sub-agents + chat interface |
| `agent_db.py` | SQLite tables: agent_patterns, agent_opportunities, agent_reports, chat_log, trader_profile |
| `agent_benchmark.py` | KSE-100 comparison — alpha per trade, rolling 30d verdict |
| `agent_learn.py` | Weekly self-learning loop — updates trader behavioral profile |
| `import_actual_trades.py` | Syncs Excel JOURNAL-2 → psx_data.db (runs daily via run_update.bat) |
| `fix_paper_actual.py` | One-time utility — finds Paper & Actual trades duplicated in Excel import |

### LLM cost strategy — IMPORTANT
- **Chat interface** (`chat_with_agent()`) → uses **Groq** (free, llama-3.3-70b-versatile)
- **Agent runs** (daily analysis, all 4 sub-agents) → uses **Claude** (Haiku for daily, Sonnet for weekly/monthly)
- Groq key in `.env` as `GROQ_API_KEY`. Falls back to Claude if key missing or Groq fails.
- Rule: **no Claude API calls except the agent run** — chat is always Groq

### Running the agent
```
python agent.py              # daily analysis
python agent.py --type weekly   # deep weekly report
run_agent.bat                # same as daily via batch
```
GitHub Actions does NOT run agent.py — it runs daily_scraper.yml (scrape + setups only).
Agent is run locally or manually.

### Reference breakout learning
User can teach the agent what a good setup looks like:
```python
from agent import analyze_reference_breakout
analyze_reference_breakout("LUCK", "2026-04-15", direction="LONG", notes="...")
analyze_reference_breakout("BAFL", "2026-05-05", direction="SHORT", notes="...")
```
Saves to `agent_reference_breakouts` table. Agent uses these as calibration examples when screening.

---

## Excel Journal Sync — CRITICAL

### Source
`D:\PERSONAL\Personal Sheets\ASSET ALLOCATION\ASSET ALLOCATION.XLSX` — sheet: `JOURNAL-2`

### Column mapping
| Excel col | DB field |
|-----------|---------|
| Date1 | created_date (entry date) |
| Name | symbol |
| Status | C=Closed / O=Active |
| BUY | entry_price + actual_entry |
| SELL | actual_exit |
| Gain/Loss | actual_pl_pkr |
| Gain/Loss% | actual_pl_pct |
| SL | stop_loss |
| R:R | actual_rr |
| Days | holding_days |
| POS | direction (Long/Short) |

### Import behaviour (upsert — not insert-only)
`import_actual_trades.py` runs daily via `run_update.bat`. It:
1. **Inserts** new trades not yet in DB
2. **Updates** existing trades when status, outcome, pl_pkr, or pl_pct differs from Excel
3. **Reclassifies** any Breakeven records where actual_pl_pct ≠ 0 → Win or Loss

Outcome threshold: `pl_pct > 0 = Win`, `pl_pct < 0 = Loss`, `pl_pct == 0 = Breakeven` (matches Excel exactly).

### Verified state (May 2026)
Analytics page matches Excel: **240 closed trades · 114 wins · 126 losses**
Excel is always ground truth for P&L, status, and outcome.
