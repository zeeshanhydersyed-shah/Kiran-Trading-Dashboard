# `data-captures` — Kiran contemporaneous PSX scrape captures

**This is a data-only orphan branch. It shares no history with `main` and holds no code.**

Local-first migration, Phase 2 (tracker: `docs/KIRAN_LOCAL_FIRST_MIGRATION.md` on `main`).

## What is here

`data/incoming/YYYY-MM-DD.parquet` — one immutable Parquet file per PSX trading
date, plus `data/incoming/latest.parquet` (a freely-overwritten copy of the
newest). Written by `.github/workflows/scrape_capture.yml` on `main`, which runs
`python -m archive.scrape_capture` and commits the result here.

- **Immutable.** A dated file is written once and never rewritten — the
  contemporaneous, hash-verifiable capture record the Data Rehabilitation program
  found missing for 2005–2019 (PG-4).
- **On its own branch, not `main`.** `main` is branch-protected (required checks,
  admins included); data-only commits can't satisfy those checks. Keeping captures
  here means the scrape workflow never fights branch protection, and code history
  on `main` stays clean.
- **Consumed by** the Phase 3 Bronze ingest — a `git pull` (or a
  `--single-branch` clone) of this branch, then append / dedupe / gap-detect,
  recording which files and hashes it consumed.
- **Retention (owner decision D4):** pruned to `psx-data-archive` after ~90 days,
  only after a copy check + SHA-256 + a real retrieval + a manifest prove
  preservation.

## File format

See `docs/KIRAN_LOCAL_FIRST_ARCHIVE/CAPTURE_FILES.md` **on `main`** for the row
schema and the per-file metadata.

## Getting just the captures

```
git clone --branch data-captures --single-branch \
  https://github.com/zeeshanhydersyed-shah/Kiran-Trading-Dashboard.git captures
```
