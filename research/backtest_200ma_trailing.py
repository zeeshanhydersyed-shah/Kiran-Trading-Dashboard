#!/usr/bin/env python3
"""
200-MA trend filter
Trailing stop (instead of hard 6% SL)
30+ day hold
"""

import pandas as pd
import numpy as np

signals = pd.read_csv('support_signals_full.csv')
prices = pd.read_csv('merged_psx_data.csv')

print("="*80)
print("NEW SETUP: 200-MA Trend + Trailing Stop + 30+ Day Hold")
print("="*80)

# Calculate 200-MA for each signal
print("\n[CALCULATE] Computing 200-MA trend...")

def get_200ma_trend(symbol, date, prices_df):
    """Check if price > 200-MA and trend is uptrend"""
    sym_prices = prices_df[prices_df['symbol'] == symbol].copy()
    sym_prices['date'] = pd.to_datetime(sym_prices['date'])
    sym_prices = sym_prices.sort_values('date').reset_index(drop=True)

    sym_prices['ma200'] = sym_prices['close'].rolling(200, min_periods=1).mean()

    signal_date = pd.to_datetime(date)
    signal_row = sym_prices[sym_prices['date'] == signal_date]

    if len(signal_row) == 0:
        return False

    c = signal_row.iloc[0]['close']
    ma200 = signal_row.iloc[0]['ma200']

    # Uptrend: close > 200-MA × 1.01
    return c > ma200 * 1.01 if pd.notna(ma200) else False

# Pre-calculate for speed
print("Pre-calculating 200-MA for all symbols...")
ma200_lookup = {}
for symbol in prices['symbol'].unique():
    sym_prices = prices[prices['symbol'] == symbol].copy()
    sym_prices['date'] = pd.to_datetime(sym_prices['date'])
    sym_prices = sym_prices.sort_values('date').reset_index(drop=True)
    sym_prices['ma200'] = sym_prices['close'].rolling(200, min_periods=1).mean()

    ma200_lookup[symbol] = {}
    for _, row in sym_prices.iterrows():
        date = str(row['date'].date())
        c = row['close']
        ma200 = row['ma200']
        is_uptrend = c > ma200 * 1.01 if pd.notna(ma200) else False
        ma200_lookup[symbol][date] = (is_uptrend, ma200)

print(f"[OK] Pre-calculated for {len(ma200_lookup)} symbols")

# Filter to 200-MA uptrend
print("\nFiltering to 200-MA uptrend...")
signals['uptrend_200ma'] = signals.apply(
    lambda row: ma200_lookup.get(row['symbol'], {}).get(row['date'], (False, np.nan))[0],
    axis=1
)

uptrend_200 = signals[signals['uptrend_200ma']].reset_index(drop=True)
print(f"[OK] {len(uptrend_200):,} signals qualify for 200-MA uptrend")

# Test with trailing stop instead of hard 6% SL
print("\nTesting with trailing stop (2% trail)...\n")

print("="*80)
print("BACKTEST: 200-MA + Trailing 2% Stop")
print("="*80)

for window in [20, 30]:
    col = f'return_{window}d'
    if col not in uptrend_200.columns:
        print(f"Note: {col} not available, using return_20d")
        col = 'return_20d'

    returns = uptrend_200[col].copy()

    # Trailing stop: if max_favorable (peak) was X%, trail stop by 2%
    # So if price went up 10%, trail stop is at +8% (10% - 2%)
    # If price went up 3%, trail stop is at +1% (but hard floor at -2%)
    trailing_returns = uptrend_200['max_favorable'].copy()
    trailing_returns = trailing_returns - 0.02  # Trail by 2%

    # If trailing stop would be worse than max loss, use actual return
    # (price might have recovered after dip)
    final_returns = np.maximum(trailing_returns, returns)

    # But cap losses at -6% hard SL as fallback
    final_returns[final_returns < -0.06] = -0.06

    wins = final_returns > 0
    losses = final_returns <= 0

    win_count = wins.sum()
    loss_count = losses.sum()
    win_rate = win_count / len(final_returns)

    avg_win = final_returns[wins].mean() if win_count > 0 else 0
    avg_loss = final_returns[losses].mean() if loss_count > 0 else 0
    avg_return = final_returns.mean()

    rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    print(f"\n{window}-Day Hold (Trailing 2% stop):")
    print(f"  Signals: {len(final_returns):,}")
    print(f"  Win rate: {win_rate*100:.1f}% ({win_count} wins)")
    print(f"  Avg Win: {avg_win:+.2%}  |  Avg Loss: {avg_loss:+.2%}")
    print(f"  Risk:Reward: {rr:.2f}x")
    print(f"  Expectancy: {avg_return:+.2%}")
    print(f"  >>> Compare to your 3.36%: {'BETTER' if avg_return*100 > 3.36 else 'WORSE'}")

# Apply quality filters
print("\n" + "="*80)
print("WITH QUALITY FILTERS")
print("="*80)

quality = uptrend_200[
    (uptrend_200['recovery_ratio'] > 0.70) &
    (uptrend_200['lower_wick_ratio'] > 0.55)
].copy()

print(f"Signals: {len(quality):,}\n")

for window in [20, 30]:
    col = f'return_{window}d'
    if col not in quality.columns:
        col = 'return_20d'

    returns = quality[col].copy()
    trailing_returns = quality['max_favorable'].copy() - 0.02
    final_returns = np.maximum(trailing_returns, returns)
    final_returns[final_returns < -0.06] = -0.06

    wins = final_returns > 0
    win_rate = wins.sum() / len(final_returns)
    avg_win = final_returns[wins].mean() if wins.sum() > 0 else 0
    avg_loss = final_returns[~wins].mean() if (~wins).sum() > 0 else 0
    avg_return = final_returns.mean()

    rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    print(f"{window}d: Signals {len(quality)}, Win rate {win_rate*100:.1f}%, "
          f"Expectancy {avg_return:+.2%}, R:R {rr:.2f}x")

# Ultra strict
print("\n" + "="*80)
print("ULTRA-STRICT (Recovery >75% + Wick >60%)")
print("="*80)

ultra = uptrend_200[
    (uptrend_200['recovery_ratio'] > 0.75) &
    (uptrend_200['lower_wick_ratio'] > 0.60)
].copy()

print(f"Signals: {len(ultra):,}\n")

for window in [20, 30]:
    col = f'return_{window}d'
    if col not in ultra.columns:
        col = 'return_20d'

    returns = ultra[col].copy()
    trailing_returns = ultra['max_favorable'].copy() - 0.02
    final_returns = np.maximum(trailing_returns, returns)
    final_returns[final_returns < -0.06] = -0.06

    wins = final_returns > 0
    win_rate = wins.sum() / len(final_returns)
    avg_win = final_returns[wins].mean() if wins.sum() > 0 else 0
    avg_loss = final_returns[~wins].mean() if (~wins).sum() > 0 else 0
    avg_return = final_returns.mean()

    rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    print(f"{window}d: Signals {len(ultra)}, Win rate {win_rate*100:.1f}%, "
          f"Expectancy {avg_return:+.2%}, R:R {rr:.2f}x")

print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"\nYour current system: 3.36% expectancy, 1.72x R:R")
print(f"\nThis system (200-MA + trailing stop, best case):")
print(f"  Can it beat 3.36%? Check results above")
print(f"  Signal volume: {len(uptrend_200):,} total, {len(ultra):,} ultra-strict")
