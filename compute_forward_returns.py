"""
Compute fwd_return_5d, fwd_return_10d, fwd_return_20d, outcome_tagged_date
for setup_log rows where the 20-trading-day forward window has fully closed.
outcome_label is NOT populated here.
"""

import os
import sqlite3
import sys
from config import DB_PATH

DRY_RUN_SYMBOLS = None  # set to a list to limit processing

_PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")


def load_price_sequence(cur, symbol):
    """Return list of (date, close) tuples ordered by date ascending."""
    cur.execute(
        "SELECT date, close FROM prices_adjusted WHERE symbol = ? ORDER BY date ASC",
        (symbol,),
    )
    return cur.fetchall()


def compute_returns(rows, symbol, price_seq, dry_run_sample):
    """
    For each setup_log row, find forward closes at +5, +10, +20 trading days.
    Returns (updates, skipped) where updates is a list of param tuples.
    """
    # Build index: date_str -> (index, close)
    date_index = {row[0]: (i, row[1]) for i, row in enumerate(price_seq)}

    updates = []
    skipped = 0

    for setup_date, setup_type in rows:
        if setup_date not in date_index:
            skipped += 1
            continue

        idx, close_0 = date_index[setup_date]

        # Check all three forward dates exist
        if idx + 20 >= len(price_seq):
            skipped += 1
            continue

        close_5 = price_seq[idx + 5][1]
        close_10 = price_seq[idx + 10][1]
        close_20 = price_seq[idx + 20][1]
        date_10 = price_seq[idx + 10][0]

        if close_0 == 0:
            skipped += 1
            continue

        fwd5 = (close_5 - close_0) / close_0 * 100
        fwd10 = (close_10 - close_0) / close_0 * 100
        fwd20 = (close_20 - close_0) / close_0 * 100

        updates.append((fwd5, fwd10, fwd20, date_10, symbol, setup_date, setup_type))

        if dry_run_sample is not None and len(dry_run_sample) < 5:
            dry_run_sample.append(
                (symbol, setup_date, setup_type, fwd5, fwd10, fwd20, date_10)
            )

    return updates, skipped


def _main_pg(dry_run_symbols=None):
    """PG-backed equivalent of main(). Same logic, %s placeholders,
    psycopg2.extras.execute_batch instead of executemany."""
    import psycopg2.extras
    from database_pg import get_conn

    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if dry_run_symbols:
            symbols = dry_run_symbols
        else:
            cur.execute("SELECT DISTINCT symbol FROM setup_log ORDER BY symbol ASC")
            symbols = [r["symbol"] for r in cur.fetchall()]

        total_updated = 0
        total_skipped = 0
        batch = []
        dry_run_sample = [] if dry_run_symbols else None

        for sym_idx, symbol in enumerate(symbols):
            cur.execute(
                "SELECT date, close FROM prices_adjusted WHERE symbol = %s ORDER BY date ASC",
                (symbol,),
            )
            price_seq = [(r["date"], r["close"]) for r in cur.fetchall()]
            if not price_seq:
                continue

            cur.execute(
                "SELECT setup_date, setup_type FROM setup_log "
                "WHERE symbol = %s AND fwd_return_20d IS NULL",
                (symbol,),
            )
            rows = [(r["setup_date"], r["setup_type"]) for r in cur.fetchall()]
            if not rows:
                continue

            updates, skipped = compute_returns(rows, symbol, price_seq, dry_run_sample)
            total_skipped += skipped
            batch.extend(updates)

            if dry_run_symbols:
                print(f"  {symbol}: {len(updates)} updated, {skipped} skipped")

            if len(batch) >= 1000:
                psycopg2.extras.execute_batch(cur, """
                    UPDATE setup_log
                    SET fwd_return_5d = %s, fwd_return_10d = %s, fwd_return_20d = %s,
                        outcome_tagged_date = %s
                    WHERE symbol = %s AND setup_date = %s AND setup_type = %s
                """, batch)
                total_updated += len(batch)
                batch = []

            if not dry_run_symbols and (sym_idx + 1) % 50 == 0:
                print(f"  Progress: {sym_idx + 1}/{len(symbols)} symbols processed")

        if batch:
            psycopg2.extras.execute_batch(cur, """
                UPDATE setup_log
                SET fwd_return_5d = %s, fwd_return_10d = %s, fwd_return_20d = %s,
                    outcome_tagged_date = %s
                WHERE symbol = %s AND setup_date = %s AND setup_type = %s
            """, batch)
            total_updated += len(batch)

    print(f"\nSummary:")
    print(f"  Rows updated : {total_updated}")
    print(f"  Rows skipped : {total_skipped} (window not yet closed)")

    if dry_run_sample:
        print(f"\nSample of updated rows:")
        print(
            f"  {'symbol':<12} {'setup_date':<12} {'setup_type':<20} "
            f"{'fwd5':>8} {'fwd10':>8} {'fwd20':>8} {'tag_date':<12}"
        )
        for r in dry_run_sample:
            print(
                f"  {r[0]:<12} {r[1]:<12} {r[2]:<20} "
                f"{r[3]:>8.2f} {r[4]:>8.2f} {r[5]:>8.2f} {r[6]:<12}"
            )


def main(dry_run_symbols=None):
    if _PG_URL:
        _main_pg(dry_run_symbols=dry_run_symbols)
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Fetch all distinct symbols to process
    if dry_run_symbols:
        symbols = dry_run_symbols
    else:
        cur.execute(
            "SELECT DISTINCT symbol FROM setup_log ORDER BY symbol ASC"
        )
        symbols = [r[0] for r in cur.fetchall()]

    total_updated = 0
    total_skipped = 0
    batch = []
    dry_run_sample = [] if dry_run_symbols else None

    for sym_idx, symbol in enumerate(symbols):
        # Load this symbol's price sequence
        price_seq = load_price_sequence(cur, symbol)
        if not price_seq:
            continue

        # Load setup_log rows for this symbol that need updating
        cur.execute(
            """
            SELECT setup_date, setup_type
            FROM setup_log
            WHERE symbol = ?
              AND fwd_return_20d IS NULL
            """,
            (symbol,),
        )
        rows = cur.fetchall()

        if not rows:
            continue

        updates, skipped = compute_returns(rows, symbol, price_seq, dry_run_sample)
        total_skipped += skipped

        batch.extend(updates)

        if dry_run_symbols:
            sym_updated = len(updates)
            print(
                f"  {symbol}: {sym_updated} updated, {skipped} skipped"
            )

        # Commit in batches
        if len(batch) >= 1000:
            cur.executemany(
                """
                UPDATE setup_log
                SET fwd_return_5d = ?,
                    fwd_return_10d = ?,
                    fwd_return_20d = ?,
                    outcome_tagged_date = ?
                WHERE symbol = ?
                  AND setup_date = ?
                  AND setup_type = ?
                """,
                batch,
            )
            conn.commit()
            total_updated += len(batch)
            batch = []

        if not dry_run_symbols and (sym_idx + 1) % 50 == 0:
            print(f"  Progress: {sym_idx + 1}/{len(symbols)} symbols processed")

    # Flush remaining
    if batch:
        cur.executemany(
            """
            UPDATE setup_log
            SET fwd_return_5d = ?,
                fwd_return_10d = ?,
                fwd_return_20d = ?,
                outcome_tagged_date = ?
            WHERE symbol = ?
              AND setup_date = ?
              AND setup_type = ?
            """,
            batch,
        )
        conn.commit()
        total_updated += len(batch)

    conn.close()

    print(f"\nSummary:")
    print(f"  Rows updated : {total_updated}")
    print(f"  Rows skipped : {total_skipped} (window not yet closed)")

    if dry_run_sample:
        print(f"\nSample of updated rows:")
        print(
            f"  {'symbol':<12} {'setup_date':<12} {'setup_type':<20} "
            f"{'fwd5':>8} {'fwd10':>8} {'fwd20':>8} {'tag_date':<12}"
        )
        for r in dry_run_sample:
            print(
                f"  {r[0]:<12} {r[1]:<12} {r[2]:<20} "
                f"{r[3]:>8.2f} {r[4]:>8.2f} {r[5]:>8.2f} {r[6]:<12}"
            )


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        import sqlite3 as _sq
        _conn = _sq.connect(DB_PATH)
        _cur = _conn.cursor()
        _cur.execute(
            "SELECT DISTINCT symbol FROM setup_log ORDER BY symbol ASC LIMIT 5"
        )
        dry_syms = [r[0] for r in _cur.fetchall()]
        _conn.close()
        print(f"DRY RUN — processing first 5 symbols: {dry_syms}\n")
        main(dry_run_symbols=dry_syms)
    else:
        main()
