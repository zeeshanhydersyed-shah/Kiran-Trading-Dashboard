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

**Overall: PHASE 1 COMPLETE (2026-09-09 → 2026-09-10). PHASE 2 COMPLETE (2026-09-10). PHASE 3
IN PROGRESS (2026-09-10) — Tasks 3.1 (Bronze ingest) + 3.2 (Silver build) DONE + merged (PRs
#88, #89); decision D8 RESOLVED (rebuild-pure, owner); Task 3.3 (Gold) IN PROGRESS.** The
immutable baseline is built,
verified, git-manifested, copied off-site under B2 COMPLIANCE Object-Lock, and a restore drill
proves it comes back. Phase 2's parallel capture path (`scrape_capture.yml` +
`archive/scrape_capture.py`) is merged (PR #85, `b943ddf`) and proven live. Phase 3: the
**DuckDB engine blocker is gone** — `duckdb 1.5.5` installs + runs on this machine's Python
3.14, so §9 D1 ("DuckDB across all three layers") is executable (`requirements-archive.txt`
updated). **Task 3.1 done:** `archive/bronze_ingest.py` seeds the live Bronze store
(`D:\KIRAN_ARCHIVE\prices_archive\bronze\`) from the frozen `bronze/` once, then appends the
`data-captures` capture files one trading day at a time — append-only, deduped, gap-detecting,
each consumed file logged with its SHA-256; re-run is byte-identical. First real run ingested
`2026-09-09` (489 stock + 5 index rows; capture sha256 `e6115b80…5338`); `archive_manifest
verify` stays PASS (the live trees are excluded from the baseline walk). Design note:
`docs/KIRAN_LOCAL_FIRST_ARCHIVE/MEDALLION.md`. **Task 3.2 done:** `archive/silver_build.py`
rebuilds the Silver layer from Bronze on DuckDB — `silver/prices_adjusted/` (port of
`apply_price_adjustments.py`'s CA-adjustment + circuit flags), `silver/sectors/`,
`silver/stock_metadata/` (port of `build_stock_metadata.py`'s idempotent upsert); `ca_v2_reader`
wired behind `--ca-source v2`, **off by default**. Deterministic re-run. Parity vs the frozen
store: exact row coverage, **one known OHLC residual — symbol DLL** (a ~10:1 split adjusted via
the Data Health page with no recoverable event record; DR-program provenance gap, not a build
bug) + 18 circuit-flag rows on 4 illiquid names. **Decision D8 RESOLVED (2026-09-10, owner):
rebuild-pure** — the parity residual is the DR program's to-do list of events still owed an
event record; no `silver_build.py` change. **Task 3.3 (Gold) IN PROGRESS.**
**The old dual pipeline (Task Scheduler + SQLite, GitHub Actions + Supabase) is
still the live system and is untouched** — nothing in Phase 1, 2 or 3 wrote to `psx_data.db`,
Supabase, or `daily_scraper.yml` (D7: preservation only; live hash `6a3b974d…425b` unchanged).

| # | Phase | Status | Since | Notes |
|---|---|---|---|---|
| 0 | Decision & planning | ✅ DONE | 2026-09-09 | Design approved in principle; tracker + ledger/register entries written; **all 7 §9 decisions resolved by the owner 2026-09-09** |
| 1 | Stand up the archive + execute SEQ-1 | ✅ DONE | 2026-09-10 | Archive root `D:\KIRAN_ARCHIVE\` (C: space-constrained), 92 baseline payload files, local read-only. Whole-DB baseline via SQLite Online Backup API — `psx_data_baseline_KIRAN_LFM_P1_20260909_222210.db`, 882,896,896 b, **SHA-256 `9418cb1bf98c197550e02eae663f0ab870ccc93c967dfb743c221cd3d5f70d61`**, self-contained (`journal_mode=DELETE`), `integrity_check` ok, 53/53 table counts + all substrate date spans match live; Bronze/Silver Parquet store (`SUM(volume)` reconciles exactly); DR-006 baseline (`c03a393f…`) + BI 17-file set folded into `backup_set/` + hash-verified; `BASELINE_MANIFEST.{md,sha256}` (92 files, 1,898,646,386 b) git-committed, `archive_manifest verify` PASS. **Off-site:** all 92 files in B2 `kiran-psx-archive` under **COMPLIANCE Object-Lock, 3000 days** (undeletable — verified `AccessDenied` on a locked version); big SQLite files zstd'd (~33%) for the slow uplink; `offsite_push` resumable at the 16 MB part level. `offsite_push --verify` PASS; `restore_drill_archive` PASS (baseline restored + `integrity_check` ok + 1,761,371 price rows). `restore_drill_b2.py` now runs both drills. `archive_checksum_check` for Task Scheduler. PRs #81 / #82 / #83. **NOTE:** `duckdb` has no cp314 wheel (Python 3.14) — the Parquet store is engine-neutral; the DuckDB attach layer is a Phase 3 item. The over-broad B2 key is moot (COMPLIANCE can't be bypassed); a minimal key is optional later hygiene. |
| 2 | Rework the scrape (GitHub Actions) | ✅ DONE | 2026-09-10 | `.github/workflows/scrape_capture.yml` + `archive/scrape_capture.py`, merged PR #85 (`b943ddf`). Reuses `scraper.py`'s fetch/parse; writes immutable `data/incoming/YYYY-MM-DD.parquet` (schema + file-level metadata: Actions run ID, `code_version`, `scraper_sha256`, self-reported counts, TR-14 per-sector completeness) + refreshes `latest.parquet`. Two side-by-side checkouts — `main` (code) + `data-captures` (commit target). **Commits to the dedicated `data-captures` orphan branch, not `main`** (`main` is branch-protected; owner decision 2026-09-10). Idempotent (`exists`/`nodata`/`unreachable` = no-op, exit 0). 12 unit tests, suite 449. **Proven live 2026-09-10:** run `34453459820` scraped PSX 2026-09-09 (489 stocks / 5 indices / 36 sectors, coverage COMPLETE 626/626) and committed `data/incoming/2026-09-09.parquet` + `latest.parquet` (494 rows, 18,922 b, sha256 `e6115b80…5338` = commit message) as `kiran-scrape-capture[bot]` → `data-captures` `dd269cc`; independent `--single-branch` clone hash-matched. Run `34453569404` = clean `exists` no-op, no new commit. `daily_scraper.yml` byte-unchanged (last touched `a7c0ce6`, 9 days prior), still scheduled. Format doc: `docs/KIRAN_LOCAL_FIRST_ARCHIVE/CAPTURE_FILES.md` |
| 3 | Build the Medallion transforms | 🔵 IN PROGRESS | 2026-09-10 | **3.1 Bronze ingest DONE** — `archive/bronze_ingest.py` + 6 tests; live store `prices_archive/bronze/` seeded from frozen `bronze/`, `2026-09-09` ingested; append-only / deduped / gap-report / SHA-256 lineage; re-run byte-identical. `archive_manifest.py` excludes the live trees (`verify` PASS). DuckDB confirmed on Py3.14 (`duckdb>=1.5`). **3.2 Silver build DONE** — `archive/silver_build.py` + 7 tests; DuckDB rebuild from Bronze → `silver/prices_adjusted/` (CA-adjust port of `apply_price_adjustments.py` + circuit flags), `silver/sectors/`, `silver/stock_metadata/` (upsert port of `build_stock_metadata.py`); `ca_v2_reader` wired behind `--ca-source v2`, default `legacy`; deterministic; `_silver_parity.json` vs frozen = exact rows, residual **DLL** (unrecoverable Data Health split) + 18 flag rows / 4 illiquid names. **D8 RESOLVED (owner, 2026-09-10): rebuild-pure** — residual = DR-program to-do, no code change. Design: `docs/KIRAN_LOCAL_FIRST_ARCHIVE/MEDALLION.md`. **3.3 Gold IN PROGRESS.** |
| 4 | Publication contract + atomic swap | ⬜ NOT STARTED | — | Four gates into the Gold build; `current_publication` with the full lineage block; staging-DB build + rename |
| 5 | Shadow run | ⬜ NOT STARTED | — | Nightly local Gold vs current Supabase output, ≥10 trading sessions, diffs investigated |
| 6 | Cutover | ⬜ NOT STARTED | — | Front end → Gold JSON; retire `daily_scraper.yml` / Supabase / Streamlit Cloud; delete the `_pg` path, `database_pg.py`, the stale `main.py` copies; snapshot + pin for the DR program |
| 7 | Burn-in | ⬜ NOT STARTED | — | 2 weeks of daily local operation, watchdog live, backup + restore drill running |
| 8 | Retire the write surface | ⬜ NOT STARTED | — | Final sweep for any script that can write outside the pipeline |
| — | Front end (2 pages) | ⬜ NOT STARTED | — | Built in parallel from Phase 2 onward — Sector Grading + Explorer; see §5 (not started this session — Phase 2 was scoped to the capture path only) |
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
one per date) + refreshes `latest.parquet` **to the dedicated `data-captures` orphan branch**
(not `main` — Phase 2, owner decision 2026-09-10) → local pipeline `git pull origin data-captures`
→ append to Bronze (deduped, gap-detecting) → Silver (CA-adjust, conform, indicators) → Gold (2-yr slice,
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
| **Q7 — `latest.parquet` overwrite** | Fixed: GitHub Actions commits one immutable `YYYY-MM-DD.parquet` per scrape date (the audit record) plus a freely-overwritten `latest.parquet` pointer, to the `data-captures` branch (Phase 2). Gives contemporaneous capture — the evidence standard the DR program found missing for 2005–2019. |

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
- [x] New GitHub Actions workflow: fetch → commit `data/incoming/YYYY-MM-DD.parquet` + refresh `latest.parquet` — `.github/workflows/scrape_capture.yml` + `archive/scrape_capture.py`, merged PR #85 (`b943ddf`). Reuses `scraper.py`; commits to the dedicated `data-captures` orphan branch (created 2026-09-10); idempotent; 12 unit tests, suite 449; two live workflow runs (one `written`, one `exists`)
- [x] Commit message carries the Actions run ID + self-reported row/sector counts — verified on `data-captures` `dd269cc`: subject `PSX 2026-09-09 -- 489 stocks, 5 indices, 36 sectors, coverage COMPLETE`, body carries the Actions run URL + attempt + `capture sha256`; the same facts are also embedded as Parquet file-level metadata
- [x] Old `daily_scraper.yml` confirmed still running in parallel (not touched) — byte-identical `86cdfb9..b943ddf` (empty diff); last touched `a7c0ce6` (9 days prior); still an active workflow on its 5-slot schedule
- [x] First dated capture file observed on `data-captures`, hash-verified — workflow run `34453459820` committed `data/incoming/2026-09-09.parquet` (494 rows). An independent `git clone --branch data-captures --single-branch` gave sha256 `e6115b809240381f2ebcef3c622dcc42c95d0b29184949206ca5c6b2add25338`, matching the value in the commit message. `latest.parquet` byte-identical.

### Phase 3 — Medallion transforms
- [x] Bronze ingest: append-only, deduped, gap-detecting, records which dated files it consumed + hashes — `archive/bronze_ingest.py`, 2026-09-10. Live store `prices_archive/bronze/` seeded from frozen `bronze/`; `2026-09-09` capture ingested (489+5 rows); `_bronze_ingest_log.jsonl` records each capture file + SHA-256; re-run byte-identical + no log growth; gap report `_bronze_gaps.json`. 6 tests. `archive_manifest` excludes the live trees (`verify` PASS). `duckdb>=1.5` enabled (runs on Py3.14). Design: `docs/KIRAN_LOCAL_FIRST_ARCHIVE/MEDALLION.md`
- [x] Silver: port the corporate-action adjustment + universe-conforming logic; wire `ca_v2_reader` as an *available* source, **gate off** (dashboard still on the current path) — `archive/silver_build.py`, 2026-09-10. DuckDB full rebuild from Bronze → `prices_archive/silver/{prices_adjusted,sectors,stock_metadata}/`. CA-adjust = faithful port of `apply_price_adjustments.py` (per-event `ROUND(_,4)`, compounding), events from the CSV auto-confirm cats + the frozen baseline's CONFIRMED suspects (read-only). Circuit flags via `compute_circuit_flags`. Universe = port of `build_stock_metadata.py`'s idempotent upsert (frozen rows preserved). `ca_v2_reader` behind `--ca-source v2` / `KIRAN_SILVER_CA_SOURCE`, default `legacy`, hard-fails on a missing reader (no silent fallback). Deterministic (byte-identical re-run). `_silver_parity.json`: 0 only-frozen / 0 only-new, OHLC residual = **DLL only** (3,576 rows — a Data Health `rebuild_symbol_adjusted` split with no recoverable event record; DR §116 provenance gap) + 18 circuit-flag rows / 4 illiquid names. 7 tests. Merged PR #89 (`66532b4`). **D8 RESOLVED (owner, 2026-09-10): rebuild-pure** — the residual is the DR program's list of events still owed a record; no `silver_build.py` change.
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

### D8 — Silver `prices_adjusted`: rebuild-pure vs. carry the frozen delta forward — RESOLVED 2026-09-10

**Owner decision (2026-09-10): (a) rebuild-pure.** Silver only reflects corporate-action
adjustments that have a reproducible event record (the CSV auto-confirm rows + the frozen
baseline's `CONFIRMED` suspects). DLL-class events — a `rebuild_symbol_adjusted` correction
made via the Data Health page that left no recoverable event — are the **DR program's** job to
resolve upstream (add a real `CONFIRMED` suspect row / CSV entry with the factor), after which
the next Silver rebuild picks them up automatically. `silver_build.py` already implements (a);
no code change. The frozen `silver/prices_adjusted` remains available as the seed for anything
that needs the as-shipped adjustment. The `_silver_parity.json` residual (currently: DLL, 3,576
rows) is the standing list of events the DR program still owes an event record for — it should
trend to zero, not be papered over.

*Background:* Task 3.2's Silver build reproduces the frozen `silver/prices_adjusted` exactly on
row coverage; the only OHLC residual was symbol **DLL** (~10.3:1 split on 2026-06-05, adjusted
in the frozen store via the Data Health page with no event record) + 18 circuit-flag rows on 4
illiquid names.

---

## 10. Running log (newest first)

### 2026-09-10 — Decision D8 resolved (rebuild-pure); Task 3.3 (Gold) started
Owner: "go with rebuild-pure and start Task 3.3." D8 recorded in §9 — Silver stays
rebuild-from-events; the `_silver_parity.json` residual (DLL + 4 illiquid names) is the DR
program's backlog of corporate actions still owed a reproducible event record, tracked there,
not worked around in `silver_build.py`. No code change. Doc-only commit.

Task 3.3 (Gold) now IN PROGRESS — see the next entry once the approach is set.

### 2026-09-10 — Phase 3 Task 3.2: Silver build done
Same session as 3.1, continuing "as far as you get, strictly under the plan".

**Built — `archive/silver_build.py` + `tests/test_silver_build.py` (7 tests):**
- Full deterministic rebuild from the live Bronze store every run (Silver is disposable, §3):
  `prices_archive/silver/prices_adjusted/` + `sectors/` + `stock_metadata/`.
- **CA adjustment** — a faithful port of `apply_price_adjustments.py`: copy Bronze `prices` into
  a DuckDB table, then per confirmed event apply `close_after/close_before` to the symbol's
  pre-ex-date OHLC with `ROUND(_,4)` **per event**, events oldest→newest so they compound.
  Event set = the DROP_50/33/25 auto-confirm rows in `corporate_action_suspects_clean.csv`
  (613) + the `CONFIRMED` rows in the **frozen baseline `.db`** (1: MTL). The live `psx_data.db`
  is opened **read-only** (`mode=ro&immutable=1`) for that one read, never for write — asserted
  by a test (`sqlite3.connect` appears exactly once, always with the ro URI).
- **Circuit flags** — `hit_circuit_up/down/thin_trading_flag` via
  `apply_price_adjustments.compute_circuit_flags` (the confirmed producer formula), computed on
  the adjusted series. Non-equity symbols (`config.is_non_equity_symbol`) dropped from Silver
  `prices_adjusted` (Bronze keeps them raw).
- **Universe conforming** — `sectors` = frozen `sectors` minus non-equity. `stock_metadata` = a
  port of `build_stock_metadata.py`'s **idempotent UPSERT** semantics: every frozen row kept
  (manual/legacy/now-excluded never deleted), source-derived columns (sector, in_kse100,
  listing_date) refreshed for the recomputed include-set (`EXCLUDED_SECTORS` /
  `SECTOR_OVERRIDES` / `UNIVERSE_WHITELIST`), `is_active`/`delisting_date`/`notes` left as
  frozen. Row count matches the frozen 468 (an earlier draft that only wrote the include-set
  gave 319 — fixed).
- **CA source gate** — `--ca-source` / `KIRAN_SILVER_CA_SOURCE`, default `legacy`. `v2` imports
  `ca_v2_reader` from the CA-pipeline dir and overwrites `close` with its `close_tr` total-return
  series for the symbols/dates it covers. **Off by default; the dashboard reads none of this
  store.** A missing `ca_v2_reader.py` → hard `SystemExit`, never a silent fallback (tested).
- **Determinism** — a re-run rewrites 24 byte-identical Parquet files (tested).
- **Engine** — DuckDB does the copy + per-event `UPDATE`; pandas runs the circuit-flag formula;
  pyarrow serializes with the standard options + `ORDER BY (symbol,date)`.
- `_silver_build_log.jsonl` (append-only provenance) + `_silver_parity.json` (rewritten each
  run).

**Parity vs the frozen `silver/prices_adjusted` (overlap through 2026-09-08):**
- Row coverage **exact** — 1,761,371 rows, 0 only-frozen, 0 only-new.
- **OHLC residual: 3,576 rows, all `DLL`.** DLL split ~10.3:1 on 2026-06-05 (raw 624.83 →
  60.43); the frozen store applied factor 0.0967 to every pre-2026-06-08 DLL row via the Data
  Health page, and that `rebuild_symbol_adjusted` correction left **no event record** in the
  baseline or the CSV. A rebuild-from-events cannot reproduce it — the DR program's documented
  provenance gap (§116 / `Known_Limitations.md`), not a build bug. → **new §9 open decision D8**
  (rebuild-pure vs. carry-forward) — flagged, not decided.
- Circuit-flag residual: 18 rows across DWAE/GAMON/MWMP/GEMBCEM — full-history recompute vs. the
  frozen incremental at a trading-gap boundary. Sub-0.001 %.

**Not touched:** `psx_data.db` (read-only baseline read only), Supabase, `daily_scraper.yml`,
the dashboard. `archive_manifest verify` still PASS (92 files; the live trees stay excluded).
Full local suite: green.

**Next:** Task 3.3 — `archive/gold_build.py` (2-yr slice, every screener, sector grades →
`psx_serving/` DuckDB + JSON, staging + atomic swap, signal parity vs the live pipeline).
**Not started.**

### 2026-09-10 — Phase 3 STARTED: Task 3.1 Bronze ingest done
Owner said "Start Phase 3", "strictly under the plan", and to work through 3.1 / 3.2 / 3.3 as
far as it goes. Capture-clone location `D:\KIRAN_ARCHIVE\data-captures\` approved.

**DuckDB blocker cleared.** The tracker / memory / `requirements-archive.txt` all carried a
"no cp314 wheel" note that made §9 D1 (DuckDB engine) unexecutable on this Python 3.14 machine.
Checked directly: `duckdb 1.5.5` installs + runs clean. `requirements-archive.txt` now pins
`duckdb>=1.5`. Bronze ingest itself is a columnar append with no joins → pure pyarrow (the
`build_store.py` precedent); DuckDB enters at Silver (3.2). Recorded in the new design note
`docs/KIRAN_LOCAL_FIRST_ARCHIVE/MEDALLION.md` (store layout: frozen seed vs. live store; the
engine split; the 3.1/3.2/3.3 contracts).

**Built — `archive/bronze_ingest.py` + `tests/test_bronze_ingest.py` (6 tests):**
- **Live store** = a new tree `D:\KIRAN_ARCHIVE\prices_archive\bronze\` (Bronze), separate from
  the frozen Phase-1 `bronze/` (which stays immutable + manifested + Object-Locked). Seeded
  once as a byte copy of the frozen tree (read-only bit cleared on the copy), then only grows.
- **Ingest:** `git pull --ff-only` the `data-captures` clone (skippable `--no-pull`), read each
  `data/incoming/YYYY-MM-DD.parquet` (never `latest.parquet`), assert its `trading_date` ==
  `source_date`, split `record_type` → `prices` / `index_prices`, append into the `year=YYYY`
  partitions with the exact `build_store.py` sort + Parquet options. A date already present is
  **skipped, never overwritten** (append-only / D7).
- **Lineage:** one JSONL line per ingested file in `prices_archive/_bronze_ingest_log.jsonl` —
  timestamp, `capture_file`, `capture_sha256`, `source_date`, capture `code_version`, rows
  added, years touched. Plus a one-time `seed` entry carrying the frozen `STORE_MANIFEST.json`
  hash and the seed's max date.
- **Gap detection:** report-only. Weekdays after the frozen seed's max date with no Bronze row
  → `missing_capture` / `nodata_or_holiday`, written to `prices_archive/_bronze_gaps.json` and
  printed. No PSX holiday calendar exists in-repo, so a `missing_capture` weekday is surfaced
  for human review, never auto-resolved and never fails the run.
- **Idempotency:** a re-run with no new capture files does zero file writes + zero log appends
  and leaves every Parquet file byte-identical (tested).
- **Safety:** the module never opens `psx_data.db` (not even read-only), Supabase, or
  `daily_scraper.yml` — asserted by a test. It is a pure function of (frozen seed + captures).

**`archive/archive_manifest.py`:** added `EXCLUDE_TOPLEVEL = {data-captures, prices_archive,
psx_serving}` so the baseline `verify` walk ignores the live Medallion trees. Without this the
`data-captures` clone (owner-approved location) alone would have made `verify` report ~3
UNTRACKED files and the scheduled `KIRAN_Archive_Checksum` job would alert. Manifest content
unchanged (92 files); `verify` = **PASS** after the change.

**First real run:** `python -m archive.bronze_ingest --no-pull` → seeded (5,360 price dates,
seed max `2026-09-08`), then ingested `2026-09-09` (489 stock + 5 index rows). Capture sha256
`e6115b809240381f2ebcef3c622dcc42c95d0b29184949206ca5c6b2add25338` — matches the value the
Phase 2 run recorded. Re-run → `up_to_date`, `2026-09-09` skipped, no writes. `psx_data.db`
untouched. Full local suite: green (was 449 → +6).

**Next:** Task 3.2 — `archive/silver_build.py` (port `apply_price_adjustments.py` CA adjustment
+ universe-conforming onto Bronze via DuckDB; `ca_v2_reader` wired as available-but-gated-OFF).
**Not started this entry.**

### 2026-09-10 — Phase 2 COMPLETE: parallel scrape-capture path merged + proven live
Owner said "start Phase 2" and approved the 5-point approach. During the build we found `main`
now carries branch protection (`enforce_admins: true`, `strict: true`, 3 required checks:
`Clean install on Python 3.11` / `Unit tests` / `App boot smoke test`) — so the original "commit
to `main` with `[skip ci]`" cannot work (a checkless commit produces none of the required
checks; `enforce_admins` blocks even an admin/bot push). **Owner decision 2026-09-10: use a
dedicated `data-captures` orphan branch.** CLAUDE.md's stale "no branch protection yet" note
was corrected in the same PR.

Built:
- **`archive/scrape_capture.py`** — reuses `scraper.py`'s `get_source_date` / `scrape_date` /
  `parse_sector_counts`. Writes `data/incoming/YYYY-MM-DD.parquet` (schema:
  `record_type, symbol, trading_date, open, high, low, close, volume, sector`; rows sorted
  deterministically) with file-level metadata: `source_date`, `scraped_at_utc`, `source_url`,
  Actions run id/url/attempt, `code_version`, `scraper_sha256`, self-reported counts, and the
  TR-14 per-sector completeness (`expected_total` / `parsed_total` / `coverage_status`).
  Refreshes `latest.parquet` only when the captured date is the newest (a `--date` backfill of
  an older gap never regresses it). Idempotent — outcomes `written` / `exists` / `nodata` /
  `unreachable`, all exit 0 (a missed capture is a detectable gap, matching `daily_scraper.yml`'s
  redundant-attempts design). Branch-agnostic — only writes into `--out-dir`. Never opens
  `psx_data.db`.
- **`data-captures` orphan branch** — created 2026-09-10 (`git checkout --orphan`), no shared
  history with `main`, README-only init commit (`bbda122`), pushed. Holds only
  `data/incoming/*.parquet` + a README. **Recommended (owner, later): protect it against
  force-push + deletion.**
- **`.github/workflows/scrape_capture.yml`** — 5 cron slots mirroring `daily_scraper.yml` +
  `workflow_dispatch` (optional `date` input for backfill). Two side-by-side checkouts: `main`
  → `code/` (scraper code), `data-captures` → `captures/` (commit target). Runs the script with
  `--out-dir captures/data/incoming`, then commits + pushes from the `captures/` checkout.
  `concurrency` group, `contents: write`, pull-rebase-retry (5×). Commit message carries the run
  ID + self-reported counts + capture sha256. `ci.yml` triggers on `main`/`staging` only, so the
  `data-captures` commits run no CI; `daily_scraper.yml` is never triggered by a push.
- **`docs/KIRAN_LOCAL_FIRST_ARCHIVE/CAPTURE_FILES.md`** (format + the `data-captures` rationale),
  `.gitignore` (`data/incoming/*.parquet` — keep local test runs off code branches),
  `archive/__init__.py` + `archive/README.md` notes.
- **`tests/test_scrape_capture.py`** — 12 tests (schema, row content, embedded metadata,
  idempotency, `--force` data-stability, nodata/unreachable, `latest.parquet` tracking + no
  backfill regression, INCOMPLETE coverage, `$GITHUB_OUTPUT` emission, no `psx_data.db` touch).

**`data-captures` branch protection (owner, 2026-09-10):** a rule for pattern `data-captures`
with *allow force pushes* + *allow deletions* checked, nothing else — no required checks/reviews,
no push restrictions, `enforce_admins` off. Permissive enough for the workflow's `GITHUB_TOKEN`
(`contents: write`) to push directly. (A stricter rule blocking force-push/deletion would suit
the "immutable record" intent, but the workflow only ever fast-forwards — fine to start.)

**Merge friction (one-time).** `pull_request` CI does **not** auto-fire for a PR that adds a
file under `.github/workflows/` (GitHub's workflow-injection guard — proven with throwaway probe
PR #86: an identical PR touching no workflow file got CI in seconds; #85 got none across 3
commits). Also `push`-CI didn't fire on the squash-merge commit `b943ddf` for the same reason.
Worked around: `ci.yml` dispatched manually — green on the merged tree (`0f3faf9` as a PR run at
08:02, and `b943ddf` on `main` by dispatch). The owner unchecked *Include administrators* on the
`main` rule to merge (**⚠ still off as of this entry — owner to re-check it**). Future edits to
`scrape_capture.yml` itself will hit the same guard; routine capture runs never touch a workflow
file, so day-to-day is unaffected.

**Merged + proven live 2026-09-10:**
- PR #85 squash-merged → `main` `b943ddf`.
- `gh workflow run scrape_capture.yml` (run `34453459820`, 38 s, success). It checked out `main`
  (code) + `data-captures` (target), scraped ksestocks for source date **2026-09-09**, and
  committed `data/incoming/2026-09-09.parquet` + `latest.parquet` to `data-captures` as
  `kiran-scrape-capture[bot]` (`dd269cc`). Commit subject: `PSX 2026-09-09 -- 489 stocks, 5
  indices, 36 sectors, coverage COMPLETE`; body carries the run URL + attempt + `capture
  sha256`.
- **Hash-verified independently:** `git clone --branch data-captures --single-branch` → file
  sha256 `e6115b809240381f2ebcef3c622dcc42c95d0b29184949206ca5c6b2add25338`, matches the commit
  message; 494 rows (489 stock + 5 index), 18,922 b; metadata carries `actions_run_id`,
  `code_version=b943ddf`, `scraper_sha256`, `expected_total=626`/`parsed_total=626`.
- **Idempotent:** a second `gh workflow run` (run `34453569404`) → outcome `exists`, the commit
  step skipped, `data-captures` still at `dd269cc`.
- `daily_scraper.yml` byte-identical `86cdfb9..b943ddf`; still an active workflow on its schedule.

**Not done:** the front-end build (parallel track from Phase 2) — not started; this work was
scoped to the capture path. Owner to re-enable *Include administrators* on `main`. **Phase 3
(Medallion transforms) begins only on an explicit "start Phase 3".**

### 2026-09-10 (earlier) — Phase 1 COMPLETE: off-site Object-Lock copy + restore drill
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
