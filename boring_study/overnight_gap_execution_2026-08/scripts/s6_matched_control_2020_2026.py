"""
s6 -- Matched-control test of the ONE surviving lead from s5:
  "take a Boring breakout only if it opens <= prior close (gap<=0), enter at that
   discounted Open(t+1)"  -- on CLEAN 2020-2026 data only.

Question: is that rule's small positive net EV an EDGE over a matched random day,
or just index beta / an entry-price mechanical effect (buying lower)?

Method (the boring study's own convention, windowed to 2020-2026):
  - Breakout days: the already-generated fires (boring_heterogeneity_panel_*),
    breakout==1, 2020-01-01..2026-07-09, first-fire-per-run collapsed.
  - Matched control: for each breakout -> same symbol, same regime (market_regime),
    a random NON-breakout day in 2020-2026, np.random.default_rng(42).
  - Rule applied identically to both sides.
  - Compare TAKEN breakouts vs TAKEN controls: win rate, mean/median net EV,
    Mann-Whitney U, bootstrap 95% CI on the mean difference.

READ-ONLY. Breakout list reused; only the controls and trail outcomes are computed.
"""
import os
import sqlite3
import numpy as np
import pandas as pd
from scipy import stats
from _paths import DB, BS, DATA

FLOOR, RT_COST, CGT = -0.08, 0.845, 0.15
SEED = 42
START, END = "2020-01-01", "2026-07-09"
REGIMES = {"TRENDING_UP", "RANGING", "VOLATILE", "TRENDING_DOWN"}

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
px = pd.read_sql_query("SELECT symbol,date,open,high,low,close FROM prices_adjusted "
                       "WHERE date >= '2019-06-01' ORDER BY symbol,date", con)
reg = dict(con.execute("SELECT date,regime FROM market_regime").fetchall())
con.close()
for c in ("open", "high", "low", "close"):
    px[c] = pd.to_numeric(px[c], errors="coerce")
PF, DIDX = {}, {}
for s, g in px.groupby("symbol", sort=False):
    g = g.reset_index(drop=True)
    PF[s] = {"d": g.date.to_numpy(), "o": g.open.to_numpy(float),
             "h": g.high.to_numpy(float), "l": g.low.to_numpy(float), "c": g.close.to_numpy(float)}
    DIDX[s] = {d: i for i, d in enumerate(g.date.to_numpy())}


def trail(sym, ei, ep):
    pf = PF[sym]; low, close = pf["l"], pf["c"]; n = len(close)
    if ei >= n - 1 or not np.isfinite(ep) or ep <= 0:
        return np.nan
    fl = ep * (1 + FLOOR); tr = low[ei]; st = max(tr, fl)
    for d in range(ei + 1, n):
        tr = max(tr, low[d - 1]); st = max(tr, fl)
        if low[d] <= st:
            return (st - ep) / ep * 100
    return (close[n - 1] - ep) / ep * 100


def rule_outcome(sym, t):
    pf = PF[sym]; n = len(pf["c"])
    if t + 1 >= n:
        return False, np.nan, np.nan, False
    ct, ot1 = pf["c"][t], pf["o"][t + 1]
    if not np.isfinite(ct) or ct <= 0 or not np.isfinite(ot1) or ot1 <= 0:
        return False, np.nan, np.nan, False
    if (ot1 - ct) / ct > 0:
        return False, np.nan, np.nan, False
    g = trail(sym, t + 1, ot1)
    if not np.isfinite(g):
        return True, np.nan, np.nan, False
    nf = g - RT_COST
    nc = nf * (1 - CGT) if nf > 0 else nf
    return True, nc, g, (nc > 0)


def first_fire(pairs, lookback):
    out, bysym = [], {}
    for s, d in pairs:
        bysym.setdefault(s, []).append(d)
    for s, ds in bysym.items():
        im = DIDX.get(s)
        if not im:
            continue
        rows = sorted((im[d], d) for d in ds if d in im)
        if not rows:
            continue
        rs, prev = rows[0], rows[0][0]
        for i, d in rows[1:]:
            if i - prev > lookback:
                out.append((s, rs[1])); rs = (i, d)
            prev = i
        out.append((s, rs[1]))
    return out


def run(lookback, panel_csv):
    panel = pd.read_csv(os.path.join(BS, panel_csv))
    bo = panel[(panel.breakout == 1) & (panel.lookback == lookback)].copy()
    bo = bo[(bo.date >= START) & (bo.date <= END)]
    gt = bo[(bo.liquidity > 200_000) & bo.stock_rs.notna()].copy()
    gt["dec"] = pd.qcut(gt.stock_rs, 10, labels=False, duplicates="drop")
    conf_pairs = set(zip(gt.loc[gt.dec == 9, "symbol"], gt.loc[gt.dec == 9, "date"]))
    all_bo_days = set(zip(panel.loc[panel.breakout == 1, "symbol"], panel.loc[panel.breakout == 1, "date"]))
    ff = first_fire(list(zip(bo.symbol, bo.date)), lookback)

    rng = np.random.default_rng(SEED)
    B, C = [], []
    for sym, d in ff:
        im = DIDX.get(sym)
        if not im or d not in im:
            continue
        rg = reg.get(d)
        if rg not in REGIMES:
            continue
        tk, nc, g, w = rule_outcome(sym, im[d])
        B.append({"symbol": sym, "date": d, "regime": rg, "confirmed": (sym, d) in conf_pairs,
                  "taken": tk, "net": nc, "gross": g, "win": w})
        dates = PF[sym]["d"]
        cand = [i for i in range(len(dates))
                if START <= dates[i] <= END and reg.get(dates[i]) == rg
                and (sym, dates[i]) not in all_bo_days and i + 1 < len(dates)]
        if not cand:
            continue
        ci = int(rng.choice(cand))
        tk, nc, g, w = rule_outcome(sym, ci)
        C.append({"symbol": sym, "date": dates[ci], "regime": rg,
                  "confirmed": (sym, d) in conf_pairs, "taken": tk, "net": nc, "gross": g, "win": w})
    return pd.DataFrame(B), pd.DataFrame(C)


def compare(b, c, label):
    bt = b[b.taken & b.net.notna()]
    ct = c[c.taken & c.net.notna()]
    print(f"\n{'='*82}\n{label}\n{'='*82}")
    print(f"  breakouts: {len(b)}   would enter (gap<=0): {b.taken.sum()} ({b.taken.mean()*100:.0f}%)   evaluable: {len(bt)}")
    print(f"  controls : {len(c)}   would enter (gap<=0): {c.taken.sum()} ({c.taken.mean()*100:.0f}%)   evaluable: {len(ct)}")
    if len(bt) < 20 or len(ct) < 20:
        print("  -- too few to test --"); return
    print(f"  BREAKOUT taken : win {bt.win.mean()*100:5.1f}%   net EV {bt.net.mean():+.2f}%   "
          f"median {bt.net.median():+.2f}%   gross {bt.gross.mean():+.2f}%")
    print(f"  CONTROL  taken : win {ct.win.mean()*100:5.1f}%   net EV {ct.net.mean():+.2f}%   "
          f"median {ct.net.median():+.2f}%   gross {ct.gross.mean():+.2f}%")
    diff = bt.net.mean() - ct.net.mean()
    _, p = stats.mannwhitneyu(bt.net, ct.net, alternative="two-sided")
    rng2 = np.random.default_rng(1)
    boot = [rng2.choice(bt.net.values, len(bt)).mean() - rng2.choice(ct.net.values, len(ct)).mean()
            for _ in range(5000)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"  EDGE (breakout net EV - control net EV): {diff:+.2f}%   95% CI [{lo:+.2f}, {hi:+.2f}]   Mann-Whitney p={p:.3f}")
    print(f"  -> {'SIGNIFICANT edge over control' if (lo > 0 or hi < 0) and p < 0.05 else 'NOT distinguishable from control'}")


for lb, csv in [(20, "boring_heterogeneity_panel_20d.csv"), (60, "boring_heterogeneity_panel_60d.csv")]:
    b, c = run(lb, csv)
    b.to_csv(os.path.join(DATA, f"mc_breakouts_N{lb}.csv"), index=False)
    c.to_csv(os.path.join(DATA, f"mc_controls_N{lb}.csv"), index=False)
    compare(b, c, f"N={lb}  ALL breakouts vs matched controls  (gap<=0 / enter-at-open, 2020-2026)")
    compare(b[b.confirmed], c[c.confirmed], f"N={lb}  STRATEGY CONFIRMED subset")

print(f"\ndetail -> {os.path.join(DATA, 'mc_{breakouts,controls}_N{20,60}.csv')}")
