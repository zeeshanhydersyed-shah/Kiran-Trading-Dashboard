#!/usr/bin/env python3
"""
Local Support Pattern Research Runner
Analyzes all 2020-2026 data with all support definitions.
No Cloud timeout issues.
"""

import pandas as pd
import numpy as np
import sys
from datetime import datetime
from support_research import SupportDetector, SignalAnalyzer

def main():
    print("=" * 80)
    print("SUPPORT PATTERN RESEARCH - LOCAL ANALYSIS")
    print("=" * 80)

    # Load data
    print("\n[LOAD] Reading price data...")
    try:
        df = pd.read_csv('merged_psx_data.csv')
        print(f"[OK] Loaded {len(df):,} records, {df['symbol'].nunique()} symbols")
        print(f"     Date range: {df['date'].min()} to {df['date'].max()}")
    except FileNotFoundError:
        print("[ERROR] merged_psx_data.csv not found in current directory")
        sys.exit(1)

    # Detect support patterns
    print("\n[DETECT] Finding support patterns...")
    detector = SupportDetector(df, lookback=60)
    signals = detector.generate_signals(tolerance_factor=1.0)
    print(f"[OK] Generated {len(signals):,} support signals")

    if len(signals) == 0:
        print("[WARN] No signals detected. Try adjusting tolerance or data range.")
        sys.exit(1)

    # Forward test
    print("\n[TEST] Forward testing signals (calculating returns)...")
    analyzer = SignalAnalyzer(signals, df)
    signals = analyzer.forward_test(signals)
    print(f"[OK] Completed forward testing")

    # Convert to DataFrame
    print("\n[ANALYZE] Processing results...")
    sig_df = analyzer.to_dataframe(signals)

    # Results summary
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)

    print(f"\n[STATS] Total signals analyzed: {len(sig_df):,}")
    print(f"        Signals with 5d return: {sig_df['return_5d'].notna().sum():,}")
    print(f"        Signals with 10d return: {sig_df['return_10d'].notna().sum():,}")
    print(f"        Signals with 20d return: {sig_df['return_20d'].notna().sum():,}")

    # By support source
    print("\n[WIN RATES] By Support Definition")
    print("-" * 80)
    perf_by_source = analyzer.win_rate_by_source(sig_df)
    print(perf_by_source.to_string(index=False))

    # By trend
    print("\n[TREND ANALYSIS] Win Rate by Trend Context")
    print("-" * 80)
    perf_by_trend = analyzer.win_rate_by_trend(sig_df)
    print(perf_by_trend.to_string(index=False))

    # Metric clusters
    print("\n[WINNERS] Metric Comparison")
    print("-" * 80)
    winners = sig_df[sig_df['return_5d'] > 0]
    losers = sig_df[sig_df['return_5d'] <= 0]

    if len(winners) > 0 and len(losers) > 0:
        metric_comparison = pd.DataFrame({
            'Metric': [
                'Lower Wick Ratio',
                'Close Position',
                'Recovery Ratio',
                'Body Ratio',
                'Volume MA Ratio',
                'Avg Return 5d'
            ],
            'Winners': [
                f"{winners['lower_wick_ratio'].mean():.3f}",
                f"{winners['close_position'].mean():.3f}",
                f"{winners['recovery_ratio'].mean():.3f}",
                f"{winners['body_ratio'].mean():.3f}",
                f"{winners['volume_ma_ratio'].mean():.2f}x",
                f"{winners['return_5d'].mean():+.2%}",
            ],
            'Losers': [
                f"{losers['lower_wick_ratio'].mean():.3f}",
                f"{losers['close_position'].mean():.3f}",
                f"{losers['recovery_ratio'].mean():.3f}",
                f"{losers['body_ratio'].mean():.3f}",
                f"{losers['volume_ma_ratio'].mean():.2f}x",
                f"{losers['return_5d'].mean():+.2%}",
            ]
        })
        print(metric_comparison.to_string(index=False))

    # Save results
    output_file = f"support_signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    sig_df.to_csv(output_file, index=False)
    print(f"\n[SAVE] Signal table saved to: {output_file}")
    print(f"       ({len(sig_df):,} rows x {len(sig_df.columns)} columns)")

    # Summary statistics
    print("\n" + "=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print(f"""
1. Open {output_file} in Excel or Python

2. Filter for winning patterns:
   - Filter to uptrend signals (trend_state = 'uptrend')
   - Filter to recovery_ratio > 0.70 (strong intraday recovery)
   - Filter to lower_wick_ratio > 0.50 (significant rejection tail)
   - Sort by return_5d descending

3. Identify best support definition:
   - Group by 'support_source'
   - Which has highest win rate AND positive expectancy?

4. Test top combinations:
   - Run backtest with best filters
   - Apply 1% risk rule (entry_price, stop_price provided)
   - Calculate Sharpe, max drawdown, win rate

5. Out-of-sample validation:
   - Hold out 2026 data
   - Test discovered rules on fresh signals
""")

if __name__ == '__main__':
    main()
