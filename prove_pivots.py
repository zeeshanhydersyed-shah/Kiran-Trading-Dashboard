"""
Show exactly what the screener sees for a given symbol.
Usage: python prove_pivots.py SYMBOL
"""
import sys, sqlite3, pandas as pd, numpy as np

symbol = sys.argv[1] if len(sys.argv) > 1 else "NBP"

conn = sqlite3.connect("psx_data.db")
df = pd.read_sql(
    f"SELECT date, open, high, low, close FROM prices WHERE symbol='{symbol}' ORDER BY date",
    conn
)
conn.close()

df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

latest_idx = len(df) - 1
latest = df.iloc[latest_idx]
history = df.iloc[:latest_idx]

close  = latest["close"]
open_p = latest["open"]
high   = latest["high"]
low    = latest["low"]
ema200 = latest["ema200"]

print(f"\n=== {symbol} — Latest candle ({latest['date']}) ===")
print(f"  O={open_p}  H={high}  L={low}  C={close}")
print(f"  EMA200={ema200:.2f}  |  Close {'>' if close > ema200 else '<'} EMA200  →  {'LONG candidate' if close > ema200 else 'SHORT candidate'}")

PIVOT_LEFT = PIVOT_RIGHT = 10
ZONE_TOL   = 0.02
TOUCH_TOL  = 0.01

def find_pivots(grp, col, find_min):
    vals = grp[col].values
    n = len(vals)
    confirmed = []
    for i in range(PIVOT_LEFT, n - PIVOT_RIGHT):
        window = vals[i - PIVOT_LEFT: i + PIVOT_RIGHT + 1]
        if find_min:
            if vals[i] == window.min() and (window == vals[i]).sum() == 1:
                confirmed.append((grp["date"].iloc[i], vals[i]))
        else:
            if vals[i] == window.max() and (window == vals[i]).sum() == 1:
                confirmed.append((grp["date"].iloc[i], vals[i]))
    return confirmed

def cluster(pivots):
    if not pivots:
        return []
    levels = sorted(pivots, key=lambda x: x[1])
    zones, cluster = [], [levels[0]]
    for p in levels[1:]:
        if cluster[0][1] > 0 and (p[1] - cluster[0][1]) / cluster[0][1] <= ZONE_TOL:
            cluster.append(p)
        else:
            zones.append(cluster)
            cluster = [p]
    zones.append(cluster)
    return [(min(c, key=lambda x:x[1])[1], max(c, key=lambda x:x[1])[1], len(c),
             [x[0] for x in c]) for c in zones]

# LONG path
if close > ema200:
    raw = find_pivots(history, "low", find_min=True)
    print(f"\n--- LONG path: all confirmed pivot LOWS in history ---")
    for d, v in raw:
        flag = "✓ below close" if v <= close else "✗ ABOVE close — filtered out"
        print(f"  {d}  low={v:.2f}  {flag}")

    zones = cluster(raw)
    filtered = [(b,t,c,dates) for (b,t,c,dates) in zones if b <= close]
    print(f"\n--- Zones after price filter (must be <= {close:.2f}) ---")
    for (b,t,c,dates) in filtered:
        touch = low <= b * (1 + TOUCH_TOL)
        candle_range = high - low
        rec  = (close - low) / candle_range if candle_range > 0 else 0
        wick = (min(open_p, close) - low) / candle_range if candle_range > 0 else 0
        print(f"  {'Zone' if c>=2 else 'Level'} {b:.2f}–{t:.2f} ({c} pivot{'s' if c>1 else ''})  pivot dates: {dates}")
        print(f"    Touch (low={low} <= {b*(1+TOUCH_TOL):.2f}): {touch}")
        if touch:
            print(f"    Recovery={rec:.1%} (need >75%)  Lower wick={wick:.1%} (need >60%)")
            print(f"    Open used: {open_p}  ← {'✓ real open' if open_p != close else '✗ FALLBACK to close (open missing)'}")

# SHORT path
if close < ema200:
    raw = find_pivots(history, "high", find_min=False)
    print(f"\n--- SHORT path: all confirmed pivot HIGHS in history ---")
    for d, v in raw:
        flag = "✓ above close" if v >= close else "✗ BELOW close — filtered out"
        print(f"  {d}  high={v:.2f}  {flag}")

    zones = cluster(raw)
    filtered = [(b,t,c,dates) for (b,t,c,dates) in zones if t >= close]
    print(f"\n--- Zones after price filter (must be >= {close:.2f}) ---")
    for (b,t,c,dates) in filtered:
        touch = high >= t * (1 - TOUCH_TOL)
        candle_range = high - low
        rej  = (high - close) / candle_range if candle_range > 0 else 0
        wick = (high - max(open_p, close)) / candle_range if candle_range > 0 else 0
        print(f"  {'Zone' if c>=2 else 'Level'} {b:.2f}–{t:.2f} ({c} pivot{'s' if c>1 else ''})  pivot dates: {dates}")
        print(f"    Touch (high={high} >= {t*(1-TOUCH_TOL):.2f}): {touch}")
        if touch:
            print(f"    Rejection={rej:.1%} (need >75%)  Upper wick={wick:.1%} (need >60%)")
            print(f"    Open used: {open_p}  ← {'✓ real open' if open_p != close else '✗ FALLBACK to close (open missing)'}")
