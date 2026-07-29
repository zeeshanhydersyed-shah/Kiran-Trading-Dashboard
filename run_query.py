import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('psx_data.db')
rows = conn.execute("""
SELECT ss.symbol, sm.sector,
       ss.rs_rank, ss.sector_rs_rank,
       ss.rs_score_20, ss.rs_score_50,
       ss.rank_change,
       ss.base_tightness,
       ss.vol_contraction,
       ss.avg_vol_10d,
       ss.pivot_high,
       ss.pivot_distance_pct,
       ss.bos_flag,
       pa.close
FROM stock_signals ss
JOIN stock_metadata sm ON ss.symbol = sm.symbol
JOIN prices_adjusted pa ON ss.symbol = pa.symbol AND ss.date = pa.date
WHERE ss.date = '2026-06-11'
  AND ss.symbol = 'MEBL'
""").fetchall()

cols = ["symbol","sector","rs_rank","sector_rs_rank","rs_score_20","rs_score_50",
        "rank_change","base_tightness","vol_contraction","avg_vol_10d",
        "pivot_high","pivot_distance_pct","bos_flag","close"]

print(f"Rows returned: {len(rows)}")
for row in rows:
    for col, val in zip(cols, row):
        print(f"  {col:<22}: {val}")
conn.close()
