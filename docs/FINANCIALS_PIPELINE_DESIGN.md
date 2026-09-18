# Financials/Announcements Pipeline — Design Doc

**Status: CODE BUILT 2026-09-18, `backfill` mode run and verified against the real
906-symbol (actual count: 904 `.html` files) corpus. `daily` mode's live-fetch path is
implemented but has not made a real network request yet. No Task Scheduler entry
created — nothing automated yet.**
This document covers schema, parsing design, and staging/build mechanics for a new,
standalone pipeline that ingests PSX corporate-announcement data (financial results,
dividends/bonus, AGM/book-closure dates) from the ksestocks.com scrape into the
local-first architecture. §12 (bottom) records what actually got built vs. this design,
including two deliberate implementation-time refinements.

## 0. Code

- `archive/financials_parser.py` — pure HTML→record parsing (Section 6 below)
- `archive/financials_pipeline.py` — Bronze/Silver/Gold orchestration, `backfill`/`daily`
  modes, CLI (Sections 4/7 below)
- `tests/test_financials_parser.py` — 17 tests, each keyed to a real confirmed edge
  case from Section 3.1 (dual-basis rows, the HBL same-date split, the misspelling, the
  thousands-separator bug, the combined book-closure line, the no-flag dividend)
- `tests/test_financials_pipeline.py` — 11 tests: build correctness, idempotent re-run,
  incremental-only-changed-symbols, decoupling from the main pipeline, crash-safety of
  the promote checkpoint, daily-mode fetch injection + failure handling, typed
  corporate_actions conformance

All 28 new tests pass. Real-corpus verification (`--mode backfill` against the actual
cache, not a synthetic fixture): 904 symbols processed, 45,812 `stock_announcements`
rows extracted, confidence mix 42,898 HIGH / 2,802 MEDIUM / 112 LOW, 139 symbols
produced zero rows (spot-checked: genuinely empty `<tr class="data-tr">` pages, mostly
preference-share/TFC codes, not a parsing failure), 0 fetch failures (backfill mode
reads local files, no network). A second consecutive run correctly detected zero
changes (Bronze content-hash idempotency confirmed on real data, not just the
synthetic test fixture).

---

## 1. Scope and non-goals

**In scope:** parse the 906 cached per-symbol HTML pages at
`ZH_Research_PSX\trading_edge_program\ca_pipeline_kse100_20260907\announcements_cache\`
into structured, typed tables covering: EPS (consolidated/unconsolidated), Profit
Before/After Tax (consolidated/unconsolidated), cash dividend %, bonus %, AGM date, book
closure from/to, fiscal period ended. This is a **historical, static-snapshot ingestion**
of data already fully scraped — no new scraping happens here.

**Updated 2026-09-18, owner direction:** this now covers TWO operating modes, not one —
(1) the one-time historical backfill of the existing 906-file cache described in v1 of
this doc, and (2) an **ongoing daily re-scrape/re-ingest cycle during active reporting
periods**, full 906-symbol sweep every cycle, to catch new quarterly announcements as
PSX companies file them. §4.4 covers the new cadence/storage model; §6.0 covers reuse
of the existing fetch script. Target use: a general-purpose fundamentals layer for
future valuation models, screeners, and research — not built for one specific consumer,
so the schema stays general (§5 unchanged for this reason).

**Out of scope / explicitly deferred, not decided in this doc:**
- Whether/how this data ever reaches the dashboard front end (`export_json.py`,
  `web/*.html`) — not addressed here, per the "Keep it manual" precedent this stays a
  standalone, manually-invoked/scheduled pipeline until a separate explicit go-ahead.
- Rights-issue percentage/price — already fully covered by the existing
  `full_ca_ledger.sqlite`, reused as-is here (see §3.2), not re-derived.
- A formal valuation model or screener built on top of this data — this doc builds the
  fundamentals layer only, per the owner's stated "core fundamental layer for future
  ... studies" framing; what gets built on top is a separate, later decision.

## 2. Zero scope-contamination — explicit guarantee

Modeled directly on the existing `archive/ca_v2_prototype.py` precedent (the established
pattern in this codebase for "parallel, additive, read-only" work):

- **New module**, e.g. `archive/financials_pipeline.py` — does not import, call, or modify
  `bronze_ingest.py`, `silver_build.py`, or `gold_build.py`.
- **New, separate store root**: `D:\KIRAN_ARCHIVE\financials_archive\` — never opens
  `psx_serving.duckdb`, Bronze, Silver, `psx_data.db`, Supabase, or `shadow_diff.duckdb`.
- **Source data read-only**: the HTML cache and `full_ca_ledger.sqlite` are opened
  read-only (`mode=ro` URI for SQLite, plain file reads for HTML) from their existing
  location in `ZH_Research_PSX\...\ca_pipeline_kse100_20260907\` — nothing in that
  directory is written to.
- **Not wired into anything automated *in the existing pipeline***: not called from
  `nightly_run.py`, not added to `shadow_diff.py`'s `EVERY_SESSION` table list
  (`market_regime`/`stock_signals`/`sector_signals`/`boring_signals`/`setup_log` stay
  exactly as they are), not added to `export_json.py`.
- **Its own, separate Task Scheduler entry** for the daily cadence (§4.4) —
  e.g. `KIRAN_Financials_Pipeline` — never appended to `KIRAN_Nightly_Pipeline`'s task or
  trigger. A failure, delay, or even a full removal of this new task has zero effect on
  the existing nightly run's timing or reliability, and vice versa.
- **A different upstream endpoint** than the existing daily price scraper: this hits
  `ksestocks.com/Announcements` (via the reused `l0_fetch_announcements.py`/`common.py`
  machinery), while `scraper.py`'s daily price scrape hits `ksestocks.com/MarketSummary`
  on its own separate schedule (GitHub Actions, not this machine). No shared session,
  no shared rate-limit budget, no risk of one scrape's traffic affecting the other's.

Because shadow-diff only ever queries those five named tables from Gold and from live
Postgres, and this pipeline creates entirely different tables in an entirely different
DuckDB file, there is no mechanism by which this work can affect the Phase 5c streak.

## 3. Source data audit (verified against real cached files, not assumed)

### 3.1 Raw HTML shape

Each `{SYMBOL}.html` has one `<tr class="data-tr">` per announcement, 3 cells: Company,
Date, Announcements (free-text with `<br />` separators, field order **not fixed** —
confirmed a row where `BOOK CLOSURE TO` appears before `BOOK CLOSURE FROM`). A single
`<tr>` is the natural grain of one record.

Confirmed real examples driving the design below:

- **OGDC, 2025-09-23** — one row carries both bases for PBT/PAT/EPS plus dividend, AGM,
  and book closure all together:
  `(UNCONSOLIDATED) PROFIT/LOSS BEFORE TAXATION RS. IN MILLION 279,314.861` /
  `(CONSOLIDATED) EPS = 39.50` / `DIVIDEND = 50%(F)` /
  `ANNUAL GENERAL MEETING WILL BE HELD ON 27/10/2025` /
  `BOOK CLOSURE FROM 23/10/2025` / `BOOK CLOSURE TO 27/10/2025`.
- **HBL, 2008-02-14** — the *same* announce date split across **two separate `<tr>`
  rows**, one labeled `(CONSOLIDATED)`-style, the other using a *different* phrasing
  (`UNCONSOLIDATED P/L AFTER TAX RS. IN MIL`, `EPS = 11.65` with **no basis label on the
  EPS token itself** — basis only inferable from the row's other tokens). Also contains a
  data-entry error: `8.041.416` (period used as a thousands separator, would silently
  corrupt a naive float-cast after comma-stripping).
- **FFC** — `(UNCONSLIDATED)` — a real misspelling (missing "O") found in the live
  corpus — and a row where `(CONSOLIDATED)` PBT/PAT are present but the consolidated EPS
  token is simply absent from that row.
- **AABS, 2005-01-09** — `DIVIDEND FOR THE YEAR ENDED 30/09/2004 35%` and
  `BOOK CLOSURE FROM 13/01/2005 TO 20/01/2005` — an older narrative phrasing where the
  book-closure from/to dates appear **combined on one line**, not the more common
  split `BOOK CLOSURE FROM D1<br/>BOOK CLOSURE TO D2` form. Neither existing parser in
  this codebase handles this combined form (confirmed by reading both).

### 3.2 What already exists vs what's genuinely new

| Data | Already exists? | Where |
|---|---|---|
| Corporate actions (bonus/rights/cash dividend %, book closure, price-factor, CONFIRMED/PROBABLE/AMBIGUOUS classification with 60-day dedup) | ✅ Yes, full-universe, already reconciled | `full_ca_ledger.sqlite` → `ca_ledger` table, 7,416 rows, 906 symbols, 2005–2026 |
| AGM date | ❌ No | not extracted by any existing script |
| EPS (consolidated/unconsolidated) | ⚠ Partial | proven regex exists (`phase_4b_eps_payout_extraction.py`) but only ever run for 26 symbols, and it **drops any row without both a dividend % and an EPS** — would silently lose most pure-earnings rows |
| PBT / PAT (either basis) | ❌ No | not extracted anywhere |
| Fiscal period ended | ❌ No | not extracted anywhere |

**Design decision:** don't re-derive the corporate-action reconciliation logic (dedup,
price-matching, CONFIRMED/PROBABLE/AMBIGUOUS) — that's already solved, tested against
real price data, and battle-hardened against edge cases (e.g. the TSBL 150% rights
mismatch). Reuse `full_ca_ledger.sqlite` as-is for that domain. Build **one new**
extractor for the genuinely-missing fields (EPS/PBT/PAT/AGM/fiscal-period), at true
per-`<tr>` grain, that does **not** drop rows the way `phase_4b`'s does.

## 4. Layer design

```
Fetch   →  (daily, every day, no season gate) l0_fetch_announcements.py-style POST per
           symbol, 906-symbol sweep, overwrites announcements_cache/{SYM}.html
Bronze  →  content-hash-triggered immutable dated capture: a symbol's fetched HTML
           is stored as a new dated artifact ONLY when its content actually changed
           since the last capture -- most daily fetches produce no new Bronze row
Silver  →  stock_announcements   (NEW parser, per-<tr> grain, INCREMENTAL append)
           corporate_actions     (typed conformance of full_ca_ledger.sqlite, as-is,
                                  re-loaded whenever the source ledger's own hash changes)
Gold    →  financials_serving.duckdb -- atomic-promote copy of both Silver tables,
           no publish() gate (see §4.3 for why)
```

The one-time historical backfill (v1 of this doc) and the ongoing daily cycle (this
revision) share every layer below — backfill is just "first run of the same pipeline,"
not a separate code path.

### 4.1 Bronze — real dated captures, change-triggered (revised from v1)

v1 of this doc proposed a manifest-only Bronze (no copy) on the premise that the cache
was a frozen, one-time snapshot. With a recurring daily fetch that premise no longer
holds — the source is now a genuinely growing feed, so Bronze needs the same
immutability guarantee `bronze_ingest.py` gives daily prices.

Mechanics: each daily cycle fetches all 906 symbols (§4.4), then for each symbol
compares the freshly-fetched HTML's SHA-256 against the hash of that symbol's
last-captured Bronze artifact.
- **Unchanged** (expected for the vast majority of symbols on the vast majority of
  days — see §4.4's empirical base rate): no new Bronze row, no Silver reprocessing.
  This is the normal case and keeps daily storage growth close to zero on quiet days.
- **Changed** (new announcement appended, or — rare, but must be handled, not
  assumed away — the site correcting/editing a past entry): the new HTML is stored as
  an immutable, dated artifact:
  `financials_archive/bronze/announcements/date=YYYY-MM-DD/{SYMBOL}.html`, and one row
  is appended to `financials_archive/_bronze_ingest_log.jsonl` (`symbol, fetch_date,
  sha256, prev_sha256, bytes, source_url`) — same append-only-lineage convention as
  `bronze_ingest.py`'s own ingest log. `full_ca_ledger.sqlite` is captured the same way
  (one dated artifact per rebuild of that ledger, keyed off its own `meta.built_at`).
- This is what makes the pipeline genuinely resumable in the sense the project's
  scripting standing rule cares about: a crash mid-sweep leaves the already-hashed
  symbols' Bronze state exactly as it was (nothing partially written, nothing
  double-counted), and the next run's hash comparison naturally picks up wherever the
  crash left off — no separate checkpoint file needed, the content hash **is** the
  checkpoint.

### 4.2 Silver — two tables, incremental (revised from v1)

**`stock_announcements`** (NEW extraction, full schema in §5.1) — one row per source
`<tr>`, every field nullable except `symbol`/`announce_date`/`raw_text`. **No longer a
full rebuild every run** (v1's proposal, correct only for the one-time static case) —
now **incremental append, keyed off Bronze**: only symbols with a *new* Bronze artifact
this cycle get re-parsed; the parser re-processes that symbol's full returned history
(the site always returns everything, per `l0_fetch_announcements.py`'s own docstring),
but `source_row_sha256` (§5.1) lets the loader skip re-inserting rows already present —
a symbol that reports one new quarter contributes exactly one new
`stock_announcements` row, not a full re-insert of its history. A symbol whose Bronze
didn't change this cycle is never touched.

**`corporate_actions`** (REUSE, full schema in §5.2) — direct typed load of
`full_ca_ledger.sqlite`'s `ca_ledger` table, re-loaded (full replace, this table is
small — 7,416 rows total) whenever the source ledger's own `meta.built_at`/hash
changes. That ledger isn't rebuilt by this pipeline — a separate, existing process in
`ca_pipeline_kse100_20260907` owns it; this pipeline only notices and reloads when it
changes.

**`corporate_actions`** (REUSE, full schema in §5.2) — direct typed load of
`full_ca_ledger.sqlite`'s `ca_ledger` table. Every existing column preserved; TEXT-typed
numerics (`is_compound`, `n_components`, `price_factor`, etc.) get cast to proper
DuckDB types (`BOOLEAN`/`INTEGER`/`DOUBLE`) on load — the only transformation applied.
Content is otherwise untouched; the reconciliation logic that produced it is not
re-run or second-guessed here.

### 4.3 Gold — atomic-promote, no four-gate publish()

`gold_build.py`'s four-gate contract (freshness/completeness/hook_coverage/coherence)
is built around **daily session data** — it asks "does today's Bronze max-date have a
complete, coherent EVERY_SESSION row." That concept doesn't map onto this data: PSX
announcements arrive irregularly (a symbol might report once a quarter), and this build
processes one bounded historical snapshot, not a rolling session window. Applying the
four gates here would be a category error, not real safety.

**Proposed instead:** the simpler `ca_v2_prototype.py`-style pattern — build into a
staging DuckDB file, then atomic `os.replace()` into `financials_serving.duckdb`. No
promote/withhold decision, no ntfy alert, no `current_publication`-style lineage table
(nothing here feeds a trading decision, so there's no "last-good keeps serving on a bad
build" requirement the way there is for Gold's signal tables). If a build fails, it just
fails loudly (`SystemExit`) and the previous `financials_serving.duckdb` is left in
place untouched, same crash-safety property as every other atomic-swap in this codebase.

### 4.4 Ongoing cadence — daily, year-round, no season gate (revised 2026-09-18, second pass)

**Requirement:** daily automated full-906-symbol sweep, catching new quarterly
announcements as they're filed.

**The season gate (previous revision) is dropped entirely — owner: "why are we
leaving any month then? it's cheap."** That's correct, and it survives scrutiny: the
gate's whole purpose was to save cost on months assumed quiet, but the actual per-cycle
cost is the **fetch** step (906 requests, ~15-20 minutes, §6.0), and that cost is
identical whether or not anything changed — Bronze's content-hash design (§4.1) already
makes a no-change day cheap downstream (one hash compare per symbol, zero new rows,
zero reprocessing). Gating by month didn't reduce the expensive part at all; it only
risked silently missing genuine off-calendar activity — a special dividend, an EOGM, a
late filer, a restated result — none of which respect a "typical" quarter-end-plus-lag
window. There's no real trade-off here, so there's no reason to keep the gate.

**New design: run the full 906-symbol sweep every day, all 12 months, no month check
anywhere in the code.** This also deletes everything that only existed to support the
gate — `EARNING_SEASON_MONTHS`, the "outside earning season, skipping" branch, and the
`--force-full-sweep` override (nothing left to force past). The Pakistan fiscal-year
mapping worked out in the previous revision isn't wasted — it's genuinely useful context
for later interpreting *why* certain months show more activity once real data exists —
but it's no longer wired into any decision the pipeline makes:

| Convention | Typically-heavy months (informational only, not a gate) |
|---|---|
| July–June fiscal year (majority of listed cos.) | Jan–Feb (half-year), Apr–May (9-month), Jun–Oct (annual: provisional through audited) |
| Calendar fiscal year (banks/insurers) | Apr (Q1), Jul–Aug (half-year), Oct–Nov (Q3), Feb–Mar (annual) |

**Mechanics — matched to the same wake-catch-up model already proven on
`KIRAN_Nightly_Pipeline`.** The Phase 5c investigation already established this machine
is routinely asleep through any fixed evening trigger time and only runs on
wake-catch-up — a second Task Scheduler entry that assumed a reliable clock-time
trigger would repeat that exact mistake. So `KIRAN_Financials_Pipeline` gets the same,
already-proven settings, not a fresh guess:
- `CalendarTrigger`, `StartBoundary` **21:00** local, **daily** — an hour before the
  nightly pipeline's 23:30, so a single catch-up wake fires both, financials first.
- `StartWhenAvailable = true` — same wake-catch-up behavior as the nightly task.
- `DisallowStartIfOnBatteries = false`, `StopIfGoingOnBatteries = false` — applied from
  day one, not after a repeat of the 2026-09-14 silent-kill incident.
- `MultipleInstancesPolicy = IgnoreNew` — same same-day dedup convention.
- `<Repetition><Interval>PT30M</Interval><Duration>P1D</Duration>
  <StopAtDurationEnd>false</StopAtDurationEnd></Repetition>` — the same 30-minute
  retry-for-24h block already added to the nightly task.
- Both tasks remain fully independent (§2) — only the *scheduling philosophy* is
  shared, not a link, a chain, or a shared lock.

**Follow-up, not required before v1 ships:** once the first full historical backfill of
`stock_announcements` completes, its real `announce_date`/`fiscal_period_ended` values
(which, unlike the ledger, *do* include pure-earnings rows) can replace the ledger-proxy
cross-check in the table above with a true earnings-announcement distribution — worth
re-running this section's analysis at that point to confirm the 9-month window still
holds.

**Cost estimate:** 906 symbols, `SLEEP_SECONDS=1.0` between non-cached fetches (§6.0) →
roughly 15-20 minutes wall-clock per sweep, every day of the year — a once-daily,
single-threaded, polite-delay sweep, well within what this project's existing daily
price scrape already does to the same site.

## 5. Schema

### 5.1 `stock_announcements` (new)

| Column | Type | Notes |
|---|---|---|
| `symbol` | VARCHAR | from filename, cross-checked against the `(CODE)` in the Company cell; mismatch → `parse_notes` flag, not a hard failure |
| `announce_date` | DATE | from the Date cell |
| `row_index` | INTEGER | 0-based position of this `<tr>` within the source file, for the rare same-date multi-row case (e.g. HBL 2008-02-14) — makes `(symbol, announce_date, row_index)` a stable natural key without assuming `(symbol, announce_date)` uniqueness, which is confirmed false |
| `fiscal_period_type` | VARCHAR | `YEAR` \| `HALF YEAR` \| `QUARTER` \| NULL |
| `fiscal_period_ended` | DATE | from `FOR THE ... ENDED DD/MM/YYYY`; NULL if absent |
| `eps_consolidated` | DOUBLE | NULL if not present in this row |
| `eps_unconsolidated` | DOUBLE | tolerant of the confirmed `UNCONSLIDATED` misspelling |
| `eps_unspecified` | DOUBLE | present but no basis label found |
| `eps_basis_inferred` | BOOLEAN | true when an unlabeled EPS's basis was inferred from other labeled tokens in the same row (e.g. HBL's second 2008-02-14 row) |
| `pbt_consolidated` / `pbt_unconsolidated` / `pbt_unspecified` | DOUBLE | profit/loss before tax, PKR millions |
| `pat_consolidated` / `pat_unconsolidated` / `pat_unspecified` | DOUBLE | profit/loss after tax, PKR millions |
| `dividend_pct` | DOUBLE | face-value %; `Nil` parses to `0.0` with `dividend_is_nil=true`, distinct from "not mentioned" (NULL) |
| `dividend_is_nil` | BOOLEAN | see above |
| `dividend_flag` | VARCHAR | `F` / `I` / `II` / NULL — interim/final marker when present |
| `bonus_pct` | DOUBLE | |
| `agm_date` | DATE | NEW field, not in any existing table |
| `book_closure_from` | DATE | handles both the split and the combined "FROM D1 TO D2" phrasing |
| `book_closure_to` | DATE | |
| `raw_text` | VARCHAR | the full flattened cell text, kept verbatim for audit/re-parse |
| `parse_confidence` | VARCHAR | `HIGH` \| `MEDIUM` \| `LOW` — see §6.4 |
| `parse_notes` | VARCHAR | free text, populated whenever something was inferred, anomalous, or a known data-entry error was corrected (mirrors the existing `ca_ledger.note` convention) |
| `source_row_sha256` | VARCHAR | hash of `raw_text`, for change detection on re-run |

Primary key: `(symbol, announce_date, row_index)`.

### 5.2 `corporate_actions` (reused, typed conformance of `ca_ledger`)

Same 26 columns as `full_ca_ledger.sqlite`'s `ca_ledger` table (§3 of the earlier
investigation — `announce_date, bonus_pct, book_closure_from, book_closure_to,
classification, close_before, dedup_merged_from, div_per_share,
dividend_pct_face_value, era, event_types, ex_date, expected_drop, factor_basis,
index_neutral_move_pct, is_compound, matched_ex_date, n_components, note,
observed_drop, observed_ratio, price_factor, rights_pct, rights_price, source,
symbol`), with numerics cast out of TEXT (`is_compound`→BOOLEAN, `n_components`→
INTEGER, `price_factor`/`div_per_share`/etc.→DOUBLE, dates→DATE) and
`dedup_merged_from` un-double-encoded into a native DuckDB `LIST(DATE)`. No content
change — this table is a faithful, typed copy, not a reinterpretation.

## 6. Parsing design

### 6.0 Fetch mechanics — reuse `l0_fetch_announcements.py`, one deliberate override

The existing `ca_pipeline_kse100_20260907/scripts/l0_fetch_announcements.py` (+ shared
`common.py`) already implements exactly the fetch this needs — reused as-is, not
rebuilt, same principle as reusing `full_ca_ledger.sqlite`'s reconciliation logic:

- One `POST` per symbol to `ksestocks.com/Announcements` returns that symbol's **entire**
  announcement history in one response (confirmed in the script's own docstring: "do NOT
  loop per-date; that was the old, slow, wrong shape") — so a daily cycle doesn't need
  incremental date-range requests, it re-fetches the full page and lets Bronze's
  content-hash comparison (§4.1) decide what's actually new.
  Headers: `User-Agent: Mozilla/5.0 ... Chrome/128.0 Safari/537.36`, `Accept: */*`,
  `Content-Type: application/x-www-form-urlencoded`, `X-Requested-With: XMLHttpRequest`.
  30s timeout. Retry/backoff already handles `429` (waits `Retry-After` or
  `20*(attempt+1)`s, capped 90s), other errors (`1.5*(attempt+1)`s), up to 5 attempts.
- **Politeness delay:** `SLEEP_SECONDS = 1.0` between non-cached requests, already
  matches this project's established convention of a fixed polite delay (the main price
  scraper, `scraper.py`, uses `REQUEST_DELAY = 2.0` for its own different endpoint) —
  reused unchanged, no new rate-limit design needed.
- **Manifest-based resumability** (`announcements_cache/_manifest.json`, tmp-file +
  atomic swap per symbol) already means a killed/restarted sweep resumes correctly —
  reused unchanged.

**One deliberate override, called out because getting it wrong would silently defeat
the whole point of a "daily" cycle:** `common.http()` defaults to a **30-day** response
cache (`ttl_hours=24*30`) — a cache hit returns instantly with no real HTTP request.
That default exists for exploratory/backfill use, where re-hitting the network for data
that hasn't changed in weeks is wasteful. For the daily cycle, this
pipeline must call `http(..., ttl_hours=20)` (or similar, comfortably under 24h) instead
— otherwise "daily" fetches would mostly return yesterday's cached response for up to a
month, and new announcements would be missed for as long as 30 days. This is a one-line
call-site change to an existing, otherwise-unmodified shared function — not a fork of
`common.py`.
- Also requires passing the equivalent of `--refresh` (bypass the "skip if already in
  manifest" check) every cycle, since the manifest's job in the original script was
  "never re-fetch a symbol once done" — the opposite of what a recurring sweep needs.
  The historical-backfill mode (v1, one-time) keeps the original skip-if-manifested
  behavior; the daily mode does not.

### 6.1 Row traversal

Per-`<tr class="data-tr">` (not the whole-page flattened-block method the existing CA
extractor uses) — chosen because financial figures are cleanly row-scoped in every
sample seen, and per-row traversal naturally preserves the same-date-multi-row case
(HBL) as two distinct records instead of risking them being merged or one being
dropped.

### 6.2 Field regexes (extending, not just copying, the two existing extractors)

```python
# Basis label, tolerant of the confirmed misspelling
_BASIS = r"(?:\((CONSOLIDATED|UNCONSOLIDATED|UNCONSLIDATED)\)\s*|(CONSOLIDATED|UNCONSOLIDATED|UNCONSLIDATED)\s+)?"

EPS_RE = re.compile(_BASIS + r"EPS\s*=\s*(\(?-?[\d,.]+\)?)", re.IGNORECASE)

# Covers both "PROFIT/LOSS BEFORE TAXATION RS. IN MILLION" and the shorter
# "P/L BEFORE TAX RS. IN MIL" phrasing confirmed in HBL
PBT_RE = re.compile(
    _BASIS + r"P(?:ROFIT)?[/\\]L(?:OSS)?\s+BEFORE\s+TAX(?:ATION)?\s+RS\.?\s+IN\s+MIL(?:LION)?\s+(\(?-?[\d,.]+\)?)",
    re.IGNORECASE)
PAT_RE = re.compile(
    _BASIS + r"P(?:ROFIT)?[/\\]L(?:OSS)?\s+AFTER\s+TAX(?:ATION)?\s+RS\.?\s+IN\s+MIL(?:LION)?\s+(\(?-?[\d,.]+\)?)",
    re.IGNORECASE)

AGM_RE = re.compile(r"ANNUAL\s+GENERAL\s+MEETING\s+WILL\s+BE\s+HELD\s+ON\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)

# Split form (most common)
BC_FROM_RE = re.compile(r"BOOK\s+CLOSURE\s+FROM\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
BC_TO_RE   = re.compile(r"BOOK\s+CLOSURE\s+TO\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
# Combined form confirmed in AABS 2005: "BOOK CLOSURE FROM D1 TO D2" on one line —
# tried FIRST; if it matches, both dates come from this one pattern and BC_FROM_RE/
# BC_TO_RE are not applied again for this row
BC_COMBINED_RE = re.compile(
    r"BOOK\s+CLOSURE\s+FROM\s+(\d{2}/\d{2}/\d{4})\s+TO\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)

FISCAL_PERIOD_RE = re.compile(
    r"FOR\s+THE\s+(YEAR|HALF\s+YEAR|QUARTER)\s+ENDED\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)

# Reused directly from the existing, already-battle-tested CA extractor
# (l0b_match_announcements.py) rather than re-derived:
DIV_RE   = re.compile(r"DIVIDEND\s*(?:=|:|FOR\s+THE\s+(?:YEAR|HALF\s+YEAR|QUARTER)\s+ENDED\s+\d{2}/\d{2}/\d{4})\s*(Nil|[\d.]+\s*%)\s*(\([A-Za-z]\))?", re.IGNORECASE)
BONUS_RE = re.compile(r"BONUS(?:\s+ISSUE)?\s*(?:=|:|FOR\s+THE\s+(?:YEAR|HALF\s+YEAR|QUARTER)\s+ENDED\s+\d{2}/\d{2}/\d{4})?\s*([\d.]+)\s*%\s*(\([A-Za-z]\))?", re.IGNORECASE)
```

Notes on deliberate choices:
- `EPS_RE`/`PBT_RE`/`PAT_RE` use `.findall()` per row (not `.search()`), since a row can
  carry both bases at once (OGDC) — every match is kept, basis-keyed.
- The dividend/bonus regexes are reused **as-is from `l0b_match_announcements.py`**, not
  from `phase_4b`'s stricter versions — `phase_4b`'s `DIV_RE` requires the trailing
  `(F)`/`(I)` flag, which would silently miss `DIVIDEND = 15%` (no flag), a real pattern
  confirmed in the sample data.

### 6.3 Numeric parsing — the thousands-separator bug

A dedicated `_parse_amount(raw)` helper, not a bare `float()` cast:
1. Strip surrounding whitespace; detect parenthesized negatives (`(12.5)` → `-12.5`,
   same convention `phase_4b` already uses for EPS).
2. Count `.` occurrences. If more than one (the confirmed `8.041.416` case), treat every
   `.` except the last as a thousands separator (`8.041.416` → `8041.416`) — but only
   after `,` has already been stripped, so a normal `12,345.67` is unaffected. Any row
   this branch fires on gets `parse_confidence = LOW` and a `parse_notes` entry
   documenting the raw string and the correction applied, since this is a source
   data-entry error being corrected, not a clean parse — it should be visibly
   flagged, not silently trusted.
3. `Nil` (case-insensitive) → `0.0` with a `*_is_nil` flag where the schema has one
   (dividend); for PBT/PAT/EPS, `Nil` isn't expected but would fall through to `None`
   with a note if ever encountered, rather than crash.

### 6.4 Confidence tiers

- **HIGH** — every extracted figure in the row had an explicit basis label, or the row
  had no competing ambiguity (one unlabeled figure, nothing else contending for it).
- **MEDIUM** — a figure's basis was inferred from other labeled tokens in the same row
  (documented case: HBL's second 2008-02-14 row, unlabeled `EPS = 11.65` inferred as
  unconsolidated because the row's only other financial tokens are explicitly
  `UNCONSOLIDATED`).
- **LOW** — a numeric anomaly was detected and corrected (the thousands-separator bug),
  or multiple unlabeled same-type figures appeared in one row with no basis to
  disambiguate (first one kept, row flagged) — these need a human glance before being
  trusted for anything quantitative.

This mirrors the existing codebase's own philosophy (`ca_ledger.classification`'s
CONFIRMED/PROBABLE/AMBIGUOUS, `ca_ledger.note`) rather than inventing a new one — flag
uncertainty explicitly, don't silently smooth it over.

## 7. Staging / build mechanics

- Store root: `D:\KIRAN_ARCHIVE\financials_archive\`
  - `bronze/announcements/date=YYYY-MM-DD/{SYMBOL}.html` — immutable, change-triggered
    (§4.1)
  - `_bronze_ingest_log.jsonl` — append-only, one entry per symbol with a genuinely
    new capture
  - `silver/stock_announcements.parquet`, `silver/corporate_actions.parquet`
  - `financials_serving.duckdb` (+ `financials_serving_staging.duckdb` during build)
  - `_financials_build_log.jsonl` — append-only, one entry per run (started_at,
    finished_at, mode [`backfill`/`daily`], symbols_fetched,
    symbols_changed, rows_added per table, outcome)
- **Two run modes, same codebase:**
  - `backfill` (one-time / manual re-run): processes the existing cache as-is, original
    v1 behavior — skip-if-already-fetched, no `ttl_hours` override.
  - `daily` (the new Task Scheduler entry, §4.4, runs every day, no season check):
    forces fresh fetches (`ttl_hours=20`, bypasses the manifest skip), full 906-symbol
    sweep, Bronze/Silver both incremental (only symbols with new content get
    written/reparsed).
  Both modes converge on the same Bronze→Silver→Gold mechanics (§4) — `daily` is not a
  separate pipeline, just a different set of fetch-step flags feeding the same loader.
- Crash-safety: content-hash-as-checkpoint at Bronze (§4.1) plus the same tmp-file-then-
  `os.replace()` atomic swap every other layer in this codebase uses for Silver/Gold — a
  crash mid-sweep leaves already-processed symbols' state intact and never leaves a
  half-written `financials_serving.duckdb`.
- CLI: `python -m archive.financials_pipeline --mode backfill|daily [--store-root DIR]
  [--cache-dir DIR] [--ledger-db PATH]`. Prints a summary JSON
  (symbols fetched/changed, rows per table, confidence tier breakdown, files with zero
  extracted rows) on completion — same reporting convention as
  `bronze_ingest.py`/`ca_v2_prototype.py`.

## 8. Testing plan

Same philosophy as `tests/test_ca_v2_prototype.py` — fixtures built from the *actual*
confirmed edge cases, not synthetic happy-path-only data:

1. Dual-basis single row (OGDC-shaped) → both `eps_consolidated`/`eps_unconsolidated`
   populated, both equal in this case (39.50/39.50), dividend/AGM/book-closure all
   populated from the same row.
2. Same-date two-row split (HBL-shaped) → two distinct `stock_announcements` rows,
   `row_index` 0 and 1, second row's `eps_basis_inferred = true`.
3. Misspelled basis label (`UNCONSLIDATED`) → parses identically to the correctly
   spelled form.
4. Thousands-separator data-entry error (`8.041.416`) → parses to `8041.416`,
   `parse_confidence = LOW`, `parse_notes` documents the correction.
5. Combined book-closure line (AABS-shaped, `FROM D1 TO D2` on one line) → both dates
   populated (this is a case the *existing* CA extractor is confirmed to get half-wrong
   — a direct regression check against a known real gap).
6. Row with PBT/PAT present but EPS absent for that basis (FFC-shaped) → PBT/PAT
   populated, `eps_*` for that basis stays NULL, no crash.
7. Decoupling test (same pattern as `test_decoupled_from_gold_build_store`) — asserts
   `psx_serving.duckdb`, Bronze, Silver, and `shadow_diff.duckdb` are untouched/absent
   after a build.
8. Full-run smoke test against the real 906-file cache — asserts total row count is in
   a sane range, reports (not asserts, since this is descriptive) the confidence-tier
   breakdown and count of files that produced zero rows, for a human to glance at.
9. **Incremental-append correctness (new, for the daily cycle):** run the pipeline
   twice against identical fetched content — second run must add zero new Bronze
   artifacts, zero new Silver rows, zero duplicate `(symbol, announce_date, row_index)`
   keys. Then mutate one symbol's fetched HTML (append one synthetic new `<tr>`) and
   re-run — asserts exactly one new Bronze artifact for that symbol, exactly one new
   `stock_announcements` row, and every other symbol's row count unchanged.
10. **Cache-ttl override test:** asserts the daily-mode fetch call passes
    `ttl_hours=20` (or whatever the final constant is) to `common.http()`, not the
    library's own 30-day default — a regression here would silently turn "daily" into
    "roughly monthly," so it gets an explicit assertion, not just a manual check.

## 9. Open questions for review (not decided here)

Resolved by the owner's 2026-09-18 direction: refresh cadence (daily, every day, no
season gate — §4.4), full 906-symbol coverage every cycle, intended use (general
fundamentals layer, no single named consumer yet), and the task's scheduling model
(mirrors `KIRAN_Nightly_Pipeline`'s proven wake-catch-up settings, §4.4) — kept out of
this list now. Remaining:

1. ~~`ttl_hours` value for daily fetches~~ — moot, see §12: the implementation dropped
   the reused-cache idea entirely rather than tune its override value.
2. **Task Scheduler registration** — the code is built and tested, but
   `KIRAN_Financials_Pipeline` has not been created yet (§4.4 specifies its settings).
   Say the word and it's a `schtasks`/XML-import step, same mechanism used for
   `KIRAN_Nightly_Pipeline`'s own fixes.
3. **First live `daily`-mode run** — §12 flags one unverified detail (the exact date
   format ksestocks.com's `sdate`/`rfdate`/`rtdate` POST fields expect) that only a real
   request can confirm. Worth a single manual `--mode daily` trial run before trusting
   the scheduled task unattended.

## 10. Sign-off checklist before any code is written

- [x] Schema in §5 — built as specified
- [x] Parsing design in §6 — built as specified, all 6 named edge cases have a passing
      test against real corpus HTML (§0/§12)
- [x] Bronze/Silver/Gold mechanics in §4 — built as specified, with one addition not in
      the original design: a crash-safety refinement (§12) to make the "only reprocess
      changed symbols" logic correct across a mid-run crash, not just a clean run
- [ ] §4.4's Task Scheduler registration — **not done, code-only so far** (open question 2)
- [x] §9's remaining open questions — resolved via §12's implementation choices, one
      residual open question (#3 above) needs a live trial run to close

## 11. Cross-references

- `docs/KIRAN_LOCAL_FIRST_MIGRATION.md` — the main migration tracker this pipeline is
  deliberately NOT part of (§2's zero-contamination guarantee)
- `docs/MAINTENANCE_LOG.md` — the 2026-09-18 Phase 5c fix this design's §4.4 scheduling
  model is patterned after

## 12. Implementation notes (2026-09-18) — what actually got built, and two deviations

Built closely to the design above, with two deliberate simplifications made during
implementation, both preserving the *intent* of the corresponding design section while
being simpler/more robust than what was originally proposed:

**1. No cross-repo code import for the fetch step (affects §6.0).** The design
proposed reusing `l0_fetch_announcements.py`/`common.py` from the sibling
`ca_pipeline_kse100_20260907` directory directly (an actual Python import), with one
call-site override (`ttl_hours=20`) to bypass that shared function's 30-day response
cache. On reflection while implementing, importing Python modules across repos from an
unversioned research scratch directory is a fragile dependency — that directory isn't a
stable package and has already been reorganized once during this project's own
investigation. Instead, `financials_pipeline.py`'s `fetch_symbol_live()` is a fresh,
self-contained implementation of the *same verified request shape* (POST body field
names, headers, timeout, 429/retry backoff, `SLEEP_SECONDS=1.0` politeness delay — all
copied from the values already confirmed against the real `common.py`/
`l0_fetch_announcements.py` source). It has **no response cache at all**, which
achieves the ttl-override's actual goal (never silently serve stale cached data on a
"daily" cycle) more simply than tuning a cache TTL would have. Data-level reuse (the
HTML cache for `backfill`, `full_ca_ledger.sqlite` for `corporate_actions`) is
unchanged from the design — only the *fetch code path* was reimplemented rather than
imported. One genuinely unverified detail carried over: the exact date format
`ksestocks.com` expects for the `sdate`/`rfdate`/`rtdate` POST fields wasn't
independently re-confirmed against a live request (this pipeline hasn't made one yet) —
flagged in the function's own docstring, worth checking on the first real `--mode daily`
run.

**2. Crash-safe change-detection checkpoint, an addition to §4.1/§4.2.** While
implementing "only reprocess symbols whose content changed," a real correctness gap
surfaced: if the process crashed *after* writing a new Bronze artifact but *before* the
atomic Silver/Gold promote, a naive "compare against the newest Bronze file on disk"
check would see that symbol as unchanged on the next run (since Bronze already has the
new content) and silently skip reprocessing it forever — the exact kind of silent-loss
bug this project's Phase 5c work (2026-09-15/18) already spent real effort hunting down
elsewhere. Fixed by comparing against `promoted_bronze_hashes`, a small table stored
*inside* the same serving DuckDB file that gets atomically swapped alongside
`stock_announcements`/`corporate_actions` — so the change-detection checkpoint can only
ever be as current as the last actually-promoted state, never ahead of it. Covered by
`test_crash_before_promote_does_not_lose_the_change` (deliberately simulates the crash
ordering, not just a clean run).

**Minor factual correction:** the corpus is 904 `.html` files, not 906 — the "906"
figure used throughout this doc and the preceding conversation was a slightly-off
recollection; verified by listing the actual `announcements_cache/` directory. Doesn't
change anything about the design, noted for accuracy.
