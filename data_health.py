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
# TR-05 publication-validity vocabulary (docs/KIRAN_BORING_STATE_TRUST_REGISTER.md,
# TR-05). Smallest possible abstraction shared by both TR-05 blockers -- the
# execution-time gate in main.py's cmd_update() and the serving-time gate in
# dashboard.py -- so "what does this Verdict mean for publication" is answered
# in exactly one place, not reimplemented at each call site.
#
# publication_status(None) is deliberately CANNOT_VERIFY, not STALE and not
# VERIFIED: a verdict that could not even be computed (e.g. check_all() itself
# raised) must never be treated as equivalent to a confirmed-fresh state --
# see TR-05's fail-closed semantics ("CANNOT VERIFY" must never become
# "CURRENT").
PUBLICATION_VERIFIED       = "VERIFIED"
PUBLICATION_STALE          = "STALE"
PUBLICATION_CANNOT_VERIFY  = "CANNOT_VERIFY"


def publication_status(verdict: "Verdict | None") -> str:
    """Map a check_all() Verdict (or its absence) to the TR-05 publication vocabulary.

    green  -> VERIFIED       (fresh/valid -- normal actionable rendering may continue)
    red    -> STALE          (actionable state must not be presented)
    amber  -> CANNOT_VERIFY  (actionable state must not be presented)
    None   -> CANNOT_VERIFY  (the verdict itself could not be produced)
    """
    if verdict is None:
        return PUBLICATION_CANNOT_VERIFY
    return {
        "green": PUBLICATION_VERIFIED,
        "red":   PUBLICATION_STALE,
        "amber": PUBLICATION_CANNOT_VERIFY,
    }.get(verdict.level, PUBLICATION_CANNOT_VERIFY)


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

    The .env fallback is consulted only when BOTH variables are genuinely
    absent from os.environ -- checked by presence (`in os.environ`), not by
    truthiness. An explicitly-set empty string (e.g. a test's
    `monkeypatch.setenv(key, "")`) is a deliberate "no database configured
    here" signal and must be honored as such, never silently overridden by
    reading the real .env file. 2026-08-26 incident: the prior truthiness
    check let exactly this happen -- a test that cleared both env vars this
    way still reached real production Supabase through this fallback,
    because `"" or ""` is falsy and fell through to the file read below.
    """
    if "DATABASE_URL" in os.environ or "SUPABASE_DB_URL" in os.environ:
        return os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or None
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
    # OI-9 / TR-11 (2026-08-31): the commit SHA of the code that produced this
    # run -- $GITHUB_SHA on an Actions runner, else the serving checkout's
    # .git/HEAD (serving_revision.resolve_code_version()), else NULL. Additive
    # and nullable like the rest: every pre-existing row and every caller that
    # does not pass it stays valid with no backfill. Makes every production
    # write permanently traceable to one commit (KIRAN_CLEANUP_AUDIT.md 88).
    ("code_version",      "TEXT",    "TEXT"),
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
    code_version: str | None = None,
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
                   run_id, execution_status, coverage_status, eligible_count, processed_count,
                   code_version)
        return

    try:
        con = sqlite3.connect(config.DB_PATH)
        try:
            ensure_ledger_sqlite(con)
            con.execute(
                """
                INSERT INTO pipeline_runs
                    (hook_name, run_date, finished_at, status, rows_written, detail,
                     run_id, execution_status, coverage_status, eligible_count, processed_count,
                     code_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hook_name, run_date) DO UPDATE SET
                    finished_at      = excluded.finished_at,
                    status           = excluded.status,
                    rows_written     = excluded.rows_written,
                    detail           = excluded.detail,
                    run_id           = excluded.run_id,
                    execution_status = excluded.execution_status,
                    coverage_status  = excluded.coverage_status,
                    eligible_count   = excluded.eligible_count,
                    processed_count  = excluded.processed_count,
                    code_version     = excluded.code_version
                """,
                (hook_name, run_date, finished_at.isoformat(), status, rows_written, detail,
                 run_id, execution_status, coverage_status, eligible_count, processed_count,
                 code_version),
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
                       run_id, execution_status, coverage_status, eligible_count, processed_count,
                       code_version)


def _record_pg(url, hook_name, run_date, finished_at, status, rows_written, detail,
                run_id=None, execution_status=None, coverage_status=None,
                eligible_count=None, processed_count=None, code_version=None) -> None:
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
                         run_id, execution_status, coverage_status, eligible_count, processed_count,
                         code_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (hook_name, run_date) DO UPDATE SET
                        finished_at      = EXCLUDED.finished_at,
                        status           = EXCLUDED.status,
                        rows_written     = EXCLUDED.rows_written,
                        detail           = EXCLUDED.detail,
                        run_id           = EXCLUDED.run_id,
                        execution_status = EXCLUDED.execution_status,
                        coverage_status  = EXCLUDED.coverage_status,
                        eligible_count   = EXCLUDED.eligible_count,
                        processed_count  = EXCLUDED.processed_count,
                        code_version     = EXCLUDED.code_version
                    """,
                    (hook_name, run_date, finished_at, status, rows_written, detail,
                     run_id, execution_status, coverage_status, eligible_count, processed_count,
                     code_version),
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
# TR-01/TR-12 -- consumer-authority alert (2026-09-02, ledger §109). Option A
# of the two-option plan agreed with the owner: alert immediately, don't
# block (that's Option B, deferred -- Postgres role separation). Closes the
# "silent" half of the OI-8 incident class: a local Windows process ends up
# with a live Postgres URL and starts writing production signal data, and
# nobody finds out until real damage is already done (OI-8 itself ran two
# days before anyone noticed). This does not prevent the write -- it makes
# sure it can never again be silent.
#
# Why "platform == Windows" and not "is this GitHub Actions" or "is this
# Streamlit Cloud": those two are the only legitimate places a real
# production write can originate, and neither one *ever* runs on Windows
# (ubuntu-latest runners, Linux containers respectively) -- a positive check
# for "is this the owner's local machine" would need to distinguish local
# Streamlit from Cloud Streamlit, which look byte-identical from inside the
# process (both read DATABASE_URL the same way). Checking for the one
# environment that can never legitimately be either is more robust than
# trying to positively identify the two that can.
#
# Why this does not also fire on the intentional boring_signals mirror
# write: that heartbeat uses _env_pg_url() (a separate, opt-in .env read)
# specifically so it can reach Postgres without flipping the process's main
# _PG_URL backend selector -- the exact thing this function's caller checks.
# The exemption is structural, not a special case bolted on here.
# ---------------------------------------------------------------------------

def is_local_windows_pg_write_risk(pg_url: str | None) -> bool:
    """True only when a Postgres URL is live AND this process is running on
    Windows -- the one combination that should never legitimately occur
    (GitHub Actions and Streamlit Cloud are both always Linux). Never
    raises; a failure to determine the platform is treated as *not* a risk
    (fail-open here, deliberately -- this is an alert, not a gate, so a
    detection failure should not itself become a spurious alarm)."""
    if not pg_url:
        return False
    try:
        import platform
        return platform.system() == "Windows"
    except Exception:
        return False


def alert_consumer_authority_violation(run_id: str | None, code_version: str | None,
                                        detail: str) -> None:
    """Log loudly, record a pipeline_runs heartbeat, and push an immediate
    ntfy alert (reusing TR-18's already-provisioned topic -- no new channel
    for the same owner's phone). Never raises -- an alert must not be able
    to break the run it is reporting on."""
    logger.error(
        "CONSUMER-AUTHORITY VIOLATION: a local Windows process has a live "
        "Postgres URL and is about to write production signal data outside "
        "GitHub Actions -- %s. See Trust Register TR-01/TR-12.", detail,
    )
    try:
        record_run(
            "consumer_authority_violation",
            __import__("datetime").date.today().isoformat(),
            status="error", detail=detail, run_id=run_id, code_version=code_version,
            execution_status=EXECUTION_FAILED,
        )
    except Exception as exc:
        logger.debug("consumer_authority_violation heartbeat failed: %s", exc)
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://ntfy.sh/kiran-psx-alerts-7g3k9qx2mp",
            data=f"Local Windows process writing to Postgres outside GitHub Actions: "
                 f"{detail}".encode("utf-8"),
            headers={
                "Title": "Kiran: local machine writing to production Postgres",
                "Priority": "urgent",
                "Tags": "rotating_light",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        logger.debug("consumer_authority_violation ntfy alert failed: %s", exc)


# ---------------------------------------------------------------------------
# TR-14 -- per-date scrape completeness vs the source's own per-sector
# traded-company counts (scraper.parse_sector_counts). Recorded every scrape;
# TR-14.1b wires a PARTIAL current session into check_all() so it blocks.
# ---------------------------------------------------------------------------

COVERAGE_COMPLETE = "COMPLETE"
COVERAGE_PARTIAL  = "PARTIAL"
COVERAGE_UNKNOWN  = "UNKNOWN"

# Owner decision (TR-14 spec §6): TOL = 0. A PARTIAL always means investigate;
# the specific short sector is named in `detail` rather than silently absorbed.
_COVERAGE_TOL = 0

_SCRAPE_COVERAGE_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS scrape_coverage (
    scrape_date     TEXT PRIMARY KEY,
    expected_total  INTEGER,
    parsed_total    INTEGER,
    coverage_status TEXT NOT NULL,
    detail          TEXT,
    recorded_at     TEXT NOT NULL DEFAULT (datetime('now')),
    code_version    TEXT
)
"""

_SCRAPE_COVERAGE_PG_DDL = """
CREATE TABLE IF NOT EXISTS scrape_coverage (
    scrape_date     DATE PRIMARY KEY,
    expected_total  INTEGER,
    parsed_total    INTEGER,
    coverage_status TEXT NOT NULL,
    detail          TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    code_version    TEXT
)
"""


def _coverage_verdict(expected_total, parsed_total) -> str:
    if expected_total is None:
        return COVERAGE_UNKNOWN
    if parsed_total is not None and parsed_total >= expected_total - _COVERAGE_TOL:
        return COVERAGE_COMPLETE
    return COVERAGE_PARTIAL


def ensure_scrape_coverage_sqlite(con) -> None:
    con.execute(_SCRAPE_COVERAGE_SQLITE_DDL)


def ensure_scrape_coverage_pg(cur) -> None:
    """One-time DDL for scrape_coverage on Postgres -- NOT called implicitly
    (same signed-off-first-run contract as ensure_boring_signals_scanned_table_pg)."""
    cur.execute(_SCRAPE_COVERAGE_PG_DDL)


def record_scrape_coverage(rows: list[dict], code_version: str | None = None) -> list[dict]:
    """Upsert one scrape_coverage row per scraped date. Never raises -- a
    completeness-telemetry write must not be able to break the scrape.

    rows: dicts from scraper.scrape_date_range(coverage_out=...) --
          {scrape_date, expected_total, parsed_total, detail}.
    Returns the same rows with 'coverage_status' filled in (for the caller's
    log line), even if the DB write itself failed.
    """
    out = []
    for r in rows:
        r = dict(r)
        r["coverage_status"] = _coverage_verdict(r.get("expected_total"), r.get("parsed_total"))
        out.append(r)
    if not out:
        return out

    try:
        if _PG_URL:
            _record_scrape_coverage_pg(out, code_version)
        else:
            con = sqlite3.connect(config.DB_PATH)
            try:
                ensure_scrape_coverage_sqlite(con)
                con.executemany(
                    """
                    INSERT INTO scrape_coverage
                        (scrape_date, expected_total, parsed_total, coverage_status, detail, code_version)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(scrape_date) DO UPDATE SET
                        expected_total  = excluded.expected_total,
                        parsed_total    = excluded.parsed_total,
                        coverage_status = excluded.coverage_status,
                        detail          = excluded.detail,
                        recorded_at     = datetime('now'),
                        code_version    = excluded.code_version
                    """,
                    [(r["scrape_date"], r.get("expected_total"), r.get("parsed_total"),
                      r["coverage_status"], r.get("detail"), code_version) for r in out],
                )
                con.commit()
            finally:
                con.close()
    except Exception as exc:
        logger.warning("record_scrape_coverage: write failed (%s)", type(exc).__name__)
    return out


def _record_scrape_coverage_pg(rows: list[dict], code_version: str | None) -> None:
    url = _env_pg_url()
    if not url:
        return
    import psycopg2
    from database_pg import _parse_pg_url
    conn = psycopg2.connect(**_parse_pg_url(url))
    try:
        with conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO scrape_coverage
                        (scrape_date, expected_total, parsed_total, coverage_status, detail, code_version)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT(scrape_date) DO UPDATE SET
                        expected_total  = EXCLUDED.expected_total,
                        parsed_total    = EXCLUDED.parsed_total,
                        coverage_status = EXCLUDED.coverage_status,
                        detail          = EXCLUDED.detail,
                        recorded_at     = NOW(),
                        code_version    = EXCLUDED.code_version
                    """,
                    [(r["scrape_date"], r.get("expected_total"), r.get("parsed_total"),
                      r["coverage_status"], r.get("detail"), code_version) for r in rows],
                )
    finally:
        conn.close()


def scrape_coverage_status(scrape_date: str) -> str | None:
    """The recorded coverage_status for one date, or None if not recorded /
    the table does not exist. Read-only; never raises. Used by check_all()
    (TR-14.1b) and boring_signals' completeness gate."""
    scrape_date = _iso(scrape_date) or str(scrape_date)
    try:
        fetch_one, close = _open()
        try:
            row = fetch_one("SELECT coverage_status FROM scrape_coverage WHERE scrape_date = {p}",
                            (scrape_date,))
            return row[0] if row and row[0] else None
        finally:
            close()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# TR-08 Publication Contract (2026-09-02, ledger §104) -- an append-only
# record of every publication *decision* main.run_freshness_gate() makes: did
# this run_id get promoted to "current published state," and if not, exactly
# which gate withheld it. v1 scope (owner-agreed, scratch
# TR08_PUBLICATION_CONTRACT_SPEC_DRAFT.md): freshness + completeness +
# per-run mandatory-hook completion only. Deliberately does NOT include a
# coherence (TR-04) or full validation (TR-06 tiering) field -- neither has a
# real per-run computed source yet; adding a fake one would be worse than
# leaving the gap named. Does NOT change dashboard.py's existing `_pub_ok`
# serving-time behavior (TR-05, already GREEN in production) -- this is a
# recording layer underneath it, not a replacement.
# ---------------------------------------------------------------------------

# The hooks a displayed SIGNAL actually depends on -- owner-confirmed
# 2026-09-02. Everything else recorded in pipeline_runs (corporate-action
# bookkeeping, the deployment_identity record, support_reversal -- a killed
# strategy since 2026-07-23 that always writes zero rows) is real telemetry
# but not required for THIS run to count as a valid publication.
MANDATORY_HOOKS = (
    "regime",
    "sector_signals",
    "stock_signals",
    "boring_signals",
    "recovery_signals",
    "portfolio_signals",
    "setup_log",
    "leaders_scan",
)

_CURRENT_PUBLICATION_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS current_publication (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                     TEXT,
    promoted_at                TEXT NOT NULL DEFAULT (datetime('now')),
    code_version               TEXT,
    source_as_of               TEXT,
    freshness_status           TEXT,
    completeness_status        TEXT,
    mandatory_hooks_completed  INTEGER,
    promoted                   INTEGER NOT NULL,
    withheld_reason            TEXT
)
"""

_CURRENT_PUBLICATION_PG_DDL = """
CREATE TABLE IF NOT EXISTS current_publication (
    id                         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                     TEXT,
    promoted_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    code_version               TEXT,
    source_as_of               TEXT,
    freshness_status           TEXT,
    completeness_status        TEXT,
    mandatory_hooks_completed  BOOLEAN,
    promoted                   BOOLEAN NOT NULL,
    withheld_reason            TEXT
)
"""


def ensure_current_publication_sqlite(con) -> None:
    con.execute(_CURRENT_PUBLICATION_SQLITE_DDL)


def ensure_current_publication_pg(cur) -> None:
    """One-time DDL for current_publication on Postgres -- NOT called
    implicitly (same signed-off-first-run contract as
    ensure_scrape_coverage_pg / ensure_boring_signals_scanned_table_pg)."""
    cur.execute(_CURRENT_PUBLICATION_PG_DDL)


def mandatory_hooks_completed_for_run(run_id: str | None,
                                       mandatory_hooks=MANDATORY_HOOKS) -> bool:
    """True only if every hook in `mandatory_hooks` has an execution_status
    of COMPLETED for this run_id in pipeline_runs. Fail-closed like every
    other publication-gate check here: no run_id, a query error, or any
    mandatory hook missing/FAILED all return False, never True by default --
    a computation that could not be verified must never look like a pass
    (the same CANNOT_VERIFY-never-becomes-VERIFIED principle TR-05 uses).
    """
    if not run_id:
        return False
    try:
        fetch_one, close = _open()
        try:
            placeholders = ",".join("{p}" for _ in mandatory_hooks)
            row = fetch_one(
                f"""
                SELECT COUNT(*) FROM pipeline_runs
                WHERE run_id = {{p}}
                  AND hook_name IN ({placeholders})
                  AND execution_status = {{p}}
                """,
                (run_id, *mandatory_hooks, EXECUTION_COMPLETED),
            )
            completed = int(row[0]) if row and row[0] is not None else 0
            return completed >= len(mandatory_hooks)
        finally:
            close()
    except Exception:
        return False


def decide_and_record_publication(
    run_id: str | None,
    code_version: str | None,
    source_as_of: str | None,
    freshness_status: str | None,
    completeness_status: str | None,
    mirror_to_postgres: bool = False,
) -> dict:
    """The TR-08 publication decision. Computes whether this run gets
    promoted to "current published state," writes one append-only row
    recording the decision and the real gate results behind it, and returns
    the same dict for the caller to log. Never raises -- a publication-
    telemetry write must not be able to break the pipeline it is measuring,
    same contract as record_run()/record_scrape_coverage().

    Promotion rule: freshness must be VERIFIED, completeness must not be
    PARTIAL (COMPLETE/UNKNOWN/absent all pass -- the same permissive reading
    boring_signals._completeness_ok() already uses for TR-14, since a date
    with no scrape_coverage row yet must not retroactively fail everything),
    and every MANDATORY_HOOKS entry must show COMPLETED for this run_id.
    A withheld run still gets a row -- an honest, queryable record of every
    decision, not just the promoted ones; the *previous* promoted row is
    never touched, so `latest_promoted_publication()` keeps returning the
    last genuinely good state exactly as TR-08's invariant requires.
    """
    mandatory_ok = mandatory_hooks_completed_for_run(run_id)
    reasons = []
    if freshness_status != PUBLICATION_VERIFIED:
        reasons.append(f"freshness={freshness_status}")
    if completeness_status == COVERAGE_PARTIAL:
        reasons.append(f"completeness={completeness_status}")
    if not mandatory_ok:
        reasons.append("mandatory_hooks_incomplete")
    promoted = not reasons
    withheld_reason = "; ".join(reasons) if reasons else None

    decision = dict(
        run_id=run_id,
        code_version=code_version,
        source_as_of=source_as_of,
        freshness_status=freshness_status,
        completeness_status=completeness_status,
        mandatory_hooks_completed=mandatory_ok,
        promoted=promoted,
        withheld_reason=withheld_reason,
    )

    try:
        if _PG_URL:
            _record_publication_pg(_PG_URL, decision)
        else:
            con = sqlite3.connect(config.DB_PATH)
            try:
                ensure_current_publication_sqlite(con)
                con.execute(
                    """
                    INSERT INTO current_publication
                        (run_id, code_version, source_as_of, freshness_status,
                         completeness_status, mandatory_hooks_completed, promoted,
                         withheld_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, code_version, source_as_of, freshness_status,
                     completeness_status, int(mandatory_ok), int(promoted),
                     withheld_reason),
                )
                con.commit()
            finally:
                con.close()
    except Exception as exc:
        logger.debug("current_publication write failed: %s", type(exc).__name__)

    if mirror_to_postgres and not _PG_URL:
        url = _env_pg_url()
        if url:
            try:
                _record_publication_pg(url, decision)
            except Exception as exc:
                logger.debug("current_publication PG mirror failed: %s", type(exc).__name__)

    return decision


def _record_publication_pg(url: str, decision: dict) -> None:
    import psycopg2
    from database_pg import _parse_pg_url
    conn = psycopg2.connect(**_parse_pg_url(url))
    try:
        with conn:
            with conn.cursor() as cur:
                ensure_current_publication_pg(cur)
                cur.execute(
                    """
                    INSERT INTO current_publication
                        (run_id, code_version, source_as_of, freshness_status,
                         completeness_status, mandatory_hooks_completed, promoted,
                         withheld_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (decision["run_id"], decision["code_version"], decision["source_as_of"],
                     decision["freshness_status"], decision["completeness_status"],
                     decision["mandatory_hooks_completed"], decision["promoted"],
                     decision["withheld_reason"]),
                )
    finally:
        conn.close()


def latest_promoted_publication() -> dict | None:
    """The most recently PROMOTED current_publication row, or None if the
    table doesn't exist yet or nothing has ever been promoted. Read-only,
    never raises. This is what a dashboard panel reads to show "what run is
    actually being served" -- deliberately the latest *promoted* row, not
    just the latest row, so a withheld decision never overwrites the last
    genuinely good publication a reader would see (TR-08's core invariant).
    """
    try:
        fetch_one, close = _open()
        try:
            row = fetch_one(
                """
                SELECT run_id, promoted_at, code_version, source_as_of,
                       freshness_status, completeness_status, withheld_reason
                FROM current_publication
                WHERE promoted = {p}
                ORDER BY promoted_at DESC, id DESC
                LIMIT 1
                """,
                # A Python bool, not an int -- SQLite's INTEGER column and
                # Postgres' BOOLEAN column both adapt True/False correctly;
                # binding 1 here would raise "operator does not exist:
                # boolean = integer" on Postgres (the exact bug class this
                # codebase has already hit twice: bos_flag TEXT-vs-DATE and
                # the Decimal-vs-float dedup guard).
                (True,),
            )
            if not row:
                return None
            return dict(zip(
                ("run_id", "promoted_at", "code_version", "source_as_of",
                 "freshness_status", "completeness_status", "withheld_reason"),
                row,
            ))
        finally:
            close()
    except Exception:
        return None


# Cast explicitly rather than trust the driver: SQLite returns an int (0/1)
# for an INTEGER column, psycopg2 returns a real bool for a BOOLEAN column --
# without this, a caller's `if row["promoted"] is False` would silently
# behave differently per backend, exactly the class of cross-backend
# surprise this codebase has hit before (TEXT-vs-DATE, Decimal-vs-float).
def _as_bool(value) -> bool:
    return bool(value)


def latest_publication_attempt() -> dict | None:
    """The single most recent current_publication row regardless of whether
    it was promoted -- used to show "the last attempt withheld state and
    why" alongside latest_promoted_publication()'s "what's actually served."
    Read-only, never raises."""
    try:
        fetch_one, close = _open()
        try:
            row = fetch_one(
                """
                SELECT run_id, promoted_at, code_version, source_as_of,
                       freshness_status, completeness_status, promoted, withheld_reason
                FROM current_publication
                ORDER BY promoted_at DESC, id DESC
                LIMIT 1
                """,
                (),
            )
            if not row:
                return None
            result = dict(zip(
                ("run_id", "promoted_at", "code_version", "source_as_of",
                 "freshness_status", "completeness_status", "promoted", "withheld_reason"),
                row,
            ))
            result["promoted"] = _as_bool(result["promoted"])
            return result
        finally:
            close()
    except Exception:
        return None


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

        # -- TR-14.1b: per-date scrape completeness vs the source's own count --
        # scrape_coverage (TR-14.1a) records COMPLETE / PARTIAL / UNKNOWN per
        # scraped date, from ksestocks' own per-sector traded-company totals.
        # A PARTIAL reference session means the scrape was truncated -> block
        # (stale -> red -> STALE -> both TR-05 gates withhold). UNKNOWN (the
        # source's count row was absent/garbled) and a missing scrape_coverage
        # row (the date predates TR-14.1a, or nothing has recorded on this
        # backend yet) are non-blocking, per the TR-14 scoping decision
        # ("PARTIAL blocks; UNKNOWN alerts, does not block").
        if reference:
            try:
                cov_row = fetch_one(
                    "SELECT coverage_status, detail FROM scrape_coverage "
                    "WHERE scrape_date = {p}",
                    (reference,),
                )
            except Exception as exc:
                # Table absent = feature not deployed / no row yet on this
                # backend -> say nothing, do not block. Any other read error
                # is a genuine fault and degrades to amber like the checks above.
                if not _is_missing_table(exc):
                    items.append(Item("scrape_coverage", "unknown",
                                      f"coverage table unreadable: {exc}"))
                cov_row = None
            if cov_row:
                cov_status, cov_detail = cov_row[0], cov_row[1]
                if cov_status == "PARTIAL":
                    items.append(Item(
                        "scrape_coverage", "stale",
                        f"{reference} scraped partially"
                        + (f" -- {cov_detail}" if cov_detail else "")))
                elif cov_status == "COMPLETE":
                    items.append(Item("scrape_coverage", "ok",
                                      f"{reference} complete vs source count"))
                else:  # UNKNOWN, or any unexpected value -- visible, non-blocking
                    items.append(Item("scrape_coverage", "ok",
                                      f"{reference} source count unavailable"))
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


def latest_pipeline_code_version() -> str | None:
    """The code_version stamped by the most recently-finished successful
    pipeline_runs row on the active backend, or None.

    Returns None -- never raises, never guesses -- when: the ledger has no
    such row yet, the code_version column predates this feature (a
    pre-migration DB or the CI fixture), or the query fails for any reason.

    Used by the Data Health page (via serving_revision.describe_drift) to
    compare the code this dashboard process is serving against the code the
    pipeline that produced the current data actually ran -- a mismatch on
    Streamlit Cloud means a reboot is needed (KIRAN_CLEANUP_AUDIT.md 88,
    Trust Register OI-9 / TR-11). Read-only.
    """
    try:
        fetch_one, close = _open()
    except Exception:
        return None
    try:
        row = fetch_one(
            "SELECT code_version FROM pipeline_runs "
            "WHERE code_version IS NOT NULL AND status = {p} "
            "ORDER BY finished_at DESC LIMIT 1",
            ("ok",),
        )
        return row[0] if row and row[0] else None
    except Exception:
        return None
    finally:
        try:
            close()
        except Exception:
            pass
