#!/usr/bin/env python3
"""
Audit the trailing stop calculation
Test on 2026 data only (out-of-sample)
"""

import pandas as pd
import numpy as np

signals = pd.read_csv('support_signals_full.csv')

print("="*80)
print("AUDIT: Trailing Stop Calculation")
print("="*80)

# Convert dates
signals['date'] = pd.to_datetime(signals['date'])

# Test on 2026 only (out-of-sample)
sig_2026 = signals[signals['date'] >= '2026-01-01'].reset_index(drop=True)
print(f"\nOut-of-sample (2026+): {len(sig_2026):,} signals")

# Uptrend only
sig_2026_up = sig_2026[sig_2026['trend_state'] == 'uptrend'].reset_index(drop=True)
print(f"Uptrend: {len(sig_2026_up):,} signals")

if len(sig_2026_up) == 0:
    print("\nNo 2026 data available. Testing on 2025 instead...")
    sig_test = signals[signals['date'] >= '2025-01-01'].reset_index(drop=True)
    sig_test = sig_test[sig_test['trend_state'] == 'uptrend'].reset_index(drop=True)
    print(f"2025+ uptrend: {len(sig_test):,} signals")
else:
    sig_test = sig_2026_up

print("\n" + "="*80)
print("SAMPLE TRADES ANALYSIS")
print("="*80)

# Show 10 random trades
sample = sig_test.sample(min(10, len(sig_test)))

print("\nSample trades (showing actual vs trailing stop):")
print("-"*80)

for i, (idx, row) in enumerate(sample.iterrows(), 1):
    max_fav = row['max_favorable']
    actual = row['return_20d']
    trailing_exit = max_fav - 0.02

    print(f"\nTrade {i}: {row['symbol']} {row['date']}")
    print(f"  Max reached: {max_fav:+.2%}")
    print(f"  Actual return (end): {actual:+.2%}")
    print(f"  Trailing 2% stop: {trailing_exit:+.2%}")
    print(f"  Exit at: {max(actual, trailing_exit):+.2%}")

# Statistics
print("\n" + "="*80)
print("STATISTICS ON OUT-OF-SAMPLE DATA")
print("="*80)

returns = sig_test['return_20d'].copy()
max_favs = sig_test['max_favorable'].copy()

# Trailing stop calculation
trailing_exits = max_favs - 0.02
final_returns = np.maximum(trailing_exits, returns)

# Also cap at -6% hard SL
final_returns_with_sl = final_returns.copy()
final_returns_with_sl[final_returns_with_sl < -0.06] = -0.06

wins = final_returns_with_sl > 0
losses = final_returns_with_sl <= 0

print(f"\nTotal trades: {len(sig_test):,}")
print(f"Wins: {wins.sum()} ({wins.sum()/len(sig_test)*100:.1f}%)")
print(f"Losses: {losses.sum()} ({losses.sum()/len(sig_test)*100:.1f}%)")

if wins.sum() > 0:
    print(f"\nAvg win: {final_returns_with_sl[wins].mean():+.2%}")
    print(f"Max win: {final_returns_with_sl[wins].max():+.2%}")
    print(f"Min win: {final_returns_with_sl[wins].min():+.2%}")

if losses.sum() > 0:
    print(f"\nAvg loss: {final_returns_with_sl[losses].mean():+.2%}")
    print(f"Max loss: {final_returns_with_sl[losses].max():+.2%}")
    print(f"Min loss: {final_returns_with_sl[losses].min():+.2%}")

expectancy = final_returns_with_sl.mean()
print(f"\nExpectancy: {expectancy:+.2%}")

if expectancy > 0:
    trades_for_10pct = 0.10 / expectancy
    print(f"Trades for 10% gain: {trades_for_10pct:.0f}")

# Compare vs hard 6% SL (no trailing)
print("\n" + "="*80)
print("COMPARISON: Hard 6% SL vs Trailing 2%")
print("="*80)

hard_sl = returns.copy()
hard_sl[hard_sl < -0.06] = -0.06

print(f"\nHard 6% SL (no trailing):")
print(f"  Avg: {hard_sl.mean():+.2%}")
print(f"  Wins: {(hard_sl > 0).sum()}/{len(hard_sl)} ({(hard_sl > 0).sum()/len(hard_sl)*100:.1f}%)")

print(f"\nTrailing 2% stop:")
print(f"  Avg: {final_returns_with_sl.mean():+.2%}")
print(f"  Wins: {wins.sum()}/{len(sig_test)} ({wins.sum()/len(sig_test)*100:.1f}%)")

print(f"\nDifference: {(final_returns_with_sl.mean() - hard_sl.mean())*100:+.2f} bps")

# Check for data quality issues
print("\n" + "="*80)
print("DATA QUALITY CHECKS")
print("="*80)

print(f"\nMax favorable stats:")
print(f"  Min: {max_favs.min():+.2%}")
print(f"  Mean: {max_favs.mean():+.2%}")
print(f"  Max: {max_favs.max():+.2%}")
print(f"  Median: {max_favs.median():+.2%}")

print(f"\nActual return stats:")
print(f"  Min: {returns.min():+.2%}")
print(f"  Mean: {returns.mean():+.2%}")
print(f"  Max: {returns.max():+.2%}")
print(f"  Median: {returns.median():+.2%}")

print(f"\nPrice went DOWN from peak more than 2%:")
stopped = (max_favs - returns) > 0.02
print(f"  Count: {stopped.sum()} ({stopped.sum()/len(sig_test)*100:.1f}%)")
print(f"  These trades would be stopped by trailing stop")

print("\n[CONCLUSION]")
print("If out-of-sample expectancy << 10.29%, original results may be overfitted.")
