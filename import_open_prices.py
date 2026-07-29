"""
Open Price Import Utility -- Phase 4 of the Open price acquisition project.

Purpose
-------
Fills NULL `open` values in the production `prices` and `index_prices` tables
using the independently-acquired, independently-verified dataset from
`acquire_open_prices.py` (staged in open_acquisition_output/acquisition_staging.db).

This implements Option C from the Phase 2.5 provenance review (see
docs/DECISIONS.md and docs/DATA_ACQUISITION_ARCHITECTURE.md): gap-fill only,
quality-filtered, additive-only. It does NOT overwrite any existing value.

Independent verification behind this policy (2026-07-04): a fresh, independently
-drawn 40-row random sample cross-checked against the original BI PostgreSQL
source came back 40/40 in favor of the EXISTING production values wherever
both exist and differ -- the acquisition dataset was never confirmed correct
against BI when it disagreed with production. Production values (2020-2023)
are therefore left untouched; only NULL gaps are filled.

What this script does NOT do
-----------------------------
- Does NOT touch `prices_adjusted.open`. That table already carries cumulative
  corporate-action factors on its existing High/Low/Close; writing a raw Open
  into the same row would create an internally inconsistent row (adjusted
  H/L/C next to unadjusted Open). Deriving `prices_adjusted.open` correctly is
  a deliberate, separate step -- re-running the existing
  apply_price_adjustments.py machinery -- not bundled into this import.
- Does NOT overwrite any existing non-NULL `open` value, under any condition.
  This is enforced twice: once when selecting candidates (only NULL rows are
  considered), and again as a live `WHERE open IS NULL` guard on the actual
  UPDATE statement -- so even a stale candidate list can never overwrite data.
- Does NOT run destructively without an explicit `--execute` flag. Without it,
  this script only computes and reports what WOULD happen.

Filters applied (Option C, Phase 2.5 report Section 8)
-------------------------------------------------------
A candidate row is imported only if ALL of the following hold:
  1. production.open IS NULL for that (symbol, date)              [gap-fill only]
  2. acquisition.valid_numeric = 1 and valid_positive = 1          [sane value]
  3. acquisition.within_hl_range != 0                              [not a confirmed
                                                                     out-of-range value;
                                                                     rows where H/L
                                                                     couldn't be checked
                                                                     -- within_hl_range
                                                                     IS NULL -- are still
                                                                     allowed through and
                                                                     counted separately]
  4. ABS(acquisition.open - acquisition.close) >= 0.001            [not a "close served
                                                                     as open" row -- a
                                                                     known ksestocks.com
                                                                     data-quality issue]
  5. trading_date != '2026-06-01'                                  [unresolved single-date
                                                                     anomaly, excluded
                                                                     pending investigation]

Pre-2020 rows (2005-2019, ~1.07M rows) have no independent verification
baseline (BI PostgreSQL only covers 2020 onward) and are imported as
"best available, unverified" -- documented explicitly in the report this
script produces, not silently treated as equally trustworthy as the
BI-corroborated 2020+ fills.

Safety mechanics
-----------------
- Dry run by default. Full candidate/exclusion breakdown and a JSON report are
  always produced; nothing is written to psx_data.db unless --execute is passed.
- Before any write, this script makes a full timestamped copy of psx_data.db
  and verifies the copy's size before proceeding.
- The read phase (candidate selection, reporting) uses a read-only connection
  to psx_data.db with the same write-rejection self-test used by
  acquire_open_prices.py.
- The write phase opens a separate, explicit read-write connection only after
  --execute and the backup are confirmed, runs in batched transactions, and
  is itself guarded by `WHERE open IS NULL` on every statement.
- Before/after non-null counts are verified and included in the report.

Usage
-----
    python import_open_prices.py                  # dry run only, writes a report
    python import_open_prices.py --execute         # backs up, then performs the import

Outputs (open_import_output/):
    import_report.json          -- full breakdown, always produced
    import.log                  -- full run log
    psx_data_pre_open_import_<timestamp>.db   -- backup, only created with --execute
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROD_DB_PATH = SCRIPT_DIR / "psx_data.db"
STAGING_DB_PATH = SCRIPT_DIR / "open_acquisition_output" / "acquisition_staging.db"

OUTPUT_DIR = SCRIPT_DIR / "open_import_output"
LOG_PATH = OUTPUT_DIR / "import.log"
REPORT_PATH = OUTPUT_DIR / "import_report.json"

EXCLUDED_DATE = "2026-06-01"          # unresolved anomaly, see module docstring
OPEN_EQ_CLOSE_EPSILON = 0.001         # matches the Phase 2.5 review's threshold
BI_COVERAGE_START = "2020-01-01"      # pre-2020 rows have no independent verification

BATCH = 5_000

logger = logging.getLogger("open_import")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging():
    OUTPUT_DIR.mkdir(exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)


# ---------------------------------------------------------------------------
# Read-only connection with self-test (same pattern as acquire_open_prices.py)
# ---------------------------------------------------------------------------

def open_readonly_prod_db(db_path: Path) -> sqlite3.Connection:
    db_path = db_path.resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Production DB not found at {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("UPDATE prices SET open = open WHERE 1 = 0")
        conn.rollback()
        raise RuntimeError(
            "SAFETY ABORT: read-only self-test did not raise -- refusing to proceed."
        )
    except sqlite3.OperationalError as exc:
        if "readonly" not in str(exc).lower():
            raise
        logger.info("Read-only self-test passed: production DB write rejected (%s)", exc)
    return conn


def open_staging_db(db_path: Path) -> sqlite3.Connection:
    db_path = db_path.resolve()
    if not db_path.exists():
        raise FileNotFoundError(
            f"Staging DB not found at {db_path} -- run acquire_open_prices.py first."
        )
    uri = f"file:{db_path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------

def _table_candidates(staging_conn: sqlite3.Connection, prod_conn: sqlite3.Connection,
                       staging_table: str, prod_table: str) -> dict:
    """
    Returns a dict with the full funnel breakdown and the list of
    (symbol, date, open) rows that pass every filter.
    """
    all_rows = staging_conn.execute(
        f"SELECT symbol, trading_date, open, close, valid_numeric, valid_positive, "
        f"within_hl_range FROM {staging_table}"
    ).fetchall()

    total = len(all_rows)
    excluded_invalid = 0
    excluded_out_of_range = 0
    excluded_open_eq_close = 0
    excluded_anomaly_date = 0
    excluded_no_prod_row = 0
    excluded_prod_already_has_open = 0
    unverifiable_hl_allowed = 0
    pre_2020_candidates = 0
    candidates = []

    # Pull current production open state once, keyed by (symbol, date).
    prod_state = {
        (r[0], r[1]): r[2]
        for r in prod_conn.execute(f"SELECT symbol, date, open FROM {prod_table}").fetchall()
    }

    for symbol, trading_date, open_v, close_v, valid_numeric, valid_positive, within_hl in all_rows:
        if not valid_numeric or not valid_positive:
            excluded_invalid += 1
            continue
        if within_hl == 0:
            excluded_out_of_range += 1
            continue
        if within_hl is None:
            unverifiable_hl_allowed += 1
        if abs(open_v - close_v) < OPEN_EQ_CLOSE_EPSILON:
            excluded_open_eq_close += 1
            continue
        if trading_date == EXCLUDED_DATE:
            excluded_anomaly_date += 1
            continue

        key = (symbol, trading_date)
        if key not in prod_state:
            excluded_no_prod_row += 1
            continue
        if prod_state[key] is not None:
            excluded_prod_already_has_open += 1
            continue

        if trading_date < BI_COVERAGE_START:
            pre_2020_candidates += 1
        candidates.append((symbol, trading_date, open_v))

    return {
        "total_acquired_rows": total,
        "excluded_invalid_value": excluded_invalid,
        "excluded_out_of_range": excluded_out_of_range,
        "excluded_open_eq_close": excluded_open_eq_close,
        "excluded_anomaly_date": excluded_anomaly_date,
        "excluded_no_matching_prod_row": excluded_no_prod_row,
        "excluded_prod_already_has_open": excluded_prod_already_has_open,
        "unverifiable_hl_range_allowed_through": unverifiable_hl_allowed,
        "pre_2020_unverified_candidates": pre_2020_candidates,
        "final_candidate_count": len(candidates),
        "candidates": candidates,
    }


def compute_plan(staging_conn: sqlite3.Connection, prod_conn: sqlite3.Connection) -> dict:
    logger.info("Computing stock price import candidates...")
    stock = _table_candidates(staging_conn, prod_conn, "stock_open_raw", "prices")
    logger.info("Computing index price import candidates...")
    index = _table_candidates(staging_conn, prod_conn, "index_open_raw", "index_prices")
    return {"stock": stock, "index": index}


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup_prod_db() -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = OUTPUT_DIR / f"psx_data_pre_open_import_{ts}.db"
    logger.info("Backing up %s -> %s ...", PROD_DB_PATH, backup_path)
    shutil.copy2(PROD_DB_PATH, backup_path)

    original_size = PROD_DB_PATH.stat().st_size
    backup_size = backup_path.stat().st_size
    if backup_size != original_size:
        raise RuntimeError(
            f"SAFETY ABORT: backup size ({backup_size}) does not match original "
            f"({original_size}). Refusing to proceed with import."
        )
    logger.info("Backup verified: %d bytes.", backup_size)
    return backup_path


# ---------------------------------------------------------------------------
# Write phase
# ---------------------------------------------------------------------------

def execute_import(table: str, candidates: list[tuple]) -> int:
    """Applies the guarded UPDATE in batches. Returns total rows actually changed."""
    conn = sqlite3.connect(PROD_DB_PATH)
    total_changed = 0
    try:
        for i in range(0, len(candidates), BATCH):
            batch = candidates[i:i + BATCH]
            cur = conn.executemany(
                f"UPDATE {table} SET open = ? WHERE symbol = ? AND date = ? AND open IS NULL",
                [(open_v, symbol, trading_date) for symbol, trading_date, open_v in batch],
            )
            conn.commit()
            total_changed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(batch)
            logger.info("  %s: committed %d / %d candidate rows", table, min(i + BATCH, len(candidates)), len(candidates))
    finally:
        conn.close()
    return total_changed


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def sha256_of(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def build_report(plan: dict, executed: bool, backup_path: Path | None,
                  before_counts: dict, after_counts: dict | None, runtime_sec: float) -> dict:
    def strip_candidates(d):
        return {k: v for k, v in d.items() if k != "candidates"}

    return {
        "report_generated_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "EXECUTED" if executed else "DRY_RUN",
        "runtime_seconds": round(runtime_sec, 2),
        "policy": "Option C -- gap-fill only, quality-filtered, additive-only (see docs/DECISIONS.md)",
        "filters_applied": {
            "gap_fill_only": "production.open IS NULL",
            "quality": "valid_numeric=1 AND valid_positive=1",
            "out_of_range_excluded": "within_hl_range != 0 (rows with unknown H/L allowed through, counted separately)",
            "open_eq_close_excluded": f"ABS(open-close) < {OPEN_EQ_CLOSE_EPSILON}",
            "anomaly_date_excluded": EXCLUDED_DATE,
        },
        "stock_prices": strip_candidates(plan["stock"]),
        "index_prices": strip_candidates(plan["index"]),
        "pre_2020_note": (
            f"{plan['stock']['pre_2020_unverified_candidates']} stock rows and "
            f"{plan['index']['pre_2020_unverified_candidates']} index rows before "
            f"{BI_COVERAGE_START} are imported as BEST AVAILABLE, UNVERIFIED -- "
            "no independent source (BI PostgreSQL only covers 2020 onward) exists "
            "to cross-check pre-2020 Open values."
        ),
        "backup_file": str(backup_path) if backup_path else None,
        "backup_sha256": sha256_of(backup_path) if backup_path else None,
        "before_counts": before_counts,
        "after_counts": after_counts,
    }


def write_report(report: dict):
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("Report written to %s", REPORT_PATH)


def get_open_counts(db_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    stock = conn.execute("SELECT COUNT(*), COUNT(open) FROM prices").fetchone()
    idx = conn.execute("SELECT COUNT(*), COUNT(open) FROM index_prices").fetchone()
    conn.close()
    return {
        "prices_total": stock[0], "prices_open_non_null": stock[1],
        "index_prices_total": idx[0], "index_prices_open_non_null": idx[1],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--execute", action="store_true",
                         help="Actually perform the import. Without this flag, dry-run only.")
    args = parser.parse_args()

    setup_logging()
    started = time.time()
    logger.info("=== Open Price Import -- mode: %s ===", "EXECUTE" if args.execute else "DRY RUN")

    before_counts = get_open_counts(PROD_DB_PATH)
    logger.info("Before state: %s", before_counts)

    staging_conn = open_staging_db(STAGING_DB_PATH)
    prod_ro_conn = open_readonly_prod_db(PROD_DB_PATH)

    plan = compute_plan(staging_conn, prod_ro_conn)
    prod_ro_conn.close()
    staging_conn.close()

    logger.info("Stock candidates passing all filters: %d", plan["stock"]["final_candidate_count"])
    logger.info("Index candidates passing all filters: %d", plan["index"]["final_candidate_count"])
    for label, d in (("stock", plan["stock"]), ("index", plan["index"])):
        logger.info(
            "  [%s] total=%d invalid=%d out_of_range=%d open_eq_close=%d anomaly_date=%d "
            "no_prod_row=%d already_has_open=%d unverifiable_hl_allowed=%d pre_2020=%d",
            label, d["total_acquired_rows"], d["excluded_invalid_value"],
            d["excluded_out_of_range"], d["excluded_open_eq_close"], d["excluded_anomaly_date"],
            d["excluded_no_matching_prod_row"], d["excluded_prod_already_has_open"],
            d["unverifiable_hl_range_allowed_through"], d["pre_2020_unverified_candidates"],
        )

    backup_path = None
    after_counts = None

    if args.execute:
        logger.warning("EXECUTE mode -- writing to production database.")
        backup_path = backup_prod_db()

        logger.info("Applying stock price updates...")
        stock_changed = execute_import("prices", plan["stock"]["candidates"])
        logger.info("Stock rows updated: %d", stock_changed)

        logger.info("Applying index price updates...")
        index_changed = execute_import("index_prices", plan["index"]["candidates"])
        logger.info("Index rows updated: %d", index_changed)

        after_counts = get_open_counts(PROD_DB_PATH)
        logger.info("After state: %s", after_counts)

        expected_stock_delta = plan["stock"]["final_candidate_count"]
        actual_stock_delta = after_counts["prices_open_non_null"] - before_counts["prices_open_non_null"]
        if actual_stock_delta != expected_stock_delta:
            logger.warning(
                "VERIFICATION MISMATCH: expected %d new non-null stock opens, observed %d. "
                "Investigate before trusting this import.",
                expected_stock_delta, actual_stock_delta,
            )
        else:
            logger.info("Verification passed: stock open count increased by exactly %d as expected.", actual_stock_delta)

    runtime = time.time() - started
    report = build_report(plan, args.execute, backup_path, before_counts, after_counts, runtime)
    write_report(report)

    if not args.execute:
        logger.info(
            "DRY RUN complete -- no changes made. Review %s, then rerun with --execute to apply.",
            REPORT_PATH,
        )
    else:
        logger.info("EXECUTE complete. Full report: %s", REPORT_PATH)


if __name__ == "__main__":
    main()
