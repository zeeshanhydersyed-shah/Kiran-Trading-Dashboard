import sqlite3

conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

# Get all trading dates 2024-2026
all_dates = [r[0] for r in conn.execute(
    "SELECT DISTINCT date FROM stock_signals WHERE date BETWEEN '2024-01-01' AND '2026-06-19' ORDER BY date"
).fetchall()]

# Pre-load sector RS ranks for all dates (for 5-day improving check)
sec_ranks_by_date = {}
for row in conn.execute("SELECT date, sector, rs_rank FROM sector_signals WHERE date BETWEEN '2024-01-01' AND '2026-06-19'").fetchall():
    sec_ranks_by_date.setdefault(row[0], {})[row[1]] = row[2]

daily_hits = []

for idx, d in enumerate(all_dates):
    # Get date 5 trading days ago
    date_5ago = all_dates[idx - 5] if idx >= 5 else None
    sec_rank_5ago = sec_ranks_by_date.get(date_5ago, {})

    rows = conn.execute('''
        SELECT ss.symbol, s.sector, ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
               ss.close_above_ema50, ss.ema50_slope_pos,
               ss.near_pivot_days, ss.pivot_distance_pct,
               sec.sector_stage, sec.sector_pivot_dist_pct, sec.sector_rs_new_high,
               sec.rs_rank AS sec_rs_today
        FROM stock_signals ss
        JOIN sectors s ON ss.symbol = s.symbol
        LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
        WHERE ss.date = ?
    ''', (d,)).fetchall()

    for r in rows:
        sym, sector, rs, chg, srank, ema50, slope, npd, pdist, sstage, spd, srnh, sec_rs_today = r
        sec_rs_prev = sec_rank_5ago.get(sector)
        sec_rank_improving = (sec_rs_today is not None and sec_rs_prev is not None and
                              sec_rs_today < sec_rs_prev)

        relaxed = (
            sstage == 'Stage 2' and
            spd is not None and spd <= 10 and
            sec_rank_improving and
            ema50 == 1 and slope == 1 and
            chg is not None and chg > 0 and
            srank is not None and srank <= 5 and
            npd is not None and npd >= 7
        )

        if relaxed:
            daily_hits.append((d, sym, sector, rs, srank, npd, pdist))

print(f"Total daily hits (relaxed): {len(daily_hits)}")

# First appearance per symbol + forward returns
from collections import defaultdict
first_hit = {}
for date, sym, sector, rs, srank, npd, pdist in daily_hits:
    if sym not in first_hit:
        first_hit[sym] = (date, sector, rs, srank, npd, pdist)

print(f"Unique symbols: {len(first_hit)}\n")

# Highlight bank stocks specifically
bank_syms = {'AKBL','BAFL','BAHL','BOK','BOP','BIPL','FABL','HBL','HMB',
             'JSBL','MCB','MEBL','NBP','SBL','SNBL','SCBPL','SILK','UBL','ABL'}

print(f"{'Symbol':<10} {'First Hit':<12} {'Sector':<28} {'RS':>5} {'SecRk':>6} {'NpD':>5} {'PivD%':>7} {'30d':>7} {'60d':>7} {'90d':>7}  BANK?")
print('-'*120)

for sym, (hit_date, sector, rs, srank, npd, pdist) in sorted(first_hit.items(), key=lambda x: x[1][0]):
    # Get adjusted entry price from stock_signals join prices_adjusted
    entry = conn.execute(
        "SELECT close FROM prices_adjusted WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1",
        (sym, hit_date)
    ).fetchone()
    if not entry:
        entry = conn.execute(
            "SELECT close FROM prices WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1",
            (sym, hit_date)
        ).fetchone()
    if not entry:
        continue
    entry_price = entry[0]

    fwd = conn.execute(
        "SELECT close FROM prices_adjusted WHERE symbol=? AND date>? ORDER BY date ASC LIMIT 90",
        (sym, hit_date)
    ).fetchall()
    if not fwd:
        fwd = conn.execute(
            "SELECT close FROM prices WHERE symbol=? AND date>? ORDER BY date ASC LIMIT 90",
            (sym, hit_date)
        ).fetchall()

    p30 = fwd[29][0] if len(fwd) >= 30 else None
    p60 = fwd[59][0] if len(fwd) >= 60 else None
    p90 = fwd[89][0] if len(fwd) >= 90 else None

    r30 = f"{(p30/entry_price-1)*100:+.1f}%" if p30 else "—"
    r60 = f"{(p60/entry_price-1)*100:+.1f}%" if p60 else "—"
    r90 = f"{(p90/entry_price-1)*100:+.1f}%" if p90 else "—"
    pdist_s = f"{pdist:+.1f}" if pdist is not None else "-"
    bank_flag = "BANK" if sym in bank_syms else ""

    print(f"{sym:<10} {hit_date:<12} {sector[:28]:<28} {str(rs):>5} {str(srank):>6} {str(npd):>5} {pdist_s:>7} {r30:>7} {r60:>7} {r90:>7}  {bank_flag}")

conn.close()
