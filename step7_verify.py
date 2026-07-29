"""
step7_verify.py  —  Post-switchover verification
Run from psx_pipeline root:  python step7_verify.py
"""
import sqlite3, os

LIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psx_data.db")
con  = sqlite3.connect(LIVE)
cur  = con.cursor()

print("=" * 55)
print("STEP 7 — POST-SWITCHOVER CHECKS")
print("=" * 55)

cur.execute("SELECT COUNT(*) FROM prices")
p = cur.fetchone()[0]
print(f"\n1. prices COUNT:          {p:>10,}   (expected ~1,809,632+)")

cur.execute("SELECT MIN(date), MAX(date) FROM prices")
p_min, p_max = cur.fetchone()
print(f"2. prices date range:     {p_min} → {p_max}")

cur.execute("SELECT COUNT(*) FROM index_prices")
i = cur.fetchone()[0]
print(f"3. index_prices COUNT:    {i:>10,}   (expected ~16,483+)")

cur.execute("SELECT MIN(date), MAX(date) FROM index_prices")
i_min, i_max = cur.fetchone()
print(f"4. index_prices range:    {i_min} → {i_max}")

cur.execute("PRAGMA integrity_check")
ic = cur.fetchone()[0]
print(f"5. integrity_check:       {ic}")

print()
print("--- Small tables ---")
for tbl, exp in [
    ("sectors",            2443),
    ("kse100_constituents",  100),
    ("trade_setups",         377),
    ("backtest_setups",     4344),
    ("screened_dates",      1548),
]:
    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
    got = cur.fetchone()[0]
    print(f"  {'✅' if got==exp else '❌'} {tbl}: {got} (exp {exp})")

print()
print("--- KSE-100 June 8-11 spot check ---")
cur.execute("""SELECT date, close FROM index_prices
               WHERE symbol='KSE-100' AND date>='2026-06-08'
               ORDER BY date""")
for r in cur.fetchall():
    print(f"  KSE-100  {r[0]}  {r[1]:,.2f}")

print()
print("--- Latest prices sample (June 11) ---")
cur.execute("""SELECT symbol, close FROM prices
               WHERE date='2026-06-11'
               ORDER BY symbol LIMIT 8""")
for r in cur.fetchall():
    print(f"  {r[0]:12s}  {r[1]:,.2f}")

con.close()
print(f"\nFile size: {os.path.getsize(LIVE)/1024/1024:.1f} MB")
print("=" * 55)
