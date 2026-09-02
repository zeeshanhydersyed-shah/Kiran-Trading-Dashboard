"""
local_archive_sync.py -- TR-01 shadow-mode Component B (Phase 4 of the §40.17
migration sequence; SHADOWMODE_SPEC_DRAFT.md §6 / ledger §111).

Pulls the authoritative published state DOWN from Postgres into a SEPARATE
local database file (`psx_archive.db`) and stores it -- append/replace only,
never computing a signal, never touching `psx_data.db`. This is the
target-architecture local role a cutover would switch to (§38.6 / §39.12):
the local machine reaches out to Postgres, never the reverse; it only ever
holds a state Postgres itself promoted.

What it does, per run:
  1. Read `current_publication` from Postgres (READ-ONLY connection). Take
     every session marked `promoted` whose `coherence` is not INCOHERENT
     (NULL / UNKNOWN / COHERENT all pass -- the same permissive reading
     TR-14's completeness gate uses; only an explicit INCOHERENT is
     excluded). These `source_as_of` dates are the eligible sessions.
     NOTE: every `current_publication` row on Postgres is written natively
     by the authoritative GitHub-Actions->Postgres pipeline --
     `main.run_freshness_gate()` never passes `mirror_to_postgres=True` for
     the publication decision (confirmed by code read; corrects the caveat
     in ledger §110.2), so there is no local-mirror contamination to filter.
  3. For every eligible session within `window_days` of the latest eligible
     session, DELETE that session's rows from the archive and re-INSERT them
     from Postgres, for every table in ARCHIVE_TABLES + `current_publication`.
     Re-pulling the whole trailing window every run keeps post-hoc mutations
     current (boring_signals status, setup_log outcome labels, forward
     returns) without per-table change tracking.
  4. Per session: compare the archive's row count for each table against
     Postgres's. A mismatch -> session status PARTIAL (never silently OK).
  5. Write `archive_sync_state` (one row per session) + `archive_sync_meta`
     (one row, the heartbeat -- a `last_run_at` that stops advancing, or a
     `last_session_synced` behind `pg_latest_promoted_session`, is the
     stale-archive signal, §39.12).

Resumable by construction: each session is pulled independently and
idempotently (DELETE+INSERT), so a crash mid-run just redoes the unfinished
sessions on the next run. No replay risk -- Postgres is the source of truth
and is only copied, never recomputed.

CLI:
    python local_archive_sync.py            # sync, default psx_archive.db
    python local_archive_sync.py --status   # print the heartbeat + last sessions, no write
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sqlite3
import sys

logger = logging.getLogger("local_archive_sync")

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import config  # noqa: E402

# (table, the column that carries the session/trading date)
ARCHIVE_TABLES: tuple[tuple[str, str], ...] = (
    ("prices",                 "date"),
    ("index_prices",           "date"),
    ("prices_adjusted",        "date"),
    ("stock_signals",          "date"),
    ("sector_signals",         "date"),
    ("market_regime",          "date"),
    ("recovery_signals",       "as_of_date"),
    ("portfolio_signals",      "as_of_date"),
    ("boring_signals",         "signal_date"),
    ("boring_signals_scanned", "scan_date"),
    ("setup_log",              "setup_date"),
    ("leaders_scan",           "scan_date"),
    ("leaders_top_picks",      "scan_date"),
    ("scrape_coverage",        "scrape_date"),
)

_STATE_DDL = """
CREATE TABLE IF NOT EXISTS archive_sync_state (
    session_date    TEXT PRIMARY KEY,
    source_run_id   TEXT,
    coherence       TEXT,
    synced_at       TEXT NOT NULL,
    status          TEXT NOT NULL,          -- OK | PARTIAL | ERROR
    row_counts_json TEXT,
    detail          TEXT
)
"""

_META_DDL = """
CREATE TABLE IF NOT EXISTS archive_sync_meta (
    id                          INTEGER PRIMARY KEY CHECK (id = 1),
    last_run_at                 TEXT,
    last_run_status             TEXT,        -- OK | PARTIAL | ERROR
    last_session_synced         TEXT,
    pg_latest_promoted_session  TEXT,
    sessions_in_window          INTEGER,
    detail                      TEXT
)
"""

STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_ERROR = "ERROR"

COHERENCE_INCOHERENT = "INCOHERENT"  # the one value that excludes a session


# ---------------------------------------------------------------------------
# value coercion: psycopg2 hands back date/datetime/Decimal/bool; SQLite
# cannot store Decimal or date. Normalise to ISO strings / float / int so the
# archive is clean for the Component C comparison.
# ---------------------------------------------------------------------------
def _coerce(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    # Decimal -> float without importing decimal
    if v.__class__.__name__ == "Decimal":
        return float(v)
    return v


def _iso_date(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()[:10]
    return str(v)[:10]


# ---------------------------------------------------------------------------
# Postgres connection (read-only). Injectable for tests.
# ---------------------------------------------------------------------------
def _default_pg_conn():
    from data_health import _env_pg_url
    from database_pg import _parse_pg_url
    import psycopg2

    url = _env_pg_url()
    if not url:
        raise RuntimeError("no DATABASE_URL / SUPABASE_DB_URL resolvable (env or .env)")
    conn = psycopg2.connect(**_parse_pg_url(url))
    conn.set_session(readonly=True)  # a direct connection, not the pool -- safe
    return conn


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------
def _archive_columns(pg_cur, table: str) -> list[str]:
    """Column names for `table`, from a zero-row probe (DB-API standard)."""
    pg_cur.execute(f"SELECT * FROM {table} LIMIT 0")
    return [d[0] for d in pg_cur.description]


def _ensure_archive_table(arc: sqlite3.Connection, table: str, columns: list[str]) -> None:
    existing = {r[1] for r in arc.execute(f"PRAGMA table_info({table})").fetchall()}
    if not existing:
        col_defs = ", ".join(f'"{c}"' for c in columns)
        arc.execute(f"CREATE TABLE {table} ({col_defs})")
        return
    for c in columns:
        if c not in existing:
            arc.execute(f'ALTER TABLE {table} ADD COLUMN "{c}"')


def _eligible_sessions(pg_cur) -> list[dict]:
    """Promoted `current_publication` rows whose coherence is not INCOHERENT,
    one per distinct source_as_of (latest promoted_at wins)."""
    pg_cur.execute(
        "SELECT source_as_of, run_id, coherence, promoted_at "
        "FROM current_publication WHERE promoted = %s "
        "ORDER BY promoted_at ASC, id ASC",
        (True,),
    )
    by_session: dict[str, dict] = {}
    for source_as_of, run_id, coherence, promoted_at in pg_cur.fetchall():
        session = _iso_date(source_as_of)
        if not session:
            continue
        if coherence == COHERENCE_INCOHERENT:
            by_session.pop(session, None)
            continue
        by_session[session] = dict(session=session, run_id=run_id,
                                   coherence=coherence, promoted_at=promoted_at)
    return [by_session[k] for k in sorted(by_session)]


def _pull_session(pg_cur, arc: sqlite3.Connection, session: str,
                  tables: tuple[tuple[str, str], ...],
                  col_cache: dict | None = None) -> tuple[str, dict, str | None]:
    """DELETE+INSERT one session's rows for every table. Returns
    (status, {table: {archived, postgres}}, detail)."""
    col_cache = col_cache if col_cache is not None else {}
    counts: dict[str, dict] = {}
    mismatches: list[str] = []
    for table, datecol in tables:
        if table not in col_cache:
            col_cache[table] = _archive_columns(pg_cur, table)
        cols = col_cache[table]
        _ensure_archive_table(arc, table, cols)

        pg_cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {datecol} = %s", (session,))
        pg_n = int(pg_cur.fetchone()[0])

        arc.execute(f"DELETE FROM {table} WHERE {datecol} = ?", (session,))
        pg_cur.execute(f"SELECT * FROM {table} WHERE {datecol} = %s", (session,))
        rows = pg_cur.fetchall()
        if rows:
            placeholders = ", ".join("?" for _ in cols)
            col_list = ", ".join(f'"{c}"' for c in cols)
            arc.executemany(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
                [tuple(_coerce(v) for v in r) for r in rows],
            )
        arc_n = arc.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {datecol} = ?", (session,)
        ).fetchone()[0]

        counts[table] = {"archived": arc_n, "postgres": pg_n}
        if arc_n != pg_n:
            mismatches.append(f"{table} {arc_n}/{pg_n}")

    status = STATUS_PARTIAL if mismatches else STATUS_OK
    detail = ("row-count mismatch: " + ", ".join(mismatches)) if mismatches else None
    return status, counts, detail


def _sync_current_publication(pg_cur, arc: sqlite3.Connection) -> None:
    """current_publication has no session date -- copy the whole (tiny) table."""
    cols = _archive_columns(pg_cur, "current_publication")
    _ensure_archive_table(arc, "current_publication", cols)
    arc.execute("DELETE FROM current_publication")
    pg_cur.execute("SELECT * FROM current_publication ORDER BY id")
    rows = pg_cur.fetchall()
    if rows:
        placeholders = ", ".join("?" for _ in cols)
        col_list = ", ".join(f'"{c}"' for c in cols)
        arc.executemany(
            f"INSERT INTO current_publication ({col_list}) VALUES ({placeholders})",
            [tuple(_coerce(v) for v in r) for r in rows],
        )


def sync_archive(pg_conn=None, archive_path: str | None = None,
                 window_days: int = 90,
                 tables: tuple[tuple[str, str], ...] = ARCHIVE_TABLES,
                 now: _dt.datetime | None = None) -> dict:
    """Run one sync pass. Returns a summary dict. Never touches psx_data.db."""
    archive_path = archive_path or os.path.join(
        os.path.dirname(config.DB_PATH), "psx_archive.db")
    if os.path.abspath(archive_path) == os.path.abspath(config.DB_PATH):
        raise RuntimeError("refusing to use psx_data.db as the archive")
    now = now or _dt.datetime.now(_dt.timezone.utc)
    now_iso = now.isoformat()

    owns_conn = pg_conn is None
    if owns_conn:
        pg_conn = _default_pg_conn()

    arc = sqlite3.connect(archive_path)
    try:
        arc.execute(_STATE_DDL)
        arc.execute(_META_DDL)

        pg_cur = pg_conn.cursor()
        eligible = _eligible_sessions(pg_cur)
        summary = dict(archive_path=archive_path, eligible_sessions=len(eligible),
                       synced=[], partial=[], errored=[], skipped_out_of_window=0)

        if not eligible:
            _write_meta(arc, now_iso, STATUS_OK, None, None, 0,
                        "no promoted+coherent sessions on Postgres yet")
            arc.commit()
            summary["status"] = STATUS_OK
            return summary

        latest = eligible[-1]["session"]
        try:
            cutoff = (_dt.date.fromisoformat(latest)
                      - _dt.timedelta(days=window_days)).isoformat()
            in_window = [e for e in eligible if e["session"] >= cutoff]
        except ValueError:  # a non-ISO source_as_of -- pull everything eligible
            in_window = list(eligible)
        summary["skipped_out_of_window"] = len(eligible) - len(in_window)

        _sync_current_publication(pg_cur, arc)

        col_cache: dict = {}
        overall = STATUS_OK
        for e in in_window:
            session = e["session"]
            try:
                status, counts, detail = _pull_session(pg_cur, arc, session, tables, col_cache)
            except Exception as exc:  # one bad session must not abort the rest
                status, counts, detail = STATUS_ERROR, {}, f"{type(exc).__name__}: {exc}"
                logger.warning("archive sync: session %s failed: %s", session, exc)
                # a failed query leaves the (read-only) PG transaction aborted --
                # clear it so the remaining sessions are not all dragged to ERROR
                try:
                    pg_conn.rollback()
                except Exception:
                    pass
            arc.execute(
                "INSERT INTO archive_sync_state "
                "(session_date, source_run_id, coherence, synced_at, status, "
                " row_counts_json, detail) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_date) DO UPDATE SET "
                "  source_run_id=excluded.source_run_id, coherence=excluded.coherence, "
                "  synced_at=excluded.synced_at, status=excluded.status, "
                "  row_counts_json=excluded.row_counts_json, detail=excluded.detail",
                (session, e["run_id"], e["coherence"], now_iso, status,
                 json.dumps(counts), detail),
            )
            if status == STATUS_OK:
                summary["synced"].append(session)
            elif status == STATUS_PARTIAL:
                summary["partial"].append(session)
                overall = STATUS_PARTIAL if overall == STATUS_OK else overall
            else:
                summary["errored"].append(session)
                overall = STATUS_ERROR

        last_ok = arc.execute(
            "SELECT MAX(session_date) FROM archive_sync_state WHERE status = ?",
            (STATUS_OK,),
        ).fetchone()[0]
        _write_meta(arc, now_iso, overall, last_ok, latest, len(in_window),
                    _meta_detail(summary))
        arc.commit()
        summary["status"] = overall
        summary["last_session_synced"] = last_ok
        summary["pg_latest_promoted_session"] = latest
        return summary
    finally:
        arc.close()
        if owns_conn:
            pg_conn.close()


def _meta_detail(summary: dict) -> str:
    return (f"{len(summary['synced'])} ok, {len(summary['partial'])} partial, "
            f"{len(summary['errored'])} error, "
            f"{summary['skipped_out_of_window']} out-of-window")


def _write_meta(arc, now_iso, status, last_session, pg_latest, n_window, detail):
    arc.execute(
        "INSERT INTO archive_sync_meta "
        "(id, last_run_at, last_run_status, last_session_synced, "
        " pg_latest_promoted_session, sessions_in_window, detail) "
        "VALUES (1, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "  last_run_at=excluded.last_run_at, last_run_status=excluded.last_run_status, "
        "  last_session_synced=excluded.last_session_synced, "
        "  pg_latest_promoted_session=excluded.pg_latest_promoted_session, "
        "  sessions_in_window=excluded.sessions_in_window, detail=excluded.detail",
        (now_iso, status, last_session, pg_latest, n_window, detail),
    )


def archive_status(archive_path: str | None = None) -> dict | None:
    """The heartbeat row + a small per-session summary. Read-only, never raises."""
    archive_path = archive_path or os.path.join(
        os.path.dirname(config.DB_PATH), "psx_archive.db")
    if not os.path.exists(archive_path):
        return None
    try:
        arc = sqlite3.connect(archive_path)
        try:
            meta = arc.execute(
                "SELECT last_run_at, last_run_status, last_session_synced, "
                "pg_latest_promoted_session, sessions_in_window, detail "
                "FROM archive_sync_meta WHERE id = 1"
            ).fetchone()
            if not meta:
                return None
            sessions = arc.execute(
                "SELECT session_date, status FROM archive_sync_state "
                "ORDER BY session_date DESC LIMIT 15"
            ).fetchall()
            keys = ("last_run_at", "last_run_status", "last_session_synced",
                    "pg_latest_promoted_session", "sessions_in_window", "detail")
            out = dict(zip(keys, meta))
            out["is_behind"] = (
                out["last_session_synced"] is not None
                and out["pg_latest_promoted_session"] is not None
                and out["last_session_synced"] < out["pg_latest_promoted_session"]
            )
            out["recent_sessions"] = [{"session": s, "status": st} for s, st in sessions]
            return out
        finally:
            arc.close()
    except Exception:
        return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true", help="print the heartbeat, no write")
    ap.add_argument("--archive-path", default=None)
    ap.add_argument("--window-days", type=int, default=90)
    args = ap.parse_args()

    if args.status:
        st = archive_status(args.archive_path)
        print(json.dumps(st, indent=2, default=str) if st else "no archive yet")
        return 0

    summary = sync_archive(archive_path=args.archive_path, window_days=args.window_days)
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary.get("status") == STATUS_OK else 1


if __name__ == "__main__":
    sys.exit(main())
