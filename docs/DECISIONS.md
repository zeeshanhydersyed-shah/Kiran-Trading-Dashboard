# Engineering Decision Log

An append-only log of architecturally significant decisions for the Kiran
PSX pipeline — the kind of thing that's easy to infer *what* was built but
hard to reconstruct *why*, six months or several years later. New entries go
at the top. Do not edit or delete past entries — if a decision is later
reversed, add a new entry that supersedes it and link back.

---

## 2026-07-04 — Two remaining gaps closed: live scraper + CSV/live-table drift

**Status:** Executed. These were flagged as follow-up items when the Open
project was first "closed," then explicitly requested as final cleanup.

### 1. scraper.py now captures Open going forward

`parse_market_summary()` (`scraper.py`) now extracts `cells[2]` (Open) for
both stock and index rows, using the same close-fallback convention already
used for High/Low (if the cell is blank/unparseable, default to close — no
new clamping logic was introduced). `price_rows` tuples grew from 6 to 7
fields (open appended last); `index_rows` from 5 to 6. Existing consumers of
the first N fields (`_price_fingerprint`, the staleness check) are
unaffected since they only ever indexed the fields that already existed.

`database.py`'s `upsert_prices()` / `upsert_index_prices()` were extended to
accept the new field, backward-compatibly (still accept the older 3/4/5/6
-tuple shapes from `load_bi_history.py` and other one-off scripts). The
`open` column uses `COALESCE(prices.open, excluded.open)` — **the opposite
priority from high/low/volume**, deliberately: existing values win, only
NULL gets filled. This matters because a re-run or retry of an already
-populated date must never let a fresh scrape silently override the
carefully-verified backfilled data from the Open Price Acquisition Project.
In normal daily operation this never triggers (new dates start NULL), but it
protects the edge case.

**Verification performed:**
- Live-fetched 2026-07-02 with the patched parser and compared against the
  already-verified production data for the same date: exact match for 5
  spot-checked stocks and all 5 indices (byte-for-byte on Open).
- Isolated in-memory test of the exact upsert SQL confirmed: (a) new dates
  populate Open correctly, (b) re-running an already-populated date does NOT
  overwrite the existing Open even when the fresh value differs, (c) legacy
  6-tuple callers still work with Open landing as NULL, no crash.
- Ran the real `python main.py --update` end-to-end; it correctly no-op'd
  (today, 2026-07-04, is a Saturday — no new trading day yet) and the rest
  of the pipeline (support reversal setups, leaders scan) completed without
  error. Production row/open counts confirmed unchanged after this run.
- **Not yet observed:** a real brand-new trading date actually being scraped
  with Open populated end-to-end (next trading day is Monday 2026-07-06).
  Recommend a quick spot-check after the next scheduled run.

**Impact on existing dataset:** none. This only affects dates scraped from
now on. No backfill required — the historical gap this was the root cause of
was already closed by the acquisition/import/adjustment-rebuild work above.

### 2. corporate_action_suspects_clean.csv / live-table drift fixed

`load_events()` in `apply_price_adjustments.py` now merges CONFIRMED events
from the live `corporate_action_suspects` table into the event list whenever
`--all` is used, in addition to the CSV, deduplicating on (symbol, date).
Merged-in events use the `adjustment_factor` already stored in the table
(the exact value the dashboard applied at confirm time — computed the same
way, `close_after / close_before`, so using the stored value avoids any
recompute drift) rather than recalculating it. Gated behind `--all` for
consistency with how CSV-CONFIRMED rows already work — the bonus-only
default mode is intentionally narrower and skips both.

**Verification performed:** re-ran the full rebuild with the fix in place
and diffed a SHA-256 checksum over the entire `prices_adjusted` table
(symbol, date, open, high, low, close, all 1,821,016 rows) against the
pre-fix state (which already had MTL's correction applied manually, per the
earlier 2026-07-04 entry). **Checksums matched exactly** — the fix
reproduces, fully automatically, the same correct state that previously
required a manual catch-and-reapply step. The rebuild log also confirms it:
`[live-table merge] MTL 2026-06-22 not in CSV -- using confirmed
factor=0.5144 from corporate_action_suspects`.

**Impact on existing dataset:** none — verified byte-identical.
**Backfill:** none needed; MTL was already correctly applied, and it was the
only CONFIRMED live-table row at the time of this fix. Any future dashboard
confirmation will now be picked up automatically by the next full rebuild
without anyone needing to remember to check for drift.

**Side note:** a pre-existing, unrelated bug in `apply_price_adjustments.py`
was also fixed along the way — several `print()` statements used Unicode
characters (→, ─, ✓, ✗) that crash under the Windows default `cp1252`
console codepage. Replaced with ASCII equivalents. This crash was safe
(happened after the uncommitted DROP+recopy, before any adjustment
committed — see the earlier 2026-07-04 Phase 5 entry for how this was
confirmed) but would have looked alarming if hit again.

---

## 2026-07-04 — Phase 5: prices_adjusted.open populated via full adjustment rebuild

**Status:** Executed. This closes out the Open price acquisition project.

Ran `apply_price_adjustments.py --all` (existing, previously-trusted production
code — not reimplemented) to rebuild `prices_adjusted` from the now
Open-populated `prices` table, applying the same 613 bonus-event
corporate-action factors (DROP_50/33/25) to `open` as already applied to
`high`/`low`/`close`. Preceded by a full `psx_data.db` backup
(`phase5_adjustment_rebuild_output/psx_data_pre_phase5_rebuild_*.db`).

**Result:** `prices_adjusted.open` non-null count: 462,377 → **1,572,584**,
now exactly matching `prices.open`. A spot-checked untouched symbol (HBL)
confirmed byte-identical before/after; a symbol with multiple chronological
events (ACPL) confirmed correct backward-compounding adjustment.

**Two issues found and fixed during this run, recorded for future reference:**

1. **Windows console encoding bug in `apply_price_adjustments.py`.** Several
   `print()` statements used Unicode characters (→, ─, ✓, ✗) not representable
   in the Windows default `cp1252` console codepage, crashing the script
   mid-run with `UnicodeEncodeError`. The crash happened *after* the
   `DROP TABLE prices_adjusted` + fresh-copy step but *before* any adjustment
   was committed (SQLite auto-rolls-back an uncommitted transaction on
   abnormal exit) — confirmed by checking that the first-alphabetical event
   symbol (ACPL) still showed its raw, unadjusted value after the crash. No
   data was lost; the table was simply in an unadjusted-copy state, safe to
   rebuild again from scratch. Fixed by replacing the non-ASCII characters
   with ASCII equivalents (`->`, `--`, `OK`/`MISMATCH`). **Anyone running this
   script on Windows should confirm the fix is still in place** — the crash
   is silent-safe (no data loss) but will look alarming if hit again.

2. **`corporate_action_suspects_clean.csv` had drifted from the live
   `corporate_action_suspects` table.** The CSV (last modified 2026-06-12) is
   the source of truth `apply_price_adjustments.py`'s full-rebuild path reads
   from. But the dashboard's Data Health page confirms individual suspects by
   calling `rebuild_symbol_adjusted()` directly against the live table and
   `prices_adjusted` — it does **not** write back to the CSV. One such
   correction (MTL, 2026-06-22, factor 0.5144, confirmed 2026-06-23) existed
   only in the live table. A naive full rebuild would have silently reverted
   this already-confirmed, already-live correction. Caught before running the
   rebuild by diffing the CSV against the live table's CONFIRMED rows;
   reapplied manually via `rebuild_symbol_adjusted()` after the rebuild, and
   verified byte-identical to the pre-rebuild state (plus now with Open
   populated).

   **This is a standing process gap, not fixed here** (out of scope for the
   Open price project) — any future full rebuild of `prices_adjusted` will
   have the same problem for any suspect confirmed via the dashboard after
   the CSV was last generated. Recommended fix for a future task: either (a)
   have the dashboard's confirm action also append/update the CSV, or better,
   (b) change `load_events()` in `apply_price_adjustments.py` to read
   CONFIRMED events directly from the live `corporate_action_suspects` table
   instead of (or merged with) the static CSV, since the table is the actual
   live source of truth going forward and the CSV is a frozen snapshot from
   the original bulk categorization exercise.

---

## 2026-07-04 — Open price import executed (Option C, gap-fill only)

**Status:** Executed

Following the 2026-07-03 decision below, and the Phase 2.5 provenance review
(independently re-verified same day — see
`docs/DATA_ACQUISITION_ARCHITECTURE.md`), `import_open_prices.py` was run
with `--execute` and completed successfully.

**Result:** `prices.open` non-null count: 462,377 → 1,572,584 (+1,110,207).
`index_prices.open`: 1,528 → 16,406 (+14,878). Every pre-existing non-NULL
`open` value is unchanged — verified both by the script's own before/after
count check and independently re-queried afterward. A full pre-import backup
(`open_import_output/psx_data_pre_open_import_20260704T100705Z.db`, sha256
in `open_import_output/import_report.json`) was taken automatically before
any write.

**What was excluded and why** (see `import_open_prices.py` module docstring
for the exact filter logic): 319,082 rows (stock + index) where the
acquisition's own open equalled its own close (known ksestocks.com data
quality issue, not a genuine open price); 207 rows outside that day's own
high/low range; 576 rows on 2026-06-01 (still-unexplained single-date
anomaly — deliberately excluded, not imported "unverified" like the rest of
pre-2020); 140,142 rows with no matching row in `prices`/`index_prices` at
all (this import only fills existing rows, never inserts new ones).

**Not yet done — deliberately deferred:** `prices_adjusted.open` is still
NULL wherever it was before. Per the 2026-07-03 decision, deriving it
correctly means re-running the existing `apply_price_adjustments.py`
machinery (which already multiplies `open` by the cumulative corporate-action
factor, same as high/low/close) against the newly-populated `prices.open` —
not copying raw values into `prices_adjusted` directly, which would produce
internally inconsistent rows (adjusted H/L/C next to unadjusted Open). This
is Phase 5, not yet started as of this entry.

**Implication:** 984,473 stock rows and 12,372 index rows before 2020-01-01
are now populated as "best available, unverified" — there is no independent
source to check them against (BI PostgreSQL only covers 2020 onward). Any
future analysis touching pre-2020 Open should carry that caveat forward.

---

## 2026-07-03 — Open price acquisition: separate, read-only, human-reviewed

**Status:** Accepted

**Context / Motivation**

The database was missing the Open price for all PSX symbols, 2005–2019
(0% coverage), and had partial coverage for 2020–2026 of unknown,
non-reproducible origin (see `docs/DATA_ACQUISITION_ARCHITECTURE.md` for the
full investigation). Fixing this required scraping ~4,300+ historical trading
dates from `ksestocks.com/MarketSummary`. The natural, fastest way to build
this would be one script: scrape → validate → write directly to
`psx_data.db`.

`psx_data.db` is described in project memory as "advanced stage,"
"production-quality research data," with an explicit rule: "prices table is
read-only — never modify." Active research (`ZH_research/` experiments) is
already built on top of it. A single-pass scrape-and-write script means any
parsing bug, source anomaly, or rate-limit-induced partial page becomes a
silent, permanent corruption of research infrastructure — discovered only
if and when someone happens to notice bad numbers downstream.

**Alternatives Considered**

1. **Single combined script** (scrape + validate + write to `psx_data.db`
   directly). Rejected — no human checkpoint before production data changes;
   a bad batch is immediately live.
2. **Scrape directly into `prices`/`prices_adjusted` with a transaction and
   rollback-on-error.** Rejected — a transaction protects against crashes
   mid-write, but not against *successfully* writing wrong data (e.g. a
   subtle parser bug that produces plausible but incorrect values for a
   date range). The failure mode this project cares about most is silent
   incorrectness, not a crash.
3. **Backfill-only scraping** (only scrape dates currently NULL in
   `psx_data.db`). Rejected after investigation — the existing 2020–2026
   Open data has unverifiable provenance, so treating it as ground truth and
   only filling gaps around it would permanently launder an unverified
   dataset into the trusted record. Superseded the initial Phase 2 proposal,
   which did suggest gap-only scraping before this was raised.
4. **Six-phase separation with a standalone, read-only acquisition tool.**
   **Selected.**

**Decision**

Split the work into six independent phases (acquisition, validation, human
review, database import, corporate-action adjustment, research), each with a
hard boundary. Built `acquire_open_prices.py` to cover only phase 1–2: it
re-acquires Open for the *entire* 2005→today range from the original source,
regardless of what's already in the database; validates each record
in isolation; and separately cross-validates against `psx_data.db` using a
connection that is read-only at the SQLite driver level, self-tested at
startup by attempting (and confirming rejection of) a no-op write. It has no
write path to `psx_data.db` at all — not disabled by a flag, not gated by a
config option, simply not implemented. Import (phase 4) is explicitly
deferred to a separate, not-yet-built utility, to be designed only after a
human has reviewed this tool's CSV output and audit report.

The tool also deliberately duplicates constants and parsing logic from
`scraper.py`/`config.py` rather than importing them, so that a latent bug in
the production parser can't cause this "independent" validation to silently
agree with it.

**Implications for Future Development**

- Any future data acquisition work in this repository should default to the
  same phase separation unless there's a specific reason not to — see the
  Guiding Principle in `docs/DATA_ACQUISITION_ARCHITECTURE.md`.
- The import utility (phase 4), when built, must never overwrite an existing
  non-NULL value in `prices` — only fill NULLs, matching the "don't launder
  unverified data as ground truth" reasoning above, and must itself go
  through the same human-review-before-write discipline.
- The 2020–2026 Open values currently in `psx_data.db` remain unverified.
  Once `acquire_open_prices.py` output is reviewed, that comparison data
  becomes the first real evidence for or against trusting them — don't
  assume they're correct until that review happens.
- If a future contributor is tempted to collapse phases for speed, re-read
  the Context section above first — that pressure is exactly what this
  decision anticipated.
