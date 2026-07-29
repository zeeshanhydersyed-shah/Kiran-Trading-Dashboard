"""
dow_weekly_explore.py — quick eyeball check: resample daily prices_adjusted
to weekly OHLC and detect swing highs/lows (Dow-theory-style structure),
for a handful of liquid names. Exploratory only, not a saved research script
for this project's formal S-00X convention — just a look.

Pivot definition: strict local max/min over a [i-LEFT, i+RIGHT] window on
weekly high/low, no ties — same convention (strict comparison, no ties) as
the existing daily pivot logic in breakout_events_v2.py/stock_signals.py,
just a shorter window (2 weeks each side vs 10 trading days each side) since
weekly bars are already far less noisy.

Read-only against psx_data.db.
"""

import sqlite3
import pandas as pd

DB = "psx_data.db"
LEFT = RIGHT = 2  # weeks each side


def load_weekly(symbol, con):
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close FROM prices_adjusted "
        "WHERE symbol=? ORDER BY date ASC", con, params=(symbol,)
    )
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    w = df.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna(how="all")
    w = w.dropna(subset=["close"])
    return w.reset_index()


def find_pivots(w):
    """Strict local max (pivot high) / local min (pivot low) over
    [i-LEFT, i+RIGHT], no ties. Returns list of (idx, date, type, price)."""
    n = len(w)
    pivots = []
    for i in range(LEFT, n - RIGHT):
        hi = w["high"].iat[i]
        lo = w["low"].iat[i]
        window_hi = w["high"].iloc[i - LEFT:i + RIGHT + 1]
        window_lo = w["low"].iloc[i - LEFT:i + RIGHT + 1]
        if hi == window_hi.max() and (window_hi == hi).sum() == 1:
            pivots.append((i, w["date"].iat[i], "H", hi))
        if lo == window_lo.min() and (window_lo == lo).sum() == 1:
            pivots.append((i, w["date"].iat[i], "L", lo))
    pivots.sort(key=lambda p: p[0])
    return enforce_alternation(pivots)


def enforce_alternation(pivots):
    """Collapse consecutive same-type candidates down to a single, most-
    extreme one — standard zigzag alternation fix. Raw local-extrema
    detection can flag e.g. three straight weekly lows in a row (no
    confirmed high in between); a real swing sequence must alternate
    H-L-H-L, so between any two same-type candidates we keep only the
    more extreme (highest H, lowest L) and drop the other."""
    result = []
    for p in pivots:
        idx, date, typ, price = p
        if result and result[-1][2] == typ:
            prev = result[-1]
            if (typ == "H" and price > prev[3]) or (typ == "L" and price < prev[3]):
                result[-1] = p
            # else: new candidate is less extreme than the one already kept — drop it
        else:
            result.append(p)
    return result


def summarize(symbol, w, pivots):
    print(f"\n{'='*70}\n{symbol} — {len(w)} weekly bars, {w['date'].iat[0].date()} -> {w['date'].iat[-1].date()}")
    print(f"{'='*70}")

    highs = [p for p in pivots if p[2] == "H"]
    lows = [p for p in pivots if p[2] == "L"]
    print(f"Confirmed pivot highs: {len(highs)}, pivot lows: {len(lows)} "
          f"(LEFT=RIGHT={LEFT} weeks)")

    # last 8 swings, alternating-ish, for eyeballing
    last8 = pivots[-8:]
    print("\nLast 8 confirmed swings:")
    for idx, date, typ, price in last8:
        print(f"  {date.date()}  {typ}  {price:.2f}")

    # simple structure read: compare last 2 highs and last 2 lows
    if len(highs) >= 2 and len(lows) >= 2:
        h1, h2 = highs[-2][3], highs[-1][3]
        l1, l2 = lows[-2][3], lows[-1][3]
        hh = h2 > h1
        hl = l2 > l1
        lh = h2 < h1
        ll = l2 < l1
        if hh and hl:
            read = "UPTREND intact (HH + HL)"
        elif lh and ll:
            read = "DOWNTREND intact (LH + LL)"
        else:
            read = f"MIXED/transitional (H:{'HH' if hh else 'LH'}, L:{'HL' if hl else 'LL'})"
        print(f"\nStructure read (last 2 highs vs last 2 lows): {read}")
        print(f"  Highs: {highs[-2][3]:.2f} ({highs[-2][1].date()}) -> {highs[-1][3]:.2f} ({highs[-1][1].date()})")
        print(f"  Lows:  {lows[-2][3]:.2f} ({lows[-2][1].date()}) -> {lows[-1][3]:.2f} ({lows[-1][1].date()})")

    last_close = w["close"].iat[-1]
    print(f"\nLatest close ({w['date'].iat[-1].date()}): {last_close:.2f}")


def main():
    con = sqlite3.connect(DB)
    symbols = ["LUCK", "HBL", "OGDC", "MEBL", "UBL", "PSO"]
    for sym in symbols:
        w = load_weekly(sym, con)
        pivots = find_pivots(w)
        summarize(sym, w, pivots)
    con.close()


if __name__ == "__main__":
    main()
