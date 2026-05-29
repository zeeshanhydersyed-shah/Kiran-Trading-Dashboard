"""
One-time fix: find the Paper & Actual closed trade(s) that are causing
double-counting with the Excel import, and delete them.

Paper & Actual = source is System/STM/Support Reversal AND actual_entry is set.
These are screener setups the user also traded — but if the same trade is
already imported from Excel as source='Actual', it's a duplicate.

Run:
    python fix_paper_actual.py          # preview
    python fix_paper_actual.py --delete # actually delete
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_conn, init_db

def main():
    delete = "--delete" in sys.argv
    init_db()

    with get_conn() as conn:
        # Find all Paper & Actual closed trades
        paper_actual = conn.execute("""
            SELECT id, created_date, symbol, direction, source,
                   actual_entry, actual_exit, actual_pl_pct, actual_pl_pkr, outcome
            FROM trade_setups
            WHERE source IN ('System','STM','Support Reversal')
              AND actual_entry IS NOT NULL AND actual_entry > 0
              AND outcome IN ('Win','Loss','Breakeven')
            ORDER BY created_date
        """).fetchall()

        if not paper_actual:
            print("No Paper & Actual closed trades found.")
            return

        print(f"Found {len(paper_actual)} Paper & Actual closed trade(s):\n")
        ids_to_delete = []

        for row in paper_actual:
            # Check if there is an Actual trade with same symbol + same entry date
            duplicate = conn.execute("""
                SELECT id FROM trade_setups
                WHERE symbol = ? AND created_date = ? AND direction = ? AND source = 'Actual'
            """, (row["symbol"], row["created_date"], row["direction"])).fetchone()

            dup_flag = "  ← DUPLICATE (same trade in Excel)" if duplicate else ""
            pl = f"{row['actual_pl_pct']:+.1f}%" if row["actual_pl_pct"] else "?"
            print(
                f"  ID {row['id']:4d} | {row['created_date']} | "
                f"{row['direction']:5} {row['symbol']:6} | "
                f"source={row['source']:18} | "
                f"entry={row['actual_entry']} | P&L={pl} | {row['outcome']}"
                f"{dup_flag}"
            )
            if duplicate:
                ids_to_delete.append(row["id"])

        if not ids_to_delete:
            print("\nNone are exact duplicates of an Actual trade.")
            print("Listing all for manual review above.")
            return

        print(f"\n{len(ids_to_delete)} duplicate(s) found (exist in both screener DB and Excel import).")

        if delete:
            for rid in ids_to_delete:
                conn.execute("DELETE FROM trade_setups WHERE id=?", (rid,))
            print(f"✅ Deleted {len(ids_to_delete)} duplicate Paper & Actual record(s).")
            print("Reload the dashboard — analytics should now match Excel exactly.")
        else:
            print("\nRun with --delete to remove them:")
            print("  python fix_paper_actual.py --delete")

if __name__ == "__main__":
    main()
