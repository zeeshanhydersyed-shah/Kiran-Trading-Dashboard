from database import get_conn
with get_conn() as c:
    r = c.execute("SELECT COUNT(*) FROM prices WHERE high IS NULL").fetchone()[0]
    t = c.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    kse = c.execute("SELECT COUNT(*) FROM index_prices WHERE symbol='KSE-100'").fetchone()[0]
    bt = c.execute("SELECT COUNT(*) FROM backtest_setups").fetchone()[0]
    bt_outcomes = c.execute("SELECT outcome, COUNT(*) FROM backtest_setups GROUP BY outcome").fetchall()

print(f"Prices total rows   : {t:,}")
print(f"H/L nulls remaining : {r:,}")
print(f"KSE-100 index rows  : {kse:,}")
print(f"Backtest setups     : {bt:,}")
for o, n in bt_outcomes:
    print(f"  {o}: {n}")
