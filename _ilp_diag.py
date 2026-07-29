import sqlite3, sys
sys.path.insert(0, r'C:\Users\Lenovo\psx_pipeline')
from config import DB_PATH
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

print("=" * 80)
print("ILP DIAGNOSTIC — READ ONLY")
print("=" * 80)

# ── 1. LATEST STOCK SIGNALS ────────────────────────────────────────────────
print("\n── 1. LATEST STOCK SIGNALS (last 20 days from stock_signals) ─────────────")
c.execute("""
    SELECT date, rs_rank, rs_rank_prev, rank_change, sector_rs_rank,
           rs_score_20, base_tightness, bos_flag, vol_contraction,
           avg_vol_10d, pivot_high, pivot_distance_pct
    FROM stock_signals
    WHERE symbol = 'ILP'
    ORDER BY date DESC LIMIT 20
""")
rows = c.fetchall()
if not rows:
    print("  NO ROWS FOUND in stock_signals for ILP")
else:
    hdr = f"  {'Date':<12} {'RS':>5} {'RSPrv':>6} {'Chg':>5} {'SecRS':>6} {'RS20':>7} {'BBW%':>7} {'BOS':>4} {'VolCnt':>7} {'AvgVol10':>10} {'PivHigh':>9} {'PivDist%':>9}"
    print(hdr)
    for r in rows:
        date, rs, rs_p, chg, sec_rs, rs20, bbw, bos, vc, avgvol, piv, pivd = r
        rs    = str(rs)   if rs   is not None else "—"
        rs_p  = str(rs_p) if rs_p is not None else "—"
        chg   = (f"{chg:+d}" if chg is not None else "—")
        sec_rs= str(sec_rs) if sec_rs is not None else "—"
        rs20  = f"{rs20:.4f}" if rs20 is not None else "—"
        bbw   = f"{bbw:.2f}%" if bbw is not None else "—"
        bos   = str(bos) if bos is not None else "—"
        vc    = f"{vc:.4f}" if vc is not None else "—"
        avgvol= f"{int(avgvol):,}" if avgvol is not None else "—"
        piv   = f"{piv:.2f}" if piv is not None else "—"
        pivd  = f"{pivd:.2f}%" if pivd is not None else "—"
        print(f"  {date:<12} {rs:>5} {rs_p:>6} {chg:>5} {sec_rs:>6} {rs20:>7} {bbw:>7} {bos:>4} {vc:>7} {avgvol:>10} {piv:>9} {pivd:>9}")

# ── 2. RECENT PRICES ───────────────────────────────────────────────────────
print("\n── 2. RECENT PRICES (last 30 days from prices_adjusted) ─────────────────")
c.execute("""
    SELECT date, close, high, low, volume
    FROM prices_adjusted
    WHERE symbol = 'ILP'
    ORDER BY date DESC LIMIT 30
""")
rows = c.fetchall()
if not rows:
    print("  NO ROWS FOUND in prices_adjusted for ILP")
else:
    print(f"  {'Date':<12} {'Close':>9} {'High':>9} {'Low':>9} {'Volume':>12}")
    for r in rows:
        date, close, high, low, vol = r
        print(f"  {date:<12} {close:>9.2f} {high:>9.2f} {low:>9.2f} {int(vol) if vol else 0:>12,}")

# ── 3. SETUP LOG HISTORY ───────────────────────────────────────────────────
print("\n── 3. SETUP LOG HISTORY (last 50 from setup_log) ────────────────────────")
c.execute("""
    SELECT setup_date, setup_type, fwd_return_5d, fwd_return_10d,
           fwd_return_20d, outcome_label
    FROM setup_log
    WHERE symbol = 'ILP'
    ORDER BY setup_date DESC LIMIT 50
""")
rows = c.fetchall()
if not rows:
    print("  NO ROWS FOUND in setup_log for ILP")
else:
    print(f"  {'Date':<12} {'Setup Type':<20} {'5d%':>7} {'10d%':>7} {'20d%':>7}  Outcome")
    for r in rows:
        date, stype, r5, r10, r20, out = r
        r5  = f"{r5:+.2f}" if r5  is not None else "  None"
        r10 = f"{r10:+.2f}" if r10 is not None else "  None"
        r20 = f"{r20:+.2f}" if r20 is not None else "  None"
        print(f"  {date:<12} {stype:<20} {r5:>7} {r10:>7} {r20:>7}  {out or 'pending'}")

# ── 4. SECTOR / METADATA ───────────────────────────────────────────────────
print("\n── 4. SECTOR / METADATA (stock_metadata) ─────────────────────────────────")
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stock_metadata'")
if c.fetchone():
    c.execute("SELECT sector, listing_date, is_active FROM stock_metadata WHERE symbol='ILP'")
    row = c.fetchone()
    print(f"  {row}" if row else "  No row for ILP in stock_metadata")
else:
    print("  Table stock_metadata does not exist — trying sectors table")
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sectors'")
    if c.fetchone():
        c.execute("SELECT * FROM sectors WHERE symbol='ILP'")
        row = c.fetchone()
        print(f"  sectors row: {row}" if row else "  No row for ILP in sectors")
    else:
        print("  No stock_metadata or sectors table found")

# ── 5. MARKET REGIME ──────────────────────────────────────────────────────
print("\n── 5. MARKET REGIME (latest 5 days) ─────────────────────────────────────")
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='market_regime'")
if c.fetchone():
    c.execute("SELECT date, regime FROM market_regime ORDER BY date DESC LIMIT 5")
    rows = c.fetchall()
    print(f"  {'Date':<12} {'Regime'}")
    for r in rows:
        print(f"  {r[0]:<12} {r[1]}")
else:
    print("  Table market_regime does not exist — trying weinstein_regimes or regime_history")
    for alt in ['weinstein_regimes', 'regime_history', 'regimes']:
        c.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{alt}'")
        if c.fetchone():
            c.execute(f"SELECT * FROM {alt} ORDER BY date DESC LIMIT 5")
            rows = c.fetchall()
            cols = [d[0] for d in c.description]
            print(f"  Table '{alt}' — columns: {cols}")
            for r in rows:
                print(f"  {r}")
            break
    else:
        print("  No regime table found. All tables:")
        c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        print("  " + str([r[0] for r in c.fetchall()]))

conn.close()
