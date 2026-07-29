# Data Acquisition Architecture

This document is architectural memory, not a how-to. It exists so that a
future Claude Code session or human contributor understands *why* the Open
price acquisition work is structured the way it is, without having to
re-derive it from scratch.

Related: [`docs/DECISIONS.md`](DECISIONS.md) (entry 2026-07-03) records this
as a formal engineering decision. `CLAUDE.md` has a short pointer to this file
under "Recent Changes."

---

## Background

The production database (`psx_data.db`) contains PSX daily OHLCV data from
2005 onward. The **Open** price was never populated for the historical range.

This was an **implementation oversight, not a source limitation.** The source
(`ksestocks.com/MarketSummary`) has always returned Open in every response —
it was simply never parsed out. See Investigation Findings below.

---

## Investigation Findings (2026-07-03)

1. **Open already exists as a schema column** in `prices`, `prices_adjusted`,
   and `index_prices`. No schema migration is needed — this is a data
   population gap, not a structural one.

2. **Historical coverage is incomplete and uneven**, not a clean binary
   missing/present split:

   | Years | Open coverage in `prices` |
   |---|---|
   | 2005–2019 | 0% — fully missing |
   | 2020–2023 | 100% — fully populated |
   | 2024 | ~74% populated |
   | 2025 | ~73% populated |
   | 2026 (to date) | ~13% populated, cutoff ~2026-06-05 |

3. **The 2020–2026 Open values have uncertain provenance.** `CLAUDE.md`
   documents a one-off historical merge from a separate local BI PostgreSQL
   database via `merged_psx_data.csv` / `load_bi_history.py`. But
   `load_bi_history.py`'s current code, and `upsert_prices()` in
   `database.py`, **do not read or write an `open` value at all** — and git
   history shows only one commit for `load_bi_history.py`, which never
   touched `open`. The ~462K populated rows were not produced by any code
   currently in the repository — most likely a raw one-off `UPDATE`, run
   directly and never committed. **This data is not reproducible from the
   current codebase and should not be treated as ground truth.**

4. **The production scraper skips a column that's already in the response.**
   `scraper.py`'s own docstring documents the row layout as `Symbol, Company,
   Open, High, Low, Close, Change, Vol` (`scraper.py:254`) — Open is
   `cells[2]`. But `parse_market_summary()` only ever reads `cells[3]`
   (high), `cells[4]` (low), `cells[5]` (close) — `scraper.py:315-317`. Open
   sits in every response and is simply never extracted. The three historical
   backfill scripts (`scrape_2005_2010.py`, `scrape_2010_2015.py`,
   `scrape_historical_2015_2020.py`) hit the same URL with the same row
   layout and hardcode `open=None` in their output tuples — confirming the
   full 2005–2019 range is recoverable from the same source via the same
   mechanism, just extracting one more cell.

5. **The corporate-action adjustment pipeline already supports Open.**
   `apply_price_adjustments.py` multiplies `open` by the same factor as
   `high`/`low`/`close` in both its incremental and full-rebuild paths
   (`apply_price_adjustments.py:95`, `:320`). No pipeline change is required
   once raw Open values exist — this was previously assumed to be a gap and
   is not.

6. **Downstream code already treats Open defensively.**
   `get_sector_price_data()` in `database.py`/`database_pg.py` does
   `COALESCE(p.open, p.close) AS open`, and `processor.py:301` does
   `latest.get("open", close)`. Nothing breaks whether Open is NULL or
   populated.

---

## Architectural Decision: Six Independent Phases

This work is deliberately split into six phases, each with a single
responsibility and a hard boundary at each transition:

1. **Data acquisition** — scrape raw Open prices from the original source.
2. **Data validation** — per-record sanity checks (numeric, positive, within
   the day's High–Low range).
3. **Human review** — a person looks at the audit report and CSVs before
   anything touches the production database.
4. **Database import** — a separate, later utility applies only the
   human-approved data to `prices`, with a guard that never overwrites an
   existing value.
5. **Corporate-action adjustment** — the existing `apply_price_adjustments.py`
   machinery picks up the new raw Open values automatically; this phase is
   not modified or re-triggered manually.
6. **Research** — only after the above, Open becomes available to research
   and screener code.

**This separation must not be collapsed into a single script.** A script that
scrapes, validates, and writes to `psx_data.db` in one pass removes the human
review checkpoint and makes a bad batch of scraped data immediately live in
research infrastructure. Each phase boundary exists specifically to prevent
that.

---

## Guiding Principle

> **The production database is considered research infrastructure. It
> should never be modified by experimental scripts.**

All new datasets are acquired independently, validated independently, and
approved by a human before any import into the production database. This
applies beyond the Open price project — it's the standing rule for any future
data acquisition work in this repository.

---

## The Open Price Acquisition Tool

`acquire_open_prices.py` (project root) has a single responsibility:

- acquire raw Open prices for every trading date, 2005 → today, directly from
  `ksestocks.com/MarketSummary`
- validate each record (numeric, positive, within High–Low range)
- compare each record against the existing `psx_data.db` (read-only) and
  surface discrepancies — informational only, never corrective
- produce an authoritative, independent CSV dataset plus a full audit log and
  a JSON summary report (row counts, mismatch counts, SHA-256 checksums of
  the output files)

It does **not** update `psx_data.db`. It has no import capability at all —
that is intentionally a separate, not-yet-built utility, to be designed after
manual review of this tool's output. See `docs/DECISIONS.md` for why this
tool has zero code coupling to `scraper.py`/`config.py`/`database.py`
(constants and parsing logic are deliberately duplicated) and why its only
database interaction is a self-testing read-only connection.

---

## Design Philosophy

Future contributors — human or Claude Code — should understand this
architecture was chosen because, in this project specifically:

- **Reproducibility is more important than convenience.** The 2020–2026 Open
  data is a cautionary example: convenient at the time, but six weeks later
  nobody — including the codebase itself — can explain how it got there or
  whether it's trustworthy. New acquisitions must be re-derivable from the
  script that produced them.
- **Auditability is more important than automation.** A fully automated
  scrape-validate-import pipeline would be faster to build, but it would
  produce exactly the kind of unverifiable state that prompted this project
  in the first place. Every acquisition run produces a checksummed,
  timestamped audit trail specifically so that question never recurs.
- **Preserving research integrity is more important than minimizing
  engineering effort.** `psx_data.db` backs active research (see
  `ZH_research/` experiments in `CLAUDE.md`). A bad write there doesn't just
  cost time to fix — it can silently invalidate conclusions already drawn
  from it.

Any change to the production database must remain **deliberate, reviewable,
and reversible.** If a future task looks like it could be done faster by
skipping the human-review checkpoint or merging phases, that pressure should
be treated as a signal to slow down, not a reason to do it.
