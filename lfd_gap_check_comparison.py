"""
lfd_gap_check_comparison.py
-------------------------------
Real-data run of lfd_gap_check.py (13/13 synthetic tests passing) against
every candidate in stop_loss_three_way_results.csv whose realized_R_lfd
is exactly -1.0 -- i.e. every candidate where the current walk-forward
model assumes the LFD stop was hit and filled cleanly at the LFD level.
Not scoped to the primary (Type-4-excluded) set -- this is a pure
data-quality/gap-risk check on the LFD mechanism itself, independent of
the Type-based stop comparison.
"""

import sqlite3
import pandas as pd

from research_filters import drop_placeholder_zero_bars
from lfd_gap_check import check_lfd_gap

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"

res = pd.read_csv("stop_loss_three_way_results.csv")
hit = res[res["realized_R_lfd"] == -1.0].copy()
print(f"Candidates with realized_R_lfd == -1.0 (assumed clean LFD stop-out): {len(hit)} / {len(res)}")

conn = sqlite3.connect(DB_PATH)
symbol_cache = {}

rows = []
anomalies = []

for _, cand in hit.iterrows():
    sym = cand["symbol"]
    trigger_bar = int(cand["lfd_hit_bar"])

    if sym not in symbol_cache:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices_adjusted WHERE symbol = ? ORDER BY date",
            conn, params=(sym,)
        )
        df = drop_placeholder_zero_bars(df)
        symbol_cache[sym] = df["open"].tolist()

    opens = symbol_cache[sym]

    if trigger_bar >= len(opens):
        anomalies.append((sym, cand["start"], cand["end"], "trigger_bar out of range"))
        continue

    open_price = opens[trigger_bar]
    if open_price is None or pd.isna(open_price) or open_price <= 0:
        anomalies.append((sym, cand["start"], cand["end"], f"invalid open price at trigger bar: {open_price}"))
        continue

    g = check_lfd_gap(
        direction=cand["direction"], open_price=open_price, lfd_level=cand["lfd_level"],
        entry_price=cand["entry_price"], r_lfd_denom=cand["r_lfd_denom"],
    )

    rows.append({
        "sector": cand["sector"], "symbol": sym, "start": cand["start"], "end": cand["end"],
        "kind": cand["kind"], "outcome": cand["outcome"], "direction": cand["direction"],
        "type_trigger": cand["type_trigger"], "trigger_bar": trigger_bar,
        "entry_price": cand["entry_price"], "lfd_level": cand["lfd_level"], "open_at_trigger": open_price,
        "gapped": g.gapped, "realistic_exit_price": g.realistic_exit_price,
        "realistic_realized_R": g.realistic_realized_R, "worse_by_R": g.worse_by_R,
    })

conn.close()

out = pd.DataFrame(rows)
out.to_csv("C:/Users/Lenovo/psx_pipeline/lfd_gap_check_results.csv", index=False)

print(f"\n{len(out)} candidates checked, {len(anomalies)} anomalies")
for a in anomalies:
    print(f"  ANOMALY: {a}")

n_gapped = out["gapped"].sum()
print(f"\n{'='*70}\nGAP-THROUGH FREQUENCY: {n_gapped}/{len(out)} ({n_gapped/len(out)*100:.1f}%)\n{'='*70}")

gapped = out[out["gapped"]].copy()
if len(gapped):
    print(f"\n--- worse_by_R distribution, gapped candidates only (n={len(gapped)}) ---")
    print(gapped["worse_by_R"].describe().to_string())

    print(f"\n--- worse_by_R percentiles ---")
    for p in [0.5, 0.75, 0.90, 0.95, 0.99, 1.0]:
        print(f"  {p*100:.0f}th percentile: {gapped['worse_by_R'].quantile(p):.4f}")

    print(f"\n--- 10 worst gap-through cases ---")
    print(gapped.sort_values("worse_by_R").head(10)[
        ["symbol", "start", "end", "direction", "entry_price", "lfd_level", "open_at_trigger",
         "realistic_realized_R", "worse_by_R"]
    ].to_string())

    print(f"\n--- how many gapped candidates exceed common floor thresholds (in realistic_realized_R) ---")
    for floor in [-1.5, -2.0, -3.0]:
        n = (gapped["realistic_realized_R"] < floor).sum()
        print(f"  worse than {floor}R: {n}/{len(gapped)} ({n/len(gapped)*100:.1f}% of gapped, "
              f"{n/len(out)*100:.2f}% of all LFD-stop-hit candidates)")

print(f"\nSaved {len(out)} rows to lfd_gap_check_results.csv")
