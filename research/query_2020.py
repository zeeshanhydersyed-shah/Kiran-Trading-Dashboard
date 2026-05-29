import sqlite3
conn = sqlite3.connect('psx_data.db')
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    SELECT symbol, setup_date, trigger_date, entry_price, stop_loss, target_1r,
           shares, position_value, capital_at_entry, outcome, exit_date, exit_price, pl_pkr, realized_r
    FROM sim_portfolio_trades
    WHERE trigger_date LIKE '2020-%'
    ORDER BY trigger_date
""").fetchall()
print(f"Triggered in 2020: {len(rows)}\n")
print(f"{'Symbol':<10} {'Setup':<12} {'Triggered':<12} {'Entry':>8} {'SL':>8} {'T1':>8} {'Shares':>7} {'PosVal':>9} {'CapEntry':>10} {'Outcome':<12} {'ExitDate':<12} {'ExitPx':>8} {'P/L PKR':>10} {'R':>6}")
print("-" * 140)
for r in rows:
    print(
        f"{r['symbol']:<10} {r['setup_date']:<12} {r['trigger_date']:<12} "
        f"{r['entry_price']:>8.2f} {r['stop_loss']:>8.2f} {r['target_1r']:>8.2f} "
        f"{r['shares']:>7} {r['position_value']:>9.0f} {r['capital_at_entry']:>10.0f} "
        f"{r['outcome']:<12} {str(r['exit_date'] or '-'):<12} "
        f"{float(r['exit_price'] or 0):>8.2f} {float(r['pl_pkr'] or 0):>10.0f} {float(r['realized_r'] or 0):>6.2f}"
    )
conn.close()
