r"""
Kiran Local-First Migration -- Phase 6 front-end track: Gold -> JSON export.

The front end (``web/``) is a static site with no build step and no server-side
compute -- it reads precomputed JSON, exactly per the design (migration tracker
Sec.3: "Static JSON from the pipeline"). This module is the missing link 3.3f
deliberately deferred ("no consumer code exists yet to validate a schema
against") -- now that the front end is the consumer, it defines the schema.

Reads the **promoted** Gold store (``psx_serving.duckdb``, read-only) and the
publication lineage (``current_publication.duckdb``, read-only) and writes
three files to ``web/data/``:

    meta.json           -- freshness/verification banner state
    sector_grades.json  -- one row per sector (latest date) + a trailing
                            composite-score history per sector for sparklines
    signals.json         -- one row per symbol (latest date) for the Explorer
                            table, joined to company name / sector / latest
                            close+change / CA provenance

Each file is written atomically (temp file + ``os.replace``) so the front end
never reads a half-written file mid-export -- the same discipline
``gold_build``'s own atomic staging swap uses, at the JSON layer.

    python -m archive.export_json [--store-root DIR] [--archive-root DIR] [--out DIR]

Tracker: docs/KIRAN_LOCAL_FIRST_MIGRATION.md, front end checklist (Sec.5).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

import duckdb

from archive.bronze_ingest import ARCHIVE_ROOT

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "web" / "data"
SECTOR_HISTORY_SESSIONS = 60  # trailing sessions for the sparkline


def _clean(v):
    """NaN -> None (DuckDB/pandas NaN isn't valid JSON); everything else as-is."""
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _row_dict(cols: list[str], row: tuple) -> dict:
    return {c: _clean(v) for c, v in zip(cols, row)}


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, default=str, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _ca_provenance(archive_root: Path) -> str:
    """The CA source in force, for the Explorer's per-symbol `price_basis`
    field (design doc Q6: 'adjusted_v2' / 'raw' -- 'legacy' here, matching
    silver_build's own default until the v2 substrate is wired in, Q5)."""
    log_path = archive_root / "prices_archive" / "silver" / "_silver_build_log.jsonl"
    if not log_path.exists():
        return "legacy"
    try:
        last = None
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last = json.loads(line)
        return (last or {}).get("ca_source", "legacy")
    except (OSError, json.JSONDecodeError):
        return "legacy"


def _latest_publication(archive_root: Path) -> dict | None:
    db = archive_root / "psx_serving" / "current_publication.duckdb"
    if not db.exists():
        return None
    con = duckdb.connect(str(db), read_only=True)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(current_publication)").fetchall()]
        row = con.execute(
            "SELECT * FROM current_publication ORDER BY promoted_at DESC LIMIT 1").fetchone()
        return _row_dict(cols, row) if row else None
    finally:
        con.close()


def export_meta(store_root: Path, archive_root: Path, out_dir: Path) -> dict:
    pub = _latest_publication(archive_root)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    if pub is None:
        payload = {"generated_at": now, "verified": False,
                   "reason": "no publication record found", "bronze_max": None, "gates": {}}
    else:
        gates = {"freshness": pub.get("freshness_status"), "completeness": pub.get("completeness_status"),
                 "hook_coverage": pub.get("hook_coverage_status"), "coherence": pub.get("coherence_status")}
        verified = bool(pub.get("promoted")) and all(v in (True, "VERIFIED", "COMPLETE", "COHERENT")
                                                       for v in gates.values() if v is not None) \
            and all(gates.values())
        payload = {
            "generated_at": now, "verified": verified,
            "bronze_max": pub.get("bronze_max"), "window_from": pub.get("window_from"),
            "run_id": pub.get("run_id"), "code_version": pub.get("code_version"),
            "gates": gates, "withheld_reason": pub.get("withheld_reason"),
        }
    _write_json_atomic(out_dir / "meta.json", payload)
    return payload


def export_sector_grades(store_root: Path, out_dir: Path) -> dict:
    con = duckdb.connect(str(store_root / "psx_serving.duckdb"), read_only=True)
    try:
        as_of = con.execute("SELECT MAX(date) FROM sector_signals").fetchone()[0]
        cols = [r[1] for r in con.execute("PRAGMA table_info(sector_signals)").fetchall()]
        rows = con.execute(
            "SELECT * FROM sector_signals WHERE date = ? ORDER BY sector", [as_of]).fetchall()
        sectors = [_row_dict(cols, r) for r in rows]

        hist_rows = con.execute(
            "WITH recent_dates AS ("
            "    SELECT DISTINCT date FROM sector_signals "
            "    ORDER BY date DESC LIMIT ?"
            ") "
            "SELECT s.sector, s.date, s.composite_score FROM sector_signals s "
            "JOIN recent_dates d USING (date) "
            "ORDER BY s.sector, s.date", [SECTOR_HISTORY_SESSIONS]).fetchall()
        history: dict[str, list] = {}
        for sector, _date, score in hist_rows:
            history.setdefault(sector, []).append(_clean(score))
        for s in sectors:
            s["history"] = history.get(s["sector"], [])[-SECTOR_HISTORY_SESSIONS:]
    finally:
        con.close()
    payload = {"as_of": as_of, "sectors": sectors}
    _write_json_atomic(out_dir / "sector_grades.json", payload)
    return payload


def export_signals(store_root: Path, archive_root: Path, out_dir: Path) -> dict:
    con = duckdb.connect(str(store_root / "psx_serving.duckdb"), read_only=True)
    try:
        as_of = con.execute("SELECT MAX(date) FROM stock_signals").fetchone()[0]
        ss_cols = [r[1] for r in con.execute("PRAGMA table_info(stock_signals)").fetchall()]
        rows = con.execute(
            "SELECT ss.*, sm.company_name, "
            "       p.close AS close, p.prev_close AS prev_close "
            "FROM stock_signals ss "
            "LEFT JOIN stock_metadata sm USING (symbol) "
            "LEFT JOIN ("
            "    SELECT symbol, close, "
            "           lag(close) OVER (PARTITION BY symbol ORDER BY date) AS prev_close, date "
            "    FROM prices_adjusted"
            ") p ON p.symbol = ss.symbol AND p.date = ss.date "
            "WHERE ss.date = ?", [as_of]).fetchall()
        out_cols = ss_cols + ["company_name", "close", "prev_close"]
        symbols = []
        ca_provenance = _ca_provenance(archive_root)
        for r in rows:
            d = _row_dict(out_cols, r)
            close, prev = d.get("close"), d.get("prev_close")
            d["chg_pct"] = round((close - prev) / prev * 100, 2) if close and prev else None
            d["price_basis"] = ca_provenance
            symbols.append(d)
        symbols.sort(key=lambda d: (d.get("rs_rank") is None, d.get("rs_rank")))
    finally:
        con.close()
    payload = {"as_of": as_of, "symbols": symbols}
    _write_json_atomic(out_dir / "signals.json", payload)
    return payload


def export_all(store_root: Path, archive_root: Path = ARCHIVE_ROOT,
                out_dir: Path = DEFAULT_OUT_DIR) -> dict:
    meta = export_meta(store_root, archive_root, out_dir)
    sectors = export_sector_grades(store_root, out_dir)
    signals = export_signals(store_root, archive_root, out_dir)
    return {"meta": meta, "sector_count": len(sectors["sectors"]), "symbol_count": len(signals["symbols"])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export Gold -> JSON for the static front end.")
    ap.add_argument("--store-root", default=str(ARCHIVE_ROOT / "psx_serving"))
    ap.add_argument("--archive-root", default=str(ARCHIVE_ROOT))
    ap.add_argument("--out", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args(argv)
    result = export_all(Path(args.store_root), Path(args.archive_root), Path(args.out))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
