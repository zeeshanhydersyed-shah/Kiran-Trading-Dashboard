"""
Audit trigger lag across all backtest setups.
Shows how many days elapsed between setup date and actual trigger date.
Flags cases where the entry fired months after the base was formed.
"""
import sys
sys.path.insert(0, r"C:\Users\Lenovo\psx_pipeline")
from database import get_conn
from datetime import date

with get_conn() as conn:
    rows = conn.execute("""
        SELECT as_of_date, symbol, direction, entry_price, stop_loss,
               risk_pct, quality_score,
               entry_triggered, trigger_date, outcome, realized_r,
               support_level, resistance_level, range_width_pct
        FROM backtest_setups
        ORDER BY as_of_date, symbol
    """).fetchall()

# ── Lag distribution ──────────────────────────────────────────────────────────
print("=" * 70)
print("TRIGGER LAG DISTRIBUTION  (setup_date → trigger_date)")
print("=" * 70)

triggered = [(r, (date.fromisoformat(r[8]) - date.fromisoformat(r[0])).days)
             for r in rows if r[7] == 1 and r[8]]

buckets = {
    "0–5d   (same week)":   0,
    "6–15d  (2–3 weeks)":   0,
    "16–30d (1 month)":     0,
    "31–60d (1–2 months)":  0,
    "61–90d (2–3 months)":  0,
    "90d+   (stale)":       0,
}
for _, lag in triggered:
    if lag <= 5:   buckets["0–5d   (same week)"]   += 1
    elif lag <= 15: buckets["6–15d  (2–3 weeks)"]  += 1
    elif lag <= 30: buckets["16–30d (1 month)"]     += 1
    elif lag <= 60: buckets["31–60d (1–2 months)"]  += 1
    elif lag <= 90: buckets["61–90d (2–3 months)"]  += 1
    else:           buckets["90d+   (stale)"]        += 1

for bucket, count in buckets.items():
    pct = count / len(triggered) * 100
    bar = "#" * int(pct / 2)
    print(f"  {bucket}: {count:>4}  ({pct:5.1f}%)  {bar}")

print(f"\n  Total triggered: {len(triggered)}")
avg_lag = sum(l for _, l in triggered) / len(triggered) if triggered else 0
print(f"  Average lag    : {avg_lag:.0f} days")
max_lag = max((l for _, l in triggered), default=0)
print(f"  Max lag        : {max_lag} days")

# ── Win rate by lag bucket ─────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("WIN RATE BY TRIGGER LAG")
print("=" * 70)
wins_by_lag = {}
for r, lag in triggered:
    outcome = r[10]
    win = outcome in ("Win_Trail", "Win_T1")
    bucket_key = (0 if lag <= 5 else 1 if lag <= 15 else 2 if lag <= 30
                  else 3 if lag <= 60 else 4 if lag <= 90 else 5)
    if bucket_key not in wins_by_lag:
        wins_by_lag[bucket_key] = [0, 0]
    wins_by_lag[bucket_key][0] += 1
    if win:
        wins_by_lag[bucket_key][1] += 1

labels = ["0–5d", "6–15d", "16–30d", "31–60d", "61–90d", "90d+"]
for k, label in enumerate(labels):
    if k in wins_by_lag:
        n, w = wins_by_lag[k]
        wr = w / n * 100
        print(f"  {label:<10}: {w:>3}/{n:<4} = {wr:5.1f}% WR")

# ── Worst offenders: long lag + loss ──────────────────────────────────────────
print("\n" + "=" * 70)
print("STALE TRIGGERS (lag > 30d)  — sorted by lag desc")
print("=" * 70)
print(f"{'Setup':>12} {'Symbol':<8} {'Dir':<5} {'Entry':>7} {'SL':>7} "
      f"{'Risk%':>6} {'Lag':>5} {'Trigger':>12}  Outcome     R")
print("-" * 80)
stale = [(r, lag) for r, lag in triggered if lag > 30]
stale.sort(key=lambda x: -x[1])
for r, lag in stale[:30]:
    rv = f"{r[10]:.2f}" if r[10] is not None else "—"
    print(f"{r[0]:>12} {r[1]:<8} {r[2]:<5} {r[3]:>7.2f} {r[4]:>7.2f} "
          f"{r[5]:>5.1f}%  {lag:>3}d  {r[8]:>12}  {r[9]:<12} {rv}")

# ── NBP specifically ───────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("NBP ALL SETUPS")
print("=" * 70)
with get_conn() as conn:
    nbp = conn.execute("""
        SELECT as_of_date, direction, entry_price, stop_loss, risk_pct,
               quality_score, entry_triggered, trigger_date, outcome, realized_r,
               support_level, resistance_level, range_width_pct
        FROM backtest_setups
        WHERE symbol = 'NBP'
        ORDER BY as_of_date
    """).fetchall()

for r in nbp:
    lag_str = ""
    if r[6] == 1 and r[7]:
        lag = (date.fromisoformat(r[7]) - date.fromisoformat(r[0])).days
        lag_str = f"  LAG={lag}d"
    rv = f"{r[9]:.2f}" if r[9] is not None else "—"
    print(f"{r[0]}  {r[1]:<5}  entry={r[2]:.2f}  sl={r[3]:.2f}  "
          f"risk={r[4]:.1f}%  Q={r[5]}  "
          f"triggered={r[6]}  on={r[7]}  => {r[8]}  R={rv}{lag_str}")
