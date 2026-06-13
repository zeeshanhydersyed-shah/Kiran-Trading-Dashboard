"""
Auto Price Adjuster — PSX Corporate Actions
============================================
Reads corporate_action_suspects_clean.csv, auto-confirms bonus share events
(DROP_50 / DROP_33 / DROP_25 — unambiguous magnitude signatures), computes
the backward adjustment factor from the observed close_before/close_after
ratio, and applies it to all OHLCV rows for that symbol BEFORE the event date.

DROP_OTHER events are NOT auto-applied — they require manual confirmation
(set review_status = CONFIRMED in the CSV first, then re-run with --all).

Writes adjusted prices to a NEW TABLE: prices_adjusted
  — raw prices table is NEVER touched.

Usage:
    python apply_price_adjustments.py           # bonus events only
    python apply_price_adjustments.py --all     # bonus + any CONFIRMED rows

After running, your queries should use prices_adjusted instead of prices.
"""

import sqlite3
import csv
import os
import sys
import argparse
from collections import defaultdict
from datetime import datetime

BASE    = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE, "psx_data.db")
CSV_PATH = os.path.join(BASE, "corporate_action_suspects_clean.csv")

AUTO_CONFIRM_CATS = {"DROP_50", "DROP_33", "DROP_25"}


def load_events(apply_all: bool) -> list[dict]:
    """Load events to apply from the review CSV."""
    events = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cat    = row["magnitude_category"]
            status = row["review_status"].strip().upper()

            if cat in AUTO_CONFIRM_CATS:
                events.append(row)
            elif apply_all and status == "CONFIRMED":
                events.append(row)

    events.sort(key=lambda r: (r["symbol"], r["date"]))
    return events


def build_adjusted_prices(con, events: list[dict]) -> None:
    cur = con.cursor()

    # ── create prices_adjusted as a copy of prices ───────────────────────────
    print("Creating prices_adjusted table …")
    cur.execute("DROP TABLE IF EXISTS prices_adjusted")
    cur.execute("""
        CREATE TABLE prices_adjusted AS
        SELECT * FROM prices
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pa_sym_date ON prices_adjusted(symbol, date)")
    con.commit()
    print(f"  Copied {cur.execute('SELECT COUNT(*) FROM prices_adjusted').fetchone()[0]:,} rows")

    # ── group events by symbol, sorted chronologically ───────────────────────
    by_symbol = defaultdict(list)
    for ev in events:
        by_symbol[ev["symbol"]].append(ev)

    total_rows_updated = 0
    skipped = 0

    for sym, sym_events in by_symbol.items():
        # Sort events oldest→newest — apply adjustments in reverse chronological
        # order so earlier adjustments compound correctly
        sym_events_sorted = sorted(sym_events, key=lambda r: r["date"])

        for ev in sym_events_sorted:
            ex_date     = ev["date"]
            close_before = float(ev["close_before"])
            close_after  = float(ev["close_after"])

            if close_before == 0:
                skipped += 1
                continue

            # Backward adjustment factor: multiply all pre-event prices by this
            adj = close_after / close_before

            cur.execute("""
                UPDATE prices_adjusted
                SET open  = ROUND(open  * ?, 4),
                    high  = ROUND(high  * ?, 4),
                    low   = ROUND(low   * ?, 4),
                    close = ROUND(close * ?, 4)
                WHERE symbol = ? AND date < ?
            """, (adj, adj, adj, adj, sym, ex_date))

            rows_hit = cur.rowcount
            total_rows_updated += rows_hit

            action = ev.get("confirmed_action") or ev.get("likely_action", "")
            print(f"  {sym:10s}  {ex_date}  adj={adj:.4f}  ({close_before:.2f}→{close_after:.2f})  "
                  f"rows={rows_hit:>5}  [{action}]")

        con.commit()

    return total_rows_updated, skipped


def verify(con, events: list[dict]) -> None:
    """Sanity check: close on ex_date in prices_adjusted should equal close_after."""
    cur = con.cursor()
    print("\n── Verification sample (first 10 events) ──")
    for ev in events[:10]:
        row = cur.execute(
            "SELECT close FROM prices_adjusted WHERE symbol=? AND date=?",
            (ev["symbol"], ev["date"])
        ).fetchone()
        adj_close = row[0] if row else "N/A"
        expected  = float(ev["close_after"])
        ok = "✓" if row and abs(adj_close - expected) < 0.01 else "✗"
        print(f"  {ok}  {ev['symbol']:10s}  {ev['date']}  "
              f"expected={expected:.2f}  got={adj_close}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true",
                        help="Also apply DROP_OTHER rows marked CONFIRMED in CSV")
    args = parser.parse_args()

    print("=" * 60)
    print("PSX Price Adjuster")
    print(f"Mode: {'bonus + CONFIRMED' if args.all else 'bonus events only (DROP_50/33/25)'}")
    print("=" * 60)

    events = load_events(apply_all=args.all)
    print(f"\nEvents to apply: {len(events)}")

    from collections import Counter
    for cat, cnt in Counter(e["magnitude_category"] for e in events).items():
        print(f"  {cat:<15} {cnt:>4}")

    if not events:
        print("Nothing to apply. Exiting.")
        return

    con = sqlite3.connect(DB_PATH)

    t0 = datetime.now()
    total_updated, skipped = build_adjusted_prices(con, events)
    elapsed = (datetime.now() - t0).total_seconds()

    verify(con, events)
    con.close()

    print(f"\n{'='*60}")
    print(f"Done in {elapsed:.1f}s")
    print(f"Total price rows adjusted: {total_updated:,}")
    print(f"Events skipped (zero close_before): {skipped}")
    print(f"\nUse prices_adjusted table in your queries going forward.")
    print("prices table is untouched.")
    print("=" * 60)


if __name__ == "__main__":
    main()
