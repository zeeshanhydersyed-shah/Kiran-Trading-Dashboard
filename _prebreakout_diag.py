import sqlite3, sys
sys.path.insert(0, r'C:\Users\Lenovo\psx_pipeline')
from config import DB_PATH
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

print("=" * 80)
print("PRE_BREAKOUT WINNER vs LOSER DIAGNOSTIC — READ ONLY")
print("=" * 80)

# Check actual column names in setup_log
c.execute("PRAGMA table_info(setup_log)")
sl_cols = [r[1] for r in c.fetchall()]
c.execute("PRAGMA table_info(stock_signals)")
ss_cols = [r[1] for r in c.fetchall()]
print(f"\nsetup_log date col: {'setup_date' if 'setup_date' in sl_cols else 'date'}")
print(f"setup_log outcome col: {'outcome_label' if 'outcome_label' in sl_cols else 'outcome'}")
print(f"stock_signals date col: {'date' if 'date' in ss_cols else ss_cols[1]}")

# Resolve column names
sl_date = 'setup_date' if 'setup_date' in sl_cols else 'date'
sl_out  = 'outcome_label' if 'outcome_label' in sl_cols else 'outcome'

# Check sector_signals table
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sector_signals'")
has_sector_signals = bool(c.fetchone())
if has_sector_signals:
    c.execute("PRAGMA table_info(sector_signals)")
    print(f"sector_signals cols: {[r[1] for r in c.fetchall()]}")

# Check stock_metadata
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stock_metadata'")
has_metadata = bool(c.fetchone())
meta_table = 'stock_metadata' if has_metadata else 'sectors'

# ── 1. SIGNAL CHARACTERISTICS BY OUTCOME ──────────────────────────────────
print("\n── 1. PRE_BREAKOUT — Avg Signal Characteristics by Outcome ───────────────")
c.execute(f"""
    SELECT
        sl.{sl_out} AS outcome,
        COUNT(*)                        AS n,
        ROUND(AVG(ss.rs_rank), 1)       AS avg_rs_rank,
        ROUND(AVG(ss.sector_rs_rank),1) AS avg_sec_rs,
        ROUND(AVG(ss.rs_score_20), 3)   AS avg_rs20,
        ROUND(AVG(ss.pivot_distance_pct),2) AS avg_piv_dist,
        ROUND(AVG(ss.base_tightness),2) AS avg_bbw,
        ROUND(AVG(ss.avg_vol_10d),0)    AS avg_vol10d
    FROM setup_log sl
    JOIN stock_signals ss
        ON sl.symbol = ss.symbol AND sl.{sl_date} = ss.date
    WHERE sl.setup_type = 'PRE_BREAKOUT'
      AND sl.{sl_out} IN ('WINNER','LOSER','BREAKEVEN')
    GROUP BY sl.{sl_out}
    ORDER BY CASE sl.{sl_out}
        WHEN 'WINNER' THEN 1 WHEN 'LOSER' THEN 2 ELSE 3 END
""")
rows = c.fetchall()
print(f"\n  {'Outcome':<11} {'n':>5} {'RS Rank':>8} {'SecRS':>6} {'RS20':>8} {'PivDist%':>9} {'BBW%':>6} {'AvgVol10d':>12}")
for r in rows:
    out, n, rs, secrs, rs20, pivd, bbw, vol = r
    vol_s = f"{int(vol):,}" if vol else "—"
    print(f"  {out:<11} {n:>5} {rs or '—':>8} {secrs or '—':>6} {rs20 or '—':>8} {pivd or '—':>9} {bbw or '—':>6} {vol_s:>12}")

total = sum(r[1] for r in rows)
print(f"\n  Total matched rows (setup_log joined to stock_signals): {total}")

# ── 2. WINNER SECTOR DISTRIBUTION ─────────────────────────────────────────
print("\n── 2. PRE_BREAKOUT WINNERS — Sector Distribution ─────────────────────────")
if has_metadata:
    c.execute(f"""
        SELECT
            sm.sector,
            COUNT(*)                        AS winners,
            ROUND(AVG(ss.rs_rank), 1)       AS avg_rs_rank,
            ROUND(AVG(ss.sector_rs_rank),1) AS avg_sec_rs
        FROM setup_log sl
        JOIN stock_signals ss
            ON sl.symbol = ss.symbol AND sl.{sl_date} = ss.date
        JOIN stock_metadata sm ON sl.symbol = sm.symbol
        WHERE sl.setup_type = 'PRE_BREAKOUT'
          AND sl.{sl_out} = 'WINNER'
        GROUP BY sm.sector
        ORDER BY winners DESC
    """)
else:
    c.execute(f"""
        SELECT
            s.sector,
            COUNT(*)                        AS winners,
            ROUND(AVG(ss.rs_rank), 1)       AS avg_rs_rank,
            ROUND(AVG(ss.sector_rs_rank),1) AS avg_sec_rs
        FROM setup_log sl
        JOIN stock_signals ss
            ON sl.symbol = ss.symbol AND sl.{sl_date} = ss.date
        JOIN sectors s ON sl.symbol = s.symbol
        WHERE sl.setup_type = 'PRE_BREAKOUT'
          AND sl.{sl_out} = 'WINNER'
        GROUP BY s.sector
        ORDER BY winners DESC
    """)
rows = c.fetchall()
print(f"\n  {'Sector':<40} {'Winners':>8} {'Avg RS':>8} {'Avg SecRS':>10}")
for r in rows:
    sec, w, rs, srs = r
    print(f"  {(sec or '—'):<40} {w:>8} {rs or '—':>8} {srs or '—':>10}")

# ── 3. SECTOR COMPOSITE SCORE AT ENTRY ────────────────────────────────────
print("\n── 3. PRE_BREAKOUT — Sector Composite Score at Entry ─────────────────────")
if has_sector_signals:
    c.execute("PRAGMA table_info(sector_signals)")
    ssc = [r[1] for r in c.fetchall()]
    print(f"  sector_signals columns: {ssc}")

    # Identify composite score column
    comp_col = None
    for candidate in ['composite_score','score','sector_score','rs_score']:
        if candidate in ssc:
            comp_col = candidate
            break
    sec_col = 'sector' if 'sector' in ssc else ssc[1]

    # Check date col in sector_signals
    ss_date_col = 'date' if 'date' in ssc else ssc[0]

    if comp_col:
        meta_join = "JOIN stock_metadata sm ON sl.symbol = sm.symbol" if has_metadata else "JOIN sectors sm ON sl.symbol = sm.symbol"
        for outcome in ('WINNER', 'LOSER'):
            c.execute(f"""
                SELECT
                    ROUND(AVG(ssc.{comp_col}), 4)    AS avg_score,
                    COUNT(*)                          AS n
                FROM setup_log sl
                JOIN stock_signals ss
                    ON sl.symbol = ss.symbol AND sl.{sl_date} = ss.date
                {meta_join}
                JOIN sector_signals ssc
                    ON ssc.{sec_col} = sm.sector AND ssc.{ss_date_col} = sl.{sl_date}
                WHERE sl.setup_type = 'PRE_BREAKOUT'
                  AND sl.{sl_out} = ?
            """, (outcome,))
            row = c.fetchone()

            # Median via Python
            c.execute(f"""
                SELECT ssc.{comp_col}
                FROM setup_log sl
                JOIN stock_signals ss
                    ON sl.symbol = ss.symbol AND sl.{sl_date} = ss.date
                {meta_join}
                JOIN sector_signals ssc
                    ON ssc.{sec_col} = sm.sector AND ssc.{ss_date_col} = sl.{sl_date}
                WHERE sl.setup_type = 'PRE_BREAKOUT'
                  AND sl.{sl_out} = ?
                  AND ssc.{comp_col} IS NOT NULL
                ORDER BY ssc.{comp_col}
            """, (outcome,))
            vals = [r[0] for r in c.fetchall()]
            median = sorted(vals)[len(vals)//2] if vals else None

            avg, n = row
            print(f"\n  {outcome} (n matched={n}): avg={avg}  median={round(median,4) if median else '—'}")
    else:
        print(f"  No composite_score column found. Columns: {ssc}")
else:
    print("  sector_signals table does not exist.")
    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    print("  All tables: " + ", ".join(r[0] for r in c.fetchall()))

# ── 4. RS RANK BUCKETS ─────────────────────────────────────────────────────
print("\n── 4. PRE_BREAKOUT — RS Rank Buckets vs Outcome ──────────────────────────")
c.execute(f"""
    SELECT
        CASE
            WHEN ss.rs_rank <= 50   THEN '1) <=50'
            WHEN ss.rs_rank <= 100  THEN '2) 51-100'
            WHEN ss.rs_rank <= 150  THEN '3) 101-150'
            WHEN ss.rs_rank <= 200  THEN '4) 151-200'
            ELSE                         '5) >200'
        END AS bucket,
        SUM(CASE WHEN sl.{sl_out}='WINNER'    THEN 1 ELSE 0 END) AS winners,
        SUM(CASE WHEN sl.{sl_out}='LOSER'     THEN 1 ELSE 0 END) AS losers,
        SUM(CASE WHEN sl.{sl_out}='BREAKEVEN' THEN 1 ELSE 0 END) AS bes,
        COUNT(*) AS total,
        ROUND(
            100.0 * SUM(CASE WHEN sl.{sl_out}='WINNER' THEN 1 ELSE 0 END) / COUNT(*),
            1
        ) AS win_pct
    FROM setup_log sl
    JOIN stock_signals ss
        ON sl.symbol = ss.symbol AND sl.{sl_date} = ss.date
    WHERE sl.setup_type = 'PRE_BREAKOUT'
      AND sl.{sl_out} IN ('WINNER','LOSER','BREAKEVEN')
    GROUP BY bucket
    ORDER BY bucket
""")
rows = c.fetchall()
print(f"\n  {'RS Rank Bucket':<14} {'W':>5} {'L':>5} {'BE':>5} {'Total':>6} {'Win%':>6}")
for r in rows:
    bkt, w, l, be, tot, wp = r
    print(f"  {bkt:<14} {w:>5} {l:>5} {be:>5} {tot:>6} {wp:>6}%")

# ── 5. SECTOR RS RANK BUCKETS ──────────────────────────────────────────────
print("\n── 5. PRE_BREAKOUT — Sector RS Rank Buckets vs Outcome ───────────────────")
c.execute(f"""
    SELECT
        CASE
            WHEN ss.sector_rs_rank <= 3   THEN '1) <=3'
            WHEN ss.sector_rs_rank <= 5   THEN '2) 4-5'
            WHEN ss.sector_rs_rank <= 10  THEN '3) 6-10'
            ELSE                               '4) >10'
        END AS bucket,
        SUM(CASE WHEN sl.{sl_out}='WINNER'    THEN 1 ELSE 0 END) AS winners,
        SUM(CASE WHEN sl.{sl_out}='LOSER'     THEN 1 ELSE 0 END) AS losers,
        SUM(CASE WHEN sl.{sl_out}='BREAKEVEN' THEN 1 ELSE 0 END) AS bes,
        COUNT(*) AS total,
        ROUND(
            100.0 * SUM(CASE WHEN sl.{sl_out}='WINNER' THEN 1 ELSE 0 END) / COUNT(*),
            1
        ) AS win_pct
    FROM setup_log sl
    JOIN stock_signals ss
        ON sl.symbol = ss.symbol AND sl.{sl_date} = ss.date
    WHERE sl.setup_type = 'PRE_BREAKOUT'
      AND sl.{sl_out} IN ('WINNER','LOSER','BREAKEVEN')
      AND ss.sector_rs_rank IS NOT NULL
    GROUP BY bucket
    ORDER BY bucket
""")
rows = c.fetchall()
print(f"\n  {'Sec RS Bucket':<14} {'W':>5} {'L':>5} {'BE':>5} {'Total':>6} {'Win%':>6}")
for r in rows:
    bkt, w, l, be, tot, wp = r
    print(f"  {bkt:<14} {w:>5} {l:>5} {be:>5} {tot:>6} {wp:>6}%")

conn.close()
