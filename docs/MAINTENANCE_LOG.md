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

### 2026-09-02 — TR-08: `current_publication` table created on live Supabase
- **What:** `CREATE TABLE current_publication` on live Postgres (Supabase) — the Postgres side of TR-08's publication-decision record (SQLite side already live since PR #60). Ran `scratch_tr08_pg_ddl_20260902/ddl.py`: dry-run (transaction + ROLLBACK, confirmed the DDL applies clean and rolls back to 0 writes) → `--apply` (commit) → independent fresh-connection re-verify → re-ran `--apply` once more to confirm a clean no-op (the same idempotent `CREATE TABLE IF NOT EXISTS` the real `ensure_current_publication_pg()` code path uses, so the next production run touching this table is deploy-safe).
- **Why:** Closes the gap flagged in ledger §104.6 — the cloud/authoritative pipeline was the one side of TR-08 with no publication record at all until this ran; every `run_freshness_gate()` call on the GitHub Actions path was silently failing to write (caught, logged at debug, never raised) with nowhere to write to.
- **DB writes:** One new, empty table (`current_publication`, 10 columns, 0 rows) on live Supabase. No existing table touched — independently confirmed: `pipeline_runs` row count unchanged (68), public table count 63→64 exactly. No backup needed for the same reason `scrape_coverage`'s PG DDL needed none: a `CREATE TABLE` of a table that didn't exist yet has no prior state to lose; rollback if ever needed is a plain `DROP TABLE current_publication`.
- **Verification:** Schema re-read fresh (10 columns, types match the SQLite DDL's intent — `BOOLEAN` not `INTEGER`, `TIMESTAMPTZ` not `TEXT`), 0 rows, second `--apply` run confirmed idempotent.
- **By:** Claude Code, owner sign-off ("Let's do the Postgres DDL first"). Full detail: audit ledger §108.

### 2026-09-02 — TR-09: first real Backblaze B2 backup executed + restoration drill PASSED
- **What:** First live run of `backup_to_b2.py` (backed up `psx_data.db` + the 3 gitignored audit docs, snapshot `ba00f7a6`, ~882MB uploaded in ~6 min) followed by `restore_drill_b2.py` (restored that snapshot into an isolated scratch dir, verified independently). Two bugs found and fixed live against the real account before either script worked: (1) the script's hardcoded bucket name (`kiran-psx-backup`) didn't match the owner's actual bucket (`kiran-psx-backups`) — caught by querying B2's `b2_authorize_account` API directly; (2) restic's native `b2:` backend returned `b2_list_buckets: 401` against the restricted key even though its capabilities include `listBuckets` — matches a known issue class restic's own docs name, fixed by switching to B2's S3-compatible API (`s3:https://s3.us-east-005.backblazeb2.com/...`) using the same B2 application key as S3-style credentials. A third, cosmetic-only issue found during the drill: restic exits non-zero restoring on Windows because it can't set a *timestamp* on the reconstructed `C:\Users` parent directory (an ACL quirk of that specific folder) — `restore_drill_b2.py` was fixed to verify actual file content instead of trusting that exit code alone, which is what it's for.
- **Why:** TR-09's acceptance criterion is explicit that tooling existing is not enough — "a documented restoration drill has been performed at least once." This produced that evidence.
- **DB writes:** none to `psx_data.db` itself (read-only backup) or Postgres. New data: one restic snapshot in the `kiran-psx-backups` B2 bucket (owner's own cloud storage, not this repo's databases).
- **Verification:** `restore_drill_b2.py` full output — `PRAGMA integrity_check` = ok, `prices` table 1,758,903 rows / MAX(date)=2026-09-01 (plausible), all 3 docs restored with plausible sizes. Overall: PASS. Full local test suite re-run clean after the two script fixes.
- **By:** Claude Code + owner (owner created the B2 bucket/restricted key, generated `RESTIC_PASSWORD` in their own terminal, set all 3 credentials as local env vars — none seen or handled by Claude Code). Full detail: audit ledger §106.

### 2026-09-01 — OI-12: backfilled the raw rows missing from the 3 TR-14.2 PARTIAL dates (both backends)
- **What:** Re-fetched ksestocks MarketSummary for 2026-04-27 / 2026-05-06 / 2026-08-20 and inserted the `prices` / `index_prices` / `prices_adjusted` rows that were absent — **both** local SQLite and Postgres were short (this is a re-fetch, not a backend sync). `scratch_oi12_backfill_20260901/backfill.py`, insert-only.
- **Why:** Owner decision on ledger §97's 3 findings = backfill. Phase 1 = the raw archive; the derived-table residual (§98.3) is deferred to the `stock_signals` PG port.
- **DB writes:** **PG** — `prices` +17, `index_prices` +9, `prices_adjusted` +17 (all `ON CONFLICT (symbol,date) DO NOTHING`). **Local SQLite** — `prices` +17, `index_prices` +5 (local already had 08-20's index), `prices_adjusted` +17. `prices_adjusted` = 1:1 copy of the new `prices` rows, factor 1.0 (verified no confirmed corporate action affects any of these symbol/date pairs). Rows added: 04-27 (5 index KSE-*), 05-06 (10 equity `AGLNCPS…SSML`), 08-20 (7 equity `WTL,YOUW,ZAHID,ZAL,ZIL,ZTL,ZUMA` + 4 index).
- **Backup first:** local — `backups/psx_data_pre_oi12_backfill_20260901.db` (`integrity_check` ok, sha256 `c323de1ea4ee5e0cd67fa3965056dfd5e0bb430be0fb70e8fb588a9612b2b53c`). PG — CSV of the 3 dates' `prices`/`index_prices`/`prices_adjusted` rows in `scratch_oi12_backfill_20260901/`. Rollback = `DELETE` the inserted (date,symbol) set.
- **Verification:** independent fresh-connection full-row compare over the 3-date window — every pre-backfill PG row still present **byte-identical, 0 changed, 0 missing**; counts match the inserts exactly; local `integrity_check` ok, MAX dates unchanged. `scrape_coverage` re-computed for the 3 dates → all COMPLETE; **PG `scrape_coverage` now 495/495 COMPLETE** (was 492/3).
- **Residual (OI-12 stays open):** `stock_signals` (WTL + 5 other tracked symbols missing a bar; cross-sectional `rs_rank` on 08-20/05-06), `sector_signals` breadth on 08-20, `market_regime` 2026-04-27 still absent — deferred to the `stock_signals` Postgres port (§98.3). Retain the backups until a clean nightly.
- **By:** Claude Code, under explicit user authorization ("OI-12: backfill the 3 partial dates"), dry-run shown first per backend. Full detail: ledger §98.

### 2026-09-01 — TR-14.2: retroactive `scrape_coverage` sweep of the Postgres 2-year window
- **What:** Re-fetched the ksestocks MarketSummary page for all **495** distinct `prices` trading dates in the last 2 years (2024-09-02 … 2026-08-31) and stamped a `scrape_coverage` verdict per date — `baseline` (symbols the source now shows traded, equity+index) vs `stored` (our `prices` + `index_prices` count). `scratch_tr14_2_retro_sweep_20260901/retro_sweep.py`, via `data_health.record_scrape_coverage()` unchanged. Read-only except the INSERTs; resumable (per-20-date chunk commit; skips dates with an existing row); ~50 min at `REQUEST_DELAY=2s`.
- **Why:** TR-14 scoping spec §4.D — the "provably checked … historical" half of TR-14. Ledger §97. Owner-approved (decision 2 = "(a) PG 2-year window now").
- **DB writes:** Supabase `scrape_coverage` — **+495 rows** (table was empty → 495), all `code_version = a5967e8` (HEAD). **No backup needed** — additive rows to a previously-empty table, nothing existing touched. No other table written. Rollback = `DELETE FROM scrape_coverage WHERE detail LIKE 'TR-14.2 retro%'` (or `TRUNCATE` — the table has no live-scrape rows yet).
- **Verification:** independent fresh read-only connection — 495 rows, every window date has one (0 missing), `prices` unchanged at 231,268 rows; a re-run of the sweep is a clean no-op. Verdict split **492 COMPLETE / 3 PARTIAL**. The 3 PARTIAL (`2026-08-20` tail-truncated 7 equity W–Z + 4 index; `2026-05-06` 10 scattered equity; `2026-04-27` `index_prices` entirely missing) each verified by symbol-level diff against the re-fetched source + neighbour-date checks — genuine previously-invisible historical losses.
- **Follow-up:** Trust Register **OI-12** (local) — owner disposition of the 3 PARTIAL dates: backfill (re-scrape + upsert + recompute the affected windows, backup-first) or accept as documented scars.
- **By:** Claude Code, under explicit user authorization (task: "TR-14.2 retroactive sweep"), dry-run sample shown first. Full detail: ledger §97.

### 2026-09-01 — TR-11 deployment-identity production observation (workflow dispatches + Cloud reboot)
- **What:** Closed out TR-11 step 4 (OI-9 / ledger §96). Two `daily_scraper.yml` `workflow_dispatch` runs — 33471393043 (on `4fdd4dc`) and **33476372598 (on `5fe1c53`)** — each hit the "already up to date" path (no new trading day) but stamped `pipeline_runs.code_version` on their `deployment_identity` / `support_reversal` / `leaders_scan` heartbeats. Owner rebooted the Streamlit Cloud serving app **twice** (once after PR #47, once after `origin/main` settled at `5fe1c53`).
- **Why:** TR-11's acceptance needs a *standing* deployed-SHA readback observed in production. First reboot showed the drift panel in ⚠️ (serving `62f32da` vs pipeline `4fdd4dc`) — an unrelated docs PR (#48) had moved `main` during the reboot window; frozen `main`, re-dispatched on HEAD, re-rebooted.
- **DB writes:** Postgres `pipeline_runs` only — heartbeat rows from the dispatch runs, `code_version` = the dispatched commit SHA (canonical `$GITHUB_SHA`). No signal-table change (both runs were "already up to date"). No backup needed (append-only telemetry).
- **Verification:** live PG `data_health.latest_pipeline_code_version()` → `5fe1c53`; Data Health page (owner screenshot) — **Serving Revision `5fe1c53c8c75723ea4933ce18312363e7ba74af0`**, `describe_drift()` panel **✅ green "Serving code matches the pipeline (`5fe1c53`)"**. Serving SHA == latest-pipeline SHA == `origin/main` HEAD.
- **Outcome:** **TR-11 → 🟢 GREEN** (Trust Register, local). Follow-up OI-11 (drift-panel message imprecise when serving is ahead of the pipeline). `scrape_coverage` on PG still 0 rows (no new trading day scraped yet).
- **By:** Claude Code (dispatches) + owner (Cloud reboots). Full detail: ledger §96.

### 2026-09-01 — TR-14.1a: `scrape_coverage` table created on Supabase Postgres
- **What:** `CREATE TABLE IF NOT EXISTS scrape_coverage (...)` on the live Supabase DB — the Postgres half of the TR-14.1a table (PR #46, ledger §94). Brand-new **empty** table; the DDL is `data_health.ensure_scrape_coverage_pg(cur)` run verbatim (the shipped function, so what ran here == what any signed-off caller runs). Not called implicitly by any pipeline code — this is the one-time explicit step, same contract as `ensure_boring_signals_scanned_table_pg()` / the OI-9 `ALTER`.
- **Why:** So the cloud `daily_scraper.yml` pipeline can record a per-date completeness verdict. Until this table exists, `record_scrape_coverage()`'s PG path fails its INSERT (caught, never raises — so the cloud was silently not recording coverage). Owner-authorized this session.
- **DB writes:** Supabase — **+1 table (`scrape_coverage`), 0 rows, no other object touched** (public tables 62 → 63; `prices` 231,268 rows / MAX 2026-08-31 and `pipeline_runs` unchanged). Method: `scratch_tr14_1a_observe_20260831/pg_ddl_scrape_coverage.py` — defensive `SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE` (pooled-conn read-only guard, ledger §79) → dry-run (txn + ROLLBACK, schema verified) → `--apply` (commit). **No backup taken — nothing to lose:** a `CREATE TABLE` of a new empty table touches no existing data. Rollback = `DROP TABLE scrape_coverage;` (empty).
- **Verification:** independent fresh read-only connection — `to_regclass('public.scrape_coverage')` = `scrape_coverage`; 7 columns exactly (`scrape_date DATE PK`, `expected_total`/`parsed_total` INT null, `coverage_status TEXT NOT NULL`, `detail` TEXT null, `recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `code_version` TEXT null); PK on `scrape_date`; 0 rows; only new table = `scrape_coverage`, nothing dropped; `prices` / `pipeline_runs` untouched. A second `ensure_scrape_coverage_pg()` call = clean no-op (`CREATE TABLE IF NOT EXISTS`).
- **Manual `workflow_dispatch` (run 33471393043, on `4fdd4dc`) — pipeline ran clean, but wrote NO `scrape_coverage` row:** source date was still 2026-08-31, so `cmd_update()` took the "Database is already up to date" path — it never re-scrapes, so `record_scrape_coverage()` is never called. `record_scrape_coverage()` only writes when a genuinely **new** trading day is scraped (and a same-day re-scrape of an already-stored date is discarded as a ghost by design — no row). What the dispatch **did** confirm: the merged TR-14.1a code imports and runs fine on Cloud (`deployment_identity` stamped `code_version=4fdd4dc`, `working_tree=clean`; freshness gate + all 5 health checks PASS). `scrape_coverage` still 0 rows — verified fresh connection.
- **Next:** the first real cloud `scrape_coverage` row will land when the next genuine new-day scrape runs — i.e. the cron **after** 2026-09-01 EOD data publishes (evening PKT). Check `scrape_coverage` + the Data Health page then to confirm `_record_scrape_coverage_pg()` writes end-to-end.
- **By:** Claude Code, under explicit user authorization, dry run shown first. Full detail: ledger §94.

### 2026-09-01 — TR-14.1a: `scrape_coverage` mechanism observed working (local pipeline + a scoped fetch)
- **What:** Two independent observations of the still-uncommitted TR-14.1a code (`scraper.parse_sector_counts()` + `data_health.record_scrape_coverage()` + the new `scrape_coverage` table). (1) `scratch_tr14_1a_observe_20260831/observe.py` — a one-off script: single live `ksestocks` MarketSummary fetch for the source date, parse the per-sector traded-company counts, `record_scrape_coverage()` against local `psx_data.db`, read back. (2) Separately and on its own schedule, the **local Task Scheduler pipeline** (`run_update.bat` → `main.py --update`, run_id `66f01996…`, 2026-09-01 ~03:49–03:58 UTC) ran the same working tree end-to-end — the OI-9 dirty-tree WARNING fired correctly ("modified tracked .py: data_health.py, main.py, scraper.py"), and it scraped 2026-08-31 and recorded coverage as part of the real hook chain.
- **Why:** Step 2 of the TR-14.1a resume plan — prove the parse + record + read-back path works on a real page before branching/PR.
- **DB writes:** local `psx_data.db` **only**. New table `scrape_coverage` (SQLite DDL, additive) + **one row, upserted**: final state `(2026-08-31, expected_total=622, parsed_total=622, COMPLETE, detail=NULL, recorded_at≈03:50:53Z, code_version=d248e31…)` — written by the scheduled pipeline run (observe.py had first written a transparent `code_version='observe-tr14.1a'` marker; the pipeline's `ON CONFLICT DO UPDATE` replaced it with the genuine SHA). Plus a `scrape_coverage` `pipeline_runs` heartbeat: `COMPLETED / EXPECTED`, eligible=1 processed=1. No existing table touched by either observation. Backup first (taken while the DB was still at `prices` MAX 2026-08-28, `scrape_coverage` absent): `backups/psx_data_pre_scrape_coverage_20260831.db` (`PRAGMA integrity_check` ok, sha256 `d0b290c3de6f2a8078f0194239934ed07b9c06974ad89cd203764ebdf39d0869`, 882016256 bytes).
- **Verification:** live fetch (re-run read-only three times, identical) → `parse_sector_counts` = `expected_total = parsed_total = 622` across 38 sectors, **0 short / 0 over** (matches the scoping spec's live-verified 622==622). `parse_market_summary` cross-check: 495 equity + 5 index rows post-filter; 622 pre-filter = 495 + 5 + ~122 non-equity the equity filter drops — internally consistent. Verdict `COMPLETE`; `scrape_coverage_status("2026-08-31")` → `COMPLETE`; table holds exactly 1 row; `PRAGMA integrity_check` → ok. The scheduled pipeline run wrote the coverage row and heartbeat with no PARTIAL/UNKNOWN and no error. Full suite this session: **335 passed** (twice).
- **Note (not a defect):** the same pipeline run also wrote a `boring_signals` heartbeat to Postgres `pipeline_runs` (run_id `66f01996…`, 03:56:57Z, 0 new signal rows) — this is the intentional `_record_hook(mirror_to_postgres=True)` cross-backend heartbeat (main.py ~L635), telemetry only, so the Cloud "Boring Breakouts" banner can tell a local hook ran. Not a data write to `boring_signals`.
- **Retention:** keep `backups/psx_data_pre_scrape_coverage_20260831.db` until the TR-14.1a PR merges and the first post-merge nightly runs clean.
- **By:** Claude Code, under explicit user authorization. Full detail: ledger §94 (pending, in the TR-14.1a PR).

### 2026-08-31 — TR-01 Phase 1c: first rolling trim of `sector_signals` (Supabase Postgres)
- **What:** `sector_signals` was added to `database_pg._TRIM_TABLES` (audit §38.1 — it was the one large PG table left growing unbounded). The first trim of a newly-covered table is a large irreversible `DELETE`, so it was run manually here rather than left for the next `daily_scraper.yml` cron. `DELETE FROM sector_signals WHERE date < CURRENT_DATE - INTERVAL '2 years'`.
- **Why:** Ledger §93 / migration §40.14. `sector_signals` had 82 % of its rows older than the 2-year operational window; no PG consumer looks back more than 30 days (`get_sector_rs_history_pg` = 30 d; everything else `MAX(date)` / prior day). Local SQLite is the permanent full-history archive.
- **DB writes:** Supabase `sector_signals` — **64,317 → 11,362 rows (−52,955)**. Range 2015-01-01…2026-08-28 → **2024-09-02…2026-08-28** (MAX unchanged). No other table touched. Method: `scratch_sector_signals_trim_20260831/backup_and_trim.py` — dry-run (txn + ROLLBACK, −52,955, verified restore) → real `DELETE` + commit. Backup first (Supabase PITR OFF): full CSV `scratch_sector_signals_trim_20260831/sector_signals_pre_trim.csv` (64,317 rows, 23 cols) + snapshot table `sector_signals_pre_trim_20260831` (64,317 rows, verified). Rollback: `TRUNCATE sector_signals; INSERT … SELECT * FROM sector_signals_pre_trim_20260831`.
- **Verification:** independent fresh-connection re-query — 11,362 rows; MIN `2024-09-02` ≥ the `2024-08-31` cutoff; MAX `2026-08-28` unchanged; **0 of the 11,362 retained rows changed value** vs the snapshot (`rs_rank` + `composite_score` join-diff); snapshot intact at 64,317; `health_check.check_rolling_trim()` re-run against live PG with the new code → PASS. Local `psx_data.db` `sector_signals` **unchanged at 64,425 rows** (PG-only op).
- **Retention:** keep the CSV + snapshot table until the next clean `daily_scraper.yml` run.
- **By:** Claude Code, under explicit user authorization, dry run shown first. Full detail: ledger §93.

### 2026-08-31 — TR-01 Phase 1b-ii: `leaders_top_picks` historical backfill (Supabase Postgres)
- **What:** Recovered the `leaders_top_picks` `scan_date`s that `_save_top_picks_pg()`'s latest-date-only defect skipped (frozen at 2026-06-30). Called the merged `leaders_scan._save_top_picks_pg(scan_date=d)` (directly, so it reads the live env not the import-time `_PG_URL`) for every `leaders_scan` `scan_date` absent from `leaders_top_picks` — 44 dates, of which 17 produce picks.
- **Why:** Trust Register TR-01 Phase 1b, item 1b-ii (ledger §91). `leaders_top_picks` history is consumed (the Leaders "audit" panel; forward-return labeling), so unlike Phase 1a's accepted gap this was backfilled. Owner-authorized after the dry run.
- **DB writes:** Supabase `leaders_top_picks` — **+34 rows across 17 dates, 0 UPDATE, 0 DELETE** of the 11 pre-existing rows (each backfilled date had zero rows; `DELETE WHERE scan_date=d` removed nothing). No other table touched (`leaders_scan` unchanged at 887 rows). New rows carry `outcome_label='OPEN'` — the next `daily_scraper.yml` run's `fill_leaders_forward_returns()` labels the closed-window ones. Backup first (Supabase PITR OFF): `scratch_leaders_toppicks_1bii_20260831/leaders_top_picks_pre_1bii.csv` (11 rows) + snapshot table `leaders_top_picks_pre_1bii_20260831` (11 rows, verified). Rollback: `DELETE ... WHERE scan_date NOT IN (<original 5 dates>)` + re-`INSERT ... SELECT * FROM` the snapshot.
- **Verification:** independent fresh-connection re-query vs the snapshot — all 11 pre-existing rows present and byte-identical (19-column compare); `leaders_scan` 887 = 887; final `leaders_top_picks` **45 rows / 22 distinct `scan_date`s**; re-deriving 3 already-done dates = 0 net change (idempotent); `transaction_read_only=off` confirmed before writing.
- **By:** Claude Code, under explicit user authorization, dry run shown first. Full detail: ledger §91.

### 2026-08-31 — TR-01 Phase 1b-ii: `leaders_top_picks` historical backfill (local SQLite)
- **What:** Same as the Postgres entry above, for `psx_data.db`. `leaders_scan.save_top_picks(psx_data.db, scan_date=d)` for every `leaders_scan` `scan_date` absent from `leaders_top_picks` — 29 dates, of which 8 produce picks. `leaders_top_picks` was frozen at 2026-08-17.
- **Why:** Ledger §91. Run in its own process, hard-guarded to abort if any Postgres env var is visible (OI-8 lesson) — the guard was never tripped.
- **DB writes:** local `psx_data.db` **only** — `leaders_top_picks` **+19 rows across 8 dates, 0 UPDATE, 0 DELETE** of the 34 pre-existing rows. `leaders_scan` unchanged (907). New rows `outcome_label='OPEN'`; the next `run_update.bat` fills forward returns. Backup first: `backups/psx_data_pre_leaders_toppicks_20260831.db` (`PRAGMA integrity_check` ok, sha256 `b7dc2b282d1498254651bec9c4b23b446c4a82c650b941dd7827e21feb0202b0`, 882016256 bytes, 34 `leaders_top_picks` rows). Retain until the next clean nightly.
- **Verification:** independent fresh-connection re-query vs the backup — `PRAGMA integrity_check` ok; all 34 pre-existing rows present + byte-identical (19-column compare); `leaders_scan` 907 = 907; final **53 rows / 25 distinct `scan_date`s**; the 21 dates still without a row all re-confirmed genuine zero-pick; re-deriving 3 already-done dates = 0 net change; the dashboard "audit" query now returns the recovered dates.
- **By:** Claude Code, under explicit user authorization, dry run shown first. Full detail: ledger §91.

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
