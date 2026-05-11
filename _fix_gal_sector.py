"""
One-off: move GAL from its current sector to AUTOMOBILE ASSEMBLERS.
Works against whichever backend is active (SQLite locally, PostgreSQL if DATABASE_URL is set).
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

TARGET_SECTOR = "AUTOMOBILE ASSEMBLERS"

use_pg = bool(os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL"))

if use_pg:
    print("Backend: PostgreSQL (Supabase)")
    from database_pg import get_conn, _fetchone
    def fetch_one(conn, sql, params=()):
        return _fetchone(conn, sql, params)
    def execute(conn, sql, params=()):
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount
    PLACEHOLDER = "%s"
else:
    print("Backend: SQLite (local)")
    import sqlite3
    from config import DB_PATH
    import contextlib

    @contextlib.contextmanager
    def get_conn():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetch_one(conn, sql, params=()):
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def execute(conn, sql, params=()):
        cur = conn.execute(sql, params)
        return cur.rowcount

    PLACEHOLDER = "?"

with get_conn() as conn:
    row = fetch_one(conn, f"SELECT symbol, sector FROM sectors WHERE symbol = {PLACEHOLDER}", ("GAL",))
    if row is None:
        print("GAL not found in sectors table.")
        sys.exit(1)

    old_sector = row["sector"]
    print(f"Current sector for GAL : {old_sector!r}")

    if old_sector == TARGET_SECTOR:
        print("Already correct — nothing to do.")
        sys.exit(0)

    n = execute(conn, f"UPDATE sectors SET sector = {PLACEHOLDER} WHERE symbol = {PLACEHOLDER}", (TARGET_SECTOR, "GAL"))
    print(f"sectors update         : {n} row(s) affected")

    # Also fix any trade_setups rows that still carry the old sector label
    n2 = execute(
        conn,
        f"UPDATE trade_setups SET sector = {PLACEHOLDER} WHERE symbol = {PLACEHOLDER} AND sector = {PLACEHOLDER}",
        (TARGET_SECTOR, "GAL", old_sector),
    )
    print(f"trade_setups update    : {n2} row(s) affected")

print(f"\nDone — GAL is now in {TARGET_SECTOR!r}")
