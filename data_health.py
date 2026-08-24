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

import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)

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
    ("setup_log",         "setup_log"),
    ("leaders_scan",      "leaders_scan"),
    ("boring_signals",    "boring_signals"),
    # TR-06 Tier 2 (2026-08-24): split from a single "corporate_action" entry
    # into its two independently-failable operations, matching main.py's
    # heartbeat split (docs/KIRAN_BORING_STATE_TRUST_REGISTER.md, TR-06).
    # Neither retires the other -- both legitimately produce zero rows most
    # days (an append with nothing new to append; a scan that finds no
    # suspects), the exact shape this HEARTBEAT list (vs. EVERY_SESSION)
    # exists for. corporate_action_append's own output table
    # (prices_adjusted) is also separately watched via EVERY_SESSION above --
    # this entry is complementary execution/coverage evidence, not the only
    # safety net for that table. Fixes a real regression found in
    # independent review: main.py no longer writes hook_name='corporate_action'
    # at all after the split, so the single old entry would have permanently
    # read "no run ever recorded" post-deployment despite both new heartbeats
    # succeeding.
    ("corporate_action_append",        "prices_adjusted append"),
    ("corporate_action_suspects_scan", "corporate_action scan"),
    # Previously in neither list -- confirmed zero monitoring on either
    # backend anywhere (docs/KIRAN_CLEANUP_AUDIT.md §37-39, §44). Heartbeat,
    # not EVERY_SESSION: run_portfolio_signals() snapshots the latest
    # sector_signals date rather than guaranteeing one row per trading
    # session, so a MAX(date)-vs-expected-session check could false-positive
    # the same way leaders_top_picks would if checked that way.
    ("portfolio_signals", "portfolio_signals"),
]

# ---------------------------------------------------------------------------
# TR-06 Tier 2 coverage vocabulary (docs/KIRAN_BORING_STATE_TRUST_REGISTER.md,
# TR-06). Two separate dimensions, not one combined enum -- an execution that
# failed has no meaningful coverage verdict, and a hook that never reports a
# coverage pair is not the same as one that reported and fell short.
#
# EXECUTION_* mirrors the pre-existing status='ok'/'error' values used by
# every existing caller -- COMPLETED/FAILED are the only two values a hook
# call site ever writes; NOT_STARTED/HEARTBEAT_WRITE_FAILED/UNKNOWN describe
# the ABSENCE of a row (or a query failure reading pipeline_runs) and are
# never persisted here, only inferred by a reader. Not wired into check_all()
# by this change -- see the design-lock record this implements.
EXECUTION_COMPLETED = "COMPLETED"
EXECUTION_FAILED = "FAILED"

# COVERAGE_* is meaningful only when execution completed. NOT_APPLICABLE
# covers both "this hook's shape has no eligible/processed pair" (e.g.
# regime's single-row-per-session presence) and "a real denominator isn't
# yet computed for this hook" -- both are honest non-answers, never a
# manufactured EXPECTED/INSUFFICIENT verdict.
COVERAGE_EXPECTED = "EXPECTED"
COVERAGE_INSUFFICIENT = "INSUFFICIENT"
COVERAGE_NOT_APPLICABLE = "NOT_APPLICABLE"


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

# TR-06 Tier 2 (2026-08-24) -- additive columns only. The existing
# UNIQUE(hook_name, run_date) natural key is deliberately left unchanged: the
# design-lock explicitly scoped this to "additive, not a natural-key
# migration" -- run_id identifies which cmd_update() invocation a row came
# from, it does not replace how rows are addressed. Every new column is
# nullable so every pre-existing row (and every caller that doesn't pass the
# new kwargs, e.g. the still-HELD main.py hooks) stays valid with no
# backfill required.
_NEW_COLUMNS: list[tuple[str, str, str]] = [
    # (column name, SQLite type, Postgres type)
    ("run_id",           "TEXT",    "TEXT"),
    ("execution_status",  "TEXT",    "TEXT"),
    ("coverage_status",   "TEXT",    "TEXT"),
    ("eligible_count",    "INTEGER", "INTEGER"),
    ("processed_count",   "INTEGER", "INTEGER"),
]


def ensure_ledger_sqlite(con) -> None:
    con.execute(_SQLITE_DDL)
    existing = {row[1] for row in con.execute("PRAGMA table_info(pipeline_runs)").fetchall()}
    for name, sqlite_type, _pg_type in _NEW_COLUMNS:
        if name not in existing:
            con.execute(f"ALTER TABLE pipeline_runs ADD COLUMN {name} {sqlite_type}")


def ensure_ledger_pg(cur) -> None:
    cur.execute(_PG_DDL)
    for name, _sqlite_type, pg_type in _NEW_COLUMNS:
        cur.execute(f"ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS {name} {pg_type}")


def record_run(
    hook_name: str,
    run_date: str,
    status: str = "ok",
    rows_written: int | None = None,
    detail: str | None = None,
    mirror_to_postgres: bool = False,
    run_id: str | None = None,
    execution_status: str | None = None,
    coverage_status: str | None = None,
    eligible_count: int | None = None,
    processed_count: int | None = None,
) -> None:
    """Record one hook execution. Never raises -- a telemetry write must not be
    able to break the pipeline it is measuring.

    mirror_to_postgres: also write to Supabase even when the active backend is
    SQLite. Used by boring_signals, whose data lives only in local SQLite but
    whose liveness the Cloud dashboard still needs to see.

    TR-06 Tier 2 (2026-08-24) -- five additive, optional fields layered on top
    of the pre-existing status/rows_written contract, per the design-lock
    record. execution_status is NOT derived from rows_written or any coverage
    field -- deriving it from status keeps every existing, unmodified caller
    (including main.py's still-HELD hooks, which never pass these new kwargs
    at all) producing a correct value automatically, with zero call-site
    changes required of them.
    """
    finished_at = datetime.now(timezone.utc)
    run_date = _iso(run_date) or str(run_date)
    if execution_status is None:
        execution_status = EXECUTION_COMPLETED if status == "ok" else EXECUTION_FAILED

    if _PG_URL:
        _record_pg(_PG_URL, hook_name, run_date, finished_at, status, rows_written, detail,
                   run_id, execution_status, coverage_status, eligible_count, processed_count)
        return

    try:
        con = sqlite3.connect(config.DB_PATH)
        try:
            ensure_ledger_sqlite(con)
            con.execute(
                """
                INSERT INTO pipeline_runs
                    (hook_name, run_date, finished_at, status, rows_written, detail,
                     run_id, execution_status, coverage_status, eligible_count, processed_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hook_name, run_date) DO UPDATE SET
                    finished_at      = excluded.finished_at,
                    status           = excluded.status,
                    rows_written     = excluded.rows_written,
                    detail           = excluded.detail,
                    run_id           = excluded.run_id,
                    execution_status = excluded.execution_status,
                    coverage_status  = excluded.coverage_status,
                    eligible_count   = excluded.eligible_count,
                    processed_count  = excluded.processed_count
                """,
                (hook_name, run_date, finished_at.isoformat(), status, rows_written, detail,
                 run_id, execution_status, coverage_status, eligible_count, processed_count),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        pass

    if mirror_to_postgres:
        url = _env_pg_url()
        if url:
            _record_pg(url, hook_name, run_date, finished_at, status, rows_written, detail,
                       run_id, execution_status, coverage_status, eligible_count, processed_count)


def _record_pg(url, hook_name, run_date, finished_at, status, rows_written, detail,
                run_id=None, execution_status=None, coverage_status=None,
                eligible_count=None, processed_count=None) -> None:
    """Ledger write against Postgres. Swallows everything by design -- a
    telemetry write must never break the pipeline it measures -- but now
    logs one safe line per attempt so a real run's outcome, and which stage
    it reached (connect / insert / commit), is observable. Never logs the
    connection string, credentials, or raw exception text -- psycopg2 error
    messages can embed the DSN -- only the exception class name is logged.

    Diagnostic added to investigate docs/KIRAN_CLEANUP_AUDIT.md 56's Hidden
    Risk 1: three already-deployed heartbeats (corporate_action/setup_log/
    leaders_scan) produce no rows in live Postgres pipeline_runs, and this
    function's prior total silence made it impossible to tell why.

    Uses database_pg._parse_pg_url() (this project's own hardened
    keyword-arg connection pattern, added after a prior Supabase-password
    special-character parsing bug, commit c361482) instead of the bare
    psycopg2.connect(url) this function used before -- named in 56.4 as one
    of two plausible failure mechanisms.
    """
    start = time.monotonic()

    def _fail(stage: str, exc: Exception) -> None:
        logger.warning(
            "pipeline_runs heartbeat failed: hook=%s date=%s stage=%s error=%s elapsed=%.2fs",
            hook_name, run_date, stage, type(exc).__name__, time.monotonic() - start,
        )

    try:
        import psycopg2

        from database_pg import _parse_pg_url

        try:
            conn = psycopg2.connect(**_parse_pg_url(url))
        except Exception as exc:
            _fail("connect", exc)
            return

        try:
            try:
                cur = conn.cursor()
                ensure_ledger_pg(cur)
                cur.execute(
                    """
                    INSERT INTO pipeline_runs
                        (hook_name, run_date, finished_at, status, rows_written, detail,
                         run_id, execution_status, coverage_status, eligible_count, processed_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (hook_name, run_date) DO UPDATE SET
                        finished_at      = EXCLUDED.finished_at,
                        status           = EXCLUDED.status,
                        rows_written     = EXCLUDED.rows_written,
                        detail           = EXCLUDED.detail,
                        run_id           = EXCLUDED.run_id,
                        execution_status = EXCLUDED.execution_status,
                        coverage_status  = EXCLUDED.coverage_status,
                        eligible_count   = EXCLUDED.eligible_count,
                        processed_count  = EXCLUDED.processed_count
                    """,
                    (hook_name, run_date, finished_at, status, rows_written, detail,
                     run_id, execution_status, coverage_status, eligible_count, processed_count),
                )
            except Exception as exc:
                conn.rollback()
                _fail("insert", exc)
                return

            try:
                conn.commit()
            except Exception as exc:
                _fail("commit", exc)
                return

            logger.info(
                "pipeline_runs heartbeat written: hook=%s date=%s elapsed=%.2fs",
                hook_name, run_date, time.monotonic() - start,
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

    expected_session: the latest completed session per ksestocks (our source,
        not PSX itself -- treated as the authority on its own holidays since
        no separate PSX holiday calendar exists in this codebase). None means
        the caller could not determine it -- the absolute check then degrades
        to amber rather than silently passing.
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

        # -- absolute: is prices itself level with the ksestocks source? --
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
                f"{prices_max}, ksestocks source has {expected_session}",
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
