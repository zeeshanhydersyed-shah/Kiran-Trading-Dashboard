from database import get_conn
with get_conn() as conn:
    latest = conn.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    today_count = conn.execute("SELECT COUNT(*) FROM prices WHERE date = '2026-05-04'").fetchone()[0]
    kse_today = conn.execute("SELECT close FROM index_prices WHERE symbol='KSE-100' AND date='2026-05-04'").fetchone()
    # Check setups table (live screener output)
    try:
        setups = conn.execute("SELECT COUNT(*) FROM setups WHERE date >= date('now','-7 days')").fetchone()[0]
        recent_setups = conn.execute("""
            SELECT date, symbol, direction, entry_price, outcome
            FROM setups ORDER BY date DESC LIMIT 10
        """).fetchall()
    except Exception as e:
        setups = f"error: {e}"
        recent_setups = []

print(f"Latest price date   : {latest}")
print(f"Symbols on 2026-05-04: {today_count}")
print(f"KSE-100 on 2026-05-04: {kse_today}")
print(f"Recent setups (7d)  : {setups}")
if recent_setups:
    print("\nRecent setups:")
    for r in recent_setups:
        print(f"  {r}")
