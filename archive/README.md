# `archive/` — Kiran Local-First Migration, Phase 1 tooling

Preservation-only utilities that build and verify the **immutable historical
baseline** (DR-program SEQ-1). Tracker: [`docs/KIRAN_LOCAL_FIRST_MIGRATION.md`](../docs/KIRAN_LOCAL_FIRST_MIGRATION.md).

**Owner decision D7 (2026-09-09): preservation only.** Nothing here writes to
`psx_data.db` or mutates / corrects / re-scrapes a historical row. The scripts
read the live DB read-only, or read a frozen `.db` copy.

## The archive

Lives **off-repo** at `D:\KIRAN_ARCHIVE\` (override with `KIRAN_ARCHIVE_ROOT`) —
C: is space-constrained. Only the manifest (`docs/KIRAN_LOCAL_FIRST_ARCHIVE/
BASELINE_MANIFEST.{md,sha256}`) is committed to git.

```
D:\KIRAN_ARCHIVE\
  baseline\      whole-DB point-in-time snapshot (all 53 tables) + capture report JSON
  bronze\        raw OHLCV as Parquet: prices/, index_prices/  (year= partitions)
  silver\        prices_adjusted/ (year=), sectors.parquet, stock_metadata.parquet
  backup_set\    folded-in prior frozen artifacts:
                   dr006_rehabilitation_baseline\   (DR-006, 2026-09-04)
                   bi_source_preservation_20260903\ (DR-003 Phase A, 17 files)
  STORE_MANIFEST.json
  BASELINE_MANIFEST.{sha256,md}   (copies; the git-committed ones are canonical)
```

## Scripts

| Command | What it does |
|---|---|
| `python -m archive.capture_baseline` | Capture + verify a fresh whole-DB baseline (SQLite Online Backup API; row-count + date-span + `integrity_check` vs live). Caller establishes quiescence — see the module docstring. |
| `python -m archive.build_store [BASELINE_DB]` | Materialise the Bronze/Silver Parquet store from a frozen baseline `.db` (deterministic, re-run = byte-identical). |
| `python -m archive.archive_manifest generate` | (Re)write `BASELINE_MANIFEST.{sha256,md}` from the current archive tree. |
| `python -m archive.archive_manifest verify` | Re-hash every file, compare to the committed `.sha256`. Exit 1 on drift. |
| `python -m archive.archive_checksum_check` | `verify` + ntfy alert on drift. For Task Scheduler (`KIRAN_Archive_Checksum`, weekly). |
| `python -m archive.scrape_capture [--date YYYY-MM-DD] [--force]` | **Phase 2.** Fetch the current PSX source date and write an immutable `data/incoming/YYYY-MM-DD.parquet` capture file (+ refresh `latest.parquet`). Reuses `scraper.py`'s fetch/parse; idempotent; never touches `psx_data.db`. Run by `.github/workflows/scrape_capture.yml`. Format: [`../docs/KIRAN_LOCAL_FIRST_ARCHIVE/CAPTURE_FILES.md`](../docs/KIRAN_LOCAL_FIRST_ARCHIVE/CAPTURE_FILES.md). |

## Deps

`pip install -r ../requirements-archive.txt` (pyarrow). `duckdb` is deferred to
Phase 3 — no cp314 wheel yet.

## Off-site

The B2 Object-Lock copy and the widened restore drill (`restore_drill_b2.py`)
are the other two legs. See the tracker §5 Phase 1 checklist.
