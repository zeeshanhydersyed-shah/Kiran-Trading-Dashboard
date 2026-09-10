# Kiran Local-First Migration — Plan & Live Status Tracker

**This is the SINGLE SOURCE OF TRUTH for what is done, ongoing, and pending on the local-first
migration.** Progress is tracked here and nowhere else — code detail lives in PRs, DB
operations in `MAINTENANCE_LOG.md`, but the *state of the migration* is §1 + §10 of this file.

- **Decision status:** approved in principle by the owner, 2026-09-09. On `origin/main` since
  PR #78 (`9b0ef22`).
- **Full design:** the reviewed architecture document (artifact, private) — see §11. This file
  carries a working summary (§3–§4) so the repo is self-contained.
- **Governance:** the three-roles model and Production-Write Discipline are unchanged. Every
  production write still needs explicit owner sign-off, backup-first, dry-run, independent
  re-verification.
- **Verdict during the migration:** unchanged — **NOT VERIFIED — DO NOT TRADE** until the
  cutover gate (§6) passes and the burn-in completes.

---

## 0. WORKING PROTOCOL (read first, every session)

**Trigger phrase.** A session that opens with **`KIRAN_LOCAL_FIRST_MIGRATION`** means: resume
this migration. Read this document top to bottom — especially §1 (the phase table) and §10 (the
running log) — confirm the current state, then wait for the owner's specific instruction for
the session. Do not auto-start a phase.

**Session reset.** The chat context is cleared after each completed task. Nothing carries over
except what is written to project files. Treat every session as starting cold from this
document.

**Auto-save.** Write code, logs, tests, and artifacts to their real project files and
directories **as work completes** — never leave finished work only in chat.

**Keep this document current — before finishing ANY task:**
1. Update **§1** (phase table) — status + date for every phase/task that changed state.
2. Tick the relevant boxes in **§5** — only when the task is done **and verified**.
3. Add a dated entry to **§10** (running log), newest first — what was done, what is next.
4. **Commit the doc update to `origin/main`** (doc-only commit is fine; branch → push → PR →
   merge on green CI, matching PR #78). An uncommitted tracker update is a lost tracker update
   once the session resets.

---

## 1. STATUS AT A GLANCE

**Overall: PHASE 1 COMPLETE (2026-09-09 → 2026-09-10). Phase 2 NOT STARTED — begins only on the
owner's explicit "start Phase 2".** The immutable baseline is built, verified, git-manifested,
copied off-site under B2 COMPLIANCE Object-Lock (undeletable by anyone, incl. the key holder and
Backblaze, for 3000 days), and a restore drill proves it comes back. **The old dual pipeline
(Task Scheduler + SQLite, GitHub Actions + Supabase) is still the live system and is untouched**
— nothing in Phase 1 wrote to `psx_data.db` or changed the pipeline (D7: preservation only;
live hash `6a3b974d…425b` unchanged before and after).

| # | Phase | Status | Since | Notes |
|---|---|---|---|---|
| 0 | Decision & planning | ✅ DONE | 2026-09-09 | Design approved in principle; tracker + ledger/register entries written; **all 7 §9 decisions resolved by the owner 2026-09-09** |
| 1 | Stand up the archive + execute SEQ-1 | ✅ DONE | 2026-09-10 | Archive root `D:\KIRAN_ARCHIVE\` (C: space-constrained), 92 baseline payload files, local read-only. Whole-DB baseline via SQLite Online Backup API — `psx_data_baseline_KIRAN_LFM_P1_20260909_222210.db`, 882,896,896 b, **SHA-256 `9418cb1bf98c197550e02eae663f0ab870ccc93c967dfb743c221cd3d5f70d61`**, self-contained (`journal_mode=DELETE`), `integrity_check` ok, 53/53 table counts + all substrate date spans match live; Bronze/Silver Parquet store (`SUM(volume)` reconciles exactly); DR-006 baseline (`c03a393f…`) + BI 17-file set folded into `backup_set/` + hash-verified; `BASELINE_MANIFEST.{md,sha256}` (92 files, 1,898,646,386 b) git-committed, `archive_manifest verify` PASS. **Off-site:** all 92 files in B2 `kiran-psx-archive` under **COMPLIANCE Object-Lock, 3000 days** (undeletable — verified `AccessDenied` on a locked version); big SQLite files zstd'd (~33%) for the slow uplink; `offsite_push` resumable at the 16 MB part level. `offsite_push --verify` PASS; `restore_drill_archive` PASS (baseline restored + `integrity_check` ok + 1,761,371 price rows). `restore_drill_b2.py` now runs both drills. `archive_checksum_check` for Task Scheduler. PRs #81 / #82 / #83. **NOTE:** `duckdb` has no cp314 wheel (Python 3.14) — the Parquet store is engine-neutral; the DuckDB attach layer is a Phase 3 item. The over-broad B2 key is moot (COMPLIANCE can't be bypassed); a minimal key is optional later hygiene. |
| 2 | Rework the scrape (GitHub Actions) | ⬜ NOT STARTED | — | New workflow: commit `YYYY-MM-DD.parquet` (immutable) + refresh `latest.parquet`. Old `daily_scraper.yml` keeps running in parallel until Phase 6 |
| 3 | Build the Medallion transforms | ⬜ NOT STARTED | — | Bronze ingest (capture-file lineage), Silver (port CA + conforming; wire the v2 reader as an available source, gate off), Gold (2-yr slice, screeners, grading). Idempotency tests per transform |
| 4 | Publication contract + atomic swap | ⬜ NOT STARTED | — | Four gates into the Gold build; `current_publication` with the full lineage block; staging-DB build + rename |
| 5 | Shadow run | ⬜ NOT STARTED | — | Nightly local Gold vs current Supabase output, ≥10 trading sessions, diffs investigated |
| 6 | Cutover | ⬜ NOT STARTED | — | Front end → Gold JSON; retire `daily_scraper.yml` / Supabase / Streamlit Cloud; delete the `_pg` path, `database_pg.py`, the stale `main.py` copies; snapshot + pin for the DR program |
| 7 | Burn-in | ⬜ NOT STARTED | — | 2 weeks of daily local operation, watchdog live, backup + restore drill running |
| 8 | Retire the write surface | ⬜ NOT STARTED | — | Final sweep for any script that can write outside the pipeline |
| — | Front end (2 pages) | ⬜ NOT STARTED | — | Built in parallel from Phase 2 onward — Sector Grading + Explorer; see §5 |
| — | *Optional:* Q6 gate — v2 in the dashboard | ⬜ DEFERRED | — | Separate sign-off, post-cutover, not coupled to the migration |

Status values: `⬜ NOT STARTED` · `🔵 IN PROGRESS` · `🟠 BLOCKED` · `✅ DONE`.

---

## 2. The decision

Kiran stops running two production pipelines. The Windows machine becomes the single
authoritative backend, running a Medallion pipeline (Bronze → Silver → Gold) once a night.
GitHub Actions keeps only the daily scrape and commits the raw data to the repo as dated,
immutable capture files. Supabase and Streamlit Cloud are retired. The dashboard becomes a
small static site of two pages that reads precomputed JSON and computes nothing on load.

This **supersedes** `CLAUDE.md`'s 2026-08-26 "Postgres/Supabase is authoritative" decision.
The forensic background that motivated the Trust Register (two independent pipelines, no
reconciliation) is unchanged — the fix direction is reversed: collapse to **local**, not cloud.

Rationale, in one line: the friction was never "the cloud," it was the dual pipeline and
piecemeal growth. One backend, one pipeline, one direction of flow fixes both — and closes or
simplifies most of the cutover-blocking register by construction (§14 of the design doc / the
Trust Register amendment 2026-09-09).

---

## 3. Target architecture (working summary)

**Two physical stores, one direction of flow:**

| Store | Holds | Written by | Read by | Engine |
|---|---|---|---|---|
| `prices_archive` | Bronze + Silver — full history 2005→now (~900 MB) | Scraper (append), Silver transform | Silver build, research, DR loops | DuckDB + Parquet |
| `psx_serving` | Gold — 2-yr window + signals + grades (<200 MB) | Nightly Gold build (full replace, atomic swap) | Front end only | DuckDB |

*Engine decided 2026-09-09 (§9 D1): **DuckDB across all three layers** (Bronze, Silver, Gold).*

**Data flow:** GitHub Actions scrapes → commits `data/incoming/YYYY-MM-DD.parquet` (immutable,
one per date) + refreshes `latest.parquet` → local pipeline `git pull` → append to Bronze
(deduped, gap-detecting) → Silver (CA-adjust, conform, indicators) → Gold (2-yr slice,
screeners, sector grades, publication gate) → JSON export → static front end. Research and the
DR loops attach **read-only** to Bronze/Silver, exactly as today.

**The Medallion layers:**
- **Bronze** — raw prices, append-only, immutable, partitioned by date. No transform ever
  rewrites a raw historical row. This is the layer that gets backed up.
- **Silver** — corporate-action-adjusted prices, conformed universe, indicators. The
  **CA v2 substrate** from the Data Rehabilitation program (`expanded_prices_v2.sqlite`, 141
  liquid names, 2021+ total return) is a **named Silver-layer input** — research reads it now
  via `ca_v2_reader.load_v2_prices`; the dashboard reads it only after the Q6 gate (a separate
  sign-off — TR-19 graded, shadow comparison, coverage decision, residual disposition).
- **Gold** — the 2-year serving window, precomputed signals and grades. Disposable — a bad run
  rebuilds it from Silver in minutes.

**The publication contract:** the Gold build promotes to `current_publication` iff all of —
freshness (TR-05), completeness vs the known universe (TR-14), hook coverage (TR-06),
coherence (TR-04), lineage complete (TR-16), atomic swap (TR-17). Any of the first four fails
→ **withhold**: keep serving the last promoted Gold, show `NOT VERIFIED — DO NOT TRADE`
naming the failed gate, fire an ntfy alert.

**Front end:** hand-written HTML + vanilla ES modules, no build step. Vendored Alpine.js +
Tabulator + uPlot. Static JSON from the pipeline, served by `python -m http.server`. Two
pages at cutover: Sector Grading, Explorer. Adding a page later = one file + one registry
line.

**Alerting / watchdog:** the healthchecks.io dead-man's-switch + ntfy push (TR-18, already
built) stays. The pipeline also emits its own ntfy alert on a withheld publication. A fixed
nightly schedule replaces "at logon" (needed for TR-18's expected-run-window).

---

## 4. The seven design questions — resolutions (summary)

Full detail in the design doc §9.

| Q | Resolution |
|---|---|
| **Q1 — verified publication** | A conjunction of 6 recorded fields (freshness + completeness + hook coverage + coherence + lineage + atomic). Any of the first four fails → withhold. "Verified" is **scoped** — verified for the universe and CA provenance the publication declares. |
| **Q2 — lineage** | Every `current_publication` row (append-only, one per promote *and* withhold) carries: `run_id`, `code_version`, `bronze_range` + hash, dated capture files consumed + hashes, `silver_snapshot_sha`, `ca_provenance` per universe segment, `gate_results`. |
| **Q3 — Bronze backups** | Execute the DR program's SEQ-1: frozen baselines at milestones + nightly `restic` → B2 **object-lock**. Verified by a git-committed `MANIFEST.sha256` + a **scheduled restore drill** (`restore_drill_b2.py`, already passed once, made recurring). RPO 24h, RTO ~15 min. |
| **Q4 — offline** | 1 day / 1 week: automatic catch-up (dated files + rolling pointer). 1 month: ingest backfills from the permanent dated files; one-line `--backfill` only if a dated file is missing. The gate withholds on any incompleteness, so a partial catch-up is never served. |
| **Q5 — DR coexistence** | DR loops + CA build stay read-only consumers of the archive (`mode=ro&immutable=1`). Bronze append-only → any past DR loop re-verifiable. Frozen DR-006 baseline untouched. The migration must **not** wire v2 into the dashboard as a side effect. |
| **Q6 — authoritative vs provisional** | Authority is **scoped and declared**: one compute path, one served state, for the 2-yr window + screened universe. CA provenance in force is recorded per segment and shown per-symbol on Explorer (`adjusted_v2` / `raw`). The provisional deep history sits outside the serving window — a research/DR problem, not a current-authority problem. |
| **Q7 — `latest.parquet` overwrite** | Fixed: GitHub Actions commits one immutable `YYYY-MM-DD.parquet` per scrape date (the audit record) plus a freely-overwritten `latest.parquet` pointer. Gives contemporaneous capture — the evidence standard the DR program found missing for 2005–2019. |

---

## 5. Phase-by-phase task breakdown

Check a box only when the task is done **and verified**. Each phase is independently
revertible; the old pipeline stays live until Phase 6.

### Phase 1 — Archive + SEQ-1 baseline
- [x] Restore the current full history into a Bronze/Silver **Parquet** store *(DuckDB attach layer deferred to Phase 3 — no cp314 wheel; Parquet is engine-neutral)* — `archive/build_store.py`, 2026-09-09
- [x] Verify row counts and date spans against the live `psx_data.db` — 53/53 table counts match, all substrate spans match, `integrity_check` ok, live SHA-256 unchanged before/after (`archive/capture_baseline.py` + `D:\KIRAN_ARCHIVE\baseline\capture_report_20260909_215346.json`)
- [x] Build the immutable-baseline manifest (`BASELINE_MANIFEST.md` + `.sha256`), commit to git — `docs/KIRAN_LOCAL_FIRST_ARCHIVE/`, 92 files / 1,898,646,386 b, `archive/archive_manifest.py`
- [x] Push to Backblaze B2 with object-lock; set local baseline files read-only — 92 objects in `kiran-psx-archive` under **COMPLIANCE Object-Lock / 3000 days** (verified undeletable), big SQLite files zstd'd, resumable at 16 MB part granularity; `offsite_push --verify` PASS; `archive_manifest protect` set the 92 local payload files read-only (`archive/offsite_push.py`, `docs/KIRAN_LOCAL_FIRST_ARCHIVE/OFFSITE.md`), 2026-09-10
- [x] Fold in the frozen DR-006 baseline (`c03a393f…`) and the BI preservation set (17 files) as backup-set members — copied to `D:\KIRAN_ARCHIVE\backup_set\`, DR-006 `.db` hash matches, BI 17/17 match `PRESERVATION_MANIFEST.sha256`; both in the off-site copy
- [x] Wire a scheduled checksum check + extend `restore_drill_b2.py` to the widened backup set; run the drill once, PASS — checksum check `archive/archive_checksum_check.py` (Task Scheduler `KIRAN_Archive_Checksum`); `restore_drill_b2.py` now also runs `archive/restore_drill_archive.py`; drill **PASS 2026-09-10** (baseline restored, `integrity_check` ok, 1,761,371 price rows, MAX(date)=2026-09-08, every object COMPLIANCE-locked)

### Phase 2 — Rework the scrape
- [ ] New GitHub Actions workflow: fetch → commit `data/incoming/YYYY-MM-DD.parquet` + refresh `latest.parquet`
- [ ] Commit message carries the Actions run ID + self-reported row/sector counts
- [ ] Old `daily_scraper.yml` confirmed still running in parallel (not touched)
- [ ] First dated capture file observed in the repo, hash-verified

### Phase 3 — Medallion transforms
- [ ] Bronze ingest: append-only, deduped, gap-detecting, records which dated files it consumed + hashes
- [ ] Silver: port the corporate-action adjustment + universe-conforming logic; wire `ca_v2_reader` as an *available* source, **gate off** (dashboard still on the current path)
- [ ] Gold: 2-yr slice, run every registered screener, grade every sector
- [ ] Idempotency test per transform (re-run → identical output)
- [ ] Signal parity check: Gold screeners vs the current pipeline on a shared date, differences explained

### Phase 4 — Publication contract + atomic swap
- [ ] Port the four gates (freshness / completeness / hook coverage / coherence) into the Gold build
- [ ] `current_publication` table with the full lineage block (Q2)
- [ ] Staging-DB build + atomic rename (`psx_serving_new` → `psx_serving`)
- [ ] Test: force a mid-run failure → last good Gold served unchanged, withhold row written
- [ ] Test: force each gate to fail individually → promotion withheld, banner + alert fire

### Phase 5 — Shadow run
- [ ] Nightly local pipeline writes Gold alongside the live Supabase pipeline
- [ ] Per-session diff of every signal that changes (RS ranks, sector stage, screener output, `boring_signals` existence)
- [ ] ≥10 consecutive clean trading sessions (diffs = 0 or fully explained)
- [ ] Watchdog fires on a forced missed run (test)

### Phase 6 — Cutover
- [ ] Cutover gate (§6) fully passed and signed off by the owner
- [ ] Front end repointed at Gold JSON
- [ ] `daily_scraper.yml` disabled; Supabase project + Streamlit Cloud app retired
- [ ] Delete the `_pg` code path, `database_pg.py`, `dashboard_pg.py`, `main_backup_e8*.py`
- [ ] Snapshot the archive at cutover; hand the DR program a pinned reference + record it in `DATA_REHABILITATION_PROGRAM.md`
- [ ] Trust Register: TR-01 re-assessed; TR-04/06/08/16/17 re-assessed; verdict re-computed

### Phase 7 — Burn-in
- [ ] 2 weeks of daily local operation with no manual intervention
- [ ] Watchdog + nightly backup + weekly restore drill all confirmed running
- [ ] Publication promoted every trading day (or every withhold explained)

### Phase 8 — Retire the write surface
- [ ] `git ls-files` sweep: no script can write to the archive outside the pipeline entry point
- [ ] `MAINTENANCE_LOG.md` + Trust Register TR-12 updated

### Front end (parallel, from Phase 2)
- [ ] Day-1 structure: `index.html` shell, `app.css` tokens, `main.js` router, `js/lib/*` (data, table, chart, format, dom), vendored libs
- [ ] Sector Grading page (reads `sector_grades.json`)
- [ ] Explorer page (reads `signals.json`; per-symbol `price_basis` flag visible)
- [ ] Freshness banner wired to `meta.json` (VERIFIED / NOT VERIFIED)
- [ ] Both pages render from real Gold JSON

---

## 6. Cutover gate (Phase 6 — hard AND)

All must hold:
1. Archive verified against the live DB (row counts, spans)
2. SEQ-1 immutable baseline built + restore drill passed
3. Every Medallion transform idempotent (tested)
4. Publication gate tested for both promote and withhold, and for each gate failing individually
5. ≥10 consecutive clean shadow sessions
6. Watchdog fires on a forced missed run
7. Front end renders both pages from real Gold JSON
8. Owner sign-off recorded here and in `MAINTENANCE_LOG.md`

---

## 7. Rollback

The old pipeline, Supabase, and Streamlit Cloud are **untouched until Phase 6**. Before
cutover, rollback is: stop the local pipeline, do nothing else — the old system never stopped.
After cutover, within the burn-in window: re-point the front end at the (still-paused) Supabase
read path and re-enable `daily_scraper.yml`; the local Gold build is halted; the archive is
retained. A full rebuild of Supabase state from the archive is possible but is a last resort.

---

## 8. What is NOT changing

- Signal logic — screeners, Weinstein stage analysis, market gates, recovery bases, breakout
  pivot rules — ported as-is.
- Sector grading logic — the four-stage framework stays as-is *during* the migration; the
  "needs rethinking" is a separate later research task.
- The DR program's read-only rule, the frozen DR-006 baseline, the BI preservation set, the
  CA v2 build process — all untouched. Only the v2 *consumer path* is formalised.
- CI stays on GitHub Actions.
- The three-roles model and Production-Write Discipline.

---

## 9. Owner decisions — ALL RESOLVED 2026-09-09

| # | Decision | Resolution (owner, 2026-09-09) | Resolved? |
|---|---|---|---|
| 1 | Serving engine for Gold | **DuckDB across all three layers** (Bronze, Silver, Gold) | ✅ |
| 2 | Front end serve mechanism | **Static files + `http.server`** as the initial mechanism; an API added **only if a real requirement emerges** | ✅ |
| 3 | Fixed local pipeline schedule | **Fixed nightly Task Scheduler trigger** with **explicit catch-up-on-wake** and **no-duplicate execution semantics** | ✅ |
| 4 | Dated-capture retention | **Prune to `psx-data-archive` after ~90 days**, but only **after the archive is verified** — copy check + SHA-256 + retrieval test + manifest evidence — **before any prune** | ✅ |
| 5 | Q6 gate for v2 in the dashboard | **Deferred until after the Kiran cutover** — not coupled to the migration | ✅ |
| 6 | Front end scope at cutover | **Sector Grading + Explorer only**; the other 13 pages dropped, not ported | ✅ |
| 7 | SEQ-1 authorization | **Authorized as an immutable baseline-preservation operation only.** Does **not** authorize any rehabilitation or mutation of the historical dataset | ✅ |

**Binding conditions carried forward from the resolutions:**
- **D3** — the scheduler design must guarantee a single execution per night: catch-up-on-wake
  if the fixed trigger was missed, and a lock / already-ran guard so a wake catch-up plus a
  later on-time trigger cannot both run the pipeline for the same date.
- **D4** — pruning dated capture files to `psx-data-archive` is gated on a verification record
  (byte copy check, SHA-256 match, a real retrieval from the archive, and a manifest) proving
  every file to be pruned is safely preserved. No prune without that evidence.
- **D7** — Phase 1 / SEQ-1 is **preservation only**: read the current full history, write an
  immutable baseline (manifest + git + B2 object-lock), fold in the frozen DR-006 baseline and
  the BI preservation set. It must not adjust, correct, re-scrape, or otherwise mutate any
  historical row. Any rehabilitation of the substrate remains the separate DR program's work
  under its own authorization.

---

## 10. Running log (newest first)

### 2026-09-10 (latest) — Phase 1 COMPLETE: off-site Object-Lock copy + restore drill
Owner created the B2 bucket `kiran-psx-archive` (Object Lock enabled) and an app key
(`B2_ARCHIVE_KEY_ID` / `B2_ARCHIVE_KEY`, local env). The key came back over-broad (bucket-scoped
but still `deleteFiles` + `bypassGovernance`); rather than another recreation round we went
**COMPLIANCE-mode** retention, which makes those caps inert for locked objects — nobody can
delete or shorten a locked version, verified directly (`AccessDenied` deleting a locked version;
a plain delete only writes a reversible hide-marker). A minimal key stays optional later hygiene.

- **Push** — `archive/offsite_push.py`. Not restic (its lock-file churn would wedge against a
  COMPLIANCE rule). Flat one-object-per-file, per-object `ObjectLockMode=COMPLIANCE` +
  retain-until now+3000d (B2 max). The owner's uplink measured ~0.12 MB/s, so the two ~883 MB
  SQLite baselines are zstd-compressed (~33%) and every upload is **resumable at the 16 MB part
  level** (`.offsite_state/<key>.json`), per the CLAUDE.md standing rule. All **92** archive
  files uploaded; `offsite_push --verify` = PASS (every local file has a COMPLIANCE-locked
  bucket version with a matching SHA-256).
- **Read-only** — `archive_manifest protect` set the read-only bit on the 92 baseline payload
  files; `OFFSITE_MANIFEST.json` / `.offsite_state/` stay writable.
- **Restore drill** — `archive/restore_drill_archive.py`, and `restore_drill_b2.py` now runs it
  after the restic daily-backup drill for one combined verdict. **PASS 2026-09-10**: every
  object COMPLIANCE-locked; 91 files downloaded + decompressed + SHA-256-matched the committed
  manifest; the restored baseline `.db` opens, `integrity_check` = ok, 1,761,371 price rows,
  MAX(date) = 2026-09-08.
- `boto3` added to `requirements-archive.txt` (local only). `docs/KIRAN_LOCAL_FIRST_ARCHIVE/OFFSITE.md`
  records location / retention / recovery-from-nothing. Committed on branch
  `phase1/offsite-object-lock` → PR #83.
- Housekeeping: two verification probes and one 0-byte stray log got COMPLIANCE-locked before
  the exclusion rules were tightened — hidden with delete-markers, ~$0.06 of storage over 8
  years, ignored by all tooling (noted in `OFFSITE.md`).

`psx_data.db` never opened for write across the whole phase — live SHA-256 `6a3b974d…425b`
before and after (D7). **Phase 2 does not auto-start** — it begins only on the owner's explicit
"start Phase 2". The `loop_dr_006/` capture report is still stale ("no baseline captured") — a
corrective note there is still open, outside this tracker.

### 2026-09-09 — Phase 1 started: local archive built + verified; off-site is the open leg
Owner said "start phase 1" and approved the recon plan (decisions A–E: archive on `D:\KIRAN_ARCHIVE\`;
whole-DB baseline **plus** derived Bronze/Silver Parquet; new Object-Lock B2 bucket, direct upload
not restic; `requirements-archive.txt`; trigger-based quiescence, non-elevated).

Executed, all read-only against `psx_data.db` (SHA-256 `6a3b974d…425b`, unchanged before and after):
- **Whole-DB immutable baseline** — SQLite Online Backup API → `D:\KIRAN_ARCHIVE\baseline\psx_data_baseline_KIRAN_LFM_P1_20260909_222210.db` (882,896,896 b, SHA-256 `9418cb1b…0d61` — see the fix note below; the first attempt was `21cf2e7f…`). `PRAGMA integrity_check` = ok. All 53 table counts and every substrate date span (`prices`/`prices_adjusted`/`index_prices` → 2005-01-03…2026-09-08, etc.) match live. Quiescence: no pipeline writer running, `PSX_TaskScheduler` logon-trigger-only with empty NextRunTime, last run 2026-09-08 complete, no WAL/SHM present.
- **Bronze/Silver Parquet store** — `bronze/prices` + `bronze/index_prices` + `silver/prices_adjusted` (year= partitions) + `silver/sectors` + `silver/stock_metadata`, built from the frozen `.db`, deterministic. `SUM(volume)` over `prices` reconciles exactly to the DB (1,545,422,618,131). Indicator tables intentionally not exported — they live in the whole-DB baseline and get rebuilt in Phase 3.
- **Folded-in members** — DR-006 rehabilitation baseline (`.db` SHA-256 `c03a393f…a8e0`, matches the tracker) and the DR-003 BI 17-file preservation set (re-verified 17/17 against its own `PRESERVATION_MANIFEST.sha256`) copied into `D:\KIRAN_ARCHIVE\backup_set\`. Canonical originals left in place.
- **Manifest** — `docs/KIRAN_LOCAL_FIRST_ARCHIVE/BASELINE_MANIFEST.{sha256,md}` (92 files, 1,898,646,386 b — corrected), committed to git. `python -m archive.archive_manifest verify` = PASS. Scheduled-check wrapper `archive/archive_checksum_check.py` written (Task Scheduler `KIRAN_Archive_Checksum`, weekly, ntfy on drift — not yet registered).

**Fix (same day, after PR #81 merged): baseline re-captured cleanly.** The first capture's `dst` connection inherited the source's `journal_mode=WAL`, so later read-only opens spawned transient `-wal`/`-shm` sidecars — and the manifest walker had picked them up (94 → should be 92 files). A `wal_checkpoint(TRUNCATE)` attempt on that copy also `VACUUM`ed it (harmless to data — 53/53 counts + integrity still ok — but it changed the file). Rather than freeze a baseline that had been poked at, it was **discarded and re-captured from scratch**: `capture_baseline.py` now forces `journal_mode=DELETE` + deletes any sidecar immediately after `.backup()`, and `archive_manifest.py` excludes `-wal`/`-shm`/`-journal`. New baseline SHA-256 **`9418cb1bf98c197550e02eae663f0ab870ccc93c967dfb743c221cd3d5f70d61`**. Live `psx_data.db` was `6a3b974d…425b` before and after every attempt — never opened for write, D7 intact. Follow-up PR #82.
- Repo test gate: `pytest` 437 passed. Nothing in `archive/` is imported by production code.

**Two Phase 1 legs remain, both blocked on the owner:** (1) create a **Backblaze B2 bucket with Object Lock enabled** + a restricted app key scoped to it (local env vars — Claude never sees the key); then Claude pushes the baseline + manifest off-site with a retention date and sets the local archive files read-only. (2) extend `restore_drill_b2.py` to the widened backup set and run the drill once to PASS — needs (1) done first. Also flagged: the `loop_dr_006/` capture report is stale (says "no baseline captured" — a later elevated attempt succeeded); worth a corrective note in the DR program.

### 2026-09-09 — All 7 §9 decisions resolved by the owner
The owner resolved every open decision in §9 in one pass:
1. DuckDB serving engine across Bronze/Silver/Gold.
2. Static files + `http.server` initially; API only if a real need appears.
3. Fixed nightly Task Scheduler trigger, with explicit catch-up-on-wake and no-duplicate
   execution semantics.
4. Prune dated captures to `psx-data-archive` after ~90 days, but only after copy check +
   SHA-256 + retrieval + manifest evidence proves preservation.
5. Defer the Q6 / v2-in-dashboard gate until after the Kiran cutover.
6. Cutover front end = Sector Grading + Explorer only; other 13 pages dropped.
7. SEQ-1 authorized as an immutable baseline-**preservation** operation only — no
   rehabilitation or mutation of the historical dataset.

§9, §1, and §3 updated to record these. Phase 1 is now **authorized** but **not started** —
per §0 it begins only on the owner's explicit "start Phase 1" for a session. Still no code
written, no pipeline touched; the old dual pipeline is still the live system. This doc update
committed to `origin/main` (doc-only). Next: owner says when to start Phase 1.

### 2026-09-09 (later) — Working protocol added; tracker on origin/main
The decision docs were merged to `origin/main` via **PR #78** (squash, `9b0ef22`) —
`CLAUDE.md`, `KIRAN_CLEANUP_AUDIT.md` §117, and this tracker. CI green (3/3). Owner then set
the working protocol for this migration: trigger phrase `KIRAN_LOCAL_FIRST_MIGRATION`, chat
context cleared after each task, this document is the single source of truth and must be
committed current before any task finishes — captured as **§0** above. Still PHASE 0, no code.
Next: owner resolves the §9 open decisions, then Phase 1 begins on authorization.

### 2026-09-09 — Design approved in principle; tracking set up
Owner approved the local-first architecture in principle. This tracker created.
`KIRAN_CLEANUP_AUDIT.md` §117 records the decision. `CLAUDE.md`'s "Production architecture"
section superseded (local-first, pointer here). Trust Register Amendment-Log entry added
(LOCAL — not committed) with the per-row impact; **no graded row's colour changed** — nothing
is built yet. `DATA_REHABILITATION_PROGRAM.md` cross-reference addendum added. `RESEARCH_LOG.md`
"Kiran Production Integrity Program" row updated + synced. No code written. No pipeline touched.
The old dual pipeline is still the live system. Next: owner resolves the §9 decisions, then
Phase 1 begins on authorization.

---

## 11. Cross-references

- **Full design doc:** the reviewed architecture artifact (private) — link held by the owner;
  also summarised in §3–§4 here.
- **Forensic ledger:** `docs/KIRAN_CLEANUP_AUDIT.md` §117 (decision), §33–§40 (the original
  architecture review), §39–§40 (the reliability contract this plan reworks for local).
- **Trust Register:** `docs/KIRAN_BORING_STATE_TRUST_REGISTER.md` — Amendment Log 2026-09-09
  (per-row impact); TR-01 / TR-04 / TR-06 / TR-08 / TR-16 / TR-17 (simplified by this),
  TR-05 / TR-09 / TR-11 / TR-12 (stay GREEN, get simpler), TR-19 (the CA v2 placeholder).
- **Completed operations:** `docs/MAINTENANCE_LOG.md` (DB writes, one-offs).
- **Code changes:** one PR per task — the PR description is the detailed log.
- **CA v2 substrate:** `C:\Users\Lenovo\ZH_Research_PSX\trading_edge_program\ca_pipeline_kse100_20260907\`
  — `PRODUCTION_INTEGRATION_PLAN.md`, `V2_DATA_DICTIONARY.md`, `ca_v2_reader.py`.
- **DR program:** `C:\Users\Lenovo\ZH_Research_PSX\trading_edge_program\DATA_REHABILITATION_PROGRAM.md`
  (SEQ-1 immutable-baseline item; §9.x cross-reference addendum).
