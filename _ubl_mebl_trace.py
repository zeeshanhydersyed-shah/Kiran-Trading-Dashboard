import sqlite3

conn = sqlite3.connect('psx_data.db')

# Trace UBL and MEBL daily, from early 2024 through their breakouts
# Apply relaxed gates: near_pivot_days >= 7, sec_top3 -> top 5

for sym in ['UBL', 'MEBL']:
    print(f"\n{'='*80}")
    print(f"=== {sym} — daily trace (near_pivot>=7, sec_rank<=5) ===")
    print(f"{'='*80}")

    rows = conn.execute("""
        SELECT ss.date, ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
               ss.close_above_ema50, ss.ema50_slope_pos,
               ss.near_pivot_days, ss.pivot_distance_pct,
               sec.sector_stage, sec.sector_pivot_dist_pct, sec.sector_rs_new_high,
               p.close
        FROM stock_signals ss
        JOIN sectors s ON ss.symbol = s.symbol
        LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
        LEFT JOIN prices p ON p.symbol = ss.symbol AND p.date = ss.date
        WHERE ss.symbol = ?
        AND ss.date BETWEEN '2024-01-01' AND '2025-06-01'
        ORDER BY ss.date ASC
    """, (sym,)).fetchall()

    first_flag = None
    print(f"\n{'Date':<12} {'Close':>8} {'PivD%':>7} {'NpD':>5} {'SecRk':>6} {'SecNH':>6} {'RsChg':>6} {'E50':>4} {'Slp':>4}  STATUS")
    print('-'*90)

    for r in rows:
        date, rs, chg, srank, ema50, slope, npd, pdist, sstage, spd, srnh, close = r

        # Original gates
        orig_pass = (
            sstage == 'Stage 2' and
            spd is not None and spd <= 10 and
            srnh == 1 and
            ema50 == 1 and slope == 1 and
            chg is not None and chg > 0 and
            srank is not None and srank <= 3 and
            npd is not None and npd >= 10 and
            pdist is not None and 0 <= pdist <= 5
        )

        # Relaxed gates
        relaxed_pass = (
            sstage == 'Stage 2' and
            spd is not None and spd <= 10 and
            srnh == 1 and
            ema50 == 1 and slope == 1 and
            chg is not None and chg > 0 and
            srank is not None and srank <= 5 and
            npd is not None and npd >= 7 and
            pdist is not None and 0 <= pdist <= 5
        )

        # Only print interesting rows: near pivot or passing
        if pdist is not None and -2 <= pdist <= 20 and npd is not None and npd >= 3:
            pdist_s = f"{pdist:+.1f}" if pdist is not None else "-"
            status = ""
            if orig_pass:
                status = "*** ORIGINAL PASS ***"
                if not first_flag: first_flag = (date, close, 'original')
            elif relaxed_pass:
                status = "==> RELAXED PASS"
                if not first_flag: first_flag = (date, close, 'relaxed')
            elif pdist is not None and pdist < 0:
                status = ">> BROKE OUT"

            print(f"{date:<12} {str(round(close,2)) if close else '-':>8} {pdist_s:>7} {str(npd):>5} {str(srank):>6} {str(srnh):>6} {str(chg):>6} {str(ema50):>4} {str(slope):>4}  {status}")

    if first_flag:
        flag_date, flag_price, flag_type = first_flag
        # Forward returns
        fwd = conn.execute("""
            SELECT date, close FROM prices
            WHERE symbol = ? AND date > ?
            ORDER BY date ASC LIMIT 90
        """, (sym, flag_date)).fetchall()
        p30 = fwd[29][1] if len(fwd) >= 30 else None
        p60 = fwd[59][1] if len(fwd) >= 60 else None
        p90 = fwd[89][1] if len(fwd) >= 90 else None
        print(f"\n  First flag ({flag_type}): {flag_date} @ {flag_price:.2f}")
        if p30: print(f"  30d return: {(p30/flag_price-1)*100:+.1f}%  ({p30:.2f})")
        if p60: print(f"  60d return: {(p60/flag_price-1)*100:+.1f}%  ({p60:.2f})")
        if p90: print(f"  90d return: {(p90/flag_price-1)*100:+.1f}%  ({p90:.2f})")
    else:
        print(f"\n  No flag triggered under either gate set.")

conn.close()
