#!/usr/bin/env python3
"""
Filter support signals and backtest with 1% risk rule
"""

import pandas as pd
import numpy as np

# Load signals
print("[LOAD] Reading support_signals_full.csv...")
df = pd.read_csv('support_signals_full.csv')
print(f"[OK] Loaded {len(df):,} signals")

print("\n" + "="*80)
print("BASELINE (NO FILTERS)")
print("="*80)

# Baseline stats
winners = df[df['return_5d'] > 0]
losers = df[df['return_5d'] <= 0]
print(f"Total signals: {len(df):,}")
print(f"Win rate: {len(winners)/len(df)*100:.1f}%")
print(f"Winners: {len(winners)} ({len(winners)/len(df)*100:.1f}%)")
print(f"Losers: {len(losers)} ({len(losers)/len(df)*100:.1f}%)")
print(f"Avg winner return: {winners['return_5d'].mean():+.2%}")
print(f"Avg loser return: {losers['return_5d'].mean():+.2%}")
print(f"Profit factor: {abs(winners['return_5d'].sum() / losers['return_5d'].sum()) if losers['return_5d'].sum() != 0 else 0:.2f}")

# Apply filters
print("\n" + "="*80)
print("FILTER 1: Uptrend Only")
print("="*80)

f1 = df[df['trend_state'] == 'uptrend'].reset_index(drop=True)
print(f"Signals: {len(f1):,}")
if len(f1) > 0:
    w1 = f1[f1['return_5d'] > 0]
    l1 = f1[f1['return_5d'] <= 0]
    print(f"Win rate: {len(w1)/len(f1)*100:.1f}%")
    print(f"Avg return: {f1['return_5d'].mean():+.2%}")

print("\n" + "="*80)
print("FILTER 2: Uptrend + Recovery > 70%")
print("="*80)

f2 = df[(df['trend_state'] == 'uptrend') &
        (df['recovery_ratio'] > 0.70)].reset_index(drop=True)
print(f"Signals: {len(f2):,}")
if len(f2) > 0:
    w2 = f2[f2['return_5d'] > 0]
    l2 = f2[f2['return_5d'] <= 0]
    print(f"Win rate: {len(w2)/len(f2)*100:.1f}%")
    print(f"Avg return: {f2['return_5d'].mean():+.2%}")
    print(f"Winners: {len(w2)}, Losers: {len(l2)}")

print("\n" + "="*80)
print("FILTER 3: Uptrend + Recovery > 70% + Wick > 55%")
print("="*80)

f3 = df[(df['trend_state'] == 'uptrend') &
        (df['recovery_ratio'] > 0.70) &
        (df['lower_wick_ratio'] > 0.55)].reset_index(drop=True)
print(f"Signals: {len(f3):,}")
if len(f3) > 0:
    w3 = f3[f3['return_5d'] > 0]
    l3 = f3[f3['return_5d'] <= 0]
    print(f"Win rate: {len(w3)/len(f3)*100:.1f}%")
    print(f"Avg return: {f3['return_5d'].mean():+.2%}")
    print(f"Winners: {len(w3)} ({len(w3)/len(f3)*100:.1f}%)")
    print(f"Losers: {len(l3)} ({len(l3)/len(f3)*100:.1f}%)")
    print(f"Profit factor: {abs(w3['return_5d'].sum() / l3['return_5d'].sum()) if l3['return_5d'].sum() != 0 else 0:.2f}")
else:
    print("No signals match criteria")

print("\n" + "="*80)
print("BACKTEST: PERFORMANCE ANALYSIS (Filter 3)")
print("="*80)

if len(f3) > 0:
    f3_test = f3.copy()

    # Count winners/losers at different timeframes
    for window in [5, 10, 20]:
        col = f'return_{window}d'
        winners_bt = f3_test[f3_test[col] > 0]
        losers_bt = f3_test[f3_test[col] <= 0]

        total_pnl = f3_test[col].sum()
        avg_pnl = f3_test[col].mean()

        print(f"\n{window}-Day Backtest:")
        print(f"  Total trades: {len(f3_test):,}")
        print(f"  Winning trades: {len(winners_bt)} ({len(winners_bt)/len(f3_test)*100:.1f}%)")
        print(f"  Losing trades: {len(losers_bt)} ({len(losers_bt)/len(f3_test)*100:.1f}%)")
        print(f"  Average win: {winners_bt[col].mean():+.2%}")
        print(f"  Average loss: {losers_bt[col].mean():+.2%}")
        print(f"  Win/loss ratio: {abs(winners_bt[col].mean() / losers_bt[col].mean()) if losers_bt[col].mean() != 0 else 0:.2f}x")
        print(f"  Total P&L: {total_pnl:+.2%}")
        print(f"  Average P&L per trade: {avg_pnl:+.2%}")

print("\n" + "="*80)
print("ALTERNATIVE FILTERS TO TRY")
print("="*80)

# Try other combinations
combos = [
    ('Downtrend + Recovery > 70%',
     df[(df['trend_state'] == 'downtrend') & (df['recovery_ratio'] > 0.70)]),
    ('All trends + Recovery > 75%',
     df[df['recovery_ratio'] > 0.75]),
    ('Uptrend + Volume ratio > 1.5x',
     df[(df['trend_state'] == 'uptrend') & (df['volume_ma_ratio'] > 1.5)]),
]

for name, subset in combos:
    if len(subset) > 0:
        w = len(subset[subset['return_5d'] > 0])
        print(f"\n{name}")
        print(f"  Signals: {len(subset):,}, Win rate: {w/len(subset)*100:.1f}%, Avg return: {subset['return_5d'].mean():+.2%}")

# Save best filter
print("\n" + "="*80)
print("SAVING BEST FILTER")
print("="*80)

best = f3.copy()
best.to_csv('support_signals_filtered.csv', index=False)
print(f"Saved {len(best):,} filtered signals to support_signals_filtered.csv")

# Show sample
print("\nTop 10 winners from filtered set:")
print(best.nlargest(10, 'return_5d')[['date', 'symbol', 'recovery_ratio', 'lower_wick_ratio', 'return_5d', 'return_20d']].to_string(index=False))
