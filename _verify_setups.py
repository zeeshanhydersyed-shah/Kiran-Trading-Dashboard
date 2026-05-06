import sys
sys.path.insert(0, r"C:\Users\Lenovo\psx_pipeline")
from processor import run_analysis

data = run_analysis()
setups = data.get("trade_setups", [])
print(f"Setups today: {len(setups)}")
print()
for s in setups:
    p60_str = f"{s['stock_perf_60d']:+.1f}%" if s.get("stock_perf_60d") is not None else "N/A"
    avg_vol = s.get("avg_vol_10d", 0) or 0
    print(f"  {s['symbol']:<6} {s['direction']:<5}  "
          f"risk={s['risk_pct']:.1f}%  "
          f"30d={s['stock_perf_30d']:+.1f}%  "
          f"60d={p60_str}  "
          f"10d={s['stock_perf_10d']:+.1f}%  "
          f"avg_vol={int(avg_vol):,}")
print()
print("Keys:", list(setups[0].keys()) if setups else "no setups")
