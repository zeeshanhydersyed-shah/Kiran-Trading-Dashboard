from database import get_conn
with get_conn() as conn:
    rows = conn.execute("""
        SELECT strftime('%Y', as_of_date) as yr,
               outcome, COUNT(*) as n
        FROM backtest_setups
        WHERE outcome IN ('Win_Trail','Win_T1','Loss')
        GROUP BY yr, outcome ORDER BY yr, outcome
    """).fetchall()

    totals = conn.execute("""
        SELECT strftime('%Y', as_of_date) as yr, COUNT(*)
        FROM backtest_setups
        WHERE outcome IN ('Win_Trail','Win_T1','Loss')
        GROUP BY yr
    """).fetchall()

for r in rows:
    print(r)
print()
for t in totals:
    print(f"  {t[0]}: {t[1]} triggered setups")
