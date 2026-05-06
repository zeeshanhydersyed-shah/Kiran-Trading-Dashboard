"""
DGKC Setup Audit: May 8 – Aug 5, 2025
Same day-by-day screener logic audit as OGDC.
"""
import sys
sys.path.insert(0, r"C:\Users\Lenovo\psx_pipeline")
from database import get_conn
import pandas as pd

# ── Raw prices first ───────────────────────────────────────────────────────────
with get_conn() as conn:
    rows = conn.execute("""
        SELECT date,
               COALESCE(high, close) as high,
               COALESCE(low,  close) as low,
               close, volume
        FROM prices
        WHERE symbol = 'DGKC'
          AND date >= '2024-12-01'
          AND date <= '2025-08-20'
        ORDER BY date
    """).fetchall()

df = pd.DataFrame(rows, columns=["date","high","low","close","volume"])
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

print(f"DGKC rows loaded: {len(df)}")
print(f"Date range: {df['date'].min().date()} to {df['date'].max().date()}")
print(f"Price range in window: low={df[df['date']>='2025-05-01']['low'].min():.2f}  high={df[df['date']>='2025-05-01']['high'].max():.2f}")

# ── Indicators ─────────────────────────────────────────────────────────────────
df["ma10"]      = df["close"].rolling(10).mean()
df["ma20"]      = df["close"].rolling(20).mean()
df["vol10"]     = df["volume"].rolling(10).mean()
df["vol_ratio"] = df["volume"] / df["vol10"]
df["perf_5d"]   = df["close"].pct_change(5)  * 100
df["perf_10d"]  = df["close"].pct_change(10) * 100
df["perf_30d"]  = df["close"].pct_change(30) * 100
df["perf_60d"]  = df["close"].pct_change(60) * 100

def momentum_label(row):
    p5, p10 = row["perf_5d"], row["perf_10d"]
    if pd.isna(p5) or pd.isna(p10): return "Unknown"
    if p10 > 5  and p5 > 0:  return "Heating Up"
    if p10 > 0  and p5 > 0:  return "Cooling Down"
    if p10 > 5  and p5 <= 0: return "Cooling Down"
    if p10 <= 0 and p5 <= 0: return "Falling"
    if p10 <= 0 and p5 > 0:  return "Rolling Over"
    return "Neutral"

df["momentum"] = df.apply(momentum_label, axis=1)

WINDOW     = 20
ENTRY_BUF  = 0.005
SL_BUF     = 0.010
MAX_RISK   = 6.0

def get_sr(df_slice, window=WINDOW):
    w = df_slice.tail(window)
    return w["high"].max(), w["low"].min()

# ── RAW price table for the focus window ──────────────────────────────────────
focus_start = pd.Timestamp("2025-05-08")
focus_end   = pd.Timestamp("2025-08-05")
focus = df[(df["date"] >= focus_start) & (df["date"] <= focus_end)].copy()

print("\n" + "=" * 90)
print("DGKC  RAW PRICES  |  08-May-2025 to 05-Aug-2025")
print("=" * 90)
print(f"{'Date':<12} {'High':>7} {'Low':>7} {'Close':>7} {'Chg%':>6}  {'Volume':>12}  {'VolRatio':>8}")
print("-" * 70)
prev_close = None
for _, r in focus.iterrows():
    chg = ((r["close"] - prev_close) / prev_close * 100) if prev_close else 0
    vflag = " ***" if r["vol_ratio"] > 1.5 else ("  **" if r["vol_ratio"] > 1.2 else "")
    print(f"{r['date'].strftime('%d-%b-%y'):<12} {r['high']:>7.2f} {r['low']:>7.2f} {r['close']:>7.2f} "
          f"{chg:>+6.1f}%  {int(r['volume'] or 0):>12,}  {r['vol_ratio']:>7.2f}x{vflag}")
    prev_close = r["close"]

# ── Day-by-day screener audit ──────────────────────────────────────────────────
focus_idx = df[(df["date"] >= focus_start) & (df["date"] <= focus_end)].index

print("\n" + "=" * 110)
print("DGKC SCREENER AUDIT  |  08-May-2025 to 05-Aug-2025")
print("=" * 110)
print(f"{'Date':<12} {'Close':>7} {'P30d':>7} {'P60d':>7} {'Momentum':<14} "
      f"{'Resist':>7} {'Supprt':>7} {'Rng%':>5} {'Entry':>7} {'Risk%':>6}  Result")
print("-" * 110)

for i in focus_idx:
    row   = df.iloc[i]
    date  = row["date"]
    close = row["close"]
    p30   = row["perf_30d"]
    p60   = row["perf_60d"]
    mom   = row["momentum"]
    vr    = row["vol_ratio"]

    df_upto = df[df["date"] <= date]
    resistance, support = get_sr(df_upto, WINDOW)
    range_pct = (resistance - support) / support * 100
    entry     = round(resistance * (1 + ENTRY_BUF), 2)
    sl        = round(support    * (1 - SL_BUF),    2)
    risk_pct  = (entry - sl) / entry * 100

    cond_mom   = mom in ("Heating Up", "Cooling Down")
    cond_p30   = (not pd.isna(p30)) and p30 >= 15.0
    cond_near  = close >= resistance * 0.985
    cond_risk  = risk_pct <= MAX_RISK
    cond_range = range_pct <= 12.0

    fails = []
    if not cond_mom:   fails.append(f"mom={mom[:8]}")
    if not cond_p30:   fails.append(f"p30={p30:.1f}%")
    if not cond_near:  fails.append(f"far({close:.0f}<{resistance*0.985:.0f})")
    if not cond_risk:  fails.append(f"risk={risk_pct:.1f}%")
    if not cond_range: fails.append(f"rng={range_pct:.1f}%")

    bo_flag = " <<< BREAKOUT" if date == pd.Timestamp("2025-08-05") else ""
    result  = "*** SETUP ***" if not fails else f"FAIL: {', '.join(fails)}"

    print(f"{date.strftime('%d-%b-%y'):<12} {close:>7.2f} {p30:>+7.1f}% {p60:>+7.1f}% "
          f"{mom:<14} {resistance:>7.2f} {support:>7.2f} {range_pct:>5.1f}% "
          f"{entry:>7.2f} {risk_pct:>5.1f}%  {result}{bo_flag}")

# ── Breakout day detail ────────────────────────────────────────────────────────
bo_date = pd.Timestamp("2025-08-05")
if bo_date in df["date"].values:
    bo = df[df["date"] == bo_date].iloc[0]
    df_upto_bo = df[df["date"] <= bo_date]
    r, s = get_sr(df_upto_bo, WINDOW)
    rng  = (r - s) / s * 100
    entry_bo = round(r * 1.005, 2)
    sl_bo    = round(s * 0.990, 2)
    t1_bo    = round(entry_bo + (entry_bo - sl_bo) * 2, 2)
    risk_bo  = (entry_bo - sl_bo) / entry_bo * 100
    avg_vol  = df_upto_bo.tail(10)["volume"].mean()

    print("\n" + "=" * 60)
    print("BREAKOUT DAY DETAIL  -  05-Aug-2025")
    print("=" * 60)
    print(f"  High         : {bo['high']:.2f}")
    print(f"  Low          : {bo['low']:.2f}")
    print(f"  Close        : {bo['close']:.2f}")
    print(f"  Volume       : {int(bo['volume']):,}  ({bo['volume']/avg_vol:.2f}x avg)")
    print(f"  20d Resist   : {r:.2f}")
    print(f"  20d Support  : {s:.2f}")
    print(f"  Range        : {rng:.1f}%")
    print(f"  Perf 30d     : {bo['perf_30d']:+.1f}%")
    print(f"  Perf 60d     : {bo['perf_60d']:+.1f}%")
    print(f"  Momentum     : {bo['momentum']}")

# ── Pre-BO setup (day before) ──────────────────────────────────────────────────
pre_date = pd.Timestamp("2025-08-04")
if pre_date in df["date"].values:
    pre = df[df["date"] == pre_date].iloc[0]
    df_upto_pre = df[df["date"] <= pre_date]
    r2, s2 = get_sr(df_upto_pre, WINDOW)
    rng2    = (r2 - s2) / s2 * 100
    entry2  = round(r2 * 1.005, 2)
    sl2     = round(s2 * 0.990, 2)
    t1_2    = round(entry2 + (entry2 - sl2) * 2, 2)
    risk2   = (entry2 - sl2) / entry2 * 100

    print("\n" + "=" * 60)
    print("PRE-BO SETUP PARAMETERS  -  04-Aug-2025 (day before BO)")
    print("=" * 60)
    print(f"  Close        : {pre['close']:.2f}")
    print(f"  Resistance   : {r2:.2f}   (20d high)")
    print(f"  Support      : {s2:.2f}   (20d low)")
    print(f"  Range        : {rng2:.1f}%")
    print(f"  Entry        : {entry2:.2f}")
    print(f"  Stop         : {sl2:.2f}")
    print(f"  T1 (2R)      : {t1_2:.2f}")
    print(f"  Risk %       : {risk2:.2f}%")
    print(f"  Perf 30d     : {pre['perf_30d']:+.1f}%  => {'PASS' if pre['perf_30d'] >= 15 else 'FAIL (need >=15%)'}")
    print(f"  Perf 60d     : {pre['perf_60d']:+.1f}%")
    print(f"  Momentum     : {pre['momentum']}  => {'PASS' if pre['momentum'] in ('Heating Up','Cooling Down') else 'FAIL'}")

# ── KIRAN backtest setups for DGKC ────────────────────────────────────────────
print("\n" + "=" * 60)
print("KIRAN BACKTEST SETUPS FOR DGKC (all time)")
print("=" * 60)
with get_conn() as conn:
    setups = conn.execute("""
        SELECT as_of_date, direction, entry_price, stop_loss,
               target_1r, quality_score, resistance_level,
               support_level, range_width_pct,
               entry_triggered, trigger_date, outcome, realized_r
        FROM backtest_setups
        WHERE symbol = 'DGKC'
        ORDER BY as_of_date
    """).fetchall()

if not setups:
    print("  No DGKC setups found in backtest_setups.")
else:
    for s in setups:
        print(f"  {s[0]}  [{s[1]}]  entry={s[2]:.2f}  sl={s[3]:.2f}  t1={s[4]:.2f}  "
              f"Q={s[5]}  R={s[6]:.2f}/S={s[7]:.2f}  rng={s[8]:.1f}%  "
              f"triggered={s[9]}  on={s[10]}  => {s[11]}  R={s[12]}")
