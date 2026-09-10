# `data/incoming/` — contemporaneous PSX scrape captures (local-first Phase 2)

One immutable Parquet file per PSX trading date, `YYYY-MM-DD.parquet`, plus a
freely-overwritten `latest.parquet` copy of the newest. Written by
[`.github/workflows/scrape_capture.yml`](../../.github/workflows/scrape_capture.yml),
which runs `python -m archive.scrape_capture`.

- **Immutable.** A dated file is written once and never rewritten. It is the
  audit record — the contemporaneous-capture evidence standard the Data
  Rehabilitation program found missing for 2005–2019 (PG-4).
- **Parallel, additive.** This path does not touch `psx_data.db`, Supabase, or
  `daily_scraper.yml`. Those keep running unchanged until the migration's Phase 6
  cutover ([`docs/KIRAN_LOCAL_FIRST_MIGRATION.md`](../../docs/KIRAN_LOCAL_FIRST_MIGRATION.md)).
- **Consumed by** the Bronze ingest in Phase 3 (`git pull` → append, dedupe,
  gap-detect, recording which files and hashes it consumed).
- **Retention (owner decision D4):** pruned to `psx-data-archive` after ~90 days,
  but only after a copy check + SHA-256 + a real retrieval + a manifest prove
  every pruned file is preserved. No prune without that evidence.

File format and metadata: [`docs/KIRAN_LOCAL_FIRST_ARCHIVE/CAPTURE_FILES.md`](../../docs/KIRAN_LOCAL_FIRST_ARCHIVE/CAPTURE_FILES.md).
