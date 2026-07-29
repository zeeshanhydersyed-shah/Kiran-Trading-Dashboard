"""
prebreakout_volume_coupling_check.py — Check 2 of the PRE_BREAKOUT follow-up:
quantify how many of the 360,576 null-bbw_pct rows in pre_breakout_v2_staging
are null specifically because of the volume-window coupling in
stock_signals.py's _compute_bt_vc(), versus null for a legitimate reason
(no stock_signals coverage yet, or genuinely insufficient price history).

READ-ONLY. Reuses _compute_bt_vc() from stock_signals.py verbatim (imported,
not reimplemented) to recompute the price-side and volume-side window
validity independently, exactly as the existing code does it.
"""

import sqlite3
from pathlib import Path
from collections import Counter

from stock_signals import _compute_bt_vc

DB = str(Path(__file__).parent / "psx_data.db")


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    null_rows = cur.execute(
        "SELECT symbol, date FROM pre_breakout_v2_staging WHERE bbw_pct IS NULL ORDER BY symbol, date"
    ).fetchall()
    print(f"Total null-bbw_pct population rows to classify: {len(null_rows):,}")

    # Which (symbol,date) actually have a stock_signals row at all?
    ss_dates_by_symbol = {}
    for symbol, date in cur.execute(
        "SELECT symbol, date FROM stock_signals ORDER BY symbol, date"
    ).fetchall():
        ss_dates_by_symbol.setdefault(symbol, set()).add(date)

    # Full prices_adjusted (close, volume) series per symbol, ASC by date —
    # used to independently recompute _compute_bt_vc's price-window and
    # volume-window validity for rows that DO have a stock_signals row.
    prices_by_symbol = {}
    for symbol, date, close, volume in cur.execute(
        "SELECT symbol, date, close, volume FROM prices_adjusted ORDER BY symbol, date"
    ).fetchall():
        prices_by_symbol.setdefault(symbol, []).append((date, close, volume))
    date_index_by_symbol = {
        sym: {d: i for i, (d, c, v) in enumerate(rows)} for sym, rows in prices_by_symbol.items()
    }

    counts = Counter()
    unexplained = []

    for symbol, date in null_rows:
        if date not in ss_dates_by_symbol.get(symbol, ()):
            counts["NO_STOCK_SIGNALS_ROW (population date predates/exceeds this symbol's "
                   "stock_signals coverage window)"] += 1
            continue

        rows = prices_by_symbol.get(symbol)
        idx = date_index_by_symbol.get(symbol, {})
        pos = idx.get(date)
        if rows is None or pos is None:
            counts["NO_PRICES_ADJUSTED_ROW (stock_signals row exists but no matching "
                   "prices_adjusted row -- shouldn't happen, flagged)"] += 1
            unexplained.append((symbol, date, "no prices_adjusted row"))
            continue

        # Reproduce _compute_bt_vc's own price-side-only check (mirrors lines
        # inside the function: pos>=19 and all 20 trailing closes non-null)
        # by calling it with volume forced non-null so ONLY the price side can
        # fail it -- cheapest way to isolate the price condition without
        # duplicating the function's internals.
        price_only_rows = [(d, c, 1.0) for (d, c, v) in rows]  # volume replaced with a
                                                                 # dummy valid value everywhere
        bt_price_only, _, _ = _compute_bt_vc(price_only_rows, pos)

        # Real recomputation using the ACTUAL stored volume, exactly as the
        # existing code does it (this is the ground-truth bt for this row).
        bt_real, vc_real, avv_real = _compute_bt_vc(rows, pos)

        if bt_price_only is None:
            counts["INSUFFICIENT_PRICE_HISTORY (pos<19 or a NULL close within the trailing "
                   "20-day window -- legitimate, not the volume bug)"] += 1
        elif bt_real is None:
            # Price side alone would have produced a value, but the real
            # (volume-coupled) computation nulled it -> this IS the bug.
            counts["VOLUME_COUPLING_BUG (20-day close window fully valid; nulled solely "
                   "because the 10d/50d volume window has a NULL/zero)"] += 1
        else:
            # Both sides valid -> bt should be non-null. If we're here, this
            # row was in the null set for some OTHER reason -- investigate,
            # don't silently drop it.
            counts["UNEXPLAINED (both price and volume windows valid on independent "
                   "recomputation, yet stock_signals.base_tightness is NULL)"] += 1
            unexplained.append((symbol, date, f"recomputed bt={bt_real}"))

    print("\nBreakdown of the 360,576 null-bbw_pct PRE_BREAKOUT rows:")
    total = sum(counts.values())
    for k, v in counts.most_common():
        print(f"  {v:>7,}  ({v/total*100:5.1f}%)  {k}")
    print(f"  {'-'*7}")
    print(f"  {total:>7,}  total")

    if unexplained:
        print(f"\nFirst {min(10, len(unexplained))} UNEXPLAINED / NO_PRICES_ADJUSTED_ROW cases "
              f"(of {len(unexplained)} total) for manual follow-up:")
        for u in unexplained[:10]:
            print(f"  {u}")

    con.close()


if __name__ == "__main__":
    main()
