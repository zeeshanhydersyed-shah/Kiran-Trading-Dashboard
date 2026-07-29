import sqlite3, pandas as pd, numpy as np

conn = sqlite3.connect("psx_data.db")

# Setup that fired
setup = pd.read_sql(
    "SELECT direction, entry_price, stop_loss, notes FROM trade_setups "
    "WHERE symbol='NBP' AND source='Support Reversal' ORDER BY created_date DESC LIMIT 1",
    conn
)
print("=== NBP Setup ===")
print(setup.to_string(index=False))

# Last 30 candles
df = pd.read_sql(
    "SELECT date, open, high, low, close FROM prices "
    "WHERE symbol='NBP' ORDER BY date DESC LIMIT 60", conn
)
conn.close()
df = df.sort_values("date").reset_index(drop=True)

print("\n=== Latest candle (rejection candle) ===")
print(df.tail(1).to_string(index=False))

# Compute pivot highs
PIVOT_LEFT = PIVOT_RIGHT = 10
highs = df["high"].values
n = len(highs)

print("\n=== All confirmed Pivot Highs in history ===")
pivots = []
for i in range(PIVOT_LEFT, n - PIVOT_RIGHT):
    window = highs[i - PIVOT_LEFT: i + PIVOT_RIGHT + 1]
    if highs[i] == window.max() and (window == highs[i]).sum() == 1:
        confirm_idx = i + PIVOT_RIGHT
        pivots.append((df["date"].iloc[i], highs[i], df["date"].iloc[confirm_idx]))
        print(f"  {df['date'].iloc[i]}  high={highs[i]:.2f}  (confirmed {df['date'].iloc[confirm_idx]})")

# Cluster within 2%
print("\n=== Zones (pivots within 2% of each other) ===")
if pivots:
    levels = sorted([p[1] for p in pivots])
    cluster = [levels[0]]
    for v in levels[1:]:
        if cluster[0] > 0 and (v - cluster[0]) / cluster[0] <= 0.02:
            cluster.append(v)
        else:
            print(f"  Zone: {min(cluster):.2f}–{max(cluster):.2f}  ({len(cluster)} pivot{'s' if len(cluster)>1 else ''})")
            cluster = [v]
    print(f"  Zone: {min(cluster):.2f}–{max(cluster):.2f}  ({len(cluster)} pivot{'s' if len(cluster)>1 else ''})")

# EMA200
df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
latest = df.iloc[-1]
print(f"\n=== Latest candle detail ===")
print(f"  Date:   {latest['date']}")
print(f"  O={latest['open']}  H={latest['high']}  L={latest['low']}  C={latest['close']}")
print(f"  EMA200: {latest['ema200']:.2f}")
print(f"  Close < EMA200: {latest['close'] < latest['ema200']}")
candle_range = latest['high'] - latest['low']
rejection = (latest['high'] - latest['close']) / candle_range if candle_range > 0 else 0
upper_wick = (latest['high'] - max(latest['open'], latest['close'])) / candle_range if candle_range > 0 else 0
print(f"  Rejection ratio: {rejection:.1%}  (need >75%)")
print(f"  Upper wick ratio: {upper_wick:.1%}  (need >60%)")
