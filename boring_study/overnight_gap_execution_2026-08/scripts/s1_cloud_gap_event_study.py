"""
s1 -- READ-ONLY event study: overnight gaps following Boring Breakout signals.
Runs against the CLOUD `boring_signals` table (Explorer "Boring Breakouts" tab),
2026-07-10 -> 2026-08-27 -- the first, small, live sample.

    signal fires EOD on day t  ->  trader can only act at Open(t+1)
    gap% = (Open(t+1) - Close(t)) / Close(t) * 100

Close(t) from prices_adjusted for the signal_date (cross-checked vs trigger_price).
Open(t+1) = open of the next trading date for that symbol. SELECT-only, no writes.
"""
import numpy as np
import pandas as pd
import psycopg2.extras
from _paths import cloud_conn, DATA
import os

conn = cloud_conn()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("""
    SELECT id, symbol, signal_date::text AS signal_date, lookback_n,
           CAST(trigger_price AS DOUBLE PRECISION)  AS trigger_price,
           CAST(breakout_level AS DOUBLE PRECISION) AS breakout_level,
           rs_60_decile, liquidity_pass, strategy_confirmed, status
    FROM boring_signals
    ORDER BY signal_date, symbol, lookback_n
""")
sig = pd.DataFrame(cur.fetchall())
print(f"boring_signals rows: {len(sig)}")
if sig.empty:
    raise SystemExit("no boring signals in cloud DB")

print(f"signal_date range : {sig.signal_date.min()} -> {sig.signal_date.max()}")
print(f"distinct symbols   : {sig.symbol.nunique()}")
print(f"distinct (symbol,signal_date) events: {sig.groupby(['symbol','signal_date']).ngroups}")
print(f"lookback_n split   : {sig.lookback_n.value_counts().to_dict()}")
print(f"strategy_confirmed : {sig.strategy_confirmed.value_counts().to_dict()}")
print(f"status split       : {sig.status.value_counts().to_dict()}")

symbols = sorted(sig.symbol.unique())
cur.execute("""
    SELECT symbol, date::text AS date,
           CAST(open  AS DOUBLE PRECISION) AS open,
           CAST(high  AS DOUBLE PRECISION) AS high,
           CAST(low   AS DOUBLE PRECISION) AS low,
           CAST(close AS DOUBLE PRECISION) AS close
    FROM prices_adjusted
    WHERE symbol = ANY(%s) AND date >= '2026-06-01'
    ORDER BY symbol, date
""", (symbols,))
px = pd.DataFrame(cur.fetchall()).sort_values(["symbol", "date"]).reset_index(drop=True)

cur.execute("""
    SELECT symbol, date::text AS date,
           CAST(open  AS DOUBLE PRECISION) AS open,
           CAST(close AS DOUBLE PRECISION) AS close
    FROM prices
    WHERE symbol = ANY(%s) AND date >= '2026-06-01'
    ORDER BY symbol, date
""", (symbols,))
praw = pd.DataFrame(cur.fetchall())
conn.close()

by_sym = {s: g.reset_index(drop=True) for s, g in px.groupby("symbol")}
by_sym_raw = {s: g.reset_index(drop=True) for s, g in praw.groupby("symbol")} if not praw.empty else {}

rows = []
for r in sig.itertuples(index=False):
    g = by_sym.get(r.symbol)
    rec = dict(symbol=r.symbol, signal_date=r.signal_date, lookback_n=r.lookback_n,
               strategy_confirmed=r.strategy_confirmed, status=r.status,
               trigger_price=r.trigger_price)
    if g is None:
        rec["note"] = "no adj price history"
        rows.append(rec); continue
    di = g.index[g.date == r.signal_date]
    if len(di) == 0:
        rec["note"] = "signal_date not in adj prices"
        rows.append(rec); continue
    i = di[0]
    if i + 1 >= len(g):
        rec["note"] = "no next trading day yet"
        rows.append(rec); continue

    close_t = g.loc[i, "close"]
    nxt = g.loc[i + 1]
    rec.update(close_t=close_t, next_date=nxt["date"], next_open=nxt["open"],
               next_high=nxt["high"], next_low=nxt["low"], next_close=nxt["close"])
    if close_t is None or close_t <= 0 or nxt["open"] is None or nxt["open"] <= 0 or np.isnan(nxt["open"]):
        rec["note"] = "missing/zero open or close"
        rows.append(rec); continue

    gap = (nxt["open"] - close_t) / close_t * 100.0
    rec["gap_pct"] = gap
    rec["gap_up"] = gap > 0
    rec["gap_vs_trigger_pct"] = (nxt["open"] - r.trigger_price) / r.trigger_price * 100.0 if r.trigger_price else np.nan
    rec["fillable_at_close_t"] = (nxt["low"] is not None and not np.isnan(nxt["low"]) and nxt["low"] <= close_t)
    gr = by_sym_raw.get(r.symbol)
    if gr is not None:
        dj = gr.index[gr.date == r.signal_date]
        if len(dj) and dj[0] + 1 < len(gr):
            rc = gr.loc[dj[0], "close"]; ro = gr.loc[dj[0] + 1, "open"]
            if rc and ro and rc > 0 and ro > 0 and not np.isnan(ro):
                rec["gap_pct_raw"] = (ro - rc) / rc * 100.0
    rows.append(rec)

res = pd.DataFrame(rows)


def summarize(d, label):
    ev = d[d.gap_pct.notna()].copy()
    n = len(ev)
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    print(f"  signals with a measurable gap : {n}   (of {len(d)} rows)")
    if n == 0:
        return
    up, dn, flat = ev[ev.gap_pct > 0], ev[ev.gap_pct < 0], ev[ev.gap_pct == 0]
    print(f"  gap UP   (open > prev close)  : {len(up):3d}  ({len(up)/n*100:5.1f}%)")
    print(f"  flat     (open = prev close)  : {len(flat):3d}  ({len(flat)/n*100:5.1f}%)")
    print(f"  gap DOWN (open < prev close)  : {len(dn):3d}  ({len(dn)/n*100:5.1f}%)")
    print(f"  mean gap {ev.gap_pct.mean():+.2f}%   median {ev.gap_pct.median():+.2f}%   "
          f"mean|gap| {ev.gap_pct.abs().mean():.2f}%")
    if len(up):
        print(f"  gap-UP subset (n={len(up)}): mean {up.gap_pct.mean():.2f}%  median {up.gap_pct.median():.2f}%  "
              f"max {up.gap_pct.max():.2f}%")
    if "fillable_at_close_t" in ev and len(up):
        fu = up[up.fillable_at_close_t == True]
        print(f"  of the {len(up)} gap-ups, {len(fu)} ({len(fu)/len(up)*100:.0f}%) had next-day LOW <= Close(t)")


summarize(res, "ALL boring_signals rows (each lookback_n counted separately)")
dedup = (res.sort_values(["symbol", "signal_date", "lookback_n"])
             .groupby(["symbol", "signal_date"], as_index=False).first())
summarize(dedup, "DE-DUPLICATED to one event per (symbol, signal_date)")
for val, name in [(True, "Strategy Confirmed"), (False, 'NOT confirmed ("Not Fit")')]:
    sub = dedup[dedup.strategy_confirmed == val]
    if len(sub):
        summarize(sub, f"DE-DUP -- {name}")

outcol = [c for c in ["symbol", "signal_date", "lookback_n", "strategy_confirmed", "status",
                      "close_t", "trigger_price", "next_date", "next_open", "next_low",
                      "gap_pct", "gap_pct_raw", "gap_vs_trigger_pct", "fillable_at_close_t", "note"]
          if c in res.columns]
out = os.path.join(DATA, "cloud_gap_detail.csv")
res.sort_values(["signal_date", "symbol", "lookback_n"])[outcol].to_csv(out, index=False)
print(f"\nper-signal detail -> {out}")
