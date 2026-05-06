"""
OGDC breakout analysis: 09-May-2025 to 04-Aug-2025
"""
import sys
sys.path.insert(0, r"C:\Users\Lenovo\psx_pipeline")

from database import get_conn
import pandas as pd

# ── 1. Pull OGDC price data (wider window for context) ────────────────────────
with get_conn() as conn:
    rows = conn.execute("""
        SELECT date, high, low, close,
               COALESCE(high, close) as h,
               COALESCE(low,  close) as l,
               volume
        FROM prices
        WHERE symbol = 'OGDC'
          AND date >= '2025-01-01'
          AND date <= '2025-08-31'
        ORDER BY date
    """).fetchall()

df = pd.DataFrame(rows, columns=["date","high_raw","low_raw","close","high","low","volume"])
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

# ── 2. Add indicators ─────────────────────────────────────────────────────────
df["ma10"]   = df["close"].rolling(10).mean()
df["ma20"]   = df["close"].rolling(20).mean()
df["ma50"]   = df["close"].rolling(50).mean()
df["vol10"]  = df["volume"].rolling(10).mean()
df["vol_ratio"] = (df["volume"] / df["vol10"]).round(2)
df["chg_pct"]   = df["close"].pct_change() * 100

# ── 3. Focus window ───────────────────────────────────────────────────────────
focus = df[(df["date"] >= "2025-05-09") & (df["date"] <= "2025-08-04")].copy()
focus = focus.reset_index(drop=True)

print("=" * 70)
print("OGDC  |  09-May-2025  to  04-Aug-2025")
print("=" * 70)
print(f"{'Date':<12} {'Close':>7} {'High':>7} {'Low':>7} {'Chg%':>6} {'Volume':>12} {'VolRatio':>9} {'MA10':>7} {'MA50':>7}")
print("-" * 70)
for _, r in focus.iterrows():
    vol_flag = " ***" if r["vol_ratio"] > 1.5 else ("  **" if r["vol_ratio"] > 1.2 else "")
    print(f"{r['date'].strftime('%d-%b-%y'):<12} "
          f"{r['close']:>7.2f} "
          f"{r['high']:>7.2f} "
          f"{r['low']:>7.2f} "
          f"{r['chg_pct']:>+6.1f}% "
          f"{int(r['volume'] or 0):>12,} "
          f"{r['vol_ratio']:>9.2f}x"
          f"{vol_flag}")

# ── 4. Consolidation analysis ──────────────────────────────────────────────────
# Identify the pre-BO consolidation range
# Find resistance (highest High) and support (lowest Low) in the range
# Typical window: 10-20 days before the BO

print("\n" + "=" * 70)
print("CONSOLIDATION WINDOWS")
print("=" * 70)

windows = [
    ("Pre-May-09 (20d)",  "2025-03-24", "2025-05-09"),
    ("Pre-May-09 (10d)",  "2025-04-24", "2025-05-09"),
    ("May-09 to Jul-31",  "2025-05-09", "2025-07-31"),
    ("May-09 to Aug-04",  "2025-05-09", "2025-08-04"),
]

for label, start, end in windows:
    w = df[(df["date"] >= start) & (df["date"] <= end)]
    if w.empty:
        continue
    resistance = w["high"].max()
    support    = w["low"].min()
    range_pct  = (resistance - support) / support * 100
    r_date     = w.loc[w["high"].idxmax(), "date"].strftime("%d-%b-%y")
    s_date     = w.loc[w["low"].idxmin(), "date"].strftime("%d-%b-%y")
    print(f"\n  {label}")
    print(f"    Resistance: {resistance:.2f}  (on {r_date})")
    print(f"    Support   : {support:.2f}  (on {s_date})")
    print(f"    Range     : {range_pct:.1f}%")

# ── 5. Check backtest_setups for OGDC ─────────────────────────────────────────
print("\n" + "=" * 70)
print("KIRAN BACKTEST SETUPS FOR OGDC (all time)")
print("=" * 70)

with get_conn() as conn:
    setups = conn.execute("""
        SELECT as_of_date, direction, entry_price, stop_loss, target_1r, target_2r,
               quality_score, resistance_level, support_level, range_width_pct,
               entry_triggered, trigger_date, outcome, realized_r
        FROM backtest_setups
        WHERE symbol = 'OGDC'
        ORDER BY as_of_date
    """).fetchall()

cols = ["as_of_date","direction","entry","sl","t1","t2",
        "quality","resistance","support","range_pct",
        "triggered","trigger_date","outcome","realized_r"]

if not setups:
    print("  No OGDC setups found in backtest_setups.")
else:
    for s in setups:
        sd = dict(zip(cols, s))
        print(f"\n  Date: {sd['as_of_date']}  [{sd['direction']}]  Q={sd['quality']}")
        print(f"    Entry={sd['entry']:.2f}  SL={sd['sl']:.2f}  T1={sd['t1']:.2f}  T2={sd['t2']:.2f}")
        print(f"    Resistance={sd['resistance']:.2f}  Support={sd['support']:.2f}  Range={sd['range_pct']:.1f}%")
        print(f"    Triggered={sd['triggered']}  on {sd['trigger_date']}  => {sd['outcome']}  R={sd['realized_r']}")

# ── 6. Check specifically around Aug 4 ────────────────────────────────────────
print("\n" + "=" * 70)
print("OGDC PRICE ACTION: LAST 5 DAYS BEFORE & AROUND 04-AUG-2025")
print("=" * 70)
aug_window = df[(df["date"] >= "2025-07-25") & (df["date"] <= "2025-08-07")]
for _, r in aug_window.iterrows():
    print(f"  {r['date'].strftime('%d-%b-%y')}  close={r['close']:.2f}  high={r['high']:.2f}  "
          f"low={r['low']:.2f}  vol={int(r['volume'] or 0):,}  vol_ratio={r['vol_ratio']:.2f}x  "
          f"ma10={r['ma10']:.2f}  ma50={r['ma50']:.2f}")
