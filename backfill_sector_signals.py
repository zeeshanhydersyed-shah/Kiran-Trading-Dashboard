import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime

DB_PATH = r'C:\Users\Lenovo\psx_pipeline\psx_data.db'
START_DATE = '2015-01-01'
END_DATE = '2026-06-11'
EMA_PERIOD = 20
BATCH_SIZE = 60  # trading days per batch

def compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def run_backfill():
    con = sqlite3.connect(DB_PATH)

    print("Loading base data...")

    prices = pd.read_sql_query("""
        SELECT pa.date, pa.symbol, pa.close, pa.volume,
               sm.sector
        FROM prices_adjusted pa
        JOIN stock_metadata sm ON pa.symbol = sm.symbol
        WHERE pa.date >= '2014-01-01'
          AND pa.close IS NOT NULL
          AND pa.close > 0
          AND sm.sector IS NOT NULL
        ORDER BY pa.symbol, pa.date
    """, con)

    kse100 = pd.read_sql_query("""
        SELECT date, close as kse_close
        FROM index_prices
        WHERE symbol = 'KSE-100'
          AND date >= '2014-01-01'
        ORDER BY date
    """, con)

    regime_df = pd.read_sql_query("""
        SELECT date, regime
        FROM market_regime
        WHERE date >= '2015-01-01'
        ORDER BY date
    """, con)

    mcap_df = pd.read_sql_query("""
        SELECT symbol, market_cap_m
        FROM stock_market_cap
    """, con)
    mcap = dict(zip(mcap_df.symbol, mcap_df.market_cap_m))

    active_df = pd.read_sql_query("""
        SELECT symbol, trading_date
        FROM active_stocks_on_date
        WHERE trading_date >= '2015-01-01'
    """, con)
    active_set = set(zip(active_df.symbol, active_df.trading_date))

    print(f"Prices loaded: {len(prices)} rows")
    print(f"KSE-100 loaded: {len(kse100)} rows")
    print(f"Regime loaded: {len(regime_df)} rows")

    print("Pre-computing per-stock EMAs and returns...")

    prices = prices.sort_values(['symbol', 'date'])
    prices['ema20'] = prices.groupby('symbol')['close'].transform(
        lambda x: compute_ema(x, 20)
    )
    prices['prev_close'] = prices.groupby('symbol')['close'].shift(1)
    prices['daily_return'] = (prices['close'] - prices['prev_close']) / prices['prev_close']

    prices['close_20d_ago'] = prices.groupby('symbol')['close'].shift(20)
    prices['close_50d_ago'] = prices.groupby('symbol')['close'].shift(50)
    prices['return_20d'] = (prices['close'] - prices['close_20d_ago']) / prices['close_20d_ago']
    prices['return_50d'] = (prices['close'] - prices['close_50d_ago']) / prices['close_50d_ago']

    prices['vol_20d_avg'] = prices.groupby('symbol')['volume'].transform(
        lambda x: x.rolling(20, min_periods=5).mean()
    )

    kse100 = kse100.sort_values('date')
    kse100['kse_20d_ago'] = kse100['kse_close'].shift(20)
    kse100['kse_50d_ago'] = kse100['kse_close'].shift(50)
    kse100['kse_return_20d'] = (kse100['kse_close'] - kse100['kse_20d_ago']) / kse100['kse_20d_ago']
    kse100['kse_return_50d'] = (kse100['kse_close'] - kse100['kse_50d_ago']) / kse100['kse_50d_ago']
    kse100_dict = kse100.set_index('date')[['kse_return_20d', 'kse_return_50d']].to_dict('index')

    regime_dict = dict(zip(regime_df.date, regime_df.regime))

    prices_analysis = prices[prices['date'] >= START_DATE].copy()

    trading_dates = sorted(prices_analysis['date'].unique())
    trading_dates = [d for d in trading_dates if d <= END_DATE]
    print(f"Trading dates to process: {len(trading_dates)}")

    sectors = sorted(prices['sector'].unique())
    print(f"Sectors: {len(sectors)}")

    all_rows = []
    prev_ranks = {}

    for i, date in enumerate(trading_dates):
        if i % 100 == 0:
            print(f"  Processing {date} ({i}/{len(trading_dates)})...")

        day_data = prices_analysis[prices_analysis['date'] == date]
        kse_ret = kse100_dict.get(date, {})
        kse_ret_20 = kse_ret.get('kse_return_20d', np.nan)
        kse_ret_50 = kse_ret.get('kse_return_50d', np.nan)
        regime = regime_dict.get(date, None)

        sector_rs_scores = {}

        for sector in sectors:
            sector_day = day_data[day_data['sector'] == sector].copy()

            sector_day = sector_day[
                sector_day.apply(
                    lambda r: (r['symbol'], date) in active_set, axis=1
                )
            ]

            if len(sector_day) < 2:
                continue

            weights = sector_day['symbol'].map(mcap)
            if weights.isna().all():
                weights = pd.Series(
                    [1.0 / len(sector_day)] * len(sector_day),
                    index=sector_day.index
                )
            else:
                weights = weights.fillna(weights.mean())
                total = weights.sum()
                if total > 0:
                    weights = weights / total
                else:
                    weights = pd.Series(
                        [1.0 / len(sector_day)] * len(sector_day),
                        index=sector_day.index
                    )

            valid_20 = sector_day['return_20d'].notna()
            valid_50 = sector_day['return_50d'].notna()

            if valid_20.sum() >= 2:
                w20 = weights[valid_20]
                w20 = w20 / w20.sum()
                sector_ret_20 = (sector_day.loc[valid_20, 'return_20d'] * w20).sum()
                rs_20 = (sector_ret_20 - kse_ret_20) * 100 if not np.isnan(kse_ret_20) else np.nan
            else:
                rs_20 = np.nan

            if valid_50.sum() >= 2:
                w50 = weights[valid_50]
                w50 = w50 / w50.sum()
                sector_ret_50 = (sector_day.loc[valid_50, 'return_50d'] * w50).sum()
                rs_50 = (sector_ret_50 - kse_ret_50) * 100 if not np.isnan(kse_ret_50) else np.nan
            else:
                rs_50 = np.nan

            above_ema = (sector_day['close'] > sector_day['ema20']).sum()
            breadth = (above_ema / len(sector_day)) * 100

            advancers = (sector_day['daily_return'] > 0).sum()
            decliners = (sector_day['daily_return'] < 0).sum()
            adr = (advancers / decliners) if decliners > 0 else np.nan

            valid_vol = sector_day['vol_20d_avg'].notna() & (sector_day['vol_20d_avg'] > 0)
            if valid_vol.sum() >= 2:
                vol_today = sector_day.loc[valid_vol, 'volume'].mean()
                vol_avg = sector_day.loc[valid_vol, 'vol_20d_avg'].mean()
                vol_ratio = vol_today / vol_avg if vol_avg > 0 else np.nan
            else:
                vol_ratio = np.nan

            sector_rs_scores[sector] = {
                'rs_score_20': rs_20,
                'rs_score_50': rs_50,
                'breadth_score': breadth,
                'adv_dec_ratio': adr,
                'vol_ratio': vol_ratio,
                'regime': regime,
            }

        valid_sectors = {s: v for s, v in sector_rs_scores.items()
                        if not np.isnan(v['rs_score_20'])}
        ranked = sorted(valid_sectors.keys(),
                       key=lambda s: valid_sectors[s]['rs_score_20'],
                       reverse=True)
        ranks = {s: i+1 for i, s in enumerate(ranked)}

        for sector, vals in sector_rs_scores.items():
            rs_rank = ranks.get(sector, None)
            rs_rank_prev = prev_ranks.get(sector, None)

            rs_infl = 0
            if (rs_rank is not None and rs_rank_prev is not None
                    and rs_rank < rs_rank_prev
                    and vals['rs_score_20'] is not None
                    and vals['rs_score_20'] > 0):
                rs_infl = 1

            all_rows.append({
                'date': date,
                'sector': sector,
                'rs_score_20': vals['rs_score_20'],
                'rs_score_50': vals['rs_score_50'],
                'rs_rank': rs_rank,
                'rs_rank_prev': rs_rank_prev,
                'breadth_score': vals['breadth_score'],
                'adv_dec_ratio': vals['adv_dec_ratio'],
                'vol_ratio': vals['vol_ratio'],
                'rs_inflection': rs_infl,
                'regime': vals['regime'],
                'composite_score': None,
            })

        prev_ranks = ranks

        if (i + 1) % BATCH_SIZE == 0 or i == len(trading_dates) - 1:
            if all_rows:
                batch_df = pd.DataFrame(all_rows)
                batch_df.to_sql('sector_signals', con, if_exists='append',
                               index=False, method='multi')
                print(f"    Wrote {len(all_rows)} rows to DB")
                all_rows = []

    print("Computing composite scores...")

    signals = pd.read_sql_query("""
        SELECT rowid, date, sector, rs_score_20, breadth_score, vol_ratio
        FROM sector_signals
    """, con)

    def minmax_norm(series):
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series([0.5] * len(series), index=series.index)
        return (series - mn) / (mx - mn)

    signals['rs_norm'] = signals.groupby('date')['rs_score_20'].transform(minmax_norm)
    signals['br_norm'] = signals.groupby('date')['breadth_score'].transform(minmax_norm)
    signals['vr_norm'] = signals.groupby('date')['vol_ratio'].transform(minmax_norm)

    signals['composite_score'] = (
        signals['rs_norm'] * 0.5 +
        signals['br_norm'] * 0.3 +
        signals['vr_norm'] * 0.2
    ).round(4)

    cur = con.cursor()
    for _, row in signals.iterrows():
        cur.execute("""
            UPDATE sector_signals
            SET composite_score = ?
            WHERE date = ? AND sector = ?
        """, (row['composite_score'], row['date'], row['sector']))
    con.commit()
    print("Composite scores updated.")

    print("\n=== FINAL VERIFICATION ===")

    cur.execute("SELECT COUNT(*) FROM sector_signals")
    print(f"Total rows: {cur.fetchone()[0]}")

    cur.execute("SELECT COUNT(DISTINCT date) FROM sector_signals")
    print(f"Distinct dates: {cur.fetchone()[0]}")

    cur.execute("SELECT COUNT(DISTINCT sector) FROM sector_signals")
    print(f"Distinct sectors: {cur.fetchone()[0]}")

    cur.execute("SELECT MIN(date), MAX(date) FROM sector_signals")
    print(f"Date range: {cur.fetchone()}")

    cur.execute("""
        SELECT COUNT(*) FROM sector_signals
        WHERE composite_score IS NOT NULL
    """)
    print(f"Rows with composite_score: {cur.fetchone()[0]}")

    cur.execute("""
        SELECT sector, ROUND(AVG(rs_score_20),2) as avg_rs,
               ROUND(AVG(breadth_score),1) as avg_breadth
        FROM sector_signals
        WHERE date >= '2025-01-01'
        GROUP BY sector
        ORDER BY avg_rs DESC
        LIMIT 5
    """)
    print("\nTop 5 sectors by avg RS (2025-present):")
    for row in cur.fetchall():
        print(f"  {row}")

    con.close()
    print("\nBackfill complete.")

if __name__ == '__main__':
    run_backfill()
