from database import get_conn
from kse100_filter import KSE100Filter
import pandas as pd

# Check KSE-100 regime history
kse = KSE100Filter()
df = kse._df.copy()
df['above_ma50'] = df['close'] >= df['ma50']
above = int(df['above_ma50'].sum())
below = int(df['above_ma50'].eq(False).sum())
na_rows = int(df['ma50'].isna().sum())
print(f"KSE-100 rows total        : {len(df)}")
print(f"Above 50MA (LONG ok)      : {above}")
print(f"Below 50MA (LONG blocked) : {below}")
print(f"MA not yet computed (~50d): {na_rows}")
below_pct = below / (above + below) * 100 if (above + below) > 0 else 0
print(f"Pct of days market BELOW 50MA: {below_pct:.1f}%")

# Show which date ranges were blocked
below_dates = df[df['above_ma50'] == False].index
if len(below_dates):
    print(f"\nEarliest LONG-blocked date: {below_dates[0].date()}")
    print(f"Latest  LONG-blocked date: {below_dates[-1].date()}")

print()

# Backtest stats
with get_conn() as conn:
    rows = conn.execute("""
        SELECT outcome, COUNT(*) as n,
               ROUND(SUM(realized_r),1) as total_r,
               ROUND(AVG(realized_r),2) as avg_r
        FROM backtest_setups
        GROUP BY outcome ORDER BY n DESC
    """).fetchall()

    net_r = conn.execute("""
        SELECT ROUND(SUM(realized_r),1)
        FROM backtest_setups
        WHERE outcome NOT IN ('No_Trigger','Expired')
    """).fetchone()[0]

    total_n = conn.execute("SELECT COUNT(*) FROM backtest_setups").fetchone()[0]

print("Backtest outcome summary:")
for o, n, tr, ar in rows:
    print(f"  {o:<12}  n={n:>3}  total_R={str(tr):>7}  avg_R={ar}")
print(f"\nTotal setups : {total_n}")
print(f"Net R (active trades): {net_r}")

win_n = sum(r[1] for r in rows if r[0] in ('Win_Trail','Win_T1'))
loss_n = sum(r[1] for r in rows if r[0] == 'Loss')
if win_n + loss_n > 0:
    wr = win_n / (win_n + loss_n) * 100
    print(f"Win rate (excl No_Trigger/Expired): {wr:.1f}%  ({win_n}W / {loss_n}L)")
