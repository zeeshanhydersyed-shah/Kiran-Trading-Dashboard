"""
s5 -- Can the Boring-Breakouts edge survive real execution? READ-ONLY vs psx_data.db.

Signal set: the existing first-fire-per-run signals (data/fullhist_gap_distribution.csv).
No signal regeneration. No parameter optimisation -- exit rule, cost model, and the
tested gap thresholds are all fixed in advance; the whole grid is reported.

Exit rule: HYBRID trailing stop, -8% floor (== trailing_stop_race_v2.race_trail).
Cost model: round trip 0.845% (0.15% brokerage x1.15 FED + 0.25% slippage, per
  side x2) + 15% CGT on a net-positive trade -- the dashboard's documented model.

Entry variants per signal:
  BASE   entry = Close(t)                                    (what the +EV numbers assume)
  OPEN   entry = Open(t+1)                                   (honest market-on-open)
  LIMIT  entry = Close(t) IF Low(t+1) <= Close(t) else SKIP  (working limit at signal price)
  GAPCAP entry = Open(t+1) IF gap% <= X else SKIP            (X in {0,1,2,3,5,inf})

Pass bar for a salvage rule (pre-specified): net+CGT EV/trade > 0 in >=3 of 4 eras
AND on both lookbacks.
"""
import os
import sqlite3
import numpy as np
import pandas as pd
from _paths import DB, DATA

FLOOR = -0.08
RT_COST = 0.845
CGT = 0.15
ERAS = ([2004, 2009, 2014, 2019, 2026], ["2005-09", "2010-14", "2015-19", "2020-26"])

det = pd.read_csv(os.path.join(DATA, "fullhist_gap_distribution.csv"))
det = det[det.bucket.isin(["A_gap_up", "F_flat", "C_gap_down"])].copy()
det["lb"] = det["set"].str.extract(r"N(\d+)").astype(int)
det["era"] = pd.cut(det.date.str[:4].astype(int), ERAS[0], labels=ERAS[1])

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
px = pd.read_sql_query("SELECT symbol,date,open,high,low,close FROM prices_adjusted ORDER BY symbol,date", con)
con.close()
for c in ("open", "high", "low", "close"):
    px[c] = pd.to_numeric(px[c], errors="coerce")
PF, DIDX = {}, {}
for s, g in px.groupby("symbol", sort=False):
    g = g.reset_index(drop=True)
    PF[s] = {"o": g.open.to_numpy(float), "l": g.low.to_numpy(float), "c": g.close.to_numpy(float)}
    DIDX[s] = {d: i for i, d in enumerate(g.date.to_numpy())}


def trail_from(sym, entry_idx, entry_price):
    pf = PF[sym]; low, close = pf["l"], pf["c"]; n = len(close)
    if entry_idx >= n - 1 or not np.isfinite(entry_price) or entry_price <= 0:
        return np.nan, True
    fl = entry_price * (1 + FLOOR)
    trail = low[entry_idx]; stop = max(trail, fl)
    for d in range(entry_idx + 1, n):
        trail = max(trail, low[d - 1]); stop = max(trail, fl)
        if low[d] <= stop:
            return (stop - entry_price) / entry_price * 100.0, False
    return (close[n - 1] - entry_price) / entry_price * 100.0, True


def net(gross):
    if not np.isfinite(gross):
        return np.nan, np.nan
    nf = gross - RT_COST
    return nf, (nf * (1 - CGT) if nf > 0 else nf)


rows = []
for r in det.itertuples(index=False):
    im = DIDX.get(r.symbol)
    if not im or r.date not in im:
        continue
    t = im[r.date]
    pf = PF[r.symbol]; n = len(pf["c"])
    rec = {"set": r.set, "lb": r.lb, "era": r.era, "symbol": r.symbol, "date": r.date,
           "bucket": r.bucket, "gap_pct": r.gap_pct}
    g, c = trail_from(r.symbol, t, pf["c"][t])
    rec["base_g"], rec["base_c"] = g, c
    if t + 1 < n and np.isfinite(pf["o"][t + 1]) and pf["o"][t + 1] > 0:
        g, c = trail_from(r.symbol, t + 1, pf["o"][t + 1])
        rec["open_g"], rec["open_c"] = g, c
    else:
        rec["open_g"], rec["open_c"] = np.nan, True
    if t + 1 < n and np.isfinite(pf["l"][t + 1]) and pf["l"][t + 1] <= pf["c"][t]:
        g, c = trail_from(r.symbol, t + 1, pf["c"][t])
        rec["lim_filled"] = True; rec["lim_g"], rec["lim_c"] = g, c
    else:
        rec["lim_filled"] = False; rec["lim_g"], rec["lim_c"] = np.nan, True
    rows.append(rec)

R = pd.DataFrame(rows)
for k in ("base", "open", "lim"):
    nf, nc = zip(*R[f"{k}_g"].map(net))
    R[f"{k}_nf"] = nf; R[f"{k}_ncgt"] = nc
    R[f"{k}_win"] = R[f"{k}_ncgt"] > 0
R.to_csv(os.path.join(DATA, "salvage_detail.csv"), index=False)


def line(d, col_g, col_ncgt, col_win, cens_col, label, denom=None):
    dd = d.dropna(subset=[col_g])
    n = len(dd)
    if n == 0:
        print(f"    {label:<26} n=0"); return
    take = f"{n/denom*100:4.0f}%" if denom else "   -"
    print(f"    {label:<26} n={n:5d} take={take}  win={dd[col_win].mean()*100:4.1f}%  "
          f"grossEV={dd[col_g].mean():+6.2f}  netEV={dd[col_ncgt].mean():+6.2f}  medNet={dd[col_ncgt].median():+6.2f}")


for setname in ["N20_ALL", "N20_CONFIRMED", "N20_RF1_CONFIRMED", "N60_ALL", "N60_CONFIRMED"]:
    d = R[R.set == setname]
    if d.empty:
        continue
    tot = len(d)
    print(f"\n{'='*94}\n{setname}   ({tot} signals)\n{'='*94}")
    print("  ENTRY METHOD (pooled 2005-2026):")
    line(d, "base_g", "base_ncgt", "base_win", "base_c", "BASE  entry=Close(t)", tot)
    line(d, "open_g", "open_ncgt", "open_win", "open_c", "OPEN  entry=Open(t+1)", tot)
    line(d[d.lim_filled], "lim_g", "lim_ncgt", "lim_win", "lim_c", "LIMIT filled @Close(t)", tot)
    print("  GAP-CAP grid (entry=Open(t+1) only if gap% <= X):")
    for X in [0, 1, 2, 3, 5, 999]:
        lab = "gap<=inf (all)" if X == 999 else f"gap<={X}%"
        line(d[d.gap_pct <= X], "open_g", "open_ncgt", "open_win", "open_c", lab, tot)
    print("  OPEN-entry EV by era:")
    for era in ERAS[1]:
        line(d[d.era == era], "open_g", "open_ncgt", "open_win", "open_c", f"{era}")
    print("  BASE (Close-entry) EV by era, for reference:")
    for era in ERAS[1]:
        line(d[d.era == era], "base_g", "base_ncgt", "base_win", "base_c", f"{era}")
    print("  BEST LEAD -- OPEN entry, gap<=0 subset, EV by era:")
    for era in ERAS[1]:
        line(d[(d.era == era) & (d.gap_pct <= 0)], "open_g", "open_ncgt", "open_win", "open_c", f"{era}")

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
k = pd.read_sql_query("SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", con)
con.close()
k["close"] = pd.to_numeric(k["close"], errors="coerce")
k["yr"] = k.date.str[:4].astype(int)
print(f"\n{'='*94}\nKSE-100 context (is a positive raw EV just index beta?)\n{'='*94}")
for lo, hi, name in zip(ERAS[0][:-1], ERAS[0][1:], ERAS[1]):
    seg = k[(k.yr > lo) & (k.yr <= hi)]
    if len(seg) > 1:
        tot = (seg.close.iloc[-1] / seg.close.iloc[0] - 1) * 100
        ann = ((seg.close.iloc[-1] / seg.close.iloc[0]) ** (252 / len(seg)) - 1) * 100
        print(f"  {name}: KSE-100 {tot:+7.1f}% total  ({ann:+6.1f}%/yr, ~{ann/252*3:+.2f}% per 3-day hold)")

print(f"\ndetail -> {os.path.join(DATA, 'salvage_detail.csv')}")
