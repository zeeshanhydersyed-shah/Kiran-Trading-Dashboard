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
- **3.3b — DONE (2026-09-10).** `stock_signals` port. `build_stock_signals` reuses
  `stock_signals.py`'s `_load_*` / `_build_pivot_lookup` / `_process_trading_dates`
  **verbatim by import** (loaders already take a `conn` + `?` params → DuckDB
  works unchanged; `_process_trading_dates(conn=None, write_fn=…)` is the PG
  port's zero-SQLite path). Universe = Silver `stock_metadata` **minus
  `config.EXCLUDED_SECTORS` + `is_non_equity_symbol`** (`_load_universe` itself
  doesn't filter — §118 Defect A). Whole 2-yr window every run, output sliced;
  also materialises `stock_metadata` + `sectors` into the serving DB. ~208 k
  rows, deterministic. Price-history lookback = `KIRAN_SS_LOOKBACK_DAYS` (default
  1050 cal ≈ 720 trading days — ~4 min/run; keeps this 7.6 GB box out of swap;
  `stock_signals.py`'s own 2015 floor thrashes it). Parity **`status: clean`
  (port verified):** `rs_score_20` + `base_tightness` / `pivot_*` / `bos_flag` /
  `avg_vol_10d` byte-exact vs live, genuine `only_live` = 0, Gold ranks
  self-consistent. `lookback_flag_residual` = EMA-stack flags NULL/flipped for
  thin names at the shallow default (load-depth, raise the env var).
  **Finding → `KIRAN_CLEANUP_AUDIT.md` §118 (2 live defects, owner: fix in the
  migration only — dashboard not in use):** (A) `_load_universe` never filtered
  `EXCLUDED_SECTORS`; live's `stock_metadata` grew ~150 excluded-sector rows on
  2026-08-03 → live has ranked ~128 untradeable stocks since (setup_log ~22 %,
  Explorer/Leaders). Gold drops them. (B) `recompute_symbol_signals` writes
  `rs_rank=1` for its symbol's whole history — `MTL` (5194) + `PIAB` (51). Gold
  recomputes over one universe → correct. 5 tests.
- **3.3c — DONE (2026-09-10).** `sector_signals` port + the four-stage
  `sector_stage` grades. `build_sector_signals` reuses
  `sector_signals._compute_and_write_sector_signals_for_date_sqlite` **verbatim
  by import** (`pd.read_sql_query(conn)` + `conn.execute("INSERT OR REPLACE …")`
  both work on DuckDB). **One tiny dialect-neutral refactor to
  `sector_signals.py`:** `WHERE date >= DATE(?, '-30 days')` (SQLite-only) →
  Python-computed floor date passed as a param; behaviour identical.
  `_medallion_views` materialises `stock_metadata` **conformed** (`EXCLUDED_SECTORS`
  + non-equity dropped); `active_stocks_on_date` is **rebuilt pure + point-in-time**
  (traded-on-D ∩ conformed universe) — a strict superset of live's stale
  hand-curated `symbol_active_dates`; `stock_market_cap` from the frozen baseline.
  `build(--only …)` param added. ~4 min/run. **Parity = RECOMPUTE-based (`clean`):**
  live's *stored* `sector_signals` derived columns are stale — not reproducible by
  current `sector_signals.py` (only `sector_ema50` 2026-06-19+ was; §118.6) — so
  `_parity_sector_signals` materialises Gold's own Silver/Bronze inputs into a
  scratch SQLite and re-runs the *same function* on SQLite (Gold ran DuckDB) over a
  45-day window: every sector-cell matches (`sector_stage`, `sector_ema50/above`,
  `rs_score_20/50`, `breadth_score`, `vol_ratio`, `adv_dec_ratio`, `composite_score`,
  `rs_rank`). Separately `sector_stage` matches live's stored values byte-exact in
  live's current-code window. Three live-side findings classified EXPECTED
  (KIRAN_CLEANUP_AUDIT.md §118.5/§118.6): pre-2026-06-19 legacy stage backfill;
  §118 Defect A EXCLUDED sectors from 2026-08-03; legacy universe omissions
  (`BML`/`FCL`/`WAVESAPP`/`SYM`/`IMAGE` — Gold grades `APPAREL` too). 1 test (12 total).
- **3.3d — DONE (2026-09-11).** `boring_signals` + `leaders_scan` / `leaders_top_picks`.
  Both modules hardcoded `sqlite3.connect(DB_PATH)` internally (unlike `sector_signals.py`'s
  already-`conn`-based per-date function) — a small conn-injection refactor
  (`scan_boring_breakouts` / `update_open_signal_statuses` / `append_leaders_scan` /
  `save_top_picks` / `fill_leaders_forward_returns` all take an optional `conn=`, default
  behaviour unchanged) makes them reusable **verbatim by import** the same way. Two dialect
  fixes (`date('now','-4 days')`, `date(?,'-120 days')` → Python-computed) + one
  engine-robustness fix (`cur.rowcount` is always `-1` on DuckDB's DBAPI, unlike SQLite's real
  0/1 — replaced with a before/after `COUNT(*)` diff). `_medallion_views` gained a `prices`
  (Bronze, raw/unadjusted) VIEW — both modules read raw prices for several to-the-day
  computations. Gold owns its own DuckDB DDL (SEQUENCE-backed `id`, DOUBLE not INTEGER for
  nominally-int columns, natural key as the sole PRIMARY KEY — DuckDB's `INSERT OR REPLACE`
  can't infer a conflict target with two unique constraints). `boring_signals` scans from its
  own 2026-07-10 go-live floor, not Gold's full window; `leaders_scan` depends on
  `stock_signals` + `sector_signals` already built in the same run. **Parity = RECOMPUTE-based
  for both (the method 3.3c needed, applied here from the start), `status: clean`:**
  `boring_signals` full-window recompute, every column matches; `leaders_scan` 30-day-window
  recompute, cell-for-cell match; `leaders_top_picks`' one residual class (a symbol swap from
  an exact `(final_score, vol_ratio_today)` tie in `save_top_picks()`'s own `ORDER BY`, which
  has no further tiebreak) is confirmed against Gold's own `leaders_scan` pool and classified
  `tie_break_residual`, not counted against `clean` — a pre-existing query characteristic, not
  a port bug. `mark_executed`/`executed`/`dedup_conflict` are human dashboard actions outside
  Gold's automated build by construction. 1 test (13 total).
- **3.3e — DONE (2026-09-11).** `recovery_signals` + `portfolio_signals` + `setup_log`.
  `trade_setups`/`processor.py` deliberately NOT ported — `processor.run_analysis()` hardcodes
  `support_setups = []` since 2026-07-23 (Support Reversal killed, -1.88% net full-history
  retest); its only automated writer is dead code, nothing live to port. Neither
  `run_recovery_signals()` nor `run_portfolio_signals()` is `conn`-based (unlike every other
  3.3x port target) — an **extract-method** refactor pulled `signal_engine.py`'s pure per-symbol
  recovery scan out into `_scan_recovery_candidates(all_df, all_dates, kse_regime_ok,
  last_recovery_as_of)`; a **parameter-injection** refactor gave `portfolio.py`'s
  `compute_portfolio_candidates()` optional `prices_df=`/`kse_df=` (every existing caller
  omits them, unchanged behaviour). `backfill_setup_log._insert_setup_log_for_date` needed zero
  logic changes (already `cur`-based) but one portability guard (`if rows:` before
  `executemany` — DuckDB raises on an empty parameter list, SQLite no-ops); `compute_forward_
  returns.main()` got the same `conn=` injection as 3.3d's targets. **Scope decision:
  `recovery_signals`/`portfolio_signals` compute the LATEST date only**, not a window backfill
  — the reused functions have no target-date parameter, and live's own tables (checked directly)
  hold only 23 sparse `as_of_date`s over 3 months, not a dense daily series;
  `dashboard.py` only ever reads `MAX(as_of_date)`. Parity = RECOMPUTE-based for all three,
  `status: clean` on a real scoped build against live production data: `recovery_signals`
  (2/2 rows, 16 cols), `portfolio_signals` (308/308 rows, 16 cols), `setup_log` (2,755/2,755
  rows across 41 dates, 15 cols) — 0 mismatches each. 1 test (14 total). Full detail: tracker §10.
- **3.3f** — front-end JSON export, full end-to-end idempotency, consolidated parity report.
