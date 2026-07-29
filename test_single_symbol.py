"""Quick test: run rectangle generation on ONE symbol to identify bottleneck."""

import sqlite3
import pandas as pd
import time
from pivots import find_pivots_collapsed
from fit_horizontal_level import fit_horizontal_level
from assemble_rectangle import assemble_rectangle
from research_filters import drop_placeholder_zero_bars

DB = "psx_data.db"

con = sqlite3.connect(DB)
prices = pd.read_sql_query(
    "SELECT symbol, date, open, high, low, close, volume FROM prices_adjusted "
    "WHERE date >= '2005-01-01' AND date <= '2026-12-31' ORDER BY symbol, date",
    con
)
prices['volume'] = prices['volume'].fillna(0)
con.close()

# Get first symbol with data
symbols = sorted(list(set(prices['symbol'].unique())))
test_symbol = symbols[0]
print(f"Testing on symbol: {test_symbol}")

symbol_data = prices[prices['symbol'] == test_symbol].copy()
print(f"  Bars: {len(symbol_data)}")

print("\n1. Dropping placeholder zeros...")
start = time.time()
symbol_data = drop_placeholder_zero_bars(symbol_data).reset_index(drop=True)
print(f"  Done in {time.time()-start:.2f}s, bars now: {len(symbol_data)}")

print("\n2. Finding pivots...")
highs = symbol_data['high'].to_numpy(dtype=float)
lows = symbol_data['low'].to_numpy(dtype=float)
closes = symbol_data['close'].to_numpy(dtype=float)

start = time.time()
pivots = find_pivots_collapsed(closes, highs, lows, left=3, right=3)
elapsed = time.time() - start
print(f"  Done in {elapsed:.2f}s, found {len(pivots)} pivots")

if len(pivots) > 0:
    print("\n3. Building price_bars and testing first rectangle...")
    price_bars = []
    for idx, row in symbol_data.iterrows():
        day_offset = (pd.to_datetime(row['date']) - pd.Timestamp("2005-01-01")).days
        price_bars.append({'day': int(day_offset), 'close': float(row['close'])})

    high_pivots = [(p.index, p.price) for p in pivots if p.kind == 'high']
    low_pivots = [(p.index, p.price) for p in pivots if p.kind == 'low']

    if high_pivots:
        pivot = [p for p in pivots if p.kind == 'high'][0]
        print(f"  Testing anchor: high pivot at index {pivot.index}, price {pivot.price}")

        support_pivs = [(idx, price) for idx, price in low_pivots if idx != pivot.index]

        start = time.time()
        result = assemble_rectangle(
            anchor_index=pivot.index,
            anchor_price=pivot.price,
            anchor_side='resistance',
            support_pivots=support_pivs,
            resistance_pivots=high_pivots,
            price_bars=price_bars,
            tolerance_pct=0.015,
            min_touches=3,
            min_duration_days=21,
            max_duration_days=60,
            margin_multiplier=2.0,
        )
        elapsed = time.time() - start
        print(f"  Rectangle assembly completed in {elapsed:.2f}s")
        print(f"  Result: {result.outcome}, {result.duration_days} days, breakout={result.breakout_direction}")
else:
    print("  No pivots found!")

print("\nTest complete.")
