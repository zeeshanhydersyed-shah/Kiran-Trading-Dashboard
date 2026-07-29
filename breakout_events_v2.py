"""
breakout_events_v2.py — Forward-tracked, stateful BREAKOUT event detector.

Implements BREAKOUT_Specification_v1.0 (Sections 1-2) as a Phase 4 prototype:
event-based breakout detection, replacing the stateless per-row lookback
polarity variable (bos_flag) audited in Phase 3.

Does NOT modify stock_signals.py's update_pivot_signals() / _build_pivot_lookup().
Does NOT write to setup_log, stock_signals, or any certified table.
Writes only to a new staging table: stock_signals_breakout_v2_staging.

Pivot confirmation logic (21-bar centered window, strict HIGH comparison,
10 bars left/right) is unchanged from the existing implementation — reused
verbatim, per Phase 4 instructions.

OPEN DESIGN QUESTION (not resolved here — see module docstring at bottom
and the accompanying report): when a new pivot confirms while a prior
active_resistance is still unbroken, should the new pivot replace it only
if HIGHER (magnitude-aware — Interpretation A, implemented below), or
always replace it regardless of magnitude (recency-only — Interpretation B,
matching the OLD code's behavior and one literal reading of spec 1.2)?
This module implements Interpretation A, per the Phase 4 pseudocode. See
the design-question section of the audit report for the alternative and
tradeoffs.
"""

import sqlite3
from pathlib import Path

DB = str(Path(__file__).parent / "psx_data.db")
STAGING_TABLE = "stock_signals_breakout_v2_staging_full"


def _confirm_pivots(prices):
    """Identical 21-bar centered pivot-confirmation logic to the existing
    update_pivot_signals()/_build_pivot_lookup() (left=10, right=10, strict
    HIGH comparison, no ties). Unchanged from current implementation.

    prices: list of (date, close, high) sorted by date ASC.
    Returns: dict {bar_index_i: high_value} for every confirmed pivot,
             plus a dict {confirmation_pos: bar_index_i} recording the
             day (pos) each pivot becomes KNOWN (10 bars after i), so the
             forward walk never uses information not yet available on
             that day (no look-ahead) — same convention as the existing code.
    """
    n = len(prices)
    confirmed_at_pos = {}  # pos (= i+10, the day it becomes known) -> (i, high)
    for pos in range(n):
        i = pos - 10
        if i >= 10:
            hi = prices[i][2]
            if hi is not None:
                left_ok = all(
                    prices[j][2] is not None and prices[j][2] < hi
                    for j in range(i - 10, i)
                )
                right_ok = all(
                    prices[j][2] is not None and prices[j][2] < hi
                    for j in range(i + 1, i + 11)
                )
                if left_ok and right_ok:
                    confirmed_at_pos[pos] = (i, hi)
    return confirmed_at_pos


def compute_breakout_events(prices):
    """Forward-tracked, stateful event detector per BREAKOUT_Specification_v1.0.

    prices: list of (date, close, high) sorted by date ASC, for ONE symbol.

    Returns: list of dicts, one per day, with keys:
        date, close, active_resistance, breakout_event (0/1), already_broken (bool, post-day state)

    State maintained across the walk (per spec 1.1/1.2/1.5, Section 3 rule 9):
        active_resistance : current pivot high level, or None. NO decay/expiry —
                             persists indefinitely until superseded or broken/reset.
        already_broken    : whether an event has already fired since this level
                             became active, or since the last fallback-below reset.

    Event test (spec 2.1): breakout_event = 1 ONLY on the first day close
    closes strictly above active_resistance since it became active or was
    last reset by a fallback-below (spec 1.5). It is never 1 merely because
    "close is still above" on a subsequent day (that would be the old
    stateless-polarity bug audited in Phase 3) — this is the direct fix
    for Section 3 rule 9 (no independent polarity/state field driving
    row generation).
    """
    confirmed_at_pos = _confirm_pivots(prices)

    active_resistance = None
    already_broken = False
    out = []

    for pos, (date, close, high) in enumerate(prices):
        # Step 1: has a new pivot just become known (confirmed) today?
        if pos in confirmed_at_pos:
            _, new_high = confirmed_at_pos[pos]
            # --- INTERPRETATION A (implemented): only supersede if HIGHER ---
            # A newly confirmed pivot that is LOWER than the still-unbroken
            # active_resistance is ignored — the higher level is still what
            # price has not yet cleared, so it remains the operative resistance.
            if active_resistance is None or new_high > active_resistance:
                active_resistance = new_high
                already_broken = False  # new level -> fresh eligibility

        # Step 2: event test for today, against whatever is active resistance now
        breakout_event = 0
        if active_resistance is not None and close is not None:
            if close > active_resistance:
                if not already_broken:
                    breakout_event = 1
                    already_broken = True
                else:
                    breakout_event = 0  # continuation -- correctly suppressed
            else:
                breakout_event = 0
                already_broken = False  # fallback below resets eligibility (spec 1.5)

        out.append({
            "date": date,
            "close": close,
            "active_resistance": active_resistance,
            "breakout_event": breakout_event,
        })

    return out


def ensure_staging_table(con):
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {STAGING_TABLE} (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL,
            active_resistance REAL,
            breakout_event INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)
    con.commit()


def run_for_symbols(symbols, db_path=DB):
    """Compute breakout events for a list of symbols and write to the
    staging table only. Does not touch setup_log or stock_signals."""
    con = sqlite3.connect(db_path)
    ensure_staging_table(con)
    cur = con.cursor()

    cur.execute(f"DELETE FROM {STAGING_TABLE} WHERE symbol IN "
                f"({','.join('?' for _ in symbols)})", symbols)

    total_rows = 0
    total_events = 0
    for symbol in symbols:
        rows = cur.execute(
            "SELECT date, close, high FROM prices_adjusted WHERE symbol = ? ORDER BY date",
            (symbol,)
        ).fetchall()
        if not rows:
            continue
        results = compute_breakout_events(rows)
        insert_rows = [
            (symbol, r["date"], r["close"], r["active_resistance"], r["breakout_event"])
            for r in results
        ]
        cur.executemany(
            f"INSERT OR REPLACE INTO {STAGING_TABLE} "
            f"(symbol, date, close, active_resistance, breakout_event) VALUES (?, ?, ?, ?, ?)",
            insert_rows
        )
        total_rows += len(insert_rows)
        total_events += sum(r["breakout_event"] for r in results)

    con.commit()
    con.close()
    return total_rows, total_events


if __name__ == "__main__":
    import sys
    syms = sys.argv[1:] if len(sys.argv) > 1 else []
    if not syms:
        print("Usage: python breakout_events_v2.py SYMBOL [SYMBOL ...]")
        sys.exit(1)
    rows, events = run_for_symbols(syms)
    print(f"Wrote {rows} rows, {events} breakout_event=1 rows, for {len(syms)} symbols "
          f"to table '{STAGING_TABLE}'.")
