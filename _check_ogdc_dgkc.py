import sys
sys.path.insert(0, r"C:\Users\Lenovo\psx_pipeline")
from database import get_conn

with get_conn() as conn:
    rows = conn.execute("""
        SELECT as_of_date, symbol, direction, entry_price, stop_loss,
               risk_pct, stock_perf_30d, stock_perf_60d, quality_score,
               entry_triggered, outcome, realized_r
        FROM backtest_setups
        WHERE symbol IN ('OGDC', 'DGKC')
        ORDER BY as_of_date, symbol
    """).fetchall()

print(f"OGDC+DGKC setups found: {len(rows)}")
print(f"{'Date':<12} {'Sym':<5} {'Dir':<5} {'Entry':>7} {'SL':>7} {'Risk%':>6} {'P30':>7} {'P60':>7} Q  Outcome         R")
print("-" * 95)
for r in rows:
    p30 = f"{r[6]:+.1f}%" if r[6] is not None else "   N/A"
    p60 = f"{r[7]:+.1f}%" if r[7] is not None else "   N/A"
    outcome = r[10] or "pending"
    rv = f"{r[11]:.2f}" if r[11] is not None else "—"
    print(f"{r[0]:<12} {r[1]:<5} {r[2]:<5} {r[3]:>7.2f} {r[4]:>7.2f} {r[5]:>5.1f}%  {p30:>7}  {p60:>7}  {r[8]}  {outcome:<16} {rv}")
