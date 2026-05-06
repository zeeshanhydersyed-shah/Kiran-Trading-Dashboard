import sys
sys.path.insert(0, r"C:\Users\Lenovo\psx_pipeline")
from database import get_conn

# Raw prices — no calculations, exactly as stored
with get_conn() as conn:
    rows = conn.execute("""
        SELECT date, high, low, close, volume
        FROM prices
        WHERE symbol = 'OGDC'
          AND date >= '2025-04-01'
          AND date <= '2025-08-31'
        ORDER BY date
    """).fetchall()

print(f"{'Date':<12} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>15}")
print("-" * 60)
for r in rows:
    date, high, low, close, vol = r
    print(f"{date:<12} {str(high) if high else 'NULL':>10} {str(low) if low else 'NULL':>10} {close:>10} {int(vol) if vol else 0:>15,}")

print(f"\nTotal rows: {len(rows)}")
