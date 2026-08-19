# Kiran PSX Trading Dashboard — Project Reference

## Deployment
- **GitHub:** zeeshanhydersyed-shah/Kiran-Trading-Dashboard (branch: `main`)
- **Live app:** kiran-trading-dashboard-g9dfmiwilzbuef2vzlktwh.streamlit.app (Streamlit Cloud)
- **Database:** Supabase PostgreSQL — `DATABASE_URL` in Streamlit secrets
- **Python:** 3.11

## How changes go live
1. Edit files locally in `C:\Users\Lenovo\psx_pipeline\`
2. `git add` + `git commit` + `git push origin main`
3. **CI runs first** (`.github/workflows/ci.yml` — clean install on 3.11, unit
   tests, and a boot smoke test that renders all 15 pages). It does not block
   the deploy until branch protection is enabled on `main` — see
   [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) §3.
4. Streamlit Cloud auto-redeploys on push — takes ~60 seconds

Local edits alone **never** update the live app.

**Preferred flow once the staging app exists:** push to `staging`, let CI go
green, click through the staging Cloud app, then `git merge --ff-only staging`
into `main`. Full procedure, rollback and hotfix paths: `docs/DEPLOYMENT.md`.

**Before pushing anything, run the gate locally:**
```
pip install -r requirements.txt -r requirements-dev.txt
pytest
```
`pytest.ini` limits collection to `tests/` (the loose root `test_*.py` files
are one-off research scripts, not a suite). If you change the database schema,
regenerate the CI fixture too: `python tests/fixtures/build_fixture_db.py`.

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
| `apply_price_adjustments.py` | Corporate action price adjustments — full rebuild + incremental hooks |
| `stock_signals.py` | Daily RS ranks, base tightness, pivot signals per symbol |
| `sector_signals.py` | Daily sector RS scores, breadth, composite scores |
| `backfill_setup_log.py` | Historical + daily setup_log population (all 4 setup types) |
| `compute_forward_returns.py` | Fills fwd_return_5d/10d/20d for setup_log rows once window closes |

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
| `ci.yml` | Every push/PR to `main` and `staging` | **The deploy gate** (added 2026-08-12). 3 jobs: `clean-install` (pip install + `pip check` + import all production modules on Python 3.11), `unit-tests` (`pytest tests/`), `app-boot` (renders all 15 dashboard pages via Streamlit's `AppTest` against `tests/fixtures/psx_fixture.db`). See `docs/DEPLOYMENT.md` |
| `daily_scraper.yml` | Mon–Fri 17:00 UTC (22:00 PKT) | Scrapes PSX prices, generates trade setups. This late hour is load-bearing, not incidental — ksestocks.com does not finish publishing final EOD figures until evening PKT; confirmed live 2026-08-17 that genuine same-day data (distinct KSE-100 close, not an echo of the prior session) was already available by ~19:40 PKT, well ahead of this job's 22:00 PKT run. Installs `playwright` explicitly — it is in `requirements-optional.txt`, not `requirements.txt` |
| `weekly_backtest.yml` | Sunday | Runs backtest engine |
| `weekly_ml_retrain.yml` | Manual only (`workflow_dispatch`) | Retrains kiran_model.pkl via phase4_train.py — schedule disabled 2026-07-31, model killed (see docs/KIRAN_CLEANUP_AUDIT.md §14). Installs `requirements-optional.txt` too — scikit-learn/joblib live there |
| `eod-scraper.yml` | Manual only (cron commented out) | Alternative headless EOD scrape → Supabase. **Installs its own unpinned package list, not `requirements.txt`** — known drift, see audit §23.5 |
| `fix_gal_sector.yml` | Manual only | One-off sector-mapping fix |
| `weekly_sim.yml` | Manual only (`workflow_dispatch`) | Runs kiran_sim.py (active-trading portfolio sim) — schedule disabled 2026-08-05, dashboard section retired, same mechanism already Concluded — negative 2026-05-12 (see docs/KIRAN_CLEANUP_AUDIT.md §19) |

## Dashboard pages (PAGES list in dashboard.py)
0. 🎯 Market Gates Dashboard
1. 🧭 Regime
2. 📊 Market
3. 🔍 Explorer
4. 📈 History
5. 📋 Trade Log
6. 📉 Analytics
7. 🔄 Recovery Bases
8. 🎯 Setup Perf
9. 🤖 Backtest
10. 🗂️ Portfolio
11. 🤖 Agent
12. 🏆 Leaders
13. 📋 Setup History
14. 🏥 Data Health

*(STM killed June 2026 — 82% overlap, Z-histogram unvalidated. Minervini killed June 2026 — N=29 proxy, 86% BREAKOUT overlap. 📡 Flows retired 2026-07-29 — Big Fish study found the underlying FIPI/LIPI flow data null, 0/360 forward cells; see docs/KIRAN_CLEANUP_AUDIT.md. `page_flows.py`'s `scrape_flows_today()` is still called from `main.py`'s daily hook — it still feeds `sector_signals.py`'s descriptive-only `Flow` column on the Market page. 🏥 Model Health retired 2026-07-31 — its ML conviction model was killed (coin-flip CV AUC 0.524±0.059, zero live consumers, retrain pipeline disconnected from production); page removed from nav, kiran_model.pkl/phase4_train.py/prediction_log.csv kept in place, unread by any page; see docs/KIRAN_CLEANUP_AUDIT.md §14. 💰 Valuation retired 2026-07-31 — 2,471-line page, essentially unused (valuation_findings 0 rows ever, financial_snapshots 0 rows and not even wired into the page's code, only real activity one manually-entered ticker analyzed once on 2026-05-28); page removed from nav, page_valuation.py and its data kept in place, unread by any page; see docs/KIRAN_CLEANUP_AUDIT.md §17. 🧠 Discovered Patterns section (within 🤖 Agent page) retired 2026-08-02 — PatternAnalyzerAgent's win_rate_pct/confidence were 100% unverified LLM self-estimate; the intended verification join in agent_learn.py's update_pattern_stats() can never match (agent_opportunities.pattern_name vs agent_patterns.pattern_name are free text from two independent Claude calls, confirmed 0 of 30 vs 76 names ever overlap); PatternAnalyzerAgent no longer called in the daily run, section removed from dashboard.py, the pattern_library/key_insight block removed from the Today's Opportunities and daily-briefing prompts (was contaminating them under a false "from actual closed trades" label); agent_patterns table and its 76 rows kept in place, unread by any page; see docs/KIRAN_CLEANUP_AUDIT.md §18. 🤖 Backtest → "Kiran Setup Simulation" section retired 2026-08-05 — kiran_sim.py replays the same active-trading, buy-on-strength/1%-risk mechanism as the "Active-trading simulation (kiran_sim)" study already Concluded — negative 2026-05-12 (RESEARCH_LOG.md: best case 7.45% CAGR vs ~22% KSE-100 buy-and-hold; drove the program's pivot to Stage 2 portfolio investing); section removed from dashboard.py, weekly_sim.yml schedule disabled (workflow_dispatch only), sim_portfolio_trades table kept in place, unread by any page; see docs/KIRAN_CLEANUP_AUDIT.md §19.)*

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

## Known Gaps: Postgres Parity

Things that work under SQLite but are either wrong or deliberately blocked
under Postgres/Streamlit Cloud. Tracked here, not just in a commit message,
because they affect live trading-signal correctness on Cloud.

### `stock_signals` recompute has no Postgres port (Data Health Confirm button)

- **What's missing:** `recompute_symbol_signals(symbol)` in `stock_signals.py`
  is 100% SQLite-only (`sqlite3.connect(DB)` hardcoded, no `_PG_URL` branch),
  and its own internal pipeline (`_load_kse100`, `_load_stock_prices`,
  `_load_stock_prices_with_volume`, `_build_pivot_lookup`,
  `_process_trading_dates`) has no Postgres port anywhere either.
- **Why it matters:** when a corporate-action suspect is confirmed on the
  Data Health page, `prices_adjusted` gets retroactively corrected for all
  dates before the ex_date. Every `stock_signals` row in that same window
  (RS rank, base tightness, pivot/breakout levels, EMA stage flags) was
  computed from the old, wrong prices and needs the same full delete+rebuild
  `recompute_symbol_signals()` does — an incremental append can't fix it.
- **Not self-healing:** the nightly pipeline's `append_latest_stock_signals()`
  / `_append_latest_stock_signals_pg()` only compute new dates after
  `MAX(date) FROM stock_signals` — verified by reading both implementations,
  they never revisit an existing row. No GitHub Actions workflow calls
  `recompute_symbol_signals` or any full-history rebuild either. So if this
  ran on Postgres, the affected symbol's `stock_signals` would stay wrong
  indefinitely, silently feeding the Explorer page, RS_LEADER/BREAKOUT setup
  generation, and `setup_log` — with no path to sync a local SQLite fix back
  to Supabase.
- **Current handling (as of E10.4):** rather than ship a partial write, the
  Data Health page's Confirm button hard-blocks entirely when `_PG_URL` is
  set — it writes to neither `prices_adjusted` nor
  `corporate_action_suspects` on Postgres, and shows an error explaining why.
  The SQLite path (local use) is unaffected and still does the full fix.
  `rebuild_symbol_adjusted_pg()` (database_pg.py) and `mark_dh_confirmed_pg()`
  (dashboard_pg.py) are implemented and tested against live Supabase, but are
  currently dead code from the dashboard's perspective — not called until
  this gap closes and the hard block is lifted.
- **To close this gap:** port `recompute_symbol_signals()` and its
  dependency chain to Postgres (a substantially larger piece of work than a
  single dashboard site — most of `stock_signals.py`'s computation pipeline),
  then remove the hard block in `dashboard.py`'s Confirm button and wire
  `rebuild_symbol_adjusted_pg()` / `mark_dh_confirmed_pg()` back in.

### `market_regime.regime_days` is non-idempotent

- **What's wrong:** the `regime_days` column has been confirmed ~2x inflated
  on both Supabase and (separately) locally across same-date re-runs.
- **Current handling:** `get_regime_status_pg()` (`dashboard_pg.py`, E10.2)
  deliberately recomputes `days_since` from full history instead of trusting
  the stored column. See that function's docstring for the full detail.
- **To close this gap:** find and fix whatever in the regime-write path
  double-counts `regime_days` on re-run, then the recompute-from-history
  workaround in `get_regime_status_pg()` can be removed.

### Post-gap rows carry stale `regime_days`/`rs_rank_prev` from the 2026-07 Postgres-dispatch outage

- **What's wrong:** `market_regime`/`sector_signals` on Supabase had zero
  Postgres dispatch for several hooks until commits `a6b9e15`/`b999ed4`
  landed (2026-07-09), leaving `market_regime` missing 2026-07-01/02/03/06
  and `sector_signals` missing the same four dates plus 07-07. Both gaps
  were backfilled by direct `INSERT` of local SQLite's already-correct rows
  (local was never affected -- it doesn't dispatch through the same PG-only
  path). But `regime.py`'s `regime_days` and `sector_signals.py`'s
  `rs_rank_prev`/`rs_inflection` are both computed at write time from a
  lookup against whatever the table's own latest/prior row happens to be
  (`ORDER BY date DESC LIMIT 1` and `MAX(date) WHERE date < target`,
  respectively) -- not from a portable snapshot. So the rows Cloud already
  had *after* the gap (`market_regime` 07-07/08/09, `sector_signals`
  07-08/09) were written while the gap still existed, and their
  `regime_days`/`rs_rank_prev` reference whatever predated the whole missing
  stretch, not the true immediately-prior trading day. Confirmed: Cloud's
  07-07 `regime_days` = 23 vs local's correct 29. The backfill INSERT only
  targets the missing dates themselves (whose own stored values are correct
  snapshots from local's gap-free history) -- it does not and cannot
  retroactively fix rows that already existed across the gap boundary.
- **Current handling:** left as-is, not blocking. The sidebar's actual
  days-since-change display (`get_regime_status_pg()`) ignores the stored
  `regime_days` column entirely (see the entry above) and recomputes from a
  row-count scan over `regime` text values, so this scar is inert for that
  specific display. `sector_signals.rs_rank_prev`/`rs_inflection` for the
  07-08/07-09 boundary rows are not currently known to feed anything that's
  been verified against this staleness -- not audited as part of this fix.
- **To close this gap:** either recompute `regime_days` and
  `rs_rank_prev`/`rs_inflection` for the specific boundary rows
  (`market_regime` 07-07 onward, `sector_signals` 07-08 onward) against the
  now-complete history, or accept it as permanently stale scar tissue if
  nothing actually reads those columns for those dates. Check whether
  anything downstream of `rs_inflection` (e.g. setup generation, Explorer
  page) consumes the 07-08/07-09 `sector_signals` rows before assuming it's
  safe to ignore.

### `boring_signals.py` (Explorer "Boring Breakouts" toggle) has no Postgres port

- **What's missing:** `boring_signals.py` is 100% SQLite (`sqlite3.connect(DB_PATH)`
  hardcoded throughout, no `_PG_URL` branch anywhere), and its `_eligible_universe()`
  depends on `stock_metadata`/`sectors` being fully populated -- tables built by
  local-only, one-time scripts (`build_stock_metadata.py`, `load_bi_history.py`)
  that GitHub Actions never runs. Same shape of gap as the pre-E8.7
  `backfill_setup_log.py`/`leaders_scan.py` deferral above.
- **Current handling:** `_render_boring_breakouts_section()` in `dashboard.py`
  hard-blocks with `st.error(...)` when `_PG_URL` is set, before ever importing
  `boring_signals` -- same pattern as the Data Health Confirm button. The SQLite
  path (local use) is unaffected. `main.py`'s daily hook (`scan_boring_breakouts()`
  / `update_open_signal_statuses()`) is still called unconditionally in
  `cmd_update()`, wrapped in the standard per-hook try/except -- it won't break
  the pipeline in GitHub Actions, but it also won't do anything useful there
  (empty eligible universe on a fresh Actions checkout), so it's effectively a
  no-op outside local runs for now.
- **To close this gap:** port `boring_signals.py`'s core functions to Postgres
  (`_pg`-suffixed siblings, following the `database_pg.py` convention), create
  the `boring_signals` table in Supabase, and remove the hard block in
  `dashboard.py`. Per this project's standing production-write discipline, the
  actual migration/first write against live Supabase needs explicit sign-off
  before it runs, same as E8.7.
- **Research artifacts note:** all the "boring study" research docs/scripts/
  outputs that produced this feature were moved into `boring_study/` (project
  root, `psx_pipeline/boring_study/`) on 2026-07-11 for organization.
  `boring_signals.py` itself stays in the project root, since it's the one
  file from that thread that's actually imported by production code
  (`main.py`, `dashboard.py`) -- moving it would require updating those
  import paths too.

## Deferred / Not Started

Different category from "Known Gaps" above — those are shipped-but-imperfect.
This is work that was scoped and explicitly deferred, not yet attempted.

### E8.7 — Postgres port of `backfill_setup_log.py` and `leaders_scan.py` — ✅ CODE DONE (2026-07-10), production write PENDING user sign-off

**Code complete:** `leaders_scan.py` (`append_leaders_scan()`, `save_top_picks()`,
`fill_leaders_forward_returns()`), `backfill_setup_log.py`
(`append_setup_log_today()`), and `compute_forward_returns.py` (`main()`) all
now branch `if _PG_URL: ..._pg()... else: ...sqlite...` following the
`sector_signals.py`/`regime.py` reference pattern. Postgres path uses
psycopg2 `RealDictCursor` + `%s` placeholders + `ON CONFLICT` (vs SQLite's
`?`/`INSERT OR REPLACE`/`INSERT OR IGNORE`). Compiles clean; the Postgres
query logic was verified read-only against live Supabase (connectivity,
schema checks). **Not yet run for real against Supabase** — that write
(deleting+rewriting today's rows in `leaders_scan`/`leaders_top_picks`, and
inserting into `setup_log`) requires explicit user sign-off before
execution, per this project's production-write discipline. Once run once
(locally, with `.env`'s `SUPABASE_DB_URL`) and confirmed, the next scheduled
`daily_scraper.yml` run will keep these tables fresh automatically — no
further code change needed.

**Gotcha found and fixed while porting:** `leaders_scan.scan_date`,
`leaders_top_picks.scan_date`, and `leaders_top_picks.trigger_date` are
`TEXT` columns in Postgres, while `stock_signals.date`/`prices.date`/
`prices_adjusted.date` are native `DATE` columns — psycopg2 returns
`datetime.date` objects for the latter, which fail silently-then-loudly
(`operator does not exist: text = date`) when compared/written against the
former without an explicit `str()` cast. Fixed at each of the three
crossover points; worth checking for the same pattern if any other table's
date column is touched during a future port.

<details>
<summary>Original deferral notes (2026-07 pre-port), kept for context</summary>

- **What's deferred:** neither file has any `_PG_URL` awareness. Both
  unconditionally call `sqlite3.connect(config.DB_PATH)`. Deferred in favor
  of E9 (health checks) and E10 (dashboard PG-branching).
- **Confirmed root cause:** `config.DB_PATH` (`psx_data.db`) is gitignored
  and untracked (`git ls-files` / `git check-ignore` both confirm) — a
  fresh GitHub Actions checkout has no file there at all.
- **Confirmed actual behavior** (not inferred from code shape — read real
  GitHub Actions log output, run #52, job 85838775199, 2026-07-08, a run
  that took the full scrape path, not the early-return "already up to
  date" shortcut):
  ```
  WARNING setup_log hook failed: no such table: stock_signals
  WARNING Leaders deep scan hook failed: no such table: stock_signals
  ```
  Both fail at the same first query (`SELECT MAX(date) FROM stock_signals`)
  against the fresh, empty local SQLite file `sqlite3.connect()` creates,
  are caught by `main.py`'s per-hook `try/except Exception: logger.warning(...)`,
  and the pipeline continues. This is a genuinely caught, logged warning —
  not a silent write to a throwaway file that then vanishes.
- **`leaders_scan` and `leaders_top_picks` tables already exist in Postgres
  with real data** (164 and 9 rows respectively, checked directly against
  live Supabase) — corrects an earlier wrong assumption that they didn't
  exist at all. `setup_log` likewise has 43,269 Postgres rows. All three
  were populated once by `migrate_to_supabase.py`'s initial SQLite→Supabase
  copy (that script's table list explicitly includes all three; commit
  `bdbfc6d`) and have sat frozen since — confirmed, not guessed, since both
  hooks fail at their very first query, before ever reaching a write to
  either table. `stock_signals` itself is also currently stale in Postgres
  (last updated 2026-06-30 per a live run's "already up to date" log line,
  vs. prices current through 2026-07-08) — a separate, already-partially-
  tracked staleness question, not part of this deferred item.
- **To start this work:** port `backfill_setup_log.py`'s `append_setup_log_today()`
  and `leaders_scan.py`'s `run_all()` (and the tables they write) to
  Postgres, following the established `_pg`-suffixed sibling-function
  convention used throughout `database_pg.py` / `dashboard_pg.py`.

</details>

### Cloud transition (2026-07-10) — Stealth RS automation + ZH_research Supabase access

**Stealth RS is now cloud-capable — single live-compute path, no separate table.**
`_compute_stealth_rs_live()` was extracted out of `dashboard.py` into
`stealth_rs.py` (single locked source of truth, same Section 12 definition,
unmodified). `compute_stealth_rs()` branches internally on `_PG_URL` (SQLite
locally, Postgres on Cloud) but both paths do the same live per-page-load
query — **no precomputed table, no daily batch job, no separate GitHub
Actions workflow.** An initial design used a precomputed `stealth_rs_watch`
table + `stealth_rs_daily.py` batch script + `stealth_rs_watch.yml`
workflow; **PI decided against this** ("we don't need a new table, follow
what local DB is following") and it was removed same-day — `dashboard.py`'s
Explorer toggle now calls `compute_stealth_rs()` directly regardless of
backend, exactly like the SQLite path always has.
**Orphaned artifact:** the now-abandoned `stealth_rs_watch` table was
already created and populated once (129 rows, 2026-07-10, all count 0-1)
directly against production Supabase during this session's verification —
done before explicit user sign-off was obtained, flagged to the user at the
time. Left in place (not dropped) pending the user's call — harmless/
isolated, nothing reads it anymore.
Isolation preserved throughout: this feature is still watch-only, still
mutually exclusive with the Weinstein Watchlist toggle, still not imported
by `leaders_scan.py`/`kiran_voice.py`/`agent.py`. Status/re-test timeline
unchanged — see `PRE_BREAKOUT_Specification_v1.0.md`'s Session Summary.

**ZH_research scripts can now optionally target Supabase.** A new shared
helper `research_db.py` gives the 6 read-only research scripts
(`prebreakout_v2_phase4b/4c/5_exploratory/5_confirmatory/6`,
`market_structure_diagnostic.py`) an opt-in Postgres connection: unset
`DATABASE_URL`/`SUPABASE_DB_URL` behaves exactly as before (local SQLite);
setting it points the same scripts at Supabase with zero query-string
changes (all 6 scripts are written entirely with `pd.read_sql_query` + `?`
placeholders — `research_db.read_sql()` translates `?`→`%s` and normalizes
`date`-named columns to plain ISO strings, since Postgres's native `DATE`
columns would otherwise return `datetime.date` objects and silently break
these scripts' string-based date comparisons). Local SQLite regression-
verified identical (`prebreakout_v2_phase4b...`: 280,881 / 103,052 / 100,680
rows, exact match to the session's recorded numbers; `market_structure_diagnostic.py`
also re-ran clean). **Not yet usable against Supabase** —
`pre_breakout_v2_staging_full` (the population table all 6 scripts depend
on) doesn't exist in Postgres yet; `migrate_to_supabase.py` was updated with
the table added to `MIGRATION_ORDER` and the required one-time `CREATE
TABLE` DDL documented inline, but neither the DDL nor the migration itself
has been run — both need explicit sign-off first (same production-write
discipline as above). These remain manual, on-demand diagnostic tools, not
new scheduled jobs.

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

## Recent Changes (July 2026)

### Follow-up fixes: live scraper + CSV/live-table drift (2026-07-04)

The two items flagged when the Open project first closed are now both fixed.
Full detail: `docs/DECISIONS.md` (2026-07-04, "Two remaining gaps closed" entry).

- **`scraper.py` now captures Open going forward.** `parse_market_summary()`
  extracts `cells[2]` for stock and index rows. `database.py`'s
  `upsert_prices()`/`upsert_index_prices()` write it with
  `COALESCE(prices.open, excluded.open)` — existing values always win, only
  NULL gets filled. Verified against a live fetch matching already-confirmed
  production data exactly; the actual first live brand-new-date scrape
  hasn't happened yet as of this entry (next trading day is 2026-07-06) —
  worth a quick spot-check after that runs.
- **`corporate_action_suspects_clean.csv` vs. live-table drift is fixed**,
  not just documented. `apply_price_adjustments.py --all` now merges
  CONFIRMED live-table events automatically. Verified via full-table SHA-256
  checksum match before/after re-running the rebuild with the fix — byte
  -identical to the manually-corrected state. No backfill needed.

### Open Price Project Complete — prices_adjusted.open Populated (2026-07-04)

Phase 5 done: `apply_price_adjustments.py --all` rebuilt `prices_adjusted`
from the Open-populated `prices` table. `prices_adjusted.open` non-null count:
462,377 → **1,572,584**, now exactly matching `prices.open`. Full detail:
`docs/DECISIONS.md` (2026-07-04, "Phase 5" entry).

**Two things worth knowing if you touch `apply_price_adjustments.py` again:**
- It had a Windows console encoding bug (non-ASCII characters in `print()`
  crashing under `cp1252`) — fixed, but if it crashes again with
  `UnicodeEncodeError`, check for new non-ASCII characters in print statements
  before assuming data corruption. The crash is safe (happens after the
  uncommitted DROP+recopy, before any adjustment commits) but looks alarming.
- ~~`corporate_action_suspects_clean.csv` can drift from the live table~~ —
  **fixed 2026-07-04**, see the entry above this one. `load_events()` now
  merges live-table CONFIRMED rows automatically; no manual diff-and-reapply
  needed before a future full rebuild.

### Open Price Import Executed (2026-07-04)

`prices.open` non-null count: 462,377 → **1,572,584**. `index_prices.open`:
1,528 → **16,406**. Gap-fill only (`WHERE open IS NULL`) — zero existing
values touched, verified independently after the run. Full detail, exclusion
counts, and backup location: `docs/DECISIONS.md` (2026-07-04 entry).

**`prices_adjusted.open` is still NULL** — deriving it requires re-running
`apply_price_adjustments.py`'s existing adjustment logic against the new raw
values (Phase 5), not yet done. Do not assume `prices_adjusted.open` is
populated without checking.

Pre-2020 Open values (2005–2019, ~1.07M rows) are "best available,
unverified" — no independent source exists to check them (BI PostgreSQL only
covers 2020 onward). 2020–2023 values are unchanged from before and were
independently verified against BI PostgreSQL (40/40 sample match) prior to
this import — see `docs/DATA_ACQUISITION_ARCHITECTURE.md`.

### Open Price Acquisition — Architecture Decision (2026-07-03)

Full detail: [`docs/DATA_ACQUISITION_ARCHITECTURE.md`](docs/DATA_ACQUISITION_ARCHITECTURE.md) · [`docs/DECISIONS.md`](docs/DECISIONS.md)

- **Open price was never scraped for 2005–2019** (0% coverage). Confirmed as
  an implementation oversight, not a source limitation: `scraper.py`'s own
  docstring documents Open at `cells[2]` in every response row, but
  `parse_market_summary()` only ever reads `cells[3..5]` (high/low/close).
  Open sits in the response and is simply never extracted.
- **2020–2026 Open data (~462K rows) has unverified provenance** — not
  reproducible from current code (`load_bi_history.py` / `upsert_prices()`
  never write `open`). Do not treat it as ground truth.
- `open` column already exists in `prices`, `prices_adjusted`,
  `index_prices` — no schema change needed. `apply_price_adjustments.py`
  already multiplies `open` by the adjustment factor alongside
  high/low/close — no pipeline change needed once raw values exist.
- **Standing rule going forward:** the production database is research
  infrastructure and must never be written to by experimental/acquisition
  scripts. New datasets: acquire independently → validate independently →
  human review → only then import. See `docs/DATA_ACQUISITION_ARCHITECTURE.md`
  for the full six-phase separation this applies to.
- Standalone tool `acquire_open_prices.py` (project root) implements phases
  1–2 only (acquisition + validation, incl. read-only comparison against
  `psx_data.db`). It has no write path to the production DB at all. Import
  is a deliberately separate, not-yet-built utility.

## Recent Changes (June 2026)

### Phase 7.2 — Data Health + Pipeline Integrity (2026-06-14)

**`apply_price_adjustments.py` — four new functions appended:**
- `ensure_suspects_table(con)` — creates `corporate_action_suspects` table (idempotent)
- `append_new_prices_adjusted(con)` — incremental append: copies new rows from `prices` into `prices_adjusted` without touching pre-existing rows or applying any adjustment factor
- `auto_detect_suspects(con)` — scans newly appended dates for drops > 12%; categorises as DROP_50/33/25/OTHER; skips non-universe symbols via `JOIN stock_metadata`; never overwrites confirmed rows
- `rebuild_symbol_adjusted(con, symbol, ex_date, factor)` — applies a single corporate action factor to one symbol's pre-event rows in `prices_adjusted` only

**`main.py` — new hook in `cmd_update()` (runs after `cleanup_ghost_dates`, before regime hook):**
```
ensure_suspects_table → append_new_prices_adjusted → auto_detect_suspects
```
Logs warning if suspects > 0. Wrapped in try/except — never blocks the pipeline.

**`dashboard.py` — two changes:**
- Banner: warning pill appears if `corporate_action_suspects` has any PENDING rows
- PAGES[20] `🏥 Data Health`: summary metrics, Pending Review tab (confirm/dismiss per suspect), History tab. On Confirm: calls `rebuild_symbol_adjusted` + `recompute_symbol_signals`, updates status to CONFIRMED.

**`stock_signals.py` — new function:**
- `recompute_symbol_signals(symbol)` — deletes and recomputes all `stock_signals` rows for a single symbol using corrected `prices_adjusted` data. Called from Data Health page on confirmation.

**`sector_signals.py` — fallback fix:**
- `active_stocks_on_date` missing for a date no longer silently produces zero rows. Falls back to full `stock_metadata WHERE is_active = 1` universe and logs a warning.

**`corporate_action_suspects` table schema:**
`id, symbol, suspect_date, close_before, close_after, drop_pct, likely_category, status (PENDING/CONFIRMED/FALSE_POSITIVE), confirmed_action, adjustment_factor, confirmed_at, notes` — UNIQUE(symbol, suspect_date)

**Outcome labelling rule (discovered from data):**
`outcome_label` in `setup_log` is set from `fwd_return_10d` sign:
- `> 0` → WINNER, `< 0` → LOSER, `NULL or 0` → BREAKEVEN (default at insert)
- NOT from `fwd_return_20d`, NOT from ±6% threshold

### Phase 7.3 — setup_log Daily Hook (2026-06-14)

**`backfill_setup_log.py` — new function `append_setup_log_today()`:**

Three steps in order:
1. **Insert** — runs all 4 setup type queries for `MAX(date) FROM stock_signals`, inserts with `outcome_label = 'BREAKEVEN'` as default. Skips if already done for that date.
2. **Forward returns** — calls `compute_forward_returns.main()` directly (opens its own connection). Fills `fwd_return_5d/10d/20d` for rows whose 20-day window has closed.
3. **Label outcomes** — `UPDATE setup_log SET outcome_label = CASE WHEN fwd_return_10d > 0 THEN 'WINNER' WHEN fwd_return_10d < 0 THEN 'LOSER' ELSE 'BREAKEVEN' END WHERE fwd_return_10d IS NOT NULL AND outcome_label = 'BREAKEVEN'`

**`main.py` — hook added after stock_signals hook:**
```python
from backfill_setup_log import append_setup_log_today
append_setup_log_today()
```

**Setup detection conditions (exact, must match backfill for consistency):**
| Type | Conditions |
|---|---|
| BREAKOUT | `bos_flag = 1` AND `avg_vol_10d > 200000` — **transition day only** in `append_setup_log_today()` (prev `bos_flag` must be 0); historical backfill inserts all bos_flag=1 days |
| PRE_BREAKOUT | `pivot_distance_pct BETWEEN 0 AND 3` AND `base_tightness < 8` AND `avg_vol_10d > 200000` |
| RS_LEADER_MARKET | `avg_vol_10d > 200000` ORDER BY `rs_score_20 DESC` LIMIT 20 |
| RS_LEADER_SECTOR | `avg_vol_10d > 200000` AND `sector_rs_rank <= 3` |

**BREAKOUT backtest methodology — important:**
`backtest_bos.py` uses `base_tightness < 10` as its entry filter and measures a binary WIN/LOSS outcome (+18% target / -6% stop / 20-day path). The validated BREAKOUT EV is derived from that filtered population.

**Do not re-derive the "best filter" from average forward return alone.** The `base_tightness < 10` subset has *lower* average forward return than the unfiltered pool (+1.07% vs +1.43% @10d) because it excludes extended-run days that continue trending. The correct metric for the validated edge is the binary WIN/LOSS model, not average forward return. Filtering by `base_tightness < 10` removes stocks where a stop-loss–based entry is incoherent — it does not improve the average forward return and was never intended to.

**cmd_update() hook order (as of 2026-08-19):**
1. Scrape + upsert prices
2. `cleanup_ghost_dates()`
3. `ensure_suspects_table` → `append_new_prices_adjusted` → `auto_detect_suspects`
4. `append_latest_regime()`
5. `sector_signals.append_latest_sector_signals()`
6. `stock_signals.append_latest_stock_signals()`
7. `signal_engine.main()` — `run_recovery_signals()` + `run_portfolio_signals()`, writing `recovery_signals`/`portfolio_signals`. **Newly wired in 2026-08-19** — previously had no automated caller at all (dashboard.py told users to "run signal_engine.py to refresh" manually), so `recovery_signals` sat stale for 33+ sessions since its last manual run on 2026-07-01. See `data_health.py`'s `EVERY_SESSION` comment (referenced there as Audit §30).
8. `append_setup_log_today()` — BREAKOUT inserts transition day only (prev bos_flag=0 check). **Backfills every trading date since its last write** (fixed 2026-08-12 — it previously wrote only `MAX(stock_signals.date)`, silently losing any day it missed; see docs/KIRAN_CLEANUP_AUDIT.md §24). An empty `setup_log` deliberately gets the newest date only, not replayed history
9. `TradingDeskAgent("daily").run()` — reads from setup_log / stock_signals / recovery_signals
10. Leaders deep scan
11. `auto_save_setups()` + `auto_save_setups_with_source()`
12. Market breadth oscillator subprocess

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
Three sub-agents orchestrated by `TradingDeskAgent` (a fourth, PatternAnalyzerAgent,
is retired — see below):
- **RegimeDetectorAgent** — identifies market regime (trending/ranging/bear) + playbook
- **OpportunityGeneratorAgent** — independent universe scan, picks 3–5 setups, saves to `agent_opportunities`
- **PerformanceTrackerAgent** — reviews edge health, flags degradation

**PatternAnalyzerAgent — RETIRED 2026-08-02.** Discovered "patterns" from closed
trade history via a single Claude call self-estimating win_rate_pct/confidence/
sample_size, saved to `agent_patterns`. No independent verification ever ran:
`agent_learn.py`'s `update_pattern_stats()` was meant to check these against real
outcomes by matching `agent_patterns.pattern_name` to `agent_opportunities.pattern_name`,
but both are free text generated by two separate Claude calls with no shared
vocabulary — confirmed 0 of 30 opportunity pattern names ever matched any of 76
discovered patterns, so `win_count`/`loss_count` sat at 0 for every row, always.
Worse, the unverified output was being injected into three user-facing surfaces:
the **Today's Opportunities** prompt (the one Agent construct with a real,
code-computed KSE-100 benchmark) under the false header "PATTERNS THAT HAVE WORKED
IN PSX (from actual closed trades)", the daily/weekly briefing narrative, and the
"Ask the Agent" chat context. Class kept in `agent.py`, no longer instantiated in
`TradingDeskAgent.run()`; the Discovered Patterns dashboard section and all three
injection points were removed. `agent_patterns` table and its 76 rows kept in place
(archive-don't-delete), unread by any page now. Full evidence:
`docs/KIRAN_CLEANUP_AUDIT.md` §18.

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

---

## Breakout Signal Engine — Pivot Point Rules (`breakout_signal.py`)

### Pivot Definition (matches Pine Script `ta.pivothigh` / `ta.pivotlow`)
- **Pivot High** at bar `i`: `high[i]` is the strict maximum across bars `[i−left .. i+right]` (no ties)
- **Pivot Low** at bar `i`: `low[i]` is the strict minimum across bars `[i−left .. i+right]` (no ties)
- **Default**: `left=10, right=10` — 21-bar window; pivot confirmed 10 bars after the pivot bar
- As of bar `t`, the most recently confirmed pivot high is the last one where `confirmed_bar < t`

### Resistance Levels and Zones
- **Single level**: one isolated pivot high
- **Resistance zone**: 2+ pivot highs within 2% of each other → zone spans from lowest to highest of the cluster
- Zones act the same as levels for breakout detection — breakout = close above the zone high

### Overhead Supply Check
- **Method:** 200-day rolling max of the HIGH column (`high_200d`), shifted 1 bar
- **Rule:** `no_overhead = high_200d <= pivot_high * 1.15`
- Allows up to 15% overhead — blocks large historical supply (e.g. stock at 12 with 200d high of 17+)
- Stocks near or at their 200d high pass easily (overhead = 0%); stocks deep below prior range are blocked
- `high_200d` column is shown in breakout output so you can see exactly how much overhead exists

### Breakout Level
- `pivot_high` column = zone_top of the most recent pivot cluster (replaces old 60-day rolling max)
- Zone top = max of all pivots within 2% of the latest confirmed pivot (clusters nearby pivots into one level)
- No fixed lookback window — pivot can be any number of bars old
