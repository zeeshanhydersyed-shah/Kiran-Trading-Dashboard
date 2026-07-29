import sqlite3
import pandas as pd

conn = sqlite3.connect('psx_data.db')

# First: find KSE-100 index history to identify early Stage 2 entry points
# Use sector_signals for KSE breadth/stage context
# Let's check a range of dates and run the screen on each

# Key dates to test - pick quarterly snapshots over last 2 years
# We want dates when market was early in Stage 2, not extended
test_dates_query = """
    SELECT DISTINCT date FROM stock_signals
    WHERE date BETWEEN '2024-01-01' AND '2026-06-01'
    AND strftime('%d', date) BETWEEN '01' AND '05'
    ORDER BY date ASC
"""
test_dates = [r[0] for r in conn.execute(test_dates_query).fetchall()]
# Pick first trading date of each month
monthly = {}
for d in test_dates:
    ym = d[:7]
    if ym not in monthly:
        monthly[ym] = d
test_dates = sorted(monthly.values())
print(f"Testing {len(test_dates)} monthly snapshots\n")

results = []

for screen_date in test_dates:
    rows = conn.execute('''
        SELECT ss.symbol, s.sector, ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
               ss.close_above_ema50, ss.ema50_slope_pos,
               ss.near_pivot_days, ss.pivot_distance_pct, ss.overhead_clear,
               sec.sector_stage, sec.sector_pivot_dist_pct, sec.sector_rs_new_high,
               p.close AS entry_close
        FROM stock_signals ss
        JOIN sectors s ON ss.symbol = s.symbol
        LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
        LEFT JOIN prices p ON p.symbol = ss.symbol AND p.date = ss.date
        WHERE ss.date = ?
    ''', (screen_date,)).fetchall()

    hits = []
    for r in rows:
        sym, sector, rs, chg, srank, ema50, slope, npd, pdist, oh, sstage, spd, srnh, entry = r
        passes = (
            sstage == 'Stage 2' and
            spd is not None and spd <= 10 and
            srnh == 1 and
            ema50 == 1 and
            slope == 1 and
            chg is not None and chg > 0 and
            srank is not None and srank <= 3 and
            npd is not None and npd >= 10 and
            pdist is not None and 0 <= pdist <= 5
        )
        if passes:
            hits.append((sym, sector, rs, entry))

    results.append((screen_date, len(hits), hits))
    if hits:
        print(f"{screen_date}: {len(hits)} hits — {[h[0] for h in hits]}")
    else:
        print(f"{screen_date}: 0 hits")

conn.close()
