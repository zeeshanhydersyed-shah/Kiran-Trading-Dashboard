r"""
Kiran Local-First Migration -- Phase 1, sub-task 1+2: capture + verify.

Capture an immutable point-in-time baseline of the live ``psx_data.db`` with the
SQLite Online Backup API (transactionally consistent even against a concurrent
writer; never modifies the source), then verify the frozen artifact against the
live DB -- every table's row count, date spans for the price/indicator
substrate, and a ``PRAGMA integrity_check`` on the copy.

D7 (owner, 2026-09-09): preservation only. This never writes to ``psx_data.db``
and never mutates a historical row -- it produces a read-only copy.

Quiescence: the caller is responsible for establishing it. Either disable
``PSX_TaskScheduler`` (needs an elevated session) or rely on the fact that the
task is logon-trigger-only with an empty NextRunTime (cannot fire on a clock)
plus: no pipeline python process running, last run logged complete, and no
dashboard "Refresh Data" click / logon / lock-unlock during the ~2 min capture.
The script records the live SHA-256 before and after and fails the verdict if it
moved.

    python -m archive.capture_baseline
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys

LIVE_DB = os.environ.get("KIRAN_LIVE_DB",
                         os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                      "psx_data.db"))
ARCHIVE_ROOT = os.environ.get("KIRAN_ARCHIVE_ROOT", r"D:\KIRAN_ARCHIVE")
BASELINE_DIR = os.path.join(ARCHIVE_ROOT, "baseline")

# table -> date-like column, for span verification
SUBSTRATE_DATE_TABLES = {
    "prices": "date",
    "prices_adjusted": "date",
    "index_prices": "date",
    "stock_signals": "date",
    "sector_signals": "date",
    "market_regime": "date",
    "setup_log": "setup_date",
    "leaders_scan": "scan_date",
}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def all_table_counts(con: sqlite3.Connection) -> dict[str, int]:
    cur = con.cursor()
    tabs = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {t: cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tabs}


def date_spans(con: sqlite3.Connection) -> dict[str, list]:
    cur = con.cursor()
    out = {}
    for t, col in SUBSTRATE_DATE_TABLES.items():
        try:
            lo, hi, n = cur.execute(
                f'SELECT MIN("{col}"), MAX("{col}"), COUNT(*) FROM "{t}"').fetchone()
            out[t] = [lo, hi, n]
        except sqlite3.Error as e:
            out[t] = ["ERR", str(e), None]
    return out


def main() -> int:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(BASELINE_DIR, exist_ok=True)
    dest = os.path.join(BASELINE_DIR, f"psx_data_baseline_KIRAN_LFM_P1_{ts}.db")

    print(f"[{dt.datetime.now():%H:%M:%S}] live : {LIVE_DB}")
    live_hash_before = sha256(LIVE_DB)
    live_size = os.path.getsize(LIVE_DB)
    print(f"           live SHA-256 (before) : {live_hash_before}")
    print(f"           live size             : {live_size:,} bytes")
    for side in ("-wal", "-shm", "-journal"):
        p = LIVE_DB + side
        state = f"present {os.path.getsize(p)} b" if os.path.exists(p) else "absent"
        print(f"           {side:<9}: {state}")

    src = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    print(f"[{dt.datetime.now():%H:%M:%S}] captured -> {dest}")

    live_hash_after = sha256(LIVE_DB)
    print(f"           live SHA-256 (after)  : {live_hash_after}")
    quiescent = live_hash_after == live_hash_before
    if not quiescent:
        print("  *** WARNING: live DB changed during capture -- NOT quiescent ***")

    base_hash = sha256(dest)
    print(f"           baseline SHA-256      : {base_hash}")
    print(f"           baseline size         : {os.path.getsize(dest):,} bytes")

    bcon = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
    integ = bcon.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"           integrity_check       : {integ}")

    lcon = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    live_counts, base_counts = all_table_counts(lcon), all_table_counts(bcon)
    live_spans, base_spans = date_spans(lcon), date_spans(bcon)
    lcon.close()
    bcon.close()

    mism = {t: (live_counts.get(t), base_counts.get(t))
            for t in set(live_counts) | set(base_counts)
            if live_counts.get(t) != base_counts.get(t)}
    span_mism = {t: [live_spans[t], base_spans[t]]
                 for t in live_spans if live_spans[t] != base_spans[t]}

    print(f"\n=== ROW COUNTS === live tables={len(live_counts)} baseline={len(base_counts)}")
    print("  ALL MATCH" if not mism else "\n".join(f"  MISMATCH {t}: {v}" for t, v in sorted(mism.items())))
    print("\n=== DATE SPANS (substrate) ===")
    for t in SUBSTRATE_DATE_TABLES:
        mark = "**" if t in span_mism else "  "
        print(f"  {mark} {t:<16} {base_spans[t]}")

    ok = quiescent and not mism and not span_mism and integ == "ok"
    report = {
        "captured_at": dt.datetime.now().isoformat(), "live_db": LIVE_DB,
        "live_sha256_before": live_hash_before, "live_sha256_after": live_hash_after,
        "live_size_bytes": live_size, "baseline_path": dest,
        "baseline_sha256": base_hash, "baseline_size_bytes": os.path.getsize(dest),
        "integrity_check": integ, "table_count": len(base_counts),
        "row_count_mismatches": mism, "date_span_mismatches": span_mism,
        "row_counts": base_counts, "date_spans": base_spans,
        "verdict": "PASS" if ok else "REVIEW",
    }
    rp = os.path.join(BASELINE_DIR, f"capture_report_{ts}.json")
    with open(rp, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n[{dt.datetime.now():%H:%M:%S}] report -> {rp}")
    print(f"VERDICT: {report['verdict']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
