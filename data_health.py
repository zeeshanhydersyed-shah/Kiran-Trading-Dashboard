"""Live data-health verdict for the sidebar banner, plus the pipeline_runs ledger.

Design notes (see docs/KIRAN_CLEANUP_AUDIT.md 31):

Two classes of checked thing, because they fail differently:

  * EVERY_SESSION tables get a row on every trading day. "Does its own MAX(date)
    equal the expected session?" is the strongest available test -- it catches a
    hook that ran but wrote nothing, which a heartbeat alone would miss.

  * HEARTBEAT items legitimately produce zero rows on a given day
    (save_top_picks(): "If none qualify, nothing is written -- this is
    intentional"). For those, table emptiness is indistinguishable from a dead
    producer, so the honest question is "when did the producer last RUN", which
    is what pipeline_runs records.

That distinction is the whole point. The retired Data Health "Last Checked"
metric read MAX(suspect_date) FROM corporate_action_suspects -- the date of the
last *finding*, not the last *look* -- so a clean run and a dead checker
displayed the same value, and it sat at 2026-06-22 for two months without
anyone noticing. Heartbeats exist so that failure mode cannot recur.

This module performs NO network I/O. The expected-session date is passed in by
the caller (dashboard.py supplies it from refresh_manager.get_source_date_cached,
which owns the short-TTL cache). Keeping the fetch out here means the verdict
itself is never cached and stays unit-testable.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import config

_PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")

_PROJECT_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# What gets checked
# ---------------------------------------------------------------------------

# (table, date column, human label)
EVERY_SESSION: list[tuple[str, str, str]] = [
    ("prices",           "date",       "prices"),
    ("index_prices",     "date",       "index_prices"),
    ("prices_adjusted",  "date",       "prices_adjusted"),
    ("stock_signals",    "date",       "stock_signals"),
    ("sector_signals",   "date",       "sector_signals"),
    ("market_regime",    "date",       "market_regime"),
    # Daily snapshot of currently-qualifying bases, NOT a ~1/year event log --
    # 11 unbroken trading days then a hard stop, and signal_engine.py has no
    # automated caller at all. Audit 30.
    ("recovery_signals", "as_of_date", "recovery_signals"),
]

# (hook_name as recorded in pipeline_runs, human label)
HEARTBEAT: list[tuple[str, str]] = [
    ("setup_log",        "setup_log"),
    ("leaders_scan",     "leaders_scan"),
    ("boring_signals",   "boring_signals"),
    ("corporate_action", "corporate_action scan"),
]

# Tables deliberately NOT checked, so the omissions are explicit rather than
# forgotten:
#   market_flows        -- feeds only the descriptive-only Flow column; the Big
#                          Fish study found the underlying data null (0/360).
#   leaders_top_picks   -- covered by the leaders_scan heartbeat; its own table
#                          is legitimately empty whenever nothing clears
#                          MIN_PICK_SCORE, so a date check would false-positive.
#   sec_global_rank     -- not a table; it is sector_signals.rs_rank aliased in
#                          dashboard_pg.py:561.


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Item:
    label: str
    status: str           # 'ok' | 'stale' | 'unknown'
    detail: str
    behind: int | None = None   # trading sessions behind, when computable


@dataclass
class Verdict:
    level: str                       # 'green' | 'red' | 'amber'
    expected: str | None             # expected latest session, or None
    expected_source: str             # where `expected` came from
    items: list[Item] = field(default_factory=list)

    @property
    def failures(self) -> list[Item]:
        """Worst first: unknown outranks stale, then most-sessions-behind."""
        bad = [i for i in self.items if i.status != "ok"]
        return sorted(
            bad,
            key=lambda i: (i.status != "unknown", -(i.behind or 0)),
        )


# ---------------------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------------------

def _env_pg_url() -> str | None:
    """Postgres URL from the environment, falling back to parsing .env.

    Nothing in this project calls load_dotenv(), so a local `main.py --all`
    run (run_update.bat, Task Scheduler at logon) has SUPABASE_DB_URL only in
    the .env file, never in os.environ. The boring_signals heartbeat has to
    reach Supabase from exactly that context -- it is the one signal the
    Streamlit Cloud app cannot otherwise see, because boring_signals is
    SQLite-only and has no Postgres table at all.
    """
    url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
    if url:
        return url
    env_path = _PROJECT_DIR / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            for key in ("SUPABASE_DB_URL=", "DATABASE_URL="):
                if line.startswith(key):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _is_missing_table(exc: Exception) -> bool:
    """True when the error is 'that table does not exist' on either backend.

    SQLite raises OperationalError("no such table: x"); psycopg2 raises
    UndefinedTable. Matched on message text so this stays import-free of
    psycopg2 when running on the SQLite path.
    """
    msg = str(exc).lower()
    return "no such table" in msg or "does not exist" in msg or "undefinedtable" in msg


def _iso(value) -> str | None:
    """Normalise a date/datetime/str to ISO YYYY-MM-DD, or None."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return str(value)[:10]


# ---------------------------------------------------------------------------
# pipeline_runs ledger
# ---------------------------------------------------------------------------

_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    hook_name    TEXT    NOT NULL,
    run_date     TEXT    NOT NULL,
    finished_at  TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    rows_written INTEGER,
    detail       TEXT,
    UNIQUE(hook_name, run_date)
)
"""

# Mirrors the SQLite shape, including the UNIQUE key. That key is not optional:
# the migration that created leaders_scan/leaders_top_picks/setup_log in
# Supabase dropped their UNIQUE(...) constraints, which left setup_log's bare
# ON CONFLICT DO NOTHING silently non-idempotent for months (audit 29.3/29.8).
_PG_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hook_name    TEXT        NOT NULL,
    run_date     TEXT        NOT NULL,
    finished_at  TIMESTAMPTZ NOT NULL,
    status       TEXT        NOT NULL,
    rows_written INTEGER,
    detail       TEXT,
    CONSTRAINT pipeline_runs_natural_key UNIQUE (hook_name, run_date)
)
"""


def ensure_ledger_sqlite(con) -> None:
    con.execute(_SQLITE_DDL)


def ensure_ledger_pg(cur) -> None:
    cur.execute(_PG_DDL)


def record_run(
    hook_name: str,
    run_date: str,
    status: str = "ok",
    rows_written: int | None = None,
    detail: str | None = None,
    mirror_to_postgres: bool = False,
) -> None:
    """Record one hook execution. Never raises -- a telemetry write must not be
    able to break the pipeline it is measuring.

    mirror_to_postgres: also write to Supabase even when the active backend is
    SQLite. Used by boring_signals, whose data lives only in local SQLite but
    whose liveness the Cloud dashboard still needs to see.
    """
    finished_at = datetime.now(timezone.utc)
    run_date = _iso(run_date) or str(run_date)

    if _PG_URL:
        _record_pg(_PG_URL, hook_name, run_date, finished_at, status, rows_written, detail)
        return

    try:
        con = sqlite3.connect(config.DB_PATH)
        try:
            ensure_ledger_sqlite(con)
            con.execute(
                """
                INSERT INTO pipeline_runs
                    (hook_name, run_date, finished_at, status, rows_written, detail)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(hook_name, run_date) DO UPDATE SET
                    finished_at  = excluded.finished_at,
                    status       = excluded.status,
                    rows_written = excluded.rows_written,
                    detail       = excluded.detail
                """,
                (hook_name, run_date, finished_at.isoformat(), status, rows_written, detail),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        pass

    if mirror_to_postgres:
        url = _env_pg_url()
        if url:
            _record_pg(url, hook_name, run_date, finished_at, status, rows_written, detail)


def _record_pg(url, hook_name, run_date, finished_at, status, rows_written, detail) -> None:
    """Ledger write against Postgres. Swallows everything by design."""
    try:
        import psycopg2

        conn = psycopg2.connect(url)
        try:
            with conn:
                cur = conn.cursor()
                ensure_ledger_pg(cur)
                cur.execute(
                    """
                    INSERT INTO pipeline_runs
                        (hook_name, run_date, finished_at, status, rows_written, detail)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (hook_name, run_date) DO UPDATE SET
                        finished_at  = EXCLUDED.finished_at,
                        status       = EXCLUDED.status,
                        rows_written = EXCLUDED.rows_written,
                        detail       = EXCLUDED.detail
                    """,
                    (hook_name, run_date, finished_at, status, rows_written, detail),
                )
        finally:
            conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The check itself
# ---------------------------------------------------------------------------

def _sessions_between(fetch_one, low: str, high: str) -> int | None:
    """Trading sessions strictly after `low`, up to and including `high`.

    Counted from distinct `prices` dates rather than calendar arithmetic, so
    weekends and PSX holidays never inflate the number. There is no holiday
    calendar anywhere in this codebase -- prices IS the trading calendar.
    """
    if not low or not high or low >= high:
        return 0
    row = fetch_one(
        "SELECT COUNT(DISTINCT date) FROM prices WHERE date > {p} AND date <= {p}",
        (low, high),
    )
    return int(row[0]) if row and row[0] is not None else None


def check_all(expected_session: str | None = None,
              source_error: str | None = None) -> Verdict:
    """Build the whole-system verdict. Runs live queries; caches nothing.

    expected_session: the latest completed session per ksestocks (the exchange
        is the authority on its own holidays). None means the caller could not
        determine it -- the absolute check then degrades to amber rather than
        silently passing.
    """
    items: list[Item] = []
    expected_source = "ksestocks" if expected_session else "unavailable"

    try:
        fetch_one, close = _open()
    except Exception as exc:
        return Verdict(
            level="red",
            expected=expected_session,
            expected_source=expected_source,
            items=[Item("database", "unknown", f"cannot connect: {exc}")],
        )

    try:
        # Reference date for the relative chain. Every downstream table is
        # compared against prices, so a uniformly-behind pipeline is caught by
        # the absolute check below rather than passing as internally consistent.
        try:
            row = fetch_one("SELECT MAX(date) FROM prices", ())
            prices_max = _iso(row[0]) if row else None
        except Exception as exc:
            prices_max = None
            items.append(Item("prices", "unknown", f"query failed: {exc}"))

        # -- absolute: is prices itself level with the exchange? --
        if prices_max is None:
            pass  # already reported as unknown above
        elif expected_session is None:
            items.append(Item(
                "prices", "unknown",
                f"at {prices_max}; cannot reach ksestocks to confirm"
                + (f" ({source_error})" if source_error else ""),
            ))
        elif prices_max < expected_session:
            items.append(Item(
                "prices", "stale",
                f"{prices_max}, exchange published {expected_session}",
                behind=1,
            ))
        else:
            items.append(Item("prices", "ok", prices_max))

        reference = expected_session if (
            expected_session and prices_max and expected_session <= prices_max
        ) else prices_max

        # -- every-session tables --
        for table, col, label in EVERY_SESSION:
            if label == "prices":
                continue  # handled above
            try:
                row = fetch_one(f"SELECT MAX({col}) FROM {table}", ())
                tmax = _iso(row[0]) if row else None
            except Exception as exc:
                items.append(Item(label, "unknown", f"query failed: {exc}"))
                continue

            if tmax is None:
                items.append(Item(label, "stale", "table is empty"))
            elif reference and tmax < reference:
                behind = _sessions_between(fetch_one, tmax, reference)
                items.append(Item(
                    label, "stale",
                    f"{tmax}" + (f", {behind} session{'s' if behind != 1 else ''} behind"
                                 if behind else ""),
                    behind=behind,
                ))
            else:
                items.append(Item(label, "ok", tmax))

        # -- heartbeat items --
        for hook, label in HEARTBEAT:
            try:
                row = fetch_one(
                    "SELECT run_date, status FROM pipeline_runs "
                    "WHERE hook_name = {p} ORDER BY run_date DESC LIMIT 1",
                    (hook,),
                )
            except Exception as exc:
                # A ledger that does not exist yet carries the same meaning as
                # an empty one -- no run has been recorded. Report that plainly
                # rather than leaking "no such table" into the banner. Any
                # other error is a genuine fault and keeps its message.
                if _is_missing_table(exc):
                    items.append(Item(label, "unknown", "no run recorded yet"))
                else:
                    items.append(Item(label, "unknown", f"ledger unreadable: {exc}"))
                continue

            if not row:
                items.append(Item(label, "unknown", "no run ever recorded"))
                continue

            last_run, run_status = _iso(row[0]), row[1]
            if run_status != "ok":
                items.append(Item(label, "stale", f"last run {last_run} failed"))
            elif reference and last_run < reference:
                behind = _sessions_between(fetch_one, last_run, reference)
                items.append(Item(
                    label, "stale",
                    f"last ran {last_run}"
                    + (f", {behind} session{'s' if behind != 1 else ''} behind" if behind else ""),
                    behind=behind,
                ))
            else:
                items.append(Item(label, "ok", f"ran {last_run}"))
    finally:
        try:
            close()
        except Exception:
            pass

    # Red dominates amber: a known-stale table is a stronger statement than an
    # unverifiable one. Green requires every item to have explicitly passed.
    if any(i.status == "stale" for i in items):
        level = "red"
    elif any(i.status == "unknown" for i in items):
        level = "amber"
    else:
        level = "green"

    return Verdict(level=level, expected=expected_session,
                   expected_source=expected_source, items=items)


def _open():
    """Return (fetch_one, close) for whichever backend is active.

    fetch_one takes SQL containing `{p}` placeholders and substitutes the
    backend's parameter style, so callers write one query string.
    """
    if _PG_URL:
        from database_pg import get_conn

        ctx = get_conn()
        conn = ctx.__enter__()
        cur = conn.cursor()

        def fetch_one(sql, params):
            cur.execute(sql.replace("{p}", "%s"), params)
            return cur.fetchone()

        def close():
            ctx.__exit__(None, None, None)

        return fetch_one, close

    con = sqlite3.connect(config.DB_PATH)

    def fetch_one(sql, params):
        return con.execute(sql.replace("{p}", "?"), params).fetchone()

    return fetch_one, con.close
