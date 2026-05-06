"""Quick check: what setups does the KIRAN screener generate for today?"""
import sys
from datetime import date
sys.path.insert(0, r"C:\Users\Lenovo\psx_pipeline")

from database import init_db
from processor import run_analysis

init_db()

today = date.today()
print(f"Running live screener for: {today}")

data = run_analysis()
setups = data.get("trade_setups", [])

print(f"Market breadth : {data.get('breadth_label', 'N/A')}")
print(f"Long candidates: {len(data.get('long_candidates', []))}")
print(f"Short candidates: {len(data.get('short_candidates', []))}")
print(f"\nSetups generated: {len(setups)}")
if setups:
    for s in setups:
        print(f"  [{s['direction']}] {s['symbol']} | entry={s.get('entry_price',0):.2f} "
              f"sl={s.get('stop_loss',0):.2f} t1={s.get('target_1r',0):.2f} | "
              f"Q={s.get('quality_score','?')} | mom={s.get('momentum_label','?')}")
else:
    print("  No setups qualifying today.")
