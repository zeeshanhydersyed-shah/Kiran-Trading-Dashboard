#!/usr/bin/env python3
"""
Fast Support Pattern Research - Local
Uses aggressive filtering to complete in <2 minutes
"""

import pandas as pd
import numpy as np
import sys
from datetime import datetime
from support_research import SupportDetector, SignalAnalyzer

def main():
    print("=" * 80)
    print("SUPPORT PATTERN RESEARCH - FAST MODE")
    print("=" * 80)

    # Load data
    print("\n[LOAD] Reading price data...")
    df = pd.read_csv('merged_psx_data.csv')
    print(f"[OK] Loaded {len(df):,} records, {df['symbol'].nunique()} symbols")

    # FILTER TO TOP SYMBOLS BY VOLUME (speed optimization)
    print("\n[FILTER] Selecting top 100 symbols by volume...")
    top_100 = df.groupby('symbol')['volume'].sum().nlargest(100).index.tolist()
    df = df[df['symbol'].isin(top_100)].reset_index(drop=True)
    print(f"[OK] Reduced to {len(df):,} records, {len(top_100)} symbols")

    # FILTER TO RECENT DATA (2024+)
    print("[FILTER] Using 2024+ data only...")
    df = df[df['date'] >= '2024-01-01'].reset_index(drop=True)
    print(f"[OK] {len(df):,} records in 2024-2026")

    # Detect support patterns (FAST MODE: higher tolerance = fewer signals)
    print("\n[DETECT] Finding support patterns (tolerance=1.5, strict filtering)...")
    detector = SupportDetector(df, lookback=60)
    signals = detector.generate_signals(tolerance_factor=1.5)  # Higher = fewer touches

    print(f"[OK] Generated {len(signals):,} support signals")

    if len(signals) < 100:
        print("[WARN] Very few signals detected. Results may not be meaningful.")

    # Forward test
    print("\n[TEST] Forward testing signals...")
    analyzer = SignalAnalyzer(signals, df)
    signals = analyzer.forward_test(signals)
    sig_df = analyzer.to_dataframe(signals)

    # Results
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)

    print(f"\nTotal signals: {len(sig_df):,}")
    print(f"With 5d return: {sig_df['return_5d'].notna().sum():,}")
    print(f"With 10d return: {sig_df['return_10d'].notna().sum():,}")

    # By support source
    print("\n[WIN RATES] By Support Definition")
    print("-" * 80)
    perf_source = analyzer.win_rate_by_source(sig_df)
    if len(perf_source) > 0:
        print(perf_source.to_string(index=False))
    else:
        print("No data")

    # By trend
    print("\n[TREND] Win Rate by Trend Context")
    print("-" * 80)
    perf_trend = analyzer.win_rate_by_trend(sig_df)
    if len(perf_trend) > 0:
        print(perf_trend.to_string(index=False))
    else:
        print("No data")

    # Winners vs losers
    print("\n[METRICS] Winners vs Losers")
    print("-" * 80)
    winners = sig_df[sig_df['return_5d'] > 0]
    losers = sig_df[sig_df['return_5d'] <= 0]

    if len(winners) > 0 and len(losers) > 0:
        print(f"Winners: {len(winners)} ({len(winners)/len(sig_df)*100:.1f}%)")
        print(f"  Avg recovery ratio: {winners['recovery_ratio'].mean():.3f}")
        print(f"  Avg lower wick: {winners['lower_wick_ratio'].mean():.3f}")
        print(f"  Avg return 5d: {winners['return_5d'].mean():+.2%}")
        print(f"\nLosers: {len(losers)} ({len(losers)/len(sig_df)*100:.1f}%)")
        print(f"  Avg recovery ratio: {losers['recovery_ratio'].mean():.3f}")
        print(f"  Avg lower wick: {losers['lower_wick_ratio'].mean():.3f}")
        print(f"  Avg return 5d: {losers['return_5d'].mean():+.2%}")

    # Save
    output_file = f"support_signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    sig_df.to_csv(output_file, index=False)
    print(f"\n[SAVE] Signals saved to: {output_file}")

    # Show sample
    print("\n[SAMPLE] Top 10 winners (by 5d return):")
    print("-" * 80)
    winners_sorted = sig_df[sig_df['return_5d'].notna()].nlargest(10, 'return_5d')
    print(winners_sorted[['date', 'symbol', 'support_source', 'recovery_ratio', 'return_5d', 'return_10d']].to_string(index=False))

if __name__ == '__main__':
    main()
