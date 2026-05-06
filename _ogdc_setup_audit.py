"""
OGDC Setup Audit: May 9 – Aug 4, 2025
Run KIRAN's screener logic on OGDC day by day to show exactly what the
algorithm was seeing during the consolidation and on the breakout day.
"""
import sys
sys.path.insert(0, r"C:\Users\Lenovo\psx_pipeline")

from database import get_conn
import pandas as pd
import numpy as np

# ── Load full OGDC price history ──────────────────────────────────────────────
with get_conn() as conn:
    rows = conn.execute("""
        SELECT date,
               COALESCE(high, close) as high,
               COALESCE(low,  close) as low,
               close, volume
        FROM prices
        WHERE symbol = 'OGDC'
          AND date >= '2024-12-01'
          AND date <= '2025-08-10'
        ORDER BY date
    """).fetchall()

df = pd.DataFrame(rows, columns=["date","high","low","close","volume"])
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

# ── Indicators ────────────────────────────────────────────────────────────────
df["ma10"]       = df["close"].rolling(10).mean()
df["ma20"]       = df["close"].rolling(20).mean()
df["ma50"]       = df["close"].rolling(50).mean()
df["vol10"]      = df["volume"].rolling(10).mean()
df["vol_ratio"]  = df["volume"] / df["vol10"]
df["atr"]        = (df["high"] - df["low"]).rolling(14).mean()
df["atr_pct"]    = df["atr"] / df["close"] * 100

# Performance windows
df["perf_10d"]   = df["close"].pct_change(10) * 100
df["perf_30d"]   = df["close"].pct_change(30) * 100
df["perf_5d"]    = df["close"].pct_change(5)  * 100

# Momentum label (mirrors processor.py logic)
def momentum_label(row):
    p5  = row["perf_5d"]
    p10 = row["perf_10d"]
    if pd.isna(p5) or pd.isna(p10):
        return "Unknown"
    if p10 > 5  and p5 > 0:   return "Heating Up"
    if p10 > 0  and p5 > 0:   return "Cooling Down"
    if p10 > 5  and p5 <= 0:  return "Cooling Down"
    if p10 <= 0 and p5 <= 0:  return "Falling"
    if p10 <= 0 and p5 > 0:   return "Rolling Over"
    return "Neutral"

df["momentum"] = df.apply(momentum_label, axis=1)

# ── Consolidation detector (rolling window, mirrors _consolidation) ───────────
WINDOW = 20   # default lookback
ENTRY_BUF  = 0.005   # 0.5% above resistance
SL_BUF     = 0.010   # 1.0% below support
MAX_RISK   = 6.0     # max risk % of entry
REWARD     = 2.0

def get_consolidation(df_slice, window=WINDOW):
    """Return (resistance, support, range_pct) using H/L."""
    w = df_slice.tail(window)
    resistance = w["high"].max()
    support    = w["low"].min()
    range_pct  = (resistance - support) / support * 100
    return resistance, support, range_pct

# ── Day-by-day audit for the consolidation window ────────────────────────────
focus_start = pd.Timestamp("2025-05-09")
focus_end   = pd.Timestamp("2025-08-04")

focus_idx = df[(df["date"] >= focus_start) & (df["date"] <= focus_end)].index

print("=" * 100)
print("OGDC SCREENER AUDIT  |  09-May-2025 to 04-Aug-2025")
print("LONG conditions: momentum in {Heating Up, Cooling Down}, perf_30d >= 15%,")
print("                 close within entry buffer of resistance, risk <= 6%, range <= 12%")
print("=" * 100)
print(f"{'Date':<12} {'Close':>7} {'H':>7} {'L':>7} {'Vol':>8} {'VRt':>5} "
      f"{'P30d':>6} {'P10d':>6} {'Momentum':<14} "
      f"{'Resist':>7} {'Supprt':>7} {'Rng%':>5} "
      f"{'Entry':>7} {'Risk%':>6} {'Setup?':<20}")
print("-" * 100)

for i in focus_idx:
    row     = df.iloc[i]
    date    = row["date"]
    close   = row["close"]
    high    = row["high"]
    low     = row["low"]
    vol     = row["volume"]
    vr      = row["vol_ratio"]
    p30     = row["perf_30d"]
    p10     = row["perf_10d"]
    mom     = row["momentum"]
    atr_pct = row["atr_pct"]

    # Get consolidation using data up to this date (point-in-time)
    df_upto = df[df["date"] <= date]
    resistance, support, range_pct = get_consolidation(df_upto, window=WINDOW)

    entry   = round(resistance * (1 + ENTRY_BUF), 2)
    sl      = round(support    * (1 - SL_BUF),    2)
    risk_r  = entry - sl
    risk_pct = risk_r / entry * 100 if entry > 0 else 99

    # Check all LONG conditions
    cond_mom    = mom in ("Heating Up", "Cooling Down")
    cond_p30    = (not pd.isna(p30)) and p30 >= 15.0
    cond_near   = close >= resistance * 0.985   # within 1.5% of resistance
    cond_risk   = risk_pct <= MAX_RISK
    cond_range  = range_pct <= 12.0

    passed = cond_mom and cond_p30 and cond_near and cond_risk and cond_range

    # Why failed?
    fails = []
    if not cond_mom:   fails.append(f"mom={mom[:8]}")
    if not cond_p30:   fails.append(f"p30={p30:.1f}%" if not pd.isna(p30) else "p30=N/A")
    if not cond_near:  fails.append(f"far({close:.0f}<{resistance*0.985:.0f})")
    if not cond_risk:  fails.append(f"risk={risk_pct:.1f}%")
    if not cond_range: fails.append(f"rng={range_pct:.1f}%")

    # Breakout marker
    bo_flag = " <<< BREAKOUT" if date == pd.Timestamp("2025-07-31") else ""
    result  = "SETUP" if passed else (f"FAIL: {', '.join(fails)}" if fails else "FAIL")

    print(f"{date.strftime('%d-%b-%y'):<12} {close:>7.2f} {high:>7.2f} {low:>7.2f} "
          f"{int(vol/1e6):>6.1f}M {vr:>5.1f}x "
          f"{p30:>+6.1f}% {p10:>+6.1f}% {mom:<14} "
          f"{resistance:>7.2f} {support:>7.2f} {range_pct:>5.1f}% "
          f"{entry:>7.2f} {risk_pct:>6.1f}% {result}{bo_flag}")

# ── Specific BO-day detail ─────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("BREAKOUT DAY DETAIL  —  31-Jul-2025")
print("=" * 60)
bo_row = df[df["date"] == pd.Timestamp("2025-07-31")].iloc[0]
bo_idx = df[df["date"] == pd.Timestamp("2025-07-31")].index[0]
df_upto_bo = df[df["date"] <= pd.Timestamp("2025-07-31")]
r, s, rng = get_consolidation(df_upto_bo, WINDOW)
print(f"  Open approx  : {bo_row['low']:.2f}  (intraday low)")
print(f"  High         : {bo_row['high']:.2f}")
print(f"  Close        : {bo_row['close']:.2f}")
print(f"  Volume       : {int(bo_row['volume']):,}  ({bo_row['vol_ratio']:.2f}x 10d avg)")
print(f"  20d Resistance (H/L): {r:.2f}")
print(f"  20d Support   (H/L): {s:.2f}")
print(f"  Range        : {rng:.1f}%")
print(f"  Breakout above resistance?: {'YES' if bo_row['close'] > r else 'NO'} (close={bo_row['close']:.2f} vs resist={r:.2f})")
print(f"  Perf 30d     : {bo_row['perf_30d']:+.1f}%")
print(f"  Momentum     : {bo_row['momentum']}")

# Volume comparison
avg_vol = df_upto_bo.tail(10)["volume"].mean()
print(f"  Avg 10d vol  : {avg_vol:,.0f}")
print(f"  BO vol ratio : {bo_row['volume']/avg_vol:.2f}x")

# ── What KIRAN setup would look like if screened PRE-BO ───────────────────────
print("\n" + "=" * 60)
print("WHAT A PRE-BO SETUP (30-Jul-2025) WOULD HAVE LOOKED LIKE")
print("=" * 60)
pre_bo = df[df["date"] == pd.Timestamp("2025-07-30")].iloc[0]
df_upto_pre = df[df["date"] <= pd.Timestamp("2025-07-30")]
r2, s2, rng2 = get_consolidation(df_upto_pre, WINDOW)
entry2  = round(r2 * 1.005, 2)
sl2     = round(s2 * 0.990, 2)
t1      = round(entry2 + (entry2 - sl2) * 2, 2)
risk2   = (entry2 - sl2) / entry2 * 100
print(f"  Close on Jul 30      : {pre_bo['close']:.2f}")
print(f"  Resistance (20d H)   : {r2:.2f}")
print(f"  Support    (20d L)   : {s2:.2f}")
print(f"  Range                : {rng2:.1f}%")
print(f"  Entry (0.5% above R) : {entry2:.2f}")
print(f"  Stop  (1.0% below S) : {sl2:.2f}")
print(f"  Target T1 (2R)       : {t1:.2f}")
print(f"  Risk % of entry      : {risk2:.2f}%")
print(f"  Perf 30d             : {pre_bo['perf_30d']:+.1f}%  <-- {'PASS' if pre_bo['perf_30d'] >= 15 else 'FAIL (need >= 15%)'}")
print(f"  Momentum             : {pre_bo['momentum']}  <-- {'PASS' if pre_bo['momentum'] in ('Heating Up','Cooling Down') else 'FAIL'}")
