# Kiran Local-First Migration — Phase 3 Medallion transforms (design note)

Tracker: [`../KIRAN_LOCAL_FIRST_MIGRATION.md`](../KIRAN_LOCAL_FIRST_MIGRATION.md) §1 / §3 / §5.
This note records the concrete decisions Phase 3 needed that §3–§4 left as
"working summary". It is strictly within the approved plan — no scope beyond the
§5 Phase 3 checkboxes.

## Engine

**DuckDB, confirmed available on this machine (2026-09-10).** The tracker, the
persistent memory and `requirements-archive.txt` all carried a note that DuckDB
had *no cp314 wheel* (Python 3.14) and that the engine choice (§9 D1: "DuckDB
across all three layers") was therefore blocked. That is no longer true —
`duckdb 1.5.5` installs and runs clean on Python 3.14.4. `duckdb>=1.5` is now a
real `requirements-archive.txt` dependency.

Writer split, matching the Phase 1 precedent (`archive/build_store.py`):

- **DuckDB** is the *query / compute* engine — joins, the CA-adjustment SQL, the
  Gold screeners, coverage scans.
- **pyarrow** is the *serializer* for the Bronze/Silver Parquet store, with the
  exact options `build_store.py` established
  (`compression="zstd", version="2.6", use_dictionary=True`) and a deterministic
  `ORDER BY (symbol, date)` before every write, so a re-run is byte-identical and
  a partition an ingest rewrites is identical to what `build_store.py` would have
  produced for the same row set.

Bronze ingest (Task 3.1) is a columnar append with no joins, so it is pure
pyarrow. DuckDB enters at Silver (Task 3.2).

## Store layout — the frozen seed vs. the live store

Two physically separate things under `D:\KIRAN_ARCHIVE\` (override
`KIRAN_ARCHIVE_ROOT`):

| Path | What | Mutability | Backed up by |
|---|---|---|---|
| `baseline/`, `bronze/`, `silver/`, `backup_set/`, `STORE_MANIFEST.json` | **Phase 1 frozen seed** — the SEQ-1 immutable baseline | **Immutable.** In `BASELINE_MANIFEST.sha256`, copied off-site under B2 COMPLIANCE Object-Lock, `archive_manifest verify` guards it | milestone Object-Lock snapshots |
| `data-captures/` | `--single-branch` clone of the `data-captures` git branch (Phase 2 capture files) | git-managed, disposable (re-clonable) | n/a (the branch is the record) |
| `prices_archive/bronze/` | **Live Bronze** — the frozen `bronze/` seeded in once, then daily capture files appended | append-only; year partitions rewritten to add new dates, existing rows never altered | nightly `restic` (Q3), RPO 24h |
| `prices_archive/silver/` | **Live Silver** (Task 3.2) | rebuilt from Bronze; disposable | nightly `restic` |
| `psx_serving/` | **Gold** (Task 3.3) — 2-yr window + signals + grades | full replace, atomic swap; disposable | not backed up (rebuilds from Silver in minutes) |

The live store is deliberately **not** in `BASELINE_MANIFEST.sha256`.
`archive_manifest.py` excludes the `data-captures/`, `prices_archive/` and
`psx_serving/` top-level trees from the baseline walk so `verify` (and the
scheduled `KIRAN_Archive_Checksum` job) stays green. The baseline manifest keeps
its single purpose: guarding the frozen preservation set.

`prices_archive/bronze/` is a byte copy of the frozen `bronze/` at seed time, so
the DR program and any research consumer can attach read-only to *either* and get
the same 2005→2026-09-08 substrate; the live one additionally carries every
trading day captured since.

## Task 3.1 — Bronze ingest (`archive/bronze_ingest.py`)

**Contract (tracker §5): append-only, deduped, gap-detecting, records which dated
files it consumed + hashes.**

1. **Seed** (one-time, idempotent) — if `prices_archive/bronze/` does not exist,
   copy the frozen `bronze/` tree into it verbatim and log the seed event with
   the frozen `STORE_MANIFEST.json` hash as provenance.
2. **Pull** — `git -C <captures-dir> pull --ff-only` (skip with `--no-pull`).
3. **Ingest** — for each `data/incoming/YYYY-MM-DD.parquet` (never
   `latest.parquet`), in date order:
   - hash the file; read its rows + Parquet metadata; assert every `trading_date`
     in it equals the file's `source_date`.
   - **dedupe / immutability:** if that date already has rows in Bronze → skip,
     no write, no log line. A capture never overwrites an ingested date.
   - else split `record_type` → `prices` (`symbol,date,close,volume,high,low,open`)
     and `index_prices` (`symbol,date,high,low,close,open`), coerce to the frozen
     column types, append into the `year=YYYY` partitions (load existing, concat,
     `ORDER BY (symbol,date)`, rewrite with the standard Parquet options).
   - append one JSONL line to `prices_archive/_bronze_ingest_log.jsonl`:
     timestamp, `capture_file`, `capture_sha256`, `source_date`, capture
     `code_version`, rows added (stock / index), years touched.
4. **Gap detection** (report-only, never fails the run) — weekdays between the
   min and max ingested date with no Bronze row: classified `missing_capture`
   (no capture file present) or `nodata_or_holiday` (weekend/holiday, or a
   capture that resolved `nodata`). Written to `prices_archive/_bronze_gaps.json`
   (overwritten each run) and printed. A real PSX holiday calendar does not exist
   in this repo, so a weekday gap with no capture is surfaced for human review,
   not auto-resolved.

**Idempotency:** a re-run with no new capture files does zero file writes, zero
log appends, and leaves every Parquet file byte-identical. Tested.

**D7 / safety:** `bronze_ingest.py` never opens `psx_data.db` at all (not even
read-only) and never touches Supabase or `daily_scraper.yml`. It is a pure
function of (frozen seed + capture files).

## Tasks 3.2 / 3.3

Stubs here so the cold-start protocol has the shape; detail lands with each PR.

- **3.2 Silver** — `archive/silver_build.py`. Port `apply_price_adjustments.py`'s
  corporate-action adjustment + universe-conforming (`config.py` filters) onto
  Bronze via DuckDB → `prices_archive/silver/prices_adjusted/`. Wire
  `ca_v2_reader.load_v2_prices` as an **available but gated-OFF** source
  (`KIRAN_SILVER_CA_SOURCE=legacy|v2`, default `legacy`; the dashboard path is
  untouched). Idempotency test.
- **3.3 Gold** — `archive/gold_build.py`. 2-yr slice from Silver, run every
  registered screener (`processor`, `weinstein`, `stock_signals`,
  `sector_signals`, `boring_signals`, `leaders_scan`, recovery/portfolio), grade
  every sector → `psx_serving/` (DuckDB) + JSON export. Staging build + atomic
  swap. Idempotency test. Signal parity vs the live pipeline on a shared date.
