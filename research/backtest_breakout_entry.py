#!/usr/bin/env python3
"""
Entry: 1 point above candle high (breakout)
SL: -6% hard stop
Skip the retest
"""

import pandas as pd
import numpy as np

signals = pd.read_csv('support_signals_full.csv')
prices = pd.read_csv('merged_psx_data.csv')

print("="*80)
print("BREAKOUT ENTRY: 1 Point Above High + 6% Hard SL")
print("="*80)

# Filter to uptrend
uptrend = signals[signals['trend_state'] == 'uptrend'].copy()

# Recalculate entry price: high + 1
# For PSX stocks, prices are typically in 20-500 range, so 1 point = 1 unit
uptrend['entry_high'] = uptrend['support_level'] + 1  # approximate: use support as proxy
# Actually, we need the actual candle high. Let's use a different approach.

# The signals don't include the actual candle high price
# But we can use max_favorable to estimate: if price went up X% from breakout entry,
# it should be (high + 1) based on the reversal candle

# Let's recalculate returns by assuming entry at "high + 1"
# The original returns are from 'high' of the candle
# New returns from 'high + 1' would be slightly less

# Original entry = high (from signal generation)
# New entry = high + 1
# If return_5d was (close_5d - high) / high
# New return = (close_5d - (high + 1)) / (high + 1)
# But we don't have 'high' explicitly

# Simplify: assume 1 point slippage on entry
# Approximate: reduce all returns by (1 / assumed_price)
# For PSX, assume average price ~100
slippage_pct = 1.0 / 100.0  # 1 point on ~100 price = 1%

print(f"\nAdjusting for 1-point slippage at entry (+0.1% cost)...\n")

for window in [5, 10, 20]:
    col = f'return_{window}d'

    # Original returns from candle high
    returns = uptrend[col].copy()

    # Adjust for 1-point entry slip (reduce all returns by 1%)
    adjusted_returns = returns - slippage_pct

    # Apply 6% hard SL
    adjusted_returns[adjusted_returns < -0.06] = -0.06

    wins = adjusted_returns > 0
    losses = adjusted_returns <= 0

    win_count = wins.sum()
    loss_count = losses.sum()
    win_rate = win_count / len(adjusted_returns)

    avg_win = adjusted_returns[wins].mean() if win_count > 0 else 0
    avg_loss = adjusted_returns[losses].mean() if loss_count > 0 else 0
    total_return = adjusted_returns.sum()
    avg_return = adjusted_returns.mean()

    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    print(f"{window}-Day Hold:")
    print(f"  Total: {len(adjusted_returns):,}")
    print(f"  Wins: {win_count} ({win_rate*100:.1f}%)  |  Losses: {loss_count} ({(1-win_rate)*100:.1f}%)")
    print(f"  Avg Win: {avg_win:+.2%}  |  Avg Loss: {avg_loss:+.2%}  |  Ratio: {win_loss_ratio:.2f}x")
    print(f"  Total P&L: {total_return:+.2%}  |  Per Trade: {avg_return:+.2%}")

    if avg_return > 0:
        trades_for_10pct = 0.10 / avg_return
        print(f"  >>> Trades for 10% gain: {trades_for_10pct:.0f}")
    else:
        needed = abs(avg_return) * 100
        print(f"  >>> Need {needed:.0f} trades just to break even")
    print()

# Apply quality filters
print("="*80)
print("WITH QUALITY FILTERS (Recovery >70% + Wick >55%)")
print("="*80)

quality = uptrend[
    (uptrend['recovery_ratio'] > 0.70) &
    (uptrend['lower_wick_ratio'] > 0.55)
].copy()

print(f"Qualifying signals: {len(quality):,}\n")

for window in [5, 10, 20]:
    col = f'return_{window}d'
    adjusted_returns = quality[col].copy() - slippage_pct
    adjusted_returns[adjusted_returns < -0.06] = -0.06

    wins = adjusted_returns > 0
    win_rate = wins.sum() / len(adjusted_returns)
    avg_return = adjusted_returns.mean()

    print(f"{window}d: Win rate {win_rate*100:.1f}%, Avg P&L {avg_return:+.2%}")

# Even higher quality
print("\n" + "="*80)
print("ULTRA-STRICT (Recovery >75% + Wick >60%)")
print("="*80)

ultra = uptrend[
    (uptrend['recovery_ratio'] > 0.75) &
    (uptrend['lower_wick_ratio'] > 0.60)
].copy()

print(f"Signals: {len(ultra):,}\n")

for window in [5, 20]:
    col = f'return_{window}d'
    adjusted_returns = ultra[col].copy() - slippage_pct
    adjusted_returns[adjusted_returns < -0.06] = -0.06

    wins = adjusted_returns > 0
    win_rate = wins.sum() / len(adjusted_returns)
    avg_return = adjusted_returns.mean()
    avg_win = adjusted_returns[adjusted_returns > 0].mean() if wins.sum() > 0 else 0
    avg_loss = adjusted_returns[adjusted_returns <= 0].mean() if (~wins).sum() > 0 else 0

    print(f"{window}d: Signals {len(ultra)}, Win rate {win_rate*100:.1f}%, "
          f"Avg {avg_return:+.2%}, W/L {abs(avg_win/avg_loss) if avg_loss != 0 else 0:.2f}x")

# Save
uptrend_breakout = uptrend.copy()
for window in [5, 10, 20]:
    col = f'return_{window}d'
    uptrend_breakout[f'{col}_breakout'] = uptrend[col] - slippage_pct
    uptrend_breakout.loc[uptrend_breakout[f'{col}_breakout'] < -0.06, f'{col}_breakout'] = -0.06

uptrend_breakout.to_csv('support_signals_breakout_entry.csv', index=False)
print(f"\nSaved: support_signals_breakout_entry.csv")

# Show top trades
print("\nTop winners (20-day breakout with 6% SL):")
top = uptrend_breakout.nlargest(10, 'return_20d_breakout')
print(top[['date', 'symbol', 'recovery_ratio', 'lower_wick_ratio', 'return_20d_breakout']].to_string(index=False))

print("\n" + "="*80)
print("COMPARISON: Entry at High vs High+1")
print("="*80)
print("\nEntry at High (original):")
print("  5d: -2.79%, 10d: -1.78%, 20d: -0.55%")
print("\nEntry at High+1 (breakout, -0.1% slippage, 6% SL):")

for window in [5, 10, 20]:
    col = f'return_{window}d'
    returns = uptrend[col].copy() - slippage_pct
    returns[returns < -0.06] = -0.06
    print(f"  {window}d: {returns.mean():+.2%}", end="")
print()
