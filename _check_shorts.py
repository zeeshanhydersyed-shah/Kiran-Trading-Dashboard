import sqlite3
from config import DFC_SYMBOLS

conn = sqlite3.connect('psx_data.db')
latest = conn.execute("SELECT MAX(date) FROM stock_signals").fetchone()[0]

dates_back = [r[0] for r in conn.execute(
    "SELECT DISTINCT date FROM sector_signals ORDER BY date DESC LIMIT 7"
).fetchall()]
date_5ago = dates_back[5] if len(dates_back) >= 6 else None

sec_rank_5ago = {}
if date_5ago:
    for r in conn.execute("SELECT sector, rs_rank FROM sector_signals WHERE date=?", (date_5ago,)).fetchall():
        sec_rank_5ago[r[0]] = r[1]

rows = conn.execute('''
    SELECT ss.symbol, s.sector, ss.rs_rank, ss.rank_change,
           ss.close_above_ema50, ss.ema50_slope_pos,
           ss.pivot_distance_pct, ss.pivot_high,
           sec.sector_stage, sec.rs_rank AS sec_rs_today
    FROM stock_signals ss
    JOIN sectors s ON ss.symbol = s.symbol
    LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
    WHERE ss.date = ?
    ORDER BY ss.rs_rank DESC
''', (latest,)).fetchall()

print(f"Date: {latest}  |  5d ago: {date_5ago}\n")
print(f"{'Symbol':<10} {'Sector':<28} {'RS':>5} {'Chg':>5} {'E50':>4} {'Slp':>4} {'PivD%':>7} {'SecStg':<10} {'SecRk':>6} {'5dAgo':>6}  PASS")
print('-'*110)

hits = []
for r in rows:
    sym, sector, rs, chg, ema50, slope, pdist, ph, sstage, sec_rs_today = r
    sec_rs_prev = sec_rank_5ago.get(sector)
    sec_deteriorating = (sec_rs_today is not None and sec_rs_prev is not None
                         and sec_rs_today > sec_rs_prev)
    passes = (
        sstage in ('Stage 3', 'Stage 4') and
        sec_deteriorating and
        ema50 == 0 and slope == 0 and
        chg is not None and chg < 0 and
        pdist is not None and -8 <= pdist <= 2 and
        sym in DFC_SYMBOLS
    )
    if sstage in ('Stage 3', 'Stage 4') or passes:
        pdist_s = f"{pdist:+.1f}" if pdist is not None else "-"
        dfc = "DFC" if sym in DFC_SYMBOLS else ""
        flag = "*** SHORT ***" if passes else ""
        print(f"{sym:<10} {sector[:28]:<28} {str(rs):>5} {str(chg):>5} {str(ema50):>4} {str(slope):>4} {pdist_s:>7} {str(sstage):<10} {str(sec_rs_today):>6} {str(sec_rs_prev):>6}  {dfc} {flag}")
        if passes:
            hits.append(sym)

print(f"\nShort hits: {len(hits)} — {hits}")
conn.close()
