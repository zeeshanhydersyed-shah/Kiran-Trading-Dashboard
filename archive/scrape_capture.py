r"""
Kiran Local-First Migration -- Phase 2: contemporaneous PSX scrape capture.

A SECOND, parallel scrape path. Fetches the ksestocks.com Market Summary for the
source date the site is currently publishing and writes it to the repo as an
immutable Parquet capture file:

    data/incoming/YYYY-MM-DD.parquet   one per source date, written once, never rewritten
    data/incoming/latest.parquet       a copy of the newest, overwritten freely

This is the contemporaneous capture log the Data Rehabilitation program found
missing for 2005-2019 (PG-4): a timestamped, hash-verifiable record of exactly
what the source served on the day, committed to git as it happened.

It does NOT touch ``psx_data.db``, Supabase, or the existing ``daily_scraper.yml``
pipeline -- those keep running unchanged until the migration's Phase 6 cutover
(tracker: docs/KIRAN_LOCAL_FIRST_MIGRATION.md).

Reuses ``scraper.py``'s fetch + parse (``get_source_date`` / ``scrape_date`` /
``parse_sector_counts``) -- the capture reflects what ``scraper.py`` parses
(light sanity coercion + non-equity filtering), not the raw HTML bytes. The exact
parser version is recorded in each file's metadata (``scraper_sha256``).

Idempotent: if ``data/incoming/<source_date>.parquet`` already exists this is a
clean no-op. Safe to run on the same redundant cron slots as ``daily_scraper.yml``.

    python -m archive.scrape_capture [--out-dir DIR] [--date YYYY-MM-DD] [--force]

Outcomes (printed as JSON, and written to $GITHUB_OUTPUT when set):
    written      a new dated capture file was created
    exists       the file for this source date already exists -- nothing done
    nodata       source date resolved but it is a holiday / no-data day
    unreachable  ksestocks could not be reached / no source date could be parsed

Exit code is 0 for every outcome (a missed capture is caught later as a gap in
data/incoming/, exactly like daily_scraper.yml's redundant-attempts design). Only
an unexpected exception exits non-zero.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import config
import scraper
from serving_revision import resolve_code_version

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "incoming"
CAPTURE_SCHEMA_VERSION = "1"

# Matches archive/build_store.py so the Phase 3 Bronze ingest reads one convention.
PARQUET_OPTS = dict(compression="zstd", version="2.6", use_dictionary=True)

SCHEMA = pa.schema([
    ("record_type", pa.string()),   # "stock" | "index"
    ("symbol", pa.string()),
    ("trading_date", pa.string()),  # YYYY-MM-DD, the source date
    ("open", pa.float64()),
    ("high", pa.float64()),
    ("low", pa.float64()),
    ("close", pa.float64()),
    ("volume", pa.int64()),          # null for index rows
    ("sector", pa.string()),         # null for index rows
])
_COLUMNS = [f.name for f in SCHEMA]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows_from_scrape(sector_rows, price_rows, index_rows) -> list[dict]:
    """Flatten scraper.py's 3 lists into one sorted list of capture records.

    price_rows : (symbol, date_str, high, low, close, volume, open)
    index_rows : (symbol, date_str, high, low, close, open)
    sector_rows: (symbol, sector)
    """
    sector_map = dict(sector_rows)
    recs: list[dict] = []
    for sym, date_str, high, low, close, volume, open_ in price_rows:
        recs.append({
            "record_type": "stock", "symbol": sym, "trading_date": date_str,
            "open": float(open_), "high": float(high), "low": float(low),
            "close": float(close), "volume": int(volume),
            "sector": sector_map.get(sym),
        })
    for sym, date_str, high, low, close, open_ in index_rows:
        recs.append({
            "record_type": "index", "symbol": sym, "trading_date": date_str,
            "open": float(open_), "high": float(high), "low": float(low),
            "close": float(close), "volume": None, "sector": None,
        })
    recs.sort(key=lambda r: (r["record_type"], r["symbol"]))
    return recs


def _table(recs: list[dict], meta: dict) -> pa.Table:
    cols = {c: [r[c] for r in recs] for c in _COLUMNS}
    t = pa.table(cols, schema=SCHEMA)
    md = {str(k): str(v) for k, v in meta.items() if v is not None}
    return t.replace_schema_metadata(md)


def _coverage_status(expected_total, parsed_total) -> str:
    if expected_total is None:
        return "UNKNOWN"
    if parsed_total is not None and parsed_total >= expected_total:
        return "COMPLETE"
    return "INCOMPLETE"


def capture(out_dir: Path, date_override: dt.date | None = None,
            force: bool = False) -> dict:
    """Fetch the current source date (or ``date_override``) and write its capture
    file into ``out_dir``. Returns a result dict with an ``outcome`` key."""
    session = scraper.build_session()

    if date_override is not None:
        source_date = date_override
    else:
        source_date = scraper.get_source_date(session)
        if source_date is None:
            return {"outcome": "unreachable", "source_date": None}

    ds = source_date.isoformat()
    target = out_dir / f"{ds}.parquet"
    if target.exists() and not force:
        return {"outcome": "exists", "source_date": ds, "path": str(target),
                "sha256": _sha256(target)}

    cov: list = []
    sector_rows, price_rows, index_rows = scraper.scrape_date(
        source_date, session, coverage_out=cov)

    if not price_rows and not index_rows:
        return {"outcome": "nodata", "source_date": ds}

    recs = _rows_from_scrape(sector_rows, price_rows, index_rows)
    covd = cov[0] if cov else {}
    expected_total = covd.get("expected_total")
    parsed_total = covd.get("parsed_total")
    coverage_status = _coverage_status(expected_total, parsed_total)

    n_stock = sum(1 for r in recs if r["record_type"] == "stock")
    n_index = sum(1 for r in recs if r["record_type"] == "index")
    n_sector = len({r["sector"] for r in recs if r["sector"]})

    run_id = os.environ.get("GITHUB_RUN_ID", "")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id and repo else ""

    meta = {
        "capture_schema_version": CAPTURE_SCHEMA_VERSION,
        "source_date": ds,
        "scraped_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_url": config.MARKET_SUMMARY_URL,
        "actions_run_id": run_id,
        "actions_run_url": run_url,
        "actions_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "code_version": resolve_code_version() or "",
        "scraper_sha256": _sha256(Path(scraper.__file__)),
        "stock_rows": n_stock,
        "index_rows": n_index,
        "sector_count": n_sector,
        "expected_total": "" if expected_total is None else expected_total,
        "parsed_total": "" if parsed_total is None else parsed_total,
        "coverage_detail": covd.get("detail") or "",
        "coverage_status": coverage_status,
        "date_override": "true" if date_override is not None else "false",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    tbl = _table(recs, meta)
    tmp = out_dir / f".{ds}.parquet.tmp"
    pq.write_table(tbl, tmp, **PARQUET_OPTS)
    os.replace(tmp, target)

    # latest.parquet points at the newest dated capture only -- never regress it
    # when a --date backfill fills an older gap.
    dated = sorted(p.stem for p in out_dir.glob("*.parquet") if p.stem != "latest")
    if dated and ds >= dated[-1]:
        shutil.copyfile(target, out_dir / "latest.parquet")
        latest_refreshed = True
    else:
        latest_refreshed = False

    return {
        "outcome": "written", "source_date": ds, "path": str(target),
        "stock_rows": n_stock, "index_rows": n_index, "sector_count": n_sector,
        "coverage_status": coverage_status, "coverage_detail": covd.get("detail") or "",
        "sha256": _sha256(target), "latest_refreshed": latest_refreshed,
    }


_GITHUB_OUTPUT_KEYS = ("outcome", "source_date", "stock_rows", "index_rows",
                       "sector_count", "coverage_status", "sha256")


def _emit_github_output(result: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for k in _GITHUB_OUTPUT_KEYS:
            v = result.get(k)
            if v is not None:
                f.write(f"{k}={v}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Capture the current PSX scrape to an immutable Parquet file.")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                    help=f"target directory (default: {DEFAULT_OUT_DIR})")
    ap.add_argument("--date", help="capture a specific YYYY-MM-DD instead of the current source date (backfill)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing dated file (default: refuse -- captures are immutable)")
    args = ap.parse_args(argv)

    date_override = dt.date.fromisoformat(args.date) if args.date else None
    result = capture(Path(args.out_dir), date_override=date_override, force=args.force)

    print(json.dumps(result, indent=2, sort_keys=True))
    _emit_github_output(result)

    outcome = result["outcome"]
    if outcome == "unreachable":
        print("::warning::scrape_capture: ksestocks source unreachable / no source "
              "date parsed -- will retry on the next slot")
    elif outcome == "nodata":
        print(f"::notice::scrape_capture: {result['source_date']} is a no-data day "
              "(holiday / weekend) -- nothing to capture")
    return 0


if __name__ == "__main__":
    sys.exit(main())
