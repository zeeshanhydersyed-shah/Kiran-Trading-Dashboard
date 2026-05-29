import sqlite3
conn = sqlite3.connect('psx_data.db')
conn.row_factory = sqlite3.Row

cols = conn.execute('PRAGMA table_info(backtest_setups)').fetchall()
print('backtest_setups columns:')
for c in cols:
    print(f"  {c['name']:25s} {c['type']}")

print()
r = conn.execute("SELECT * FROM backtest_setups WHERE direction='LONG' LIMIT 1").fetchone()
print('Sample row:')
for k in r.keys():
    print(f"  {k:25s} = {r[k]}")

print()
# quality_score distribution
rows = conn.execute("""
    SELECT quality_score, COUNT(*) n
    FROM backtest_setups
    WHERE direction='LONG'
    GROUP BY quality_score
    ORDER BY quality_score
""").fetchall()
print('quality_score distribution:')
for r2 in rows:
    print(f"  score={r2['quality_score']}  n={r2['n']}")

# risk_pct distribution using actual sim data
print()
rows2 = conn.execute("""
    SELECT
        SUM(CASE WHEN risk_pct <= 6  THEN 1 ELSE 0 END) le6,
        SUM(CASE WHEN risk_pct <= 8  THEN 1 ELSE 0 END) le8,
        SUM(CASE WHEN risk_pct <= 10 THEN 1 ELSE 0 END) le10,
        COUNT(*) total
    FROM sim_portfolio_trades
    WHERE outcome != 'Skipped'
       OR skip_reason NOT LIKE '%Capital%'
""").fetchone()
print('Signals from sim (excl capital-limit skips):')
print(f"  risk <=6%:  {rows2['le6']} of {rows2['total']}")
print(f"  risk <=8%:  {rows2['le8']} of {rows2['total']}")
print(f"  risk <=10%: {rows2['le10']} of {rows2['total']}")

conn.close()
