"""
research_db.py — opt-in Postgres connection helper for the ZH_research
one-off scripts (prebreakout_v2_phase4b/4c/5*/6, market_structure_diagnostic).

Each of those scripts is written entirely against pd.read_sql_query(sql,
con, params=(...)) with SQLite '?' placeholders — never raw con.execute()/
con.cursor(). That means the only two things a script needs to run against
Supabase instead of local psx_data.db are: (1) a connection object, and
(2) '?' placeholders translated to psycopg2's '%s' before executing.
get_connection() + read_sql() provide exactly that, so each script's own
SQL strings stay completely unchanged.

Env-var driven (DATABASE_URL / SUPABASE_DB_URL) — unset means local SQLite,
zero behavior change from today. These remain manual, run-when-needed
diagnostic tools; this does not turn them into scheduled/automated jobs.
"""

import os
import sqlite3

import pandas as pd

_PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")


def is_postgres() -> bool:
    return bool(_PG_URL)


def get_connection(sqlite_path=None):
    """Returns a live connection — psycopg2 if DATABASE_URL/SUPABASE_DB_URL
    is set, otherwise sqlite3.connect(sqlite_path) unchanged from today."""
    if _PG_URL:
        from database_pg import _connect
        return _connect()
    return sqlite3.connect(sqlite_path)


def read_sql(sql, conn, params=None):
    """pd.read_sql_query wrapper that translates '?' placeholders to '%s'
    when conn is a Postgres connection, so each script's SQL strings (all
    written with '?') don't need to be touched. params may be a tuple/list
    (positional, same order as '?' occurrences) — passed straight through
    to pandas either way, since psycopg2 also accepts a sequence for '%s'
    placeholders in that same left-to-right order.

    Also normalizes any 'date'-named column to a plain ISO string on the
    Postgres path: these tables' date columns are native Postgres DATE type
    (vs SQLite's plain TEXT), so pandas would otherwise return
    datetime.date objects here — breaking every one of these scripts'
    string-based date comparisons/filters downstream (e.g.
    df['date'] <= '2019-12-31'), which all assume the SQLite string
    convention. Same normalization already applied in stealth_rs.py's
    Postgres path, for the same reason."""
    if is_postgres():
        sql = sql.replace("?", "%s")
    df = pd.read_sql_query(sql, conn, params=params)
    if is_postgres() and "date" in df.columns:
        df["date"] = df["date"].astype(str)
    return df
