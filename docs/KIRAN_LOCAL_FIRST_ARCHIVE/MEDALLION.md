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

## Task 3.2 — Silver build (`archive/silver_build.py`)

**Contract (tracker §5): port the corporate-action adjustment + universe-conforming
logic; wire `ca_v2_reader` as an *available* source, gate off.**

A full rebuild from the live Bronze store every run (Silver is disposable),
deterministic (re-run → byte-identical), producing:

- `prices_archive/silver/prices_adjusted/year=YYYY/data.parquet` — Bronze `prices`
  with each confirmed backward CA factor (`close_after/close_before`) applied to
  that symbol's pre-ex-date OHLC, `ROUND(_,4)` per event, oldest→newest so events
  compound — a faithful port of `apply_price_adjustments.py`'s inner loop, on
  **DuckDB**. Plus `hit_circuit_up/down/thin_trading_flag` from the confirmed
  producer formula (`apply_price_adjustments.compute_circuit_flags`) — the exact
  columns the frozen `silver/prices_adjusted` carries. Non-equity symbols
  (`config.is_non_equity_symbol`) are dropped here (Bronze keeps them raw).
- `prices_archive/silver/sectors/sectors.parquet` — the frozen `sectors` with
  non-equity dropped.
- `prices_archive/silver/stock_metadata/stock_metadata.parquet` — a port of
  `build_stock_metadata.py`'s **idempotent UPSERT** (not drop-and-rebuild): every
  frozen row preserved (manual/legacy rows never deleted), source-derived columns
  refreshed for the recomputed include-set (`EXCLUDED_SECTORS` / `SECTOR_OVERRIDES`
  / `UNIVERSE_WHITELIST`), `is_active`/`delisting_date`/`notes` kept as frozen.
- `prices_archive/_silver_build_log.jsonl` — append-only provenance.
- `prices_archive/_silver_parity.json` — rewritten each run (below).

**Legacy CA event set** = the DROP_50/33/25 auto-confirm rows in
`corporate_action_suspects_clean.csv` + the `CONFIRMED` rows in the **frozen
baseline `.db`**'s `corporate_action_suspects` table. The live `psx_data.db` is
opened read-only (`mode=ro&immutable=1`) for that one read and never for write.

**CA source gate** — `--ca-source` / `KIRAN_SILVER_CA_SOURCE`, default `legacy`.
`v2` makes `ca_v2_reader.load_v2_prices` an available Silver `close` source (it
overwrites `close` for the symbols/dates the v2 total-return artifact covers). It
is **off by default**; the dashboard reads none of this store yet. Wiring v2 into
the dashboard stays a separate, Q6-gated sign-off (§9 D5 / TR-19). A missing
`ca_v2_reader.py` is a hard `SystemExit`, never a silent fallback.

### Parity vs. the frozen store — a known residual, one open owner decision

Every run compares the rebuilt `prices_adjusted` to the frozen
`silver/prices_adjusted` over the overlap (through 2026-09-08) and writes
`_silver_parity.json`. Current result:

- **row coverage exact** — 1,761,371 rows, 0 only-frozen, 0 only-new.
- **OHLC residual: 3,576 rows, all symbol `DLL`.** DLL had a ~10.3:1 split on
  2026-06-05 (raw 624.83 → 60.43) that the frozen `prices_adjusted` applied via
  the Data Health page (`rebuild_symbol_adjusted`), which leaves **no recoverable
  event record** in the baseline `.db` or the CSV. A pure rebuild-from-events
  cannot reproduce it — this is the DR program's documented provenance gap
  (`DATA_REHABILITATION_PROGRAM` §116 / `ZH_research/Known_Limitations.md`), not a
  build bug.
- **circuit-flag residual: 18 rows across 4 illiquid names** (DWAE 9, GAMON 6,
  MWMP 2, GEMBCEM 1) — full-history single-formula recompute vs. the frozen
  incremental (`_circuit_flags_for_new_rows`) at a trading-gap boundary. Sub-0.001 %.

**Owner decision D8 (2026-09-10): rebuild-pure.** Silver stays strictly
rebuild-from-events. DLL-class events are the DR program's to resolve upstream —
add a real `CONFIRMED` suspect row / CSV entry with the factor, and the next
rebuild picks it up. `_silver_parity.json`'s residual list *is* that backlog and
should trend to zero, not be papered over. The frozen store (the seed) stays
available for anything that needs the as-shipped adjustment. No code change.

## Task 3.3 — Gold build (`archive/gold_build.py`) — IN PROGRESS

**Engine decision (owner, 2026-09-10): full DuckDB port.** Not a SQLite compute
scratchpad, not a read-path-only refactor. §9 D1 governs; §8's "signal logic
ported as-is" means *same algorithm on DuckDB*, not *same file*.

**Method.** Every screener already separates a **pure compute core** (DB-agnostic
pandas / plain Python) from thin SQLite I/O wrappers — e.g.
`regime._compute_indicators` / `_classify` / `_pending_regime_rows`;
`stock_signals._ema` / `_build_pivot_lookup` / `_compute_bt_vc`, and its loaders
(`_load_kse100`, `_load_stock_prices`, …) already take a `conn`. The port:

1. **reuses the pure cores by import** — one source of truth for the algorithm; a
   later change to production signal logic flows through automatically;
2. reimplements only the **I/O against DuckDB** (`INSERT OR REPLACE` /
   `PRAGMA table_info` have DuckDB equivalents; loaders get a DuckDB `conn`
   attached to the Silver Parquet);
3. where a screener's core is **not** cleanly separable, factoring it out is part
   of that screener's port PR — a behaviour-preserving production refactor, tested.

**Gold store.** `D:\KIRAN_ARCHIVE\psx_serving\psx_serving.duckdb` — full replace
every run, built into `psx_serving_staging.duckdb` then `os.replace`d over the
live file (atomic swap; staging removed on failure). A deterministic Parquet
export per table (`psx_serving/parquet/<table>.parquet`) is the idempotency-check
form and the JSON feed. `_gold_build_log.jsonl` + `_gold_parity.json`. Serving
window = latest Bronze `prices` date − `--window-days` (default 730 ≈ 2 yr);
screeners compute over full history for lookback correctness, output is sliced.

**Parity.** Each screener's Gold output is compared to the live `psx_data.db`
(opened read-only). The live pipeline is incremental and has documented gaps
(CLAUDE.md "Known Gaps"); Gold recomputes over the complete series, so it is a
**superset on dates** and its rolling state (EMAs, `regime_days`, RS chains)
legitimately diverges from the live one *at and after the first live gap*.
`_gold_parity.json` reports `pre_gap_residual` (must be empty = clean) separately
from `post_gap_expected_divergence` (knock-on of the gap-fill, expected).

**Sub-tasks (one PR each):**

- **3.3a — DONE (2026-09-10).** Scaffold (`GoldStore`, staging + atomic swap,
  Parquet export, `SCREENERS` registry, parity/logging) + the **`regime`** port
  (`market_regime`). Reuses `regime.py`'s pure functions verbatim. Parity: CLEAN
  before the first live gap; Gold fills 2026-04-27 + 2026-07-20/21/29 and
  re-chains from there. 6 tests, 498 window rows.
- **3.3b** — `stock_signals` (RS ranks, base tightness, pivot/BOS, EMA stage flags).
- **3.3c** — `sector_signals` + the four-stage sector grades (`_stage`).
- **3.3d** — `boring_signals` + `leaders_scan` / `leaders_top_picks`.
- **3.3e** — `signal_engine` (`recovery_signals` / `portfolio_signals`) + `setup_log` / `processor` (`trade_setups`).
- **3.3f** — front-end JSON export, full end-to-end idempotency, consolidated parity report.
