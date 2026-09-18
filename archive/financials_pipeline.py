r"""
Kiran Local-First Migration -- Financials/Announcements Pipeline (PROPOSED, new
2026-09-18 -- not wired into anything automated yet).

Ingests PSX corporate-announcement data (financial results EPS/PBT/PAT both
bases, cash dividend/bonus %, AGM date, book closure from/to) from the
ksestocks.com per-symbol announcements pages into a standalone Bronze/Silver/Gold
store, fully decoupled from the main Kiran pipeline -- same isolation precedent as
``archive/ca_v2_prototype.py``. Design doc: docs/FINANCIALS_PIPELINE_DESIGN.md.

Zero scope contamination (design doc Section 2), restated here because it is the
whole reason this is a separate module:
  - Never imports/calls bronze_ingest.py, silver_build.py, or gold_build.py.
  - Never opens psx_serving.duckdb, Bronze, Silver, psx_data.db, Supabase, or
    shadow_diff.duckdb.
  - Own, separate store root: D:\KIRAN_ARCHIVE\financials_archive\
  - Not called from nightly_run.py, not in shadow_diff.py's EVERY_SESSION list.

Two run modes, same code path (Section 7 of the design doc):
  - ``backfill``: reads the EXISTING cached HTML at ca_pipeline_kse100_20260907's
    announcements_cache/ (read-only, never written to) -- the one-time historical
    load, no network access.
  - ``daily``: fetches fresh HTML directly from ksestocks.com itself (a fresh,
    self-contained implementation of the same request shape verified in that
    sibling project's l0_fetch_announcements.py/common.py -- reused as a *pattern*,
    not imported cross-repo, since that directory is an unversioned research
    scratch space, not a stable package). Writes fetched HTML straight into this
    module's own Bronze, never into the sibling announcements_cache/ directory.
    Deliberately has NO response cache at all (a simplification from the design
    doc's original "override ttl_hours on the reused common.http()" plan, made
    possible by not reusing that function in the first place) -- every daily
    call is a real request, so "daily" can never silently degrade into "whatever
    a stale cache last returned."

Change-triggered, crash-safe increment (Section 4.1/4.2 of the design doc):
  - Bronze: a symbol's fetched HTML is stored as a new dated artifact only when
    its content differs from the last thing captured for that symbol.
  - Silver reprocessing decision is made against ``promoted_bronze_hashes``, a
    small table stored INSIDE the same serving DuckDB file that gets atomically
    swapped alongside stock_announcements/corporate_actions -- not against "the
    latest Bronze artifact on disk". This matters for crash safety: if the
    process dies after writing a Bronze artifact but before the atomic promote,
    a re-run's change-detection still compares against the last *promoted*
    state (unchanged), so that symbol is correctly picked up again rather than
    silently lost.

    python -m archive.financials_pipeline --mode backfill|daily
        [--store-root DIR] [--cache-dir DIR] [--ledger-db PATH] [--symbols-file PATH]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd

from archive import financials_parser
from archive.bronze_ingest import ARCHIVE_ROOT, _now

REPO_ROOT = Path(__file__).resolve().parent.parent

# The CA pipeline's own directory -- a sibling research project, not part of
# psx_pipeline. Read-only for `backfill` mode's HTML cache and the reused
# corporate-actions ledger; never written to. Overridable so tests can point
# at a synthetic fixture.
CA_PIPELINE_DIR = REPO_ROOT.parent / "ZH_Research_PSX" / "trading_edge_program" / "ca_pipeline_kse100_20260907"
DEFAULT_CACHE_DIR = CA_PIPELINE_DIR / "announcements_cache"
DEFAULT_LEDGER_DB = CA_PIPELINE_DIR / "full_ca_ledger.sqlite"

_FETCH_URL = "https://www.ksestocks.com/Announcements"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
SLEEP_SECONDS = 1.0  # politeness delay between live fetches, daily mode only

_STOCK_ANNOUNCEMENTS_DDL = """CREATE TABLE IF NOT EXISTS stock_announcements (
    symbol TEXT, announce_date TEXT, row_index INTEGER,
    fiscal_period_type TEXT, fiscal_period_ended TEXT,
    eps_consolidated DOUBLE, eps_unconsolidated DOUBLE, eps_unspecified DOUBLE,
    eps_basis_inferred BOOLEAN,
    pbt_consolidated DOUBLE, pbt_unconsolidated DOUBLE, pbt_unspecified DOUBLE,
    pat_consolidated DOUBLE, pat_unconsolidated DOUBLE, pat_unspecified DOUBLE,
    dividend_pct DOUBLE, dividend_is_nil BOOLEAN, dividend_flag TEXT,
    bonus_pct DOUBLE, agm_date TEXT, book_closure_from TEXT, book_closure_to TEXT,
    raw_text TEXT, parse_confidence TEXT, parse_notes TEXT, source_row_sha256 TEXT,
    PRIMARY KEY (symbol, announce_date, row_index))"""

_CA_NUMERIC_COLS = ("bonus_pct", "rights_pct", "rights_price", "div_per_share",
                    "dividend_pct_face_value", "price_factor", "expected_drop",
                    "observed_drop", "observed_ratio", "index_neutral_move_pct")


# ---------------------------------------------------------------------- store

class Store:
    """Mirrors archive.ca_v2_prototype.CaV2Store's layout convention, in its
    own root -- see module docstring for the isolation guarantee this gives."""

    def __init__(self, root: Path):
        self.root = root
        self.bronze_dir = root / "bronze" / "announcements"
        self.db = root / "financials_serving.duckdb"
        self.staging = root / "financials_serving_staging.duckdb"
        self.ingest_log = root / "_bronze_ingest_log.jsonl"
        self.build_log = root / "_financials_build_log.jsonl"

    def latest_bronze_path(self, symbol: str) -> Path | None:
        candidates = sorted(self.bronze_dir.glob(f"date=*/{symbol}.html"))
        return candidates[-1] if candidates else None

    def log_ingest(self, entry: dict) -> None:
        self.ingest_log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ingest_log, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")

    def log_build(self, entry: dict) -> None:
        self.build_log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.build_log, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", (name,)).fetchone())


# --------------------------------------------------------------------- fetch

def list_cached_symbols(cache_dir: Path) -> list[str]:
    if not cache_dir.exists():
        raise SystemExit(f"announcements cache not found: {cache_dir}")
    return sorted(p.stem for p in cache_dir.glob("*.html"))


def fetch_symbol_live(symbol: str, *, from_date: str = "01/01/2005",
                      to_date: str | None = None) -> str:
    """Real network fetch -- one POST returns the symbol's entire announcement
    history. Field NAMES verified against ca_pipeline_kse100_20260907/scripts/
    common.py's http()/l0_fetch_announcements.py; the exact date FORMAT for
    sdate/rfdate/rtdate was not independently re-verified against a live
    request (this pipeline has not made one yet) -- worth confirming on the
    first real `--mode daily` run before trusting it unattended.
    No response cache, deliberately (see module docstring)."""
    to_date = to_date or dt.date.today().strftime("%d/%m/%Y")
    data = {"dtype": "byscrip", "sdate": to_date, "ssym": symbol,
           "rfdate": from_date, "rtdate": to_date, "mansear": ""}
    body = urllib.parse.urlencode(data).encode()
    headers = {"User-Agent": _UA, "Accept": "*/*",
              "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
              "X-Requested-With": "XMLHttpRequest"}
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(_FETCH_URL, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_exc = e
            if e.code == 429:
                wait = e.headers.get("Retry-After")
                time.sleep(min(float(wait), 90) if wait else min(20 * (attempt + 1), 90))
            elif e.code == 404:
                raise
            else:
                time.sleep(1.5 * (attempt + 1))
        except Exception as e:  # noqa: BLE001 -- retried below, re-raised after exhaustion
            last_exc = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed for {symbol} after 5 attempts: {last_exc}")


# --------------------------------------------------------------------- bronze

def _bronze_capture_if_changed(store: Store, symbol: str, html_text: str, capture_date: str) -> str:
    """Writes a new dated, immutable Bronze artifact only if `html_text`
    differs from the last one captured for this symbol. Returns the new
    content's sha256 regardless (used by the crash-safe Silver-change check,
    which compares against `promoted_bronze_hashes`, not against this)."""
    new_hash = _sha256_text(html_text)
    prev_path = store.latest_bronze_path(symbol)
    prev_hash = _sha256_text(prev_path.read_text(encoding="utf-8", errors="replace")) if prev_path else None
    if new_hash == prev_hash:
        return new_hash

    dest_dir = store.bronze_dir / f"date={capture_date}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{symbol}.html"
    tmp = dest.with_suffix(".html.tmp")
    tmp.write_text(html_text, encoding="utf-8")
    os.replace(tmp, dest)

    store.log_ingest({"ts": _now(), "symbol": symbol, "capture_date": capture_date,
                      "sha256": new_hash, "prev_sha256": prev_hash, "bytes": len(html_text)})
    return new_hash


# --------------------------------------------------------------------- silver

def _read_promoted_hashes(store: Store) -> dict[str, str]:
    """The crash-safe checkpoint: what Bronze content is actually reflected in
    the LAST SUCCESSFULLY PROMOTED serving DB, not what's newest on disk."""
    if not store.db.exists():
        return {}
    con = duckdb.connect(str(store.db), read_only=True)
    try:
        if not _table_exists(con, "promoted_bronze_hashes"):
            return {}
        return dict(con.execute("SELECT symbol, sha256 FROM promoted_bronze_hashes").fetchall())
    finally:
        con.close()


def _load_corporate_actions(gcon: "duckdb.DuckDBPyConnection", ledger_path: Path) -> dict:
    """Typed, faithful conformance of full_ca_ledger.sqlite's ca_ledger table
    (design doc Section 5.2) -- content untouched, only types cast out of the
    source's all-TEXT schema. Reused as-is: no reconciliation logic re-derived
    here (see design doc Section 3.2 for why)."""
    if not ledger_path.exists():
        raise SystemExit(f"corporate-action ledger not found: {ledger_path}")
    con = sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query("SELECT * FROM ca_ledger", con)
        meta = dict(con.execute("SELECT k, v FROM meta").fetchall())
    finally:
        con.close()

    for c in _CA_NUMERIC_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["is_compound"] = df["is_compound"].map({"0": False, "1": True}).astype("boolean")
    df["n_components"] = pd.to_numeric(df["n_components"], errors="coerce").astype("Int64")
    df["dedup_merged_from"] = df["dedup_merged_from"].apply(
        lambda v: json.loads(v) if isinstance(v, str) and v.strip().startswith("[") else None)

    gcon.register("_ca_df", df)
    gcon.execute("CREATE OR REPLACE TABLE corporate_actions AS SELECT * FROM _ca_df")
    gcon.unregister("_ca_df")
    return {"rows": len(df), "ledger_built_at": meta.get("built_at"), "ledger_n_events": meta.get("n_events")}


# ----------------------------------------------------------------------- run

def run(mode: str, store_root: Path, *, cache_dir: Path | None = None,
       ledger_db: Path | None = None, symbols: list[str] | None = None,
       fetch_fn=None) -> dict:
    if mode not in ("backfill", "daily"):
        raise SystemExit(f"--mode must be 'backfill' or 'daily', got {mode!r}")

    store = Store(store_root)
    store.root.mkdir(parents=True, exist_ok=True)
    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    ledger_db = ledger_db or DEFAULT_LEDGER_DB
    today = dt.date.today().isoformat()

    syms = symbols or list_cached_symbols(cache_dir)
    promoted_hashes = _read_promoted_hashes(store)

    fresh_hashes: dict[str, str] = {}
    changed_symbols: list[str] = []
    fetch_failures: dict[str, str] = {}
    for sym in syms:
        try:
            if mode == "backfill":
                html_text = (cache_dir / f"{sym}.html").read_text(encoding="utf-8", errors="replace")
            else:
                fetch = fetch_fn or fetch_symbol_live
                html_text = fetch(sym)
                time.sleep(SLEEP_SECONDS)
        except Exception as e:  # noqa: BLE001 -- one bad symbol must not kill the sweep
            fetch_failures[sym] = str(e)
            continue

        new_hash = _bronze_capture_if_changed(store, sym, html_text, today)
        fresh_hashes[sym] = new_hash
        if promoted_hashes.get(sym) != new_hash:
            changed_symbols.append(sym)

    gcon = duckdb.connect()
    if store.db.exists():
        gcon.execute(f"ATTACH '{store.db.as_posix()}' AS prev (READ_ONLY)")
        gcon.execute("CREATE TABLE stock_announcements AS SELECT * FROM prev.stock_announcements")
        gcon.execute("DETACH prev")
    else:
        gcon.execute(_STOCK_ANNOUNCEMENTS_DDL)

    rows_added = 0
    confidence_counts: dict[str, int] = {}
    zero_row_symbols: list[str] = []
    for sym in changed_symbols:
        path = store.latest_bronze_path(sym)
        html_text = path.read_text(encoding="utf-8", errors="replace")
        records = financials_parser.extract_rows(sym, html_text)
        gcon.execute("DELETE FROM stock_announcements WHERE symbol = ?", (sym,))
        if records:
            df = pd.DataFrame.from_records(records)
            gcon.register("_new_rows", df)
            gcon.execute("INSERT INTO stock_announcements SELECT * FROM _new_rows")
            gcon.unregister("_new_rows")
            rows_added += len(records)
            for r in records:
                confidence_counts[r["parse_confidence"]] = confidence_counts.get(r["parse_confidence"], 0) + 1
        else:
            zero_row_symbols.append(sym)

    ca_result = _load_corporate_actions(gcon, ledger_db)

    new_promoted = dict(promoted_hashes)
    new_promoted.update(fresh_hashes)
    promoted_df = pd.DataFrame(sorted(new_promoted.items()), columns=["symbol", "sha256"])
    gcon.register("_promoted", promoted_df)
    gcon.execute("CREATE OR REPLACE TABLE promoted_bronze_hashes AS SELECT * FROM _promoted")
    gcon.unregister("_promoted")

    if store.staging.exists():
        store.staging.unlink()
    gcon.execute(f"ATTACH '{store.staging.as_posix()}' AS out")
    for table in ("stock_announcements", "corporate_actions", "promoted_bronze_hashes"):
        gcon.execute(f"CREATE OR REPLACE TABLE out.{table} AS SELECT * FROM {table}")
    gcon.execute("DETACH out")
    gcon.close()
    os.replace(store.staging, store.db)

    result = {
        "outcome": "built", "mode": mode, "run_at": _now(),
        "symbols_checked": len(syms), "symbols_changed": len(changed_symbols),
        "symbols_fetch_failed": len(fetch_failures), "fetch_failures": fetch_failures,
        "stock_announcement_rows_added": rows_added,
        "confidence_counts": confidence_counts,
        "changed_symbols_with_zero_rows": zero_row_symbols,
        "corporate_actions": ca_result,
    }
    store.log_build(result)
    return result


# ------------------------------------------------------------------------ cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", required=True, choices=["backfill", "daily"])
    ap.add_argument("--store-root", type=Path, default=ARCHIVE_ROOT / "financials_archive")
    ap.add_argument("--cache-dir", type=Path, default=None)
    ap.add_argument("--ledger-db", type=Path, default=None)
    ap.add_argument("--symbols-file", type=Path, default=None,
                    help="optional newline-delimited symbol list override (default: "
                         "every *.html in --cache-dir)")
    args = ap.parse_args(argv)

    symbols = None
    if args.symbols_file:
        symbols = [s.strip() for s in args.symbols_file.read_text().splitlines() if s.strip()]

    result = run(args.mode, args.store_root, cache_dir=args.cache_dir,
                ledger_db=args.ledger_db, symbols=symbols)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
