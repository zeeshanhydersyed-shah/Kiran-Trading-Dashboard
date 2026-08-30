"""
s4 -- Win rate of bucket (b) "open <= prior close" vs bucket (a) "gap up".
READ-ONLY vs psx_data.db. Reuses data/fullhist_gap_distribution.csv (s3 output:
first-fire signal set + bucket) and adds the trade outcome.

Outcome 1 -- HYBRID trailing stop (production exit): entry = Close(t), stop starts
  at max(Low(t), Entry*0.92) then trails prior-day low; exit first day Low <= stop;
  resolution = stop level. Win = exit above entry.
Outcome 2 -- hit_tp_10: +10% before -6% race, from the already-computed
  boring_heterogeneity_panel_{20,60}d_race.csv (pure join).
"""
import os
import sqlite3
import numpy as np
import pandas as pd
from _paths import DB, BS, DATA

FLOOR = -0.08

det = pd.read_csv(os.path.join(DATA, "fullhist_gap_distribution.csv"))
det = det[det.bucket.isin(["A_gap_up", "F_flat", "C_gap_down"])].copy()
det["b_le_close"] = det.bucket.isin(["F_flat", "C_gap_down"])

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
px = pd.read_sql_query("SELECT symbol, date, high, low, close FROM prices_adjusted ORDER BY symbol, date", con)
con.close()
for c in ("high", "low", "close"):
    px[c] = pd.to_numeric(px[c], errors="coerce")
PF, DIDX = {}, {}
for s, g in px.groupby("symbol", sort=False):
    g = g.reset_index(drop=True)
    PF[s] = {"h": g.high.to_numpy(float), "l": g.low.to_numpy(float), "c": g.close.to_numpy(float)}
    DIDX[s] = {d: i for i, d in enumerate(g.date.to_numpy())}


def hybrid_trail(sym, t):
    pf = PF[sym]; low, close = pf["l"], pf["c"]; n = len(close)
    entry = close[t]
    fl = entry * (1 + FLOOR)
    trail = low[t]; stop = max(trail, fl)
    for d in range(t + 1, n):
        trail = max(trail, low[d - 1]); stop = max(trail, fl)
        if low[d] <= stop:
            return (stop - entry) / entry * 100.0, False
    return (close[n - 1] - entry) / entry * 100.0, True


rets, cens = [], []
for r in det.itertuples(index=False):
    idxmap = DIDX.get(r.symbol)
    if not idxmap or r.date not in idxmap:
        rets.append(np.nan); cens.append(True); continue
    ret, c = hybrid_trail(r.symbol, idxmap[r.date])
    rets.append(ret); cens.append(c)
det["ht_ret"] = rets
det["ht_censored"] = cens
det["ht_win"] = det["ht_ret"] > 0

tp = {}
for lb, pth in [(20, "boring_heterogeneity_panel_20d_race.csv"),
                (60, "boring_heterogeneity_panel_60d_race.csv")]:
    d = pd.read_csv(os.path.join(BS, pth))
    d = d[(d.breakout == 1) & (d.lookback == lb)]
    for row in d.itertuples(index=False):
        tp[(lb, row.symbol, row.date)] = row.hit_tp_10
det["lb"] = det["set"].str.extract(r"N(\d+)").astype(int)
det["hit_tp_10"] = [tp.get((lb, s, dt), np.nan) for lb, s, dt in zip(det.lb, det.symbol, det.date)]


def wr(seg, col):
    d = seg.dropna(subset=[col])
    if col == "ht_win":
        d = d[~d.ht_censored]
    return len(d), int(d[col].sum() if col != "hit_tp_10" else (d[col] == 1).sum())


def block(setname, label):
    d = det[det.set == setname]
    a = d[d.bucket == "A_gap_up"]
    b = d[d.b_le_close]
    print(f"\n{'='*72}\n{label}   (evaluable {len(d)}: gap-up {len(a)}, <=close {len(b)})\n{'='*72}")
    for name, seg in [("(a) Gap Up        ", a), ("(b) <= prior close", b),
                      ("     - unchanged  ", d[d.bucket == 'F_flat']),
                      ("     - gap down   ", d[d.bucket == 'C_gap_down'])]:
        nH, wH = wr(seg, "ht_win")
        nT, wT = wr(seg, "hit_tp_10")
        hs = f"{wH}/{nH} = {wH/nH*100:4.1f}%" if nH else "n/a"
        ts = f"{wT}/{nT} = {wT/nT*100:4.1f}%" if nT else "n/a"
        mret = seg.ht_ret[~seg.ht_censored].mean()
        print(f"  {name}  HYBRID-trail win {hs:>18}   |  +10/-6 race win {ts:>18}   |  mean trail ret {mret:+6.2f}%")


for lb in (20, 60):
    block(f"N{lb}_ALL", f"N={lb}  ALL breakouts")
    block(f"N{lb}_CONFIRMED", f"N={lb}  Strategy Confirmed")
    block(f"N{lb}_NOTFIT", f"N={lb}  Not Fit")
block("N20_RF1_CONFIRMED", "N=20  Confirmed (RF1 sc_corrected)")

det.to_csv(os.path.join(DATA, "fullhist_bucket_win_detail.csv"), index=False)
print(f"\ndetail -> {os.path.join(DATA, 'fullhist_bucket_win_detail.csv')}")
