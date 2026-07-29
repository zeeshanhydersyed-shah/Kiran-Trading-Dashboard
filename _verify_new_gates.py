import sqlite3

conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

latest = cur.execute("SELECT MAX(date) FROM stock_signals").fetchone()[0]
print(f"Verifying on: {latest}\n")

# Get sector RS rank 5 trading days ago for "sector rank improving" gate
# Find the date 5 trading days back
dates_back = cur.execute(
    "SELECT DISTINCT date FROM sector_signals ORDER BY date DESC LIMIT 7"
).fetchall()
date_5ago = dates_back[5][0] if len(dates_back) >= 6 else None
print(f"5 trading days ago: {date_5ago}\n")

# Load sector rank 5 days ago
sec_rank_5ago = {}
if date_5ago:
    rows = cur.execute(
        "SELECT sector, rs_rank FROM sector_signals WHERE date = ?", (date_5ago,)
    ).fetchall()
    sec_rank_5ago = {r[0]: r[1] for r in rows}

# Full stock screen
all_rows = cur.execute('''
    SELECT ss.symbol, s.sector, ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
           ss.close_above_ema50, ss.ema50_slope_pos,
           ss.near_pivot_days, ss.pivot_distance_pct, ss.overhead_clear,
           sec.sector_stage, sec.sector_pivot_dist_pct, sec.sector_rs_new_high,
           sec.rs_rank AS sec_rs_rank_today
    FROM stock_signals ss
    JOIN sectors s ON ss.symbol = s.symbol
    LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
    WHERE ss.date = ?
    ORDER BY ss.rs_rank ASC
''', (latest,)).fetchall()

results = []
for r in all_rows:
    sym, sector, rs, chg, srank, ema50, slope, npd, pdist, oh, sstage, spd, srnh, sec_rs_today = r

    # Sector RS rank improving over 5 days
    sec_rs_5ago = sec_rank_5ago.get(sector)
    sec_rank_improving = (sec_rs_today is not None and sec_rs_5ago is not None and
                          sec_rs_today < sec_rs_5ago)  # lower rank = better

    # ORIGINAL gates
    orig = (
        sstage == 'Stage 2' and
        spd is not None and spd <= 10 and
        srnh == 1 and
        ema50 == 1 and slope == 1 and
        chg is not None and chg > 0 and
        srank is not None and srank <= 3 and
        npd is not None and npd >= 10 and
        pdist is not None and 0 <= pdist <= 5
    )

    # RELAXED gates
    relaxed = (
        sstage == 'Stage 2' and
        spd is not None and spd <= 10 and
        sec_rank_improving and              # ← sector RS rank better than 5d ago
        ema50 == 1 and slope == 1 and
        chg is not None and chg > 0 and
        srank is not None and srank <= 5 and  # ← top 5
        npd is not None and npd >= 7           # ← 7 days
        # ← pivot_distance_pct removed as gate
    )

    results.append((sym, sector, rs, srank, npd, pdist, sec_rs_today, sec_rs_5ago,
                    sec_rank_improving, srnh, orig, relaxed))

orig_pass  = [r for r in results if r[10]]
relax_pass = [r for r in results if r[11]]

print(f"Original gates:  {len(orig_pass)} stocks")
print(f"Relaxed gates:   {len(relax_pass)} stocks\n")

if relax_pass:
    print(f"{'Symbol':<10} {'Sector':<30} {'RS':>5} {'SecRk':>6} {'NpD':>5} {'PivD%':>7} {'SecRS':>6} {'5dAgo':>6} {'OH':>4}")
    print('-'*100)
    for r in relax_pass:
        sym, sector, rs, srank, npd, pdist, sec_rs_today, sec_rs_5ago, _, srnh, _, _ = r
        pdist_s = f"{pdist:+.1f}" if pdist is not None else "-"
        print(f"{sym:<10} {sector[:30]:<30} {str(rs):>5} {str(srank):>6} {str(npd):>5} {pdist_s:>7} {str(sec_rs_today):>6} {str(sec_rs_5ago):>6} {str(srnh):>4}")

# Also show how many pass if we go top 7
print("\n--- Sensitivity: top 7 instead of top 5 ---")
top7 = [r for r in results if (
    r[2+8] or  # already passes relaxed
    False
)]
# recompute with top 7
top7_pass = []
for r in results:
    sym, sector, rs, srank, npd, pdist, sec_rs_today, sec_rs_5ago, sec_rank_improving, srnh, orig, relaxed = r
    sstage_ok = True  # already filtered Stage 2 in query implicitly
    t7 = (
        relaxed or  # already passes top5
        (sec_rank_improving and ema50 == 1 and slope == 1 and
         chg is not None and True and  # rank_change not in tuple, approximate
         srank is not None and srank <= 7 and
         npd is not None and npd >= 7)
    )
    # Simpler: just check srank <= 7 with same other gates
    pass

# Requery with srank <= 7
top7_pass = []
for r in results:
    sym, sector, rs, srank, npd, pdist, sec_rs_today, sec_rs_5ago, sec_rank_improving, srnh, orig, relaxed = r
    if (srank is not None and srank <= 7 and
        sec_rank_improving and
        npd is not None and npd >= 7):
        top7_pass.append(r)

# Need rank_change — get it from all_rows
rank_changes = {r[0]: r[3] for r in all_rows}

top7_pass2 = []
for r in results:
    sym, sector, rs, srank, npd, pdist, sec_rs_today, sec_rs_5ago, sec_rank_improving, srnh, orig, relaxed = r
    chg = rank_changes.get(sym)
    ema50_ok = True  # we need to get this from all_rows too
    if (srank is not None and srank <= 7 and
        sec_rank_improving and
        chg is not None and chg > 0 and
        npd is not None and npd >= 7):
        top7_pass2.append((sym, sector, rs, srank, npd, pdist, sec_rs_today, sec_rs_5ago))

print(f"Top 7 (relaxed other gates, without ema50/slope recheck): {len(top7_pass2)} additional potential")
for r in top7_pass2:
    sym, sector, rs, srank, npd, pdist, sec_rs_today, sec_rs_5ago = r
    pdist_s = f"{pdist:+.1f}" if pdist is not None else "-"
    if sym not in [x[0] for x in relax_pass]:
        print(f"  +NEW: {sym:<10} {sector[:28]:<28} RS={rs} SecRk={srank} NpD={npd} PivD={pdist_s}")

conn.close()
