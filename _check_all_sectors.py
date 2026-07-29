import sqlite3

conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

latest = cur.execute('SELECT MAX(date) FROM stock_signals').fetchone()[0]
print('Latest date:', latest)

# First check all sectors' current state
print("\n=== SECTOR DASHBOARD ===")
sec_rows = cur.execute('''
    SELECT sector, sector_stage, sector_pivot_dist_pct, rs_rank, rs_score_20, sector_rs_new_high
    FROM sector_signals
    WHERE date = ?
    ORDER BY rs_rank ASC
''', (latest,)).fetchall()

print(f"{'Sector':<35} {'Stage':<10} {'PivDist':>8} {'RS Rank':>8} {'RS20':>8} {'RS_NH':>6}")
print('-'*80)
for r in sec_rows:
    sector, stage, spd, srank, rs20, srnh = r
    spd_s = f"{spd:.1f}" if spd is not None else "-"
    rs20_s = f"{rs20:.1f}" if rs20 is not None else "-"
    print(f"{str(sector):<35} {str(stage):<10} {spd_s:>8} {str(srank):>8} {rs20_s:>8} {str(srnh):>6}")

# Now full Weinstein screen - all stocks
print("\n\n=== FULL WEINSTEIN SCREEN (all gates) ===")
all_rows = cur.execute('''
    SELECT ss.symbol, s.sector, ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
           ss.close_above_ema50, ss.ema50_slope_pos,
           ss.near_pivot_days, ss.pivot_distance_pct, ss.overhead_clear,
           sec.sector_stage, sec.sector_pivot_dist_pct, sec.sector_rs_new_high
    FROM stock_signals ss
    JOIN sectors s ON ss.symbol = s.symbol
    LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
    WHERE ss.date = ?
    ORDER BY ss.rs_rank ASC
''', (latest,)).fetchall()

passes = []
for r in all_rows:
    sym, sector, rs, chg, srank, ema50, slope, npd, pdist, oh, sstage, spd, srnh = r
    checks = {
        'sec_stage2':    sstage == 'Stage 2',
        'sec_early':     spd is not None and spd <= 10,
        'sec_rs_nh':     srnh == 1,
        'ema50':         ema50 == 1,
        'slope':         slope == 1,
        'rs_improving':  chg is not None and chg > 0,
        'sec_top3':      srank is not None and srank <= 3,
        'near_pivot':    npd is not None and npd >= 10,
        'piv_dist':      pdist is not None and 0 <= pdist <= 5,
    }
    n_pass = sum(checks.values())
    passes.append((sym, sector, rs, chg, srank, ema50, slope, npd, pdist, sstage, spd, srnh, checks, n_pass))

full_pass = [p for p in passes if p[13] == 9]
print(f"Full pass (all 9 gates): {len(full_pass)}")
for p in full_pass:
    print(f"  {p[0]} ({p[1]}) RS={p[2]}")

# Show stocks passing 7 or 8 gates - near misses
print("\n=== NEAR MISSES (7-8 gates passing) ===")
near_miss = [p for p in passes if p[13] in (7, 8)]
near_miss.sort(key=lambda x: -x[13])
for p in near_miss:
    sym, sector, rs, chg, srank, ema50, slope, npd, pdist, sstage, spd, srnh, checks, n = p
    failing = [k for k,v in checks.items() if not v]
    print(f"  {sym:<10} ({sector[:25]:<25}) RS={str(rs):<5} NpD={str(npd):<4} PivD={str(round(pdist,1) if pdist else '-'):<6} Pass={n}/9  FAIL: {failing}")

# Show what gates are most commonly blocking
print("\n=== GATE FAILURE FREQUENCY (across all Stage 2 sector stocks) ===")
stage2_stocks = [p for p in passes if p[9] == 'Stage 2']
print(f"Total stocks in Stage 2 sectors: {len(stage2_stocks)}")
gate_fails = {}
for p in stage2_stocks:
    for gate, passed in p[12].items():
        if not passed:
            gate_fails[gate] = gate_fails.get(gate, 0) + 1
for gate, cnt in sorted(gate_fails.items(), key=lambda x: -x[1]):
    pct = cnt / len(stage2_stocks) * 100
    print(f"  {gate:<20}: {cnt:>4} stocks failing ({pct:.0f}%)")

conn.close()
