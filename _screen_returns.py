import sqlite3

conn = sqlite3.connect('psx_data.db')

# Hits from monthly screen
hits = [
    ('PPL',   '2024-05-02'),
    ('PPP',   '2024-06-03'),
    ('POWER', '2025-02-03'),
    ('FEROZ', '2025-06-02'),
    ('JVDC',  '2025-09-01'),
    ('TPLI',  '2025-11-03'),
    ('GTYR',  '2026-01-01'),
]

# Also run daily screen to find ALL hits across the period
print("=== DAILY SCREEN — ALL HITS 2024-2026 ===\n")

all_dates = [r[0] for r in conn.execute(
    "SELECT DISTINCT date FROM stock_signals WHERE date BETWEEN '2024-01-01' AND '2026-06-19' ORDER BY date"
).fetchall()]

daily_hits = []
for d in all_dates:
    rows = conn.execute('''
        SELECT ss.symbol, s.sector, ss.rs_rank, ss.sector_rs_rank,
               ss.near_pivot_days, ss.pivot_distance_pct,
               p.close AS entry_close
        FROM stock_signals ss
        JOIN sectors s ON ss.symbol = s.symbol
        LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
        LEFT JOIN prices p ON p.symbol = ss.symbol AND p.date = ss.date
        WHERE ss.date = ?
          AND sec.sector_stage = 'Stage 2'
          AND sec.sector_pivot_dist_pct <= 10
          AND sec.sector_rs_new_high = 1
          AND ss.close_above_ema50 = 1
          AND ss.ema50_slope_pos = 1
          AND ss.rank_change > 0
          AND ss.sector_rs_rank <= 3
          AND ss.near_pivot_days >= 10
          AND ss.pivot_distance_pct BETWEEN 0 AND 5
    ''', (d,)).fetchall()
    for r in rows:
        daily_hits.append((d,) + r)

print(f"Total hits across all daily screens: {len(daily_hits)}")
print()

# Group by symbol — show first appearance date and entry price
from collections import defaultdict
first_hit = {}
for row in daily_hits:
    date, sym, sector, rs, srank, npd, pdist, entry = row
    if sym not in first_hit:
        first_hit[sym] = (date, sector, rs, entry)

print(f"Unique symbols that ever passed: {len(first_hit)}")
print()
print(f"{'Symbol':<10} {'First Hit':<12} {'Sector':<30} {'RS':>5} {'Entry':>8} {'30d Ret':>8} {'60d Ret':>8} {'90d Ret':>8}")
print('-'*100)

for sym, (hit_date, sector, rs, entry) in sorted(first_hit.items(), key=lambda x: x[1][0]):
    if entry is None:
        continue
    # Get forward prices
    fwd = conn.execute('''
        SELECT date, close FROM prices
        WHERE symbol = ? AND date > ?
        ORDER BY date ASC
        LIMIT 90
    ''', (sym, hit_date)).fetchall()

    def get_price_near_day(n):
        if len(fwd) >= n:
            return fwd[n-1][1]
        elif fwd:
            return fwd[-1][1]
        return None

    p30 = get_price_near_day(30)
    p60 = get_price_near_day(60)
    p90 = get_price_near_day(90)

    r30 = f"{(p30/entry-1)*100:+.1f}%" if p30 else "—"
    r60 = f"{(p60/entry-1)*100:+.1f}%" if p60 else "—"
    r90 = f"{(p90/entry-1)*100:+.1f}%" if p90 else "—"

    print(f"{sym:<10} {hit_date:<12} {sector[:30]:<30} {str(rs):>5} {entry:>8.2f} {r30:>8} {r60:>8} {r90:>8}")

conn.close()
