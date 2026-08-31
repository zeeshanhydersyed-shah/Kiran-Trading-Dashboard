# Kiran — Maintenance Log

Append-only record of **routine operational maintenance** on the Kiran production
system: manual data backfills, Supabase console changes, one-off scraper runs,
config/dependency changes, restarts — anything operational that does **not** go
through a Pull Request. (Code and data-pipeline changes are logged by their PR;
they do not belong here.)

Governed by `CLAUDE.md` → "Standing rule — log routine maintenance as it happens".
Pending / not-yet-done items live in the **Open Items Ledger** in
`docs/KIRAN_BORING_STATE_TRUST_REGISTER.md` (kept local), not here — this file is
**completed work only**.

## Format

Newest first. A few lines per entry:

    ### YYYY-MM-DD — <short title>
    - **What:** what was done
    - **Why:** trigger / reason
    - **DB writes:** none  |  table(s), row counts, and where the backup is
    - **Verification:** how it was confirmed to have worked
    - **By:** who

A DB write with **no backup location recorded** is a red flag — if that ever
happens, say so explicitly and why.

---

## Entries

### 2026-08-31 — OI-9 rollout step 3: `pipeline_runs.code_version` column added to Supabase Postgres
- **What:** `ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS code_version TEXT` on the live Supabase DB — the cloud half of the OI-9 additive column (Trust Register §0a.3 / ledger §88). Additive, nullable, no backfill of the 43 existing rows.
- **Why:** So the cloud `daily_scraper.yml` pipeline can stamp the producing commit SHA on every `pipeline_runs` row once the OI-9 code merges. `data_health.ensure_ledger_pg()` would apply this automatically on the next run, but per the project's Postgres-write discipline it was run under explicit user sign-off first.
- **DB writes:** Supabase `pipeline_runs` — **+1 column only, 0 rows changed** (43 → 43, all `code_version` NULL). No other table touched. Method: `scratch_code_version_20260831/ddl.py` — dry-run (txn + ROLLBACK) → `--apply` (commit). Backup first (Supabase PITR is OFF): `scratch_code_version_20260831/pipeline_runs_pre_code_version.csv` (43 rows, 12 cols) + `pipeline_runs_schema_pre.json`.
- **Verification:** independent fresh-connection re-query — `code_version` present as `text` / nullable; `pipeline_runs` still 43 rows, 0 non-null; 13 columns total; `boring_signals` untouched. `data_health.ensure_ledger_pg()` then run once and confirmed a clean no-op (no further schema change) — so the next pipeline run will not re-alter anything.
- **By:** Claude Code, under explicit user authorization. Full detail: ledger §88.9.

### 2026-08-31 — OI-9 Phase 1: `pipeline_runs.code_version` column added to local `psx_data.db` + one observed pipeline run
- **What:** Rollout step 1 of OI-9 (Trust Register §0a.3 / ledger §88 — the standing deployment-identity mechanism for TR-11). Ran `python main.py --update` once against the live local SQLite DB with the OI-9 Phase 1 code in the working tree. `data_health.ensure_ledger_sqlite()` auto-added the additive nullable `code_version` column to `pipeline_runs` on first `record_run()`; the run then stamped it on the 3 hook rows it wrote.
- **Why:** Confirm the new column and SHA-stamping work end-to-end on a real DB before the Postgres `ALTER TABLE` (separate sign-off) and the PR. Held gate #1 of the §0a.3.7 rollout.
- **DB writes:** local `psx_data.db` **only** (no Postgres — `DATABASE_URL`/`SUPABASE_DB_URL` both unset, verified; import of `main` adds no env keys; OI-8 fix confirmed in place). `pipeline_runs`: +1 column (`code_version TEXT`, nullable), +1 row (`deployment_identity` / 2026-08-31, `code_version=37705ad…`, `detail` records `working_tree=dirty` — the 5 uncommitted Phase-1 `.py` files), and `code_version` set on the 2 rows this run refreshed (`support_reversal`, `leaders_scan`, both 2026-08-28). 55 pre-existing rows keep `code_version` NULL (additive, no backfill). Backup first: `backups/psx_data_pre_code_version_20260831.db` (`PRAGMA integrity_check` ok, sha256 `e4072fbc77f6f957dc9f5f1868158b889938d51e4999ab2150a40e5334017176`, 882016256 bytes, 57 `pipeline_runs` rows). Retain until the OI-9 PR merges and the first post-merge nightly runs clean.
- **Verification:** `PRAGMA integrity_check` → ok. All 10 signal tables byte-unchanged (identical row counts + MAX dates pre/post — `prices`/`prices_adjusted` 1,757,895; `boring_signals` 212; `leaders_scan` 907 refreshed idempotently; etc.). The 3 stamped rows carry exactly `37705adf11d986593291f151f6cb9eb67251981f` = local `git rev-parse HEAD`. `data_health.latest_pipeline_code_version()` (the function the Data Health drift panel calls) returns that SHA against the real DB. `run_freshness_gate()` → **passed** ("state verified fresh as of 2026-08-28"), run exit 0. The dirty-tree WARNING fired correctly (expected — Phase-1 changes are uncommitted).
- **By:** Claude Code, under explicit user authorization. Full detail: ledger §88.7.

### 2026-08-31 — OI-8: local SQLite pipeline caught up to 2026-08-28 after the routing fix
- **What:** After OI-8 (`signal_engine.py` `load_dotenv()`, fixed in PR #36) had been misrouting local runs' signal-table writes to Postgres, the local SQLite copies of `recovery_signals`/`portfolio_signals`/`boring_signals`/`leaders_scan` were frozen at 2026-08-20/25 while everything else had reached 08-28. With the fix in the working tree, re-ran the affected hooks locally.
- **Why:** User reported the local dashboard's "Refresh Data" wasn't working — it was the TR-05 freshness gate correctly failing STALE on the frozen `recovery_signals`. Local Task Scheduler pipeline effectively down since 2026-08-26.
- **Method:** `scratch_oi8_catchup_20260830/catchup.py` — real production functions in `cmd_update()` tail order, with a hard `sys.exit()` guard that aborts if any Postgres URL is visible (it never tripped): `signal_engine.main()` → `scan_boring_breakouts_pending()` + `update_open_signal_statuses()` → `leaders_scan.run_all()` → `main.run_freshness_gate()`.
- **DB writes:** local `psx_data.db` **only** (0 Postgres writes, independently verified). `recovery_signals` +5 @ 08-28, `portfolio_signals` +308 @ 08-28, `boring_signals` +13 (9 on 08-27, 4 on 08-28) + `boring_signals_scanned` markers, `leaders_scan` backfilled 08-21→08-28. Backup first: `backups/psx_data_pre_oi8_catchup_20260830.db` (`PRAGMA integrity_check` ok, sha256 `fd000f5a012fc1651cf83f74320e644f0f25bf8b0c9d2d64d10c18575296290c`, 882016256 bytes). Retain until the next clean nightly `run_update.bat`.
- **Verification:** all local tables now MAX-date 2026-08-28; `PRAGMA integrity_check` → ok; `run_freshness_gate()` → **`Freshness gate passed -- state verified fresh as of 2026-08-28`** (first time the local gate has been observed passing — TR-05 §84.4(b)). PG's own 08-28 rows (written earlier by the OI-8 leak during the §82 cloud outage) cross-checked sound and kept — ledger §85.5.
- **By:** Claude Code, under explicit user authorization. Full detail: ledger §85.

### 2026-08-30 — TR-13/OI-7: removed the 87 `dedup_conflict` pairs from Postgres `boring_signals` (direct sync)
- **What:** Reconciled the 165 rows / 87 (symbol,date) pairs in PG `boring_signals` that violated the table's own dedup rule — an artefact of the 2026-07-10-floored rebuild having no memory of pre-floor open positions (ledger §63.6/§71.3). Pre-registered spec Trust Register §0a.2; user chose Option B (remove, not label-forever) 2026-08-28; executed under sign-off on the dry-run.
- **Method:** direct sync, not a replay. `DELETE FROM boring_signals WHERE dedup_conflict IS TRUE` (165) + `INSERT` `BUXL`/2026-08-21 (2 rows, from SQLite — the one legitimate signal the conflicts had suppressed) + `update_open_signal_statuses()` (PG).
- **DB writes:** live Supabase `boring_signals` only. 400 → 237 rows. `dedup_conflict` count 165 → 0. `update_open_signal_statuses()` resolved the 2 new `BUXL` rows `Pending→Stopped` (marginal signal, already stopped out) and touched nothing else. Backup first: `scratch_boring_reconcile_20260828/boring_signals_pre_oi7_FULL.csv` (400 rows) + PG snapshot table `boring_signals_pre_oi7_20260830` (400 rows, verified). Supabase PITR OFF — these are the rollback net. Rollback: `TRUNCATE boring_signals; INSERT ... SELECT * FROM boring_signals_pre_oi7_20260830`.
- **Verification:** dry-run (txn + ROLLBACK) PASS first; post-write full 23-column diff of all 235 pre-existing non-flagged rows = **0 identity changes, 0 status/display changes, 0 missing**; Strategy-Confirmed perf panel **27 / +4.43% unchanged** (independent raw recompute, matches ledger §71.6); `scope.py` re-run → 0 flagged, 0 SQLite-only. 31 CLEAN PG-only orphan rows deliberately retained (§0a.2.5).
- **Retention:** keep the CSV + snapshot table until the next successful `daily_scraper.yml` run confirms the table is healthy.
- **By:** Claude Code, dry-run shown and signed off. Full detail: audit ledger §83 + Trust Register §0a.2. OI-7 CLOSED; TR-13 → A still needs TR-14 + the §35.3 parity test.

### 2026-08-30 — Cloud daily scraper found DOWN since 2026-08-28 (`parse_market_summary` return-arity bug)
- **What:** During the OI-7 re-scope, noticed PG data frozen at 2026-08-27. The `daily_scraper.yml` run 2026-08-29 00:52 UTC failed; none since. Root cause: `scraper.py` `parse_market_summary()` returned `[], []` (2 values) on its "no table found in HTML" path while every caller unpacks 3 → `ValueError` → the whole `cmd_update()` aborted before any hook ran. Triggered because ksestocks served no parseable table for 2026-08-28 (holidays / long weekends / brief source outages).
- **Impact:** cloud Postgres and all cloud signal tables stuck at 2026-08-27 from Fri 08-28. Not caused by the OI-6 merge — a latent bug. Not silent (GitHub Actions failure + email).
- **DB writes:** none. Read-only investigation + a code fix (below).
- **Fix (PR — see the PR description for the log):** 3-part, design-compliant (audit ledger §39.17 row 18 / §39.19 "ingestion logged, non-fatal"; TR-05/TR-07): (1) `parse_market_summary()` returns a 3-tuple on every path; (2) `scrape_date_range()` isolates a single date's failure — logged, skipped, batch continues; (3) verified `main.run_freshness_gate()` still fails the run when an expected session is genuinely missing, so a real gap is a visible red run, not a silent exit 0. Tests: `tests/test_scraper_no_data_resilience.py` + a TR-05 integration test.
- **Still to do after deploy:** a catch-up scrape for 2026-08-28 → present (the pipeline's own `dates_since` does this on the next good run; 08-28's trading-day status still to be confirmed).
- **By:** Claude Code. Full detail: audit ledger §82.

### 2026-08-28 — TR-13/OI-6: created `boring_signals_scanned` + seeded the verified window (live Supabase / Postgres)
- **What:** The Postgres half of the OI-6 scan-progress marker (spec §0a.1.8 steps 3–5; SQLite half was 2026-08-28 earlier, above). `ensure_boring_signals_scanned_table_pg()` created the new empty table, then `seed_scanned_window("2026-08-27")` marked all 33 trading dates from the 2026-07-10 go-live floor through 2026-08-27 `complete` **without scanning** (the PG `boring_signals` table was rebuilt by chronological replay §71 and the daily hook has kept it current through 08-27 — no missed tail, unlike SQLite).
- **Why seed vs scan:** a replay over a populated `boring_signals` table produces backdated dedup artifacts (spec §0a.1 amendment 2). The window is audit-§36-verified intact, so it is seeded, not re-scanned.
- **DB writes:** live Supabase only. New table `boring_signals_scanned` (33 rows, all `complete=TRUE`, `run_id='SEED-audit'`). **Zero writes to `boring_signals` or any other existing table** — full 23-column identity diff pre vs post = 0 added / 0 dropped / 0 changed; row-set sha256 `9698229e9821a51ebff283713c63271ac964e59e4c8a8dc6619e17b36b85115d` unchanged. Backup first: `scratch_boring_scanned_20260828/boring_signals_pre_seed.csv` (400 rows) + identity + schema snapshots. (Supabase PITR is OFF — this CSV is the only rollback net; rollback = re-import + `DROP TABLE boring_signals_scanned`.)
- **Verification:** DB read-write status confirmed (`transaction_read_only=off`, not in recovery) before writing; DDL dry-run (rolled back) first; post-seed identity diff 0/0/0; marker dates exactly match the 33-date `prices_adjusted` calendar since the floor; `scan_boring_breakouts_pending()` on the PG backend returns `(0,0,0)` — a pure no-op.
- **Not done:** the OI-6 code is still uncommitted in the working tree — one PR (`boring_signals.py`, `main.py`, `dashboard.py`, 5 test files, schema-only fixture ALTER) is the last step. The PG marker table now exists, so merging is safe (the pending-scan path fails loud with SQLSTATE 42P01 only if the table is absent).
- **By:** Claude Code, under explicit user authorization for spec steps 3–5 with four stated conditions (strict CSV backup, verify read-write, post-seed full identity diff, halt on any deviation) — all honoured. Full detail: audit ledger §79.

### 2026-08-28 — Cloud Streamlit app found serving stale `dashboard.py` (pre-PR #25)
- **What:** User asked why the cloud Boring Breakouts panel shows "54 resolved
  trades" vs the ledger §71 figure of 27. Read-only investigation: reproduced
  **exactly** — computing the panel logic against live Postgres, the current
  code (with PR #25's dedup-conflict exclusion) gives 27 / EV +4.43%; the
  pre-#25 code gives **54 / EV +7.94%**. PR #25 (`ef295ee`) merged 2026-08-27
  19:42 PKT; the Streamlit serving process has not rebooted since, so it runs
  pre-#25 `dashboard.py` (the §62 "in-place redeploy doesn't recycle" issue).
- **Impact:** Postgres **data is correct and current** (MAX date 2026-08-27);
  only the **rendering code** is ~1 day stale. The cloud panel is showing the
  pre-correction (overstated, dedup-included) Boring Breakouts numbers, and is
  missing the dedup-conflict tags + "Recorded" freshness column. The correct
  current number is 27 Strategy-Confirmed resolved trades, EV +4.43% gross /
  +3.59% net (§71 disclosure still applies — DBCI tail dependence).
- **DB writes:** none — read-only.
- **Action needed:** a Streamlit Cloud **reboot** (not redeploy) to pick up
  `origin/main` (`11a9c4e`). Streamlit-console action → user's, per the deploy
  boundary. `serving_revision.py` on the Data Health page shows the served SHA.
- **By:** Claude Code. Full detail: audit ledger §78. (TR-11 evidence.)

### 2026-08-28 — TR-13/OI-6: seeded `boring_signals_scanned` + scanned the tail (local SQLite)
- **What:** One-time transition for the new scan-progress marker (OI-6 code,
  not yet merged — in the working tree). `python boring_signals.py seed-verified
  2026-08-20` (marked the 29 audit-§36-verified operating-window trading dates
  `complete` in the new `boring_signals_scanned` table, **no scan**), then
  `python boring_signals.py scan-pending` (genuinely scanned the 3 un-covered
  tail dates 2026-08-21/24/25).
- **Why:** A plain `scan-pending` first run would replay 6 weeks over the
  already-populated `boring_signals` table and add ~113 backdated dedup-artifact
  signals (proven by smoke tests). Seeding the verified span and scanning only
  the genuine tail avoids that.
- **DB writes:** local `psx_data.db` only. New table `boring_signals_scanned`
  (32 rows). `boring_signals` 183 → 199 (+16 real recovered breakouts on the 3
  tail dates; **0 existing rows mutated or deleted** — full 9-column identity
  diff). Backup: `backups/psx_data_pre_boring_scanned_20260827.db` (sha256
  `328e15a17376b65a0cb2fdcd07efff67bda6b63ab9c9b35677b871a2a46bda9d`,
  `integrity_check ok`).
- **Verification:** pre/post identity snapshot diff (0/0), `PRAGMA
  integrity_check ok`, marker covers all 32 in-window trading dates, a second
  `scan-pending` is a 0-row no-op (idempotent), WAL checkpointed.
- **Postgres:** NOT touched — still on the old bounded-window code, held for a
  separate DDL sign-off.
- **By:** Claude Code, observed, under explicit user go-ahead. Full detail:
  audit ledger §77.7.

### 2026-08-28 — Investigated a reported cloud data lag / "date rolled back 26→25"
- **What:** User reported the Streamlit app (Aug 27 ~22:20) hadn't caught up
  despite source data being available, and that the shown latest date flipped
  from Aug 26 (daytime) to Aug 25 (night). Read-only investigation against live
  Postgres + GitHub Actions logs.
- **Findings:** (1) **2026-08-26 (Wed) was a PSX holiday** — the scraper logged
  `No trading data for 2026-08-26 (holiday or weekend)` on the Aug 28 catch-up
  run; ksestocks.com has no Aug 26 data; PG date sequence is 08-24, 08-25,
  **08-27** with no gap to fill. (2) The **Aug 27 17:00 UTC scheduled scrape did
  not fire** — GitHub Actions delayed/dropped it ~8 h; it ran Aug 28 01:16 UTC
  and caught up cleanly (skipped the holiday, scraped real Aug 27). (3) The
  26→25 flip the user saw was the sidebar's **live "ksestocks: <date>"
  indicator** (`dashboard.py` ~L1141, 30-min TTL, scraped off the source
  banner), not stored data — the DB's data date was Aug 25 throughout. Aug 27
  verified a genuine distinct session (0/488 symbols match Aug 25).
- **Current status:** Cloud/Postgres **current and correct** — MAX date
  2026-08-27 across all tables, all 5 health checks passed on the Aug 28 run.
  Local SQLite behind at 2026-08-25 (local nightly hasn't run; will catch up).
- **DB writes:** none — read-only.
- **Verification:** direct Postgres queries + `gh run view` logs for the Aug 26
  and Aug 28 daily_scraper runs.
- **By:** Claude Code. (Related standing gap: TR-18 — no independent watchdog
  for a missed/delayed scheduled run; it self-recovered here via `dates_since`.)

### 2026-08-27 — Working branch `feat/tr05-freshness-gates` reconciled to `main`
- **What:** The local repo had sat on a 2-week-old working branch while 8 PRs
  (#21–#28) merged all this session's work into `main`. Reconciled the branch:
  backup marker `backup/feat-tr05-758f866` → stash → `git checkout main` →
  `git stash pop` (3 trivial conflicts resolved) → deleted the old branch. Local
  repo is now on `main` (`d800a4d`). `git status` went from 28 items to 2
  (`breadth_data.csv` and `local_cloud_price_reconciliation.py`, both deliberate).
- **Why:** Close out the TR-11 arc-classification work; get onto the simple
  PR-per-task workflow going forward.
- **DB writes:** none (git only).
- **Verification:** all 5 runtime files (`main.py` etc.) confirmed byte-identical
  to `origin/main`; modules import; 37-test subset + full suite green. Safety
  nets (`backup/feat-tr05-758f866` branch, `stash@{0}`) retained until the next
  successful nightly run.
- **By:** Claude Code. Full detail: audit ledger §76.8.

### 2026-08-27 — Maintenance log established
- **What:** Created this file, added the governing standing rule to `CLAUDE.md`,
  and seeded the Open Items Ledger in the Trust Register. Closeout of the TR-11
  arc-classification work (audit ledger §76).
- **Why:** No single standard existed for recording routine maintenance going
  forward, and the audit/Trust-Register/RESEARCH_LOG split left "what did I do
  last week" unanswerable at a glance.
- **DB writes:** none.
- **Verification:** n/a — documentation only.
- **By:** Claude Code.
