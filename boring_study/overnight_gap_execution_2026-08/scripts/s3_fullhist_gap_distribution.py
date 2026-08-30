"""
s3 -- Overnight-gap bucket distribution on the EXISTING boring-breakout signal set,
full history 2005-2026. READ-ONLY vs psx_data.db (SQLite). Signal generation is
NOT recomputed.

Signal set : boring_heterogeneity_panel_{20,60}d.csv, rows where breakout == 1.
Dedup      : first-fire-per-run -- new run when the gap since the prior fire in the
             SAME subset exceeds `lookback` trading days (the exact rule
             boring_donchian_trailing_stop_race_v2.build_run_population() uses).
Restricted : to symbols still in prices_adjusted after the 2026-08-27 non-equity
             purge (drops ~75 futures contracts that had leaked into the pre-purge
             panel; 3.6% of breakout rows). See reports/02.

Buckets:
    A  Gap Up          open_t1  >  close_t
    F  Unchanged       open_t1  == close_t
    C  Gap Down        open_t1  <  close_t
    B  At/below close   open_t1 <= close_t   ==  F + C

Strategy Confirmed (primary): liquidity > 200k AND decile 9 of
    pd.qcut(liquidity-gated stock_rs, 10) -- the build_run_population() proxy.
N=20 cross-check: sc_corrected from boring_rf1_misclassification_detail.csv.
"""
import os
import sqlite3
import numpy as np
import pandas as pd
from _paths import DB, BS, DATA

LIQ = 200_000

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
px = pd.read_sql_query("SELECT symbol, date, open, close FROM prices_adjusted ORDER BY symbol, date", con)
con.close()
px["open"] = pd.to_numeric(px["open"], errors="coerce")
px["close"] = pd.to_numeric(px["close"], errors="coerce")
PF, DIDX = {}, {}
for sym, g in px.groupby("symbol", sort=False):
    g = g.reset_index(drop=True)
    PF[sym] = {"d": g["date"].to_numpy(), "o": g["open"].to_numpy(float), "c": g["close"].to_numpy(float)}
    DIDX[sym] = {d: i for i, d in enumerate(g["date"].to_numpy())}

rf1 = pd.read_csv(os.path.join(BS, "boring_rf1_misclassification_detail.csv"))
RF1 = {(r.symbol, r.date): r.sc_corrected for r in rf1.itertuples(index=False)}


def collapse_runs(pairs, lookback):
    out, bysym = [], {}
    for s, d in pairs:
        bysym.setdefault(s, []).append(d)
    for s, dates in bysym.items():
        idxmap = DIDX.get(s)
        if not idxmap:
            continue
        rows = sorted((idxmap[d], d) for d in dates if d in idxmap)
        if not rows:
            continue
        run_start, prev = rows[0], rows[0][0]
        for idx, d in rows[1:]:
            if idx - prev > lookback:
                out.append((s, run_start[1]))
                run_start = (idx, d)
            prev = idx
        out.append((s, run_start[1]))
    return out


def bucketize(runs):
    recs = []
    for s, d in runs:
        pf = PF[s]; t = DIDX[s][d]
        r = {"symbol": s, "date": d}
        if t + 1 >= len(pf["d"]):
            r["bucket"] = "no_next_day"
        else:
            ct, ot1 = pf["c"][t], pf["o"][t + 1]
            if not np.isfinite(ct) or ct <= 0 or not np.isfinite(ot1) or ot1 <= 0:
                r["bucket"] = "no_open_data"
            else:
                r["close_t"] = ct; r["open_t1"] = ot1
                r["gap_pct"] = (ot1 - ct) / ct * 100
                r["bucket"] = "A_gap_up" if ot1 > ct else ("C_gap_down" if ot1 < ct else "F_flat")
        recs.append(r)
    return pd.DataFrame(recs)


def report(df, label):
    n = len(df)
    nod = int((df["bucket"] == "no_open_data").sum())
    nnd = int((df["bucket"] == "no_next_day").sum())
    ev = df[df["bucket"].isin(["A_gap_up", "F_flat", "C_gap_down"])]
    e = len(ev)
    A = int((ev["bucket"] == "A_gap_up").sum())
    F = int((ev["bucket"] == "F_flat").sum())
    C = int((ev["bucket"] == "C_gap_down").sum())
    print(f"\n{'='*76}\n{label}\n{'='*76}")
    print(f"  first-fire runs (signals)        : {n}")
    print(f"  excluded - no next trading day    : {nnd}")
    print(f"  excluded - no/zero open price     : {nod}   ({nod/max(n,1)*100:.1f}%)")
    print(f"  EVALUABLE                         : {e}")
    if not e:
        return
    print(f"  (a) Gap Up     open > close       : N={A:5d}   {A/e*100:5.1f}%")
    print(f"      Unchanged  open = close       : N={F:5d}   {F/e*100:5.1f}%")
    print(f"  (c) Gap Down   open < close       : N={C:5d}   {C/e*100:5.1f}%")
    print(f"  (b) At/below prior close  (F+C)   : N={C+F:5d}   {(C+F)/e*100:5.1f}%")
    print(f"      gap%: mean {ev['gap_pct'].mean():+.2f}  median {ev['gap_pct'].median():+.2f}  "
          f"mean|gap| {ev['gap_pct'].abs().mean():.2f}   "
          f"[up: mean {ev.loc[ev.bucket=='A_gap_up','gap_pct'].mean():+.2f}]")


ALL_DETAIL = []
for panel_csv, lb in [("boring_heterogeneity_panel_20d.csv", 20),
                      ("boring_heterogeneity_panel_60d.csv", 60)]:
    panel = pd.read_csv(os.path.join(BS, panel_csv))
    bo = panel[(panel["breakout"] == 1) & (panel["lookback"] == lb)].copy()

    gated = bo[(bo["liquidity"] > LIQ) & (bo["stock_rs"].notna())].copy()
    gated["dec"] = pd.qcut(gated["stock_rs"], 10, labels=False, duplicates="drop")
    bo["confirmed"] = bo.index.isin(gated.index[gated["dec"] == 9])

    all_runs = collapse_runs(list(zip(bo["symbol"], bo["date"])), lb)
    conf_runs = collapse_runs(list(zip(bo.loc[bo.confirmed, "symbol"], bo.loc[bo.confirmed, "date"])), lb)
    notfit_runs = collapse_runs(list(zip(bo.loc[~bo.confirmed, "symbol"], bo.loc[~bo.confirmed, "date"])), lb)

    d_all = bucketize(all_runs); d_all["set"] = f"N{lb}_ALL"
    d_conf = bucketize(conf_runs); d_conf["set"] = f"N{lb}_CONFIRMED"
    d_nf = bucketize(notfit_runs); d_nf["set"] = f"N{lb}_NOTFIT"
    ALL_DETAIL += [d_all, d_conf, d_nf]

    report(d_all, f"N={lb}  --  ALL breakouts, first-fire-per-run")
    report(d_conf, f"N={lb}  --  STRATEGY CONFIRMED (decile-9 + liq), first-fire-per-run")
    report(d_nf, f"N={lb}  --  NOT FIT, first-fire-per-run")

    if lb == 20:
        sc1 = [(s, d) for s, d in zip(bo["symbol"], bo["date"]) if RF1.get((s, d)) == 1]
        sc0 = [(s, d) for s, d in zip(bo["symbol"], bo["date"]) if RF1.get((s, d)) == 0]
        d_sc1 = bucketize(collapse_runs(sc1, lb)); d_sc1["set"] = "N20_RF1_CONFIRMED"
        d_sc0 = bucketize(collapse_runs(sc0, lb)); d_sc0["set"] = "N20_RF1_NOTCONF"
        ALL_DETAIL += [d_sc1, d_sc0]
        print(f"\n{'#'*76}\n# N=20 CROSS-CHECK -- Confirmed via RF1 sc_corrected\n{'#'*76}")
        report(d_sc1, "N=20  --  RF1 Confirmed (sc_corrected == 1)")
        report(d_sc0, "N=20  --  RF1 Not Confirmed (sc_corrected == 0)")

out = pd.concat(ALL_DETAIL, ignore_index=True)
p = os.path.join(DATA, "fullhist_gap_distribution.csv")
out.to_csv(p, index=False)

print(f"\n{'='*76}\nBY ERA  --  gap-up % (a) / at-or-below-close % (b) / gap-down % (c)\n{'='*76}")
ev = out[out.bucket.isin(["A_gap_up", "F_flat", "C_gap_down"])].copy()
ev["era"] = pd.cut(ev["date"].str[:4].astype(int), [2004, 2009, 2014, 2019, 2026],
                   labels=["2005-09", "2010-14", "2015-19", "2020-26"])
for s in ["N20_ALL", "N20_CONFIRMED", "N60_ALL", "N60_CONFIRMED"]:
    sub = ev[ev.set == s]
    print(f"\n  {s}")
    for era, g in sub.groupby("era", observed=True):
        a = (g.bucket == "A_gap_up").mean() * 100
        c = (g.bucket == "C_gap_down").mean() * 100
        b = (g.bucket != "A_gap_up").mean() * 100
        print(f"    {era}:  N={len(g):5d}   a={a:5.1f}%   b={b:5.1f}%   c={c:5.1f}%   mean gap {g.gap_pct.mean():+.2f}%")

print(f"\nper-signal detail -> {p}")
print(f"signal date span : {ev['date'].min()} .. {ev['date'].max()}")
