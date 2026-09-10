# Scrape capture files — format (`data/incoming/*.parquet`)

Local-first migration, Phase 2. Produced by `archive/scrape_capture.py` via
`.github/workflows/scrape_capture.yml`. Tracker:
[`../KIRAN_LOCAL_FIRST_MIGRATION.md`](../KIRAN_LOCAL_FIRST_MIGRATION.md).

## What a capture is

A single Parquet table holding **every stock and index row** ksestocks.com's
Market Summary served for one source date, as parsed by `scraper.py`
(`get_source_date` → `scrape_date` → `parse_market_summary` / `parse_sector_counts`).

It reflects `scraper.py`'s **parse output**, not the raw HTML bytes: the same
light sanity coercion the live pipeline applies (`high = max(high, close)`,
`low = min(low, close)`, blank/unparseable `open` falls back to `close`,
`close <= 0` rows dropped) and the same non-equity filter (futures, government
paper `P0x`, `786`/`786R`). The exact parser is pinned per file by
`scraper_sha256` in the metadata.

`latest.parquet` is a byte copy of the highest-dated capture, refreshed on every
new capture and **never regressed** by a `--date` backfill of an older gap. It is
a convenience pointer; the dated files are the record.

## Row schema

| column | type | notes |
|---|---|---|
| `record_type` | string | `stock` or `index` |
| `symbol` | string | |
| `trading_date` | string | `YYYY-MM-DD`, the source date (never the wall clock) |
| `open` | float64 | |
| `high` | float64 | |
| `low` | float64 | |
| `close` | float64 | |
| `volume` | int64 | null for `index` rows |
| `sector` | string | null for `index` rows; ksestocks' sector for `stock` rows |

Rows are sorted by `(record_type, symbol)` before writing, so a `--force`
re-capture of the same scrape produces byte-identical **data** (the file-level
metadata still differs — it carries a fresh `scraped_at_utc`).

Compression `zstd`, Parquet format version `2.6` — matches `archive/build_store.py`.

## File-level metadata (Parquet schema metadata)

All values are strings.

| key | meaning |
|---|---|
| `capture_schema_version` | `1` |
| `source_date` | the date this file captures |
| `scraped_at_utc` | when the fetch ran (ISO 8601, seconds) — audit only, never a data label |
| `source_url` | `config.MARKET_SUMMARY_URL` |
| `actions_run_id` / `actions_run_url` / `actions_run_attempt` | the GitHub Actions run that produced it (`""` for a local run) |
| `code_version` | commit SHA of the code that ran (`$GITHUB_SHA` on a runner, else `.git/HEAD`), or `""` |
| `scraper_sha256` | SHA-256 of the `scraper.py` that parsed this capture |
| `stock_rows` / `index_rows` / `sector_count` | self-reported counts |
| `expected_total` / `parsed_total` | ksestocks' own per-sector "Number of traded companies" sum vs. rows actually present in the HTML (TR-14 completeness) — `""` if the page stated none |
| `coverage_detail` | names any sector where `parsed < stated`, else `""` |
| `coverage_status` | `COMPLETE` (`parsed_total >= expected_total`), `INCOMPLETE`, or `UNKNOWN` (no stated counts) |
| `date_override` | `true` if produced by `--date` backfill, else `false` |

Read them with:

```python
import pyarrow.parquet as pq
meta = pq.read_schema("data/incoming/2026-09-09.parquet").metadata
{k.decode(): v.decode() for k, v in meta.items()}
```

## Outcomes

`scrape_capture.py` prints a JSON result and (on a runner) writes the same keys
to `$GITHUB_OUTPUT`. `outcome` is one of:

| outcome | meaning | workflow action |
|---|---|---|
| `written` | a new dated file was created | commit + push to the `data-captures` branch |
| `exists` | the file for this source date already exists | nothing |
| `nodata` | source date resolved but it is a holiday / weekend | nothing (`::notice::`) |
| `unreachable` | ksestocks could not be reached / no source date parsed | nothing (`::warning::`) |

Exit code is `0` for all four — a missed capture surfaces later as a gap in
`data/incoming/`, which the Phase 3 Bronze ingest gap-detects. This mirrors
`daily_scraper.yml`'s "redundant attempts, not one perfectly-timed run" design.

## Where captures are committed — the `data-captures` branch

Captures go to a dedicated **`data-captures` orphan branch**, never `main`:

- `main` is branch-protected — required status checks, `enforce_admins` on. A
  data-only commit produces none of those checks, so a push to `main` (even a
  bot's, even `[skip ci]`) is rejected. `data-captures` is unprotected, so the
  workflow never fights branch protection.
- The branch shares **no history with `main`** and holds only
  `data/incoming/*.parquet` + a README. Code history on `main` stays clean.
- `scrape_capture.yml` checks out `main` (into `code/`) for the scraper code and
  `data-captures` (into `captures/`) for the commit target, side by side. The
  script writes into `captures/data/incoming/`; the commit + push happens from
  that checkout.
- **Phase 3 Bronze ingest** reads this branch — `git pull origin data-captures`
  in its own checkout, or a `git clone --branch data-captures --single-branch`.
- **Recommended (not yet done):** protect `data-captures` against force-push and
  deletion — it aligns with the "immutable capture record" intent. Requires an
  owner repo-settings change.
- `daily_scraper.yml` is `schedule` + `workflow_dispatch` only — nothing here can
  perturb the live pipeline. `ci.yml` triggers on `main` / `staging` only, so the
  `data-captures` commits run no CI.

### First-run prerequisite

The `data-captures` branch must exist before the workflow runs. It was created
2026-09-10 as an orphan branch with an initial README-only commit
(`git checkout --orphan data-captures`).
