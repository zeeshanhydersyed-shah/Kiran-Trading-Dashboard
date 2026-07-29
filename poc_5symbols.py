"""POC: Generate rectangles for 5 symbols to prove code works."""

import sqlite3
import pandas as pd
from pivots import find_pivots_collapsed
from assemble_rectangle import assemble_rectangle
from research_filters import exclude_known_artifact_symbols, drop_placeholder_zero_bars

DB = "psx_data.db"

print("Loading data...")
con = sqlite3.connect(DB)
prices = pd.read_sql_query(
    "SELECT symbol, date, open, high, low, close, volume FROM prices_adjusted "
    "WHERE date >= '2005-01-01' AND date <= '2026-12-31' ORDER BY symbol, date",
    con
)
prices['volume'] = prices['volume'].fillna(0)
con.close()

symbols = sorted(list(set(prices['symbol'].unique())))
symbols = exclude_known_artifact_symbols(symbols)
test_symbols = symbols[:5]  # Just 5 symbols

print(f"Testing on: {test_symbols}\n")

all_candidates = []

for symbol in test_symbols:
    print(f"Processing {symbol}...", end=" ")

    symbol_data = prices[prices['symbol'] == symbol].copy()
    symbol_data = drop_placeholder_zero_bars(symbol_data).reset_index(drop=True)

    if len(symbol_data) < 30:
        print("SKIP (too few bars)")
        continue

    highs = symbol_data['high'].to_numpy(dtype=float)
    lows = symbol_data['low'].to_numpy(dtype=float)
    closes = symbol_data['close'].to_numpy(dtype=float)
    dates_arr = symbol_data['date'].to_numpy()

    try:
        pivots = find_pivots_collapsed(closes, highs, lows, left=3, right=3)
    except Exception as e:
        print(f"PIVOT ERROR: {e}")
        continue

    print(f"found {len(pivots)} pivots", end=" ... ")

    if not pivots:
        print("SKIP (no pivots)")
        continue

    price_bars = []
    for idx, row in symbol_data.iterrows():
        day_offset = (pd.to_datetime(row['date']) - pd.Timestamp("2005-01-01")).days
        price_bars.append({'day': int(day_offset), 'close': float(row['close'])})

    high_pivots = [(p.index, p.price) for p in pivots if p.kind == 'high']
    low_pivots = [(p.index, p.price) for p in pivots if p.kind == 'low']

    count = 0
    for pivot in pivots:
        try:
            if pivot.kind == 'high':
                support_pivs = [(idx, price) for idx, price in low_pivots if idx != pivot.index]
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
            else:
                resistance_pivs = [(idx, price) for idx, price in high_pivots if idx != pivot.index]
                result = assemble_rectangle(
                    anchor_index=pivot.index,
                    anchor_price=pivot.price,
                    anchor_side='support',
                    support_pivots=low_pivots,
                    resistance_pivots=resistance_pivs,
                    price_bars=price_bars,
                    tolerance_pct=0.015,
                    min_touches=3,
                    min_duration_days=21,
                    max_duration_days=60,
                    margin_multiplier=2.0,
                )

            height_pct = abs(result.resistance_level - result.support_level) / result.support_level if result.support_level > 0 else 0

            all_candidates.append({
                'symbol': symbol,
                'anchor_index': pivot.index,
                'anchor_date': dates_arr[pivot.index],
                'outcome': result.outcome,
                'breakout_direction': result.breakout_direction,
                'support_level': result.support_level,
                'resistance_level': result.resistance_level,
                'height_pct': height_pct,
                'duration_days': result.duration_days,
            })
            count += 1
        except Exception as e:
            pass

    print(f"generated {count} candidates")

print(f"\n{'='*80}")
print(f"RESULTS (5 symbols, min_touches=3)")
print(f"{'='*80}\n")
print(f"Total candidates: {len(all_candidates)}")

if all_candidates:
    df = pd.DataFrame(all_candidates)
    df.to_csv("poc_results_5symbols.csv", index=False)
    print(f"Saved: poc_results_5symbols.csv\n")

    print("Outcome distribution:")
    for outcome in ['VALID', 'EXPIRED_NO_BREAKOUT', 'REJECTED_TOO_SHORT', 'REJECTED_HEIGHT_FLOOR', 'REJECTED_INSUFFICIENT_TOUCHES']:
        count = (df['outcome'] == outcome).sum()
        pct = 100 * count / len(df) if len(df) > 0 else 0
        print(f"  {outcome:35s}: {count:5d} ({pct:6.2f}%)")

    valid = df[df['outcome'] == 'VALID']
    if len(valid) > 0:
        print(f"\nVALID: {len(valid)}")
        print(f"  Up:   {(valid['breakout_direction']=='up').sum()}")
        print(f"  Down: {(valid['breakout_direction']=='down').sum()}")
        print(f"  Duration: {valid['duration_days'].min()}-{valid['duration_days'].median()}-{valid['duration_days'].max()} days")
        print(f"  Height:   {valid['height_pct'].min()*100:.2f}%-{valid['height_pct'].median()*100:.2f}%-{valid['height_pct'].max()*100:.2f}%")
else:
    print("No candidates!")
