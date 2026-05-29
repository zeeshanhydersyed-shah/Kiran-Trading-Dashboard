#!/usr/bin/env python3
"""
Redefine trend: 50SMA sloping higher for last 5 days
Add hard stop loss: 6% max risk
"""

import pandas as pd
import numpy as np

print("[LOAD] Loading signals and price data...")
signals = pd.read_csv('support_signals_full.csv')
prices = pd.read_csv('merged_psx_data.csv')

print(f"Signals: {len(signals):,}")
print(f"Prices: {len(prices):,}")

# Pre-calculate SMA slopes for all symbols
print("\n[CALCULATE] Computing 50SMA slopes for all symbols...")

sma_lookup = {}
for symbol in prices['symbol'].unique():
    sym_prices = prices[prices['symbol'] == symbol].copy()
    sym_prices['date'] = pd.to_datetime(sym_prices['date'])
    sym_prices = sym_prices.sort_values('date').reset_index(drop=True)
    sym_prices['sma50'] = sym_prices['close'].rolling(50, min_periods=1).mean()

    # Build lookup: date -> (is_rising_sma, current_sma)
    sma_lookup[symbol] = {}
    for i in range(5, len(sym_prices)):
        date = str(sym_prices.iloc[i]['date'].date())
        sma_last5 = sym_prices.iloc[i-5:i]['sma50'].values
        is_rising = all(sma_last5[j] < sma_last5[j+1] for j in range(4))
        current_sma = sym_prices.iloc[i]['sma50']
        sma_lookup[symbol][date] = (is_rising, current_sma)

print(f"[OK] Pre-calculated SMA slopes for {len(sma_lookup)} symbols")

# Apply trend filter (fast lookup)
print("Filtering signals with rising SMA trend...")
signals['has_rising_sma'] = signals.apply(
    lambda row: sma_lookup.get(row['symbol'], {}).get(row['date'], (False, np.nan))[0],
    axis=1
)

signals_rising_sma = signals[signals['has_rising_sma']].reset_index(drop=True)
print(f"[OK] {len(signals_rising_sma):,} signals have rising 50-SMA ({len(signals_rising_sma)/len(signals)*100:.1f}%)")

# Apply hard SL filter: 6% max risk
print("\nApplying 6% hard stop loss filter...")

# Entry = support_level (we touch and bounce from here)
# Hard SL = entry - (entry * 0.06)
# If price goes below that, trade is stopped out with 6% loss

signals_rising_sma['entry'] = signals_rising_sma['support_level']
signals_rising_sma['hard_sl'] = signals_rising_sma['entry'] * (1 - 0.06)
signals_rising_sma['max_loss'] = -0.06

# Calculate if trade would hit hard SL
signals_rising_sma['hit_hard_sl'] = signals_rising_sma['max_adverse'] < -0.06

print(f"Trades that hit 6% SL: {signals_rising_sma['hit_hard_sl'].sum():,} ({signals_rising_sma['hit_hard_sl'].sum()/len(signals_rising_sma)*100:.1f}%)")

print("\n" + "="*80)
print("RESULTS: Rising SMA Trend + 6% Hard SL")
print("="*80)

# Backtest at different timeframes
for window in [5, 10, 20]:
    col = f'return_{window}d'

    # For trades that hit SL, cap return at -6%
    test_returns = signals_rising_sma[col].copy()
    test_returns[signals_rising_sma['hit_hard_sl']] = -0.06

    winners = test_returns > 0
    losers = test_returns <= 0

    total_return = test_returns.sum()
    avg_return = test_returns.mean()

    print(f"\n{window}-Day Backtest:")
    print(f"  Total signals: {len(signals_rising_sma):,}")
    print(f"  Winning trades: {winners.sum()} ({winners.sum()/len(test_returns)*100:.1f}%)")
    print(f"  Losing trades: {losers.sum()} ({losers.sum()/len(test_returns)*100:.1f}%)")

    if winners.sum() > 0 and losers.sum() > 0:
        avg_win = test_returns[winners].mean()
        avg_loss = test_returns[losers].mean()
        print(f"  Average win: {avg_win:+.2%}")
        print(f"  Average loss: {avg_loss:+.2%}")
        print(f"  Win/loss ratio: {abs(avg_win / avg_loss):.2f}x")

    print(f"  Total P&L: {total_return:+.2%}")
    print(f"  Average P&L per trade: {avg_return:+.2%}")

    if avg_return != 0:
        trades_for_10pct = 0.10 / abs(avg_return)
        print(f"  Trades needed for 10% gain: {trades_for_10pct:.0f}")

# Filter for best metrics
print("\n" + "="*80)
print("FILTER FOR HIGHEST QUALITY SETUPS")
print("="*80)

quality = signals_rising_sma[
    (signals_rising_sma['recovery_ratio'] > 0.70) &
    (signals_rising_sma['lower_wick_ratio'] > 0.55)
].reset_index(drop=True)

print(f"\nWith recovery >70% + wick >55%: {len(quality):,} signals")

if len(quality) > 0:
    for window in [5, 20]:
        col = f'return_{window}d'
        test_returns = quality[col].copy()
        test_returns[quality['hit_hard_sl']] = -0.06

        winners = test_returns > 0
        avg_return = test_returns.mean()

        print(f"  {window}d: {winners.sum()}/{len(quality)} wins ({winners.sum()/len(quality)*100:.1f}%), Avg: {avg_return:+.2%}")

# Save
final_df = signals_rising_sma.copy()
final_df.to_csv('support_signals_rising_sma_6psl.csv', index=False)
print(f"\n[SAVE] support_signals_rising_sma_6psl.csv ({len(final_df):,} rows)")

# Sample trades
print("\nSample winning trades (20d):")
test_ret = final_df['return_20d'].copy()
test_ret[final_df['hit_hard_sl']] = -0.06
final_df['return_20d_with_sl'] = test_ret

winners_sample = final_df[final_df['return_20d_with_sl'] > 0].nlargest(10, 'return_20d_with_sl')
print(winners_sample[['date', 'symbol', 'recovery_ratio', 'lower_wick_ratio', 'return_20d_with_sl', 'hit_hard_sl']].to_string(index=False))
