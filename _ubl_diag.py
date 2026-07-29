import sqlite3, sys
sys.path.insert(0, r'C:\Users\Lenovo\psx_pipeline')
from config import DB_PATH
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

print("=" * 70)
print("UBL DIAGNOSTIC — READ ONLY")
print("=" * 70)

# ── 1. PRICE MILESTONES ────────────────────────────────────────────────────
print("\n── 1. PRICE MILESTONES (prices_adjusted) ──────────────────────────")

# Check if prices_adjusted exists
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='prices_adjusted'")
pa_exists = c.fetchone()
price_table = 'prices_adjusted' if pa_exists else 'prices'
print(f"  (using table: {price_table})")

c.execute(f"""
    SELECT date, close FROM {price_table}
    WHERE symbol='UBL' AND date >= '2023-01-01' AND date <= '2023-03-31'
    ORDER BY close ASC LIMIT 1
""")
row = c.fetchone()
print(f"\n  Lowest close 2023-01-01 to 2023-03-31: {row}")

c.execute(f"""
    SELECT date, close FROM {price_table}
    WHERE symbol='UBL' AND date >= '2025-10-01' AND date <= '2026-03-31'
    ORDER BY close DESC LIMIT 1
""")
row = c.fetchone()
print(f"  Highest close 2025-10-01 to 2026-03-31 (ATH window): {row}")

c.execute(f"""
    SELECT date, close FROM {price_table}
    WHERE symbol='UBL'
    ORDER BY close DESC LIMIT 1
""")
row = c.fetchone()
print(f"  All-time highest close in {price_table}: {row}")

# ── 2. YEARLY CHECKPOINTS ──────────────────────────────────────────────────
print("\n── 2. YEARLY CHECKPOINTS (prices_adjusted) ────────────────────────")
for year in [2023, 2024, 2025, 2026]:
    y_start = f"{year}-01-01"
    y_end   = f"{year}-12-31"
    c.execute(f"""
        SELECT date, close FROM {price_table}
        WHERE symbol='UBL' AND date >= ? AND date <= ?
        ORDER BY date ASC LIMIT 1
    """, (y_start, y_end))
    first = c.fetchone()
    c.execute(f"""
        SELECT date, close FROM {price_table}
        WHERE symbol='UBL' AND date >= ? AND date <= ?
        ORDER BY date DESC LIMIT 1
    """, (y_start, y_end))
    last = c.fetchone()
    c.execute(f"""
        SELECT date, high FROM {price_table}
        WHERE symbol='UBL' AND date >= ? AND date <= ?
        ORDER BY high DESC LIMIT 1
    """, (y_start, y_end))
    hi = c.fetchone()
    c.execute(f"""
        SELECT date, low FROM {price_table}
        WHERE symbol='UBL' AND date >= ? AND date <= ?
        ORDER BY low ASC LIMIT 1
    """, (y_start, y_end))
    lo = c.fetchone()
    print(f"\n  {year}:")
    print(f"    First: {first}   Last: {last}")
    print(f"    High:  {hi}   Low: {lo}")

# ── 3. BREAKOUT SIGNALS ────────────────────────────────────────────────────
print("\n── 3. BREAKOUT SIGNALS from setup_log ─────────────────────────────")
c.execute("""
    SELECT setup_date, fwd_return_5d, fwd_return_10d, fwd_return_20d, outcome_label
    FROM setup_log
    WHERE symbol='UBL' AND setup_type='BREAKOUT' AND setup_date >= '2023-01-01'
    ORDER BY setup_date ASC
""")
rows = c.fetchall()
print(f"  Count: {len(rows)}")
print(f"  {'Date':<14} {'5d%':>7} {'10d%':>7} {'20d%':>7}  {'Outcome'}")
for r in rows:
    d, r5, r10, r20, out = r
    r5  = f"{r5:+.2f}" if r5 is not None else "  None"
    r10 = f"{r10:+.2f}" if r10 is not None else "  None"
    r20 = f"{r20:+.2f}" if r20 is not None else "  None"
    print(f"  {d:<14} {r5:>7} {r10:>7} {r20:>7}  {out or 'pending'}")

# ── 4. PRE-BREAKOUT SIGNALS ────────────────────────────────────────────────
print("\n── 4. PRE-BREAKOUT SIGNALS from setup_log ─────────────────────────")
c.execute("""
    SELECT setup_date, fwd_return_5d, fwd_return_10d, fwd_return_20d, outcome_label
    FROM setup_log
    WHERE symbol='UBL' AND setup_type='PRE_BREAKOUT' AND setup_date >= '2023-01-01'
    ORDER BY setup_date ASC
""")
rows = c.fetchall()
print(f"  Count: {len(rows)}")
print(f"  {'Date':<14} {'5d%':>7} {'10d%':>7} {'20d%':>7}  {'Outcome'}")
for r in rows:
    d, r5, r10, r20, out = r
    r5  = f"{r5:+.2f}" if r5 is not None else "  None"
    r10 = f"{r10:+.2f}" if r10 is not None else "  None"
    r20 = f"{r20:+.2f}" if r20 is not None else "  None"
    print(f"  {d:<14} {r5:>7} {r10:>7} {r20:>7}  {out or 'pending'}")

# ── 5. RS LEADER APPEARANCES ───────────────────────────────────────────────
print("\n── 5. RS LEADER APPEARANCES from setup_log ────────────────────────")
c.execute("""
    SELECT setup_date, setup_type, regime, rs_rank, sector_rs_rank,
           fwd_return_5d, fwd_return_10d, fwd_return_20d, outcome_label
    FROM setup_log
    WHERE symbol='UBL'
      AND setup_type IN ('RS_LEADER_MARKET','RS_LEADER_SECTOR')
      AND setup_date >= '2023-01-01'
    ORDER BY setup_date ASC
""")
rows = c.fetchall()
print(f"  Count: {len(rows)}")
print(f"  {'Date':<14} {'Type':<18} {'Regime':<14} {'RS':>5} {'SecRS':>6} {'5d%':>7} {'10d%':>7} {'20d%':>7}  Outcome")
for r in rows:
    d, stype, regime, rs, srs, r5, r10, r20, out = r
    r5  = f"{r5:+.2f}" if r5 is not None else "  None"
    r10 = f"{r10:+.2f}" if r10 is not None else "  None"
    r20 = f"{r20:+.2f}" if r20 is not None else "  None"
    rs  = str(rs) if rs is not None else "—"
    srs = str(srs) if srs is not None else "—"
    print(f"  {d:<14} {stype:<18} {(regime or '—'):<14} {rs:>5} {srs:>6} {r5:>7} {r10:>7} {r20:>7}  {out or 'pending'}")

conn.close()
