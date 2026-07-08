"""
E9 — production health check.

Run as its own GitHub Actions step, after main.py --update, not folded into
cmd_update(). A separate step name ("Health Check") makes it obvious in the
Actions log which stage failed, and this script must still run and report
clearly even if something upstream silently no-op'd.

Confirms:
  1. A live Postgres connection actually succeeds (closes the run #46
     silent-fallback-to-ephemeral-SQLite hole -- database.py's backend
     selection is a bare `if _PG_URL:` truthiness check with no connection
     test of its own; this check performs that missing test).
  2. prices -> prices_adjusted/market_regime -> stock_signals/sector_signals
     haven't silently frozen relative to each other (the prices_adjusted
     freeze pattern diagnosed in E8.5).
  3. prices itself hasn't stopped updating entirely.
  4. market_flows is fresh, T+2-lag-adjusted (khistocks.com publishes flows
     two calendar days behind price data -- confirmed this week).
  5. The E8.6a rolling 2-year trim job is still actually firing.

Exit code: 0 if every check passes, 1 if any fails. Alerting is GitHub-native
only (red Actions badge + GitHub's built-in email-on-failure to repo
watchers) -- no Slack/Discord/webhook, no auto-created Issues.

NOT checked here, deliberately (see design discussion, E9):
  - sector_signals.flow_direction being NULL for most sectors on any given
    date is CORRECT (khistocks.com only reports high-institutional-activity
    sectors; typically only 5-9 of 23 sectors have it) -- not a per-sector
    coverage check.
  - stock_signals.stage2_bull / close_above_ema150 / ema150_slope_pos being
    NULL on freshly-appended daily rows is CORRECT (need 199/149-day
    lookback windows only available on a full rebuild) -- not a per-column
    NULL-rate check.
"""

import os
import sys

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str) -> bool:
    RESULTS.append((name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"{name:<34} {status:<5} {detail}")
    return passed


def check_connection() -> bool:
    """Check 1 -- connection-is-real. Fail-fast: nothing else can run without this."""
    url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
    if not url:
        return record(
            "[1/5] Connection-is-real", False,
            "DATABASE_URL and SUPABASE_DB_URL are both unset/empty -- pipeline "
            "would silently fall back to ephemeral local SQLite (the run #46 bug)."
        )

    try:
        from database_pg import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            row = cur.fetchone()
    except Exception as exc:
        return record("[1/5] Connection-is-real", False, f"Connection or query failed: {exc!r}")

    if not row or row[0] != 1:
        return record("[1/5] Connection-is-real", False, f"SELECT 1 returned unexpected result: {row!r}")

    return record("[1/5] Connection-is-real", True, "SELECT 1 succeeded via live Postgres connection.")


def _max_dates(conn, tables: list[tuple[str, str]]) -> dict:
    cur = conn.cursor()
    out = {}
    for table, col in tables:
        cur.execute(f"SELECT MAX({col}) FROM {table}")
        out[table] = cur.fetchone()[0]
    return out


def _min_dates(conn, tables: list[tuple[str, str]]) -> dict:
    cur = conn.cursor()
    out = {}
    for table, col in tables:
        cur.execute(f"SELECT MIN({col}) FROM {table}")
        out[table] = cur.fetchone()[0]
    return out


def check_relative_staleness(conn) -> bool:
    """Check 2 -- relative staleness / frozen-table chain (E8.5 pattern)."""
    tables = [
        ("prices", "date"), ("prices_adjusted", "date"),
        ("stock_signals", "date"), ("sector_signals", "date"),
        ("market_regime", "date"),
    ]
    dates = _max_dates(conn, tables)
    detail = ", ".join(f"{t}={d}" for t, d in dates.items())

    missing = [t for t, d in dates.items() if d is None]
    if missing:
        return record("[2/5] Relative staleness chain", False, f"No data at all in: {missing} | {detail}")

    problems = []
    for newer, older, label in [
        ("prices", "prices_adjusted", "prices_adjusted"),
        ("prices", "market_regime", "market_regime"),
        ("prices_adjusted", "stock_signals", "stock_signals"),
        ("prices_adjusted", "sector_signals", "sector_signals"),
    ]:
        lag = (dates[newer] - dates[older]).days
        if lag > 1:
            problems.append(f"{label} is {lag}d behind {newer}")

    if problems:
        return record("[2/5] Relative staleness chain", False, f"{'; '.join(problems)} | {detail}")
    return record("[2/5] Relative staleness chain", True, f"All within 1 day | {detail}")


def check_absolute_freshness(conn) -> bool:
    """Check 3 -- absolute freshness floor (4 calendar days: weekend + 1 buffer)."""
    cur = conn.cursor()
    cur.execute("SELECT MAX(date), CURRENT_DATE FROM prices")
    max_date, today = cur.fetchone()
    if max_date is None:
        return record("[3/5] Absolute freshness floor", False, "prices table is empty.")

    age = (today - max_date).days
    return record(
        "[3/5] Absolute freshness floor", age <= 4,
        f"prices MAX(date)={max_date}, {age}d old, threshold 4",
    )


def check_flows_freshness(conn) -> bool:
    """Check 4 -- flows freshness, T+2-adjusted (4-day base buffer + 2-day known lag)."""
    cur = conn.cursor()
    cur.execute("SELECT MAX(date), CURRENT_DATE FROM market_flows")
    max_date, today = cur.fetchone()
    if max_date is None:
        return record("[4/5] Flows freshness (T+2)", False, "market_flows table is empty.")

    age = (today - max_date).days
    return record(
        "[4/5] Flows freshness (T+2)", age <= 6,
        f"market_flows MAX(date)={max_date}, {age}d old, threshold 6",
    )


def check_rolling_trim(conn) -> bool:
    """Check 5 -- rolling trim sanity (E8.6a regression guard). Same 5 tables as _TRIM_TABLES."""
    tables = [
        ("prices", "date"), ("prices_adjusted", "date"),
        ("stock_signals", "date"), ("setup_log", "setup_date"),
        ("symbol_active_dates", "date"),
    ]
    cur = conn.cursor()
    cur.execute("SELECT CURRENT_DATE - INTERVAL '2 years' - INTERVAL '7 days'")
    cutoff = cur.fetchone()[0]
    if hasattr(cutoff, "date"):
        cutoff = cutoff.date()

    mins = _min_dates(conn, tables)
    detail = ", ".join(f"{t}={d}" for t, d in mins.items())
    problems = [f"{t}={d}" for t, d in mins.items() if d is not None and d < cutoff]

    if problems:
        return record("[5/5] Rolling trim sanity", False, f"older than cutoff {cutoff}: {problems} | {detail}")
    return record("[5/5] Rolling trim sanity", True, f"cutoff={cutoff} | {detail}")


def print_summary() -> bool:
    print("=" * 60)
    all_passed = all(passed for _, passed, _ in RESULTS)
    if all_passed:
        print("HEALTH CHECK: ALL PASS")
    else:
        failed = [name for name, passed, _ in RESULTS if not passed]
        print(f"HEALTH CHECK: FAILED -- {', '.join(failed)}")
    return all_passed


def main() -> None:
    if not check_connection():
        print_summary()
        sys.exit(1)

    from database_pg import get_conn
    with get_conn() as conn:
        check_relative_staleness(conn)
        check_absolute_freshness(conn)
        check_flows_freshness(conn)
        check_rolling_trim(conn)

    all_passed = print_summary()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
