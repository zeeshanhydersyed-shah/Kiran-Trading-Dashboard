# Kiran Local-First Migration — Plan & Live Status Tracker

**This is the single document to check for what is done, ongoing, and pending on the
local-first migration.** Update §1 (the phase table) and §10 (the running log) every time a
phase or task changes state — same discipline as `MAINTENANCE_LOG.md` and the Trust Register.

- **Decision status:** approved in principle by the owner, 2026-09-09.
- **Full design:** the reviewed architecture document (artifact, private) — see §11. This file
  carries a working summary (§3–§4) so the repo is self-contained.
- **Governance:** the three-roles model and Production-Write Discipline are unchanged. Every
  production write still needs explicit owner sign-off, backup-first, dry-run, independent
  re-verification.
- **Verdict during the migration:** unchanged — **NOT VERIFIED — DO NOT TRADE** until the
  cutover gate (§6) passes and the burn-in completes.

---

## 1. STATUS AT A GLANCE

**Overall: PHASE 0 — approved, not started.** No code written. No pipeline changed. The old
dual pipeline (Task Scheduler + SQLite, GitHub Actions + Supabase) is still the live system.

| # | Phase | Status | Since | Notes |
|---|---|---|---|---|
| 0 | Decision & planning | ✅ DONE | 2026-09-09 | Design approved in principle; this tracker + the ledger/register entries written |
| 1 | Stand up the archive + execute SEQ-1 | ⬜ NOT STARTED | — | Bronze/Silver store from the current full history; immutable-baseline manifest (git + B2 object-lock); fold in the frozen DR-006 baseline + BI preservation set |
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
| `prices_archive` | Bronze + Silver — full history 2005→now (~900 MB) | Scraper (append), Silver transform | Silver build, research, DR loops | DuckDB / Parquet |
| `psx_serving` | Gold — 2-yr window + signals + grades (<200 MB) | Nightly Gold build (full replace, atomic swap) | Front end only | SQLite / DuckDB |

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
- [ ] Restore the current full history into a Bronze/Silver DuckDB + Parquet store
- [ ] Verify row counts and date spans against the live `psx_data.db`
- [ ] Build the immutable-baseline manifest (`BASELINE_MANIFEST.md` + `.sha256`), commit to git
- [ ] Push to Backblaze B2 with object-lock; set local baseline files read-only
- [ ] Fold in the frozen DR-006 baseline (`rehabilitation_baseline/…c03a393f…db`) and the BI preservation set (17 files) as backup-set members
- [ ] Wire a scheduled checksum check + extend `restore_drill_b2.py` to the widened backup set; run the drill once, PASS

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

## 9. Open owner decisions

| # | Decision | Recommendation | Resolved? |
|---|---|---|---|
| 1 | Serving engine for Gold | DuckDB across all three layers | ⬜ |
| 2 | Front end serve mechanism | Pure static files + `http.server`; add a Flask API only if a page needs parameterized queries | ⬜ |
| 3 | Fixed local pipeline schedule | Nightly Task Scheduler trigger at a set hour + catch-up-on-wake fallback | ⬜ |
| 4 | Dated-capture retention | Prune to a `psx-data-archive` repo after ~90 days | ⬜ |
| 5 | Q6 gate for v2 in the dashboard | Defer to a post-cutover follow-up, not coupled to the migration | ⬜ |
| 6 | Front end scope at cutover | Two pages (Sector Grading, Explorer); the other 13 dropped, not ported | ⬜ |
| 7 | SEQ-1 authorization | The migration executes the immutable-baseline build the DR program has had pending | ⬜ |

---

## 10. Running log (newest first)

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
