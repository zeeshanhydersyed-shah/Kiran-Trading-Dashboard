import sqlite3

conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

latest = cur.execute('SELECT MAX(date) FROM stock_signals').fetchone()[0]
print('Latest date:', latest)

rows = cur.execute('''
    SELECT ss.symbol, ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
           ss.close_above_ema50, ss.ema50_slope_pos,
           ss.base_tightness, ss.base_duration, ss.near_pivot_days,
           ss.pivot_distance_pct, ss.overhead_clear, ss.stage2_bull,
           sec.sector_stage, sec.sector_pivot_dist_pct, sec.sector_rs_new_high
    FROM stock_signals ss
    JOIN sectors s ON ss.symbol = s.symbol
    LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
    WHERE ss.date = ? AND s.sector = 'TECHNOLOGY & COMMUNICATION'
    ORDER BY ss.rs_rank ASC
''', (latest,)).fetchall()

print(f'Tech stocks on {latest}: {len(rows)}\n')
print(f"{'Symbol':<10} {'RS':>5} {'Chg':>5} {'SecRk':>6} {'E50':>4} {'Slp':>4} {'BBW%':>6} {'BDur':>5} {'NpD':>5} {'PivD%':>6} {'OH':>4} {'S2':>4} {'SecStg':<10} {'SpD':>5} {'SrsNH':>6}")
print('-' * 110)

for r in rows:
    sym, rs, chg, srank, ema50, slope, bbw, bdur, npd, pdist, oh, s2, sstage, spd, srnh = r
    bbw_s   = f"{bbw:.1f}"   if bbw   is not None else "-"
    pdist_s = f"{pdist:.1f}" if pdist is not None else "-"
    spd_s   = f"{spd:.1f}"  if spd   is not None else "-"
    print(f"{sym:<10} {str(rs):>5} {str(chg):>5} {str(srank):>6} {str(ema50):>4} {str(slope):>4} {bbw_s:>6} {str(bdur):>5} {str(npd):>5} {pdist_s:>6} {str(oh):>4} {str(s2):>4} {str(sstage):<10} {spd_s:>5} {str(srnh):>6}")

conn.close()
