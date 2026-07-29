import sqlite3

conn = sqlite3.connect('psx_data.db')

# First - when did COMMERCIAL BANKS enter Stage 2?
print("=== COMMERCIAL BANKS sector stage history ===")
stage_hist = conn.execute("""
    SELECT date, sector_stage, sector_pivot_dist_pct, rs_rank, rs_score_20, sector_rs_new_high
    FROM sector_signals
    WHERE sector = 'COMMERCIAL BANKS'
    AND date BETWEEN '2024-01-01' AND '2025-06-01'
    ORDER BY date ASC
""").fetchall()

prev_stage = None
for r in stage_hist:
    date, stage, spd, srank, rs20, srnh = r
    if stage != prev_stage or srnh == 1:
        spd_s = f"{spd:.1f}" if spd else "-"
        rs20_s = f"{rs20:.1f}" if rs20 else "-"
        marker = " <-- STAGE CHANGE" if stage != prev_stage else ""
        print(f"  {date}  {str(stage):<12}  pivot_dist={spd_s:>5}%  rs_rank={str(srank):<4}  rs20={rs20_s:>6}  rs_nh={srnh}{marker}")
        prev_stage = stage

# Now check every bank stock gate by gate during early Stage 2
print("\n=== BANK STOCKS — gate-by-gate during early Stage 2 (2024-06 to 2025-03) ===")

bank_stocks = [r[0] for r in conn.execute("""
    SELECT DISTINCT symbol FROM sectors WHERE sector = 'COMMERCIAL BANKS'
""").fetchall()]
print(f"Bank symbols: {bank_stocks}\n")

# Check monthly for each bank
check_dates = [r[0] for r in conn.execute("""
    SELECT DISTINCT date FROM stock_signals
    WHERE date BETWEEN '2024-06-01' AND '2025-04-01'
    ORDER BY date ASC
""").fetchall()]

# Sample every ~20 trading days
check_dates = check_dates[::20]

print(f"{'Date':<12} {'Symbol':<8} {'SecStg':<10} {'SecPivD':>8} {'SecNH':>6} {'E50':>4} {'Slp':>4} {'RsChg':>6} {'SecRk':>6} {'NpD':>5} {'PivD':>6}  FAIL")
print('-'*120)

for d in check_dates:
    rows = conn.execute("""
        SELECT ss.symbol, ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
               ss.close_above_ema50, ss.ema50_slope_pos,
               ss.near_pivot_days, ss.pivot_distance_pct,
               sec.sector_stage, sec.sector_pivot_dist_pct, sec.sector_rs_new_high
        FROM stock_signals ss
        JOIN sectors s ON ss.symbol = s.symbol
        LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
        WHERE ss.date = ? AND s.sector = 'COMMERCIAL BANKS'
        ORDER BY ss.sector_rs_rank ASC
    """, (d,)).fetchall()

    for r in rows:
        sym, rs, chg, srank, ema50, slope, npd, pdist, sstage, spd, srnh = r
        fails = []
        if sstage != 'Stage 2': fails.append('sec_stage')
        if spd is None or spd > 10: fails.append('sec_early')
        if srnh != 1: fails.append('sec_rs_nh')
        if ema50 != 1: fails.append('ema50')
        if slope != 1: fails.append('slope')
        if chg is None or chg <= 0: fails.append('rs_chg')
        if srank is None or srank > 3: fails.append(f'sec_top3(rank={srank})')
        if npd is None or npd < 10: fails.append(f'npd={npd}')
        if pdist is None or not (0 <= pdist <= 5): fails.append(f'piv={round(pdist,1) if pdist else None}')

        # Only print if 2 or fewer failures (near misses) or full pass
        if len(fails) <= 3:
            spd_s = f"{spd:.1f}" if spd else "-"
            pdist_s = f"{pdist:.1f}" if pdist else "-"
            print(f"{d:<12} {sym:<8} {str(sstage):<10} {spd_s:>8} {str(srnh):>6} {str(ema50):>4} {str(slope):>4} {str(chg):>6} {str(srank):>6} {str(npd):>5} {pdist_s:>6}  {fails}")

conn.close()
