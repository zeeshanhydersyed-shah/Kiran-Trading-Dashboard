"""
One-shot script: add regime_at_entry, days_since_last_transition,
days_to_nearest_transition columns to trade_setups and backfill all rows.

Run once locally against psx_data.db. Safe to re-run (idempotent via
column-existence check). Prints a report of every NULL row (outside
market_regime coverage) and a verification summary at the end.
"""

import os
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "psx_data.db")

_PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")


def _transitions_from_regime_rows(rows):
    """Shared computation: given [(date, regime), ...] ordered ASC, return
    (trading_days, day_to_idx, sorted transition_idxs). DB-agnostic — used by
    both the SQLite and PG paths so the transition logic can never drift
    between them."""
    trading_days = [r[0] for r in rows]
    regimes = [r[1] for r in rows]
    day_to_idx = {d: i for i, d in enumerate(trading_days)}

    # Transition = day where regime differs from the prior trading day
    transition_idxs = set()
    for i in range(1, len(rows)):
        if regimes[i] != regimes[i - 1]:
            transition_idxs.add(i)

    return trading_days, day_to_idx, sorted(transition_idxs)


def get_trading_days_and_transitions(conn):
    """Return sorted list of all trading days and indices of transition days."""
    rows = conn.execute(
        "SELECT date, regime FROM market_regime ORDER BY date"
    ).fetchall()
    return _transitions_from_regime_rows(rows)


def compute_regime_columns(entry_date, day_to_idx, transition_idxs, regime_lookup):
    """
    Returns (regime_at_entry, days_since_last_transition, days_to_nearest_transition)
    or (None, None, None) if entry_date not in market_regime.

    days_since_last_transition: trading days back to last transition BEFORE or
        ON entry_date (causal — knowable in real time at entry).
    days_to_nearest_transition: trading days to nearest transition in either
        direction (retrospective — requires future data, never use in live rules).
    """
    if entry_date not in day_to_idx:
        return None, None, None

    idx = day_to_idx[entry_date]
    regime_at_entry = regime_lookup[entry_date]

    # days_since_last_transition: look only backward
    past = [t for t in transition_idxs if t <= idx]
    if past:
        days_since = idx - past[-1]
    else:
        # No prior transition in the data — set to distance from start of series
        days_since = idx

    # days_to_nearest_transition: look both directions
    if transition_idxs:
        nearest = min(transition_idxs, key=lambda t: abs(t - idx))
        days_nearest = abs(nearest - idx)
    else:
        days_nearest = None

    return regime_at_entry, days_since, days_nearest


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # --- Step 1: Add columns if they don't exist ---
    existing = {r[1] for r in cur.execute("PRAGMA table_info(trade_setups)").fetchall()}
    added = []
    for col, typedef in [
        ("regime_at_entry", "TEXT"),
        ("days_since_last_transition", "INTEGER"),
        ("days_to_nearest_transition", "INTEGER"),
    ]:
        if col not in existing:
            cur.execute(f"ALTER TABLE trade_setups ADD COLUMN {col} {typedef}")
            added.append(col)
    conn.commit()
    if added:
        print(f"Added columns: {added}")
    else:
        print("All 3 columns already exist — backfilling values only.")

    # --- Step 2: Build lookup structures from market_regime ---
    trading_days, day_to_idx, transition_idxs = get_trading_days_and_transitions(conn)
    regime_lookup = dict(
        conn.execute("SELECT date, regime FROM market_regime").fetchall()
    )
    print(f"market_regime: {len(trading_days)} trading days, "
          f"{len(transition_idxs)} transitions identified.")

    # --- Step 3: Fetch all trade_setups rows ---
    setups = cur.execute(
        "SELECT id, created_date FROM trade_setups"
    ).fetchall()
    print(f"trade_setups: {len(setups)} rows to process.")

    # --- Step 4: Compute and update ---
    null_rows = []
    updates = []
    for row in setups:
        sid, created_date = row["id"], row["created_date"]
        regime, days_since, days_nearest = compute_regime_columns(
            created_date, day_to_idx, transition_idxs, regime_lookup
        )
        if regime is None:
            null_rows.append((sid, created_date))
        updates.append((regime, days_since, days_nearest, sid))

    cur.executemany(
        """
        UPDATE trade_setups
        SET regime_at_entry             = ?,
            days_since_last_transition  = ?,
            days_to_nearest_transition  = ?
        WHERE id = ?
        """,
        updates,
    )
    conn.commit()

    # --- Step 5: Report NULLs ---
    print(f"\nRows left NULL (created_date not in market_regime): {len(null_rows)}")
    for sid, d in null_rows:
        print(f"  id={sid}, created_date={d}")

    # --- Step 6: Verification spot-check ---
    print("\n--- Verification spot-check (5 sample rows) ---")
    samples = cur.execute("""
        SELECT id, created_date, regime_at_entry,
               days_since_last_transition, days_to_nearest_transition
        FROM trade_setups
        WHERE regime_at_entry IS NOT NULL
        ORDER BY created_date DESC
        LIMIT 5
    """).fetchall()
    for r in samples:
        print(dict(r))

    # --- Step 7: Summary ---
    counts = cur.execute("""
        SELECT regime_at_entry, COUNT(*) as n
        FROM trade_setups
        GROUP BY regime_at_entry
        ORDER BY n DESC
    """).fetchall()
    print("\n--- regime_at_entry distribution across all 577 rows ---")
    for r in counts:
        print(f"  {r[0]}: {r[1]}")

    conn.close()
    print("\nDone.")


def _backfill_days_to_nearest_sqlite(db_path: str = DB_PATH) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    trading_days, day_to_idx, transition_idxs = get_trading_days_and_transitions(conn)

    # Only process rows where days_to_nearest_transition is still NULL but
    # regime_at_entry is already populated (i.e. the date exists in market_regime)
    pending = cur.execute(
        """
        SELECT id, created_date FROM trade_setups
        WHERE days_to_nearest_transition IS NULL
          AND regime_at_entry IS NOT NULL
        """
    ).fetchall()

    updates = []
    for row in pending:
        sid, created_date = row["id"], row["created_date"]
        if created_date not in day_to_idx:
            continue
        idx = day_to_idx[created_date]
        if transition_idxs:
            nearest = min(transition_idxs, key=lambda t: abs(t - idx))
            days_nearest = abs(nearest - idx)
            updates.append((days_nearest, sid))

    if updates:
        cur.executemany(
            "UPDATE trade_setups SET days_to_nearest_transition = ? WHERE id = ?",
            updates,
        )
        conn.commit()

    conn.close()
    return len(updates)


def _backfill_days_to_nearest_pg() -> int:
    from database_pg import (
        get_market_regime_series_pg,
        get_pending_days_to_nearest_pg,
        update_days_to_nearest_batch_pg,
    )

    regime_rows = get_market_regime_series_pg()
    trading_days, day_to_idx, transition_idxs = _transitions_from_regime_rows(regime_rows)

    pending = get_pending_days_to_nearest_pg()

    updates = []
    for sid, created_date in pending:
        if created_date not in day_to_idx:
            continue
        idx = day_to_idx[created_date]
        if transition_idxs:
            nearest = min(transition_idxs, key=lambda t: abs(t - idx))
            days_nearest = abs(nearest - idx)
            updates.append((days_nearest, sid))

    return update_days_to_nearest_batch_pg(updates)


def backfill_days_to_nearest(db_path: str = DB_PATH) -> int:
    """
    Daily hook called from main.py after append_latest_regime().

    Fills days_to_nearest_transition for any trade_setups row where it is
    currently NULL and the nearest transition (in either direction) is now
    determinable from market_regime.

    Returns the number of rows updated.

    NOTE: days_to_nearest_transition is RETROSPECTIVE-ONLY. It requires knowledge
    of future regime transitions and must NEVER be used in live trading filters.
    Rows created very recently (within ~10 trading days) may remain NULL until
    the nearest future transition has occurred and been recorded in market_regime.
    """
    if _PG_URL:
        return _backfill_days_to_nearest_pg()
    return _backfill_days_to_nearest_sqlite(db_path)


if __name__ == "__main__":
    main()
