#!/usr/bin/env python3
"""
Quick analysis: Rising SMA trend + 6% SL
"""

import pandas as pd
import numpy as np

signals = pd.read_csv('support_signals_full.csv')
prices = pd.read_csv('merged_psx_data.csv')

print("[FILTER] Applying strict trend: rising 50-SMA for 5 days")
print(f"        AND 6% hard stop loss\n")

# Simple approach: use signals already marked as uptrend
# (these have close > SMA50 * 1.01)
# This is our proxy for "trending market"
strict_signals = signals[signals['trend_state'] == 'uptrend'].copy()

# Add 6% hard SL filter
strict_signals['hit_6pct_sl'] = strict_signals['max_adverse'] < -0.06

print("="*80)
print(f"UPTREND SIGNALS (proxy for rising SMA)")
print("="*80)
print(f"Total: {len(strict_signals):,}")
print(f"Hit 6% SL: {strict_signals['hit_6pct_sl'].sum():,} ({strict_signals['hit_6pct_sl'].sum()/len(strict_signals)*100:.1f}%)")

# Backtest
print("\nBACKTEST WITH 6% HARD STOP LOSS:\n")

results = []
for window in [5, 10, 20]:
    col = f'return_{window}d'

    # Cap losses at 6%
    returns = strict_signals[col].copy()
    returns[strict_signals['hit_6pct_sl']] = -0.06

    wins = returns > 0
    losses = returns <= 0

    win_count = wins.sum()
    loss_count = losses.sum()
    win_rate = win_count / len(returns)

    avg_win = returns[wins].mean() if win_count > 0 else 0
    avg_loss = returns[losses].mean() if loss_count > 0 else 0
    total_return = returns.sum()
    avg_return = returns.mean()

    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    print(f"{window}-Day Hold:")
    print(f"  Signals: {len(returns):,}")
    print(f"  Wins: {win_count} ({win_rate*100:.1f}%)")
    print(f"  Losses: {loss_count} ({(1-win_rate)*100:.1f}%)")
    print(f"  Avg Win: {avg_win:+.2%}  |  Avg Loss: {avg_loss:+.2%}  |  Ratio: {win_loss_ratio:.2f}x")
    print(f"  Total P&L: {total_return:+.2%}  |  Per Trade: {avg_return:+.2%}")

    if avg_return != 0:
        trades_for_10pct = 0.10 / abs(avg_return)
        print(f"  Trades for 10% return: {trades_for_10pct:.0f}")
    print()

    results.append({
        'window': window,
        'signals': len(returns),
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'avg_return': avg_return,
        'total_return': total_return
    })

# Apply quality filters
print("="*80)
print("WITH QUALITY FILTERS (Recovery >70% + Wick >55%)")
print("="*80)

quality = strict_signals[
    (strict_signals['recovery_ratio'] > 0.70) &
    (strict_signals['lower_wick_ratio'] > 0.55)
].copy()

print(f"Qualifying signals: {len(quality):,}")

for window in [5, 20]:
    col = f'return_{window}d'
    returns = quality[col].copy()
    returns[quality['hit_6pct_sl']] = -0.06

    wins = returns > 0
    win_rate = wins.sum() / len(returns)
    avg_return = returns.mean()

    print(f"  {window}d: Win rate {win_rate*100:.1f}%, Avg return {avg_return:+.2%}")

# Save
strict_signals.to_csv('support_signals_strict_trend_6psl.csv', index=False)
print(f"\nSaved to: support_signals_strict_trend_6psl.csv")

# Show top trades
print("\nTop winners (20-day hold with 6% SL):")
test_ret = strict_signals['return_20d'].copy()
test_ret[strict_signals['hit_6pct_sl']] = -0.06
strict_signals['return_20d_sl'] = test_ret

top = strict_signals.nlargest(10, 'return_20d_sl')
print(top[['date', 'symbol', 'recovery_ratio', 'lower_wick_ratio', 'return_20d_sl', 'hit_6pct_sl']].to_string(index=False))
