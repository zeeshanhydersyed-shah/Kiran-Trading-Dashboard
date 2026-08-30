"""
s2 -- READ-ONLY follow-up to s1. Joins the cloud overnight-gap event set to each
signal's realised outcome:

  Q1  Fill-to-Loss Rate -- of the up-gap events where a limit at Close(t) would
      have filled next day (Low(t+1) <= Close(t)), what share exited at a loss?
  Q2  Gap-Up Win Probability -- of all up-gap events, what share closed positive?

Outcome = the dashboard's own (_render_boring_performance): collapse N20/N60 to one
trade per (symbol, signal_date); RESOLVED once status='Stopped' & current_stop not
null; ret% = (current_stop - trigger_price)/trigger_price*100; WIN = ret > 0.
dedup_conflict rows shown both ways. SELECT-only.
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
           CAST(trigger_price AS DOUBLE PRECISION) AS trigger_price,
           CAST(current_stop  AS DOUBLE PRECISION) AS current_stop,
           resolution_date::text AS resolution_date, days_open,
           status, strategy_confirmed::int AS strategy_confirmed,
           dedup_conflict::int AS dedup_conflict
    FROM boring_signals ORDER BY signal_date, symbol, lookback_n
""")
sig = pd.DataFrame(cur.fetchall())
symbols = sorted(sig.symbol.unique())
cur.execute("""
    SELECT symbol, date::text AS date,
           CAST(open AS DOUBLE PRECISION) AS open,
           CAST(low  AS DOUBLE PRECISION) AS low,
           CAST(close AS DOUBLE PRECISION) AS close
    FROM prices_adjusted WHERE symbol = ANY(%s) AND date >= '2026-06-01'
    ORDER BY symbol, date
""", (symbols,))
px = pd.DataFrame(cur.fetchall()).sort_values(["symbol", "date"]).reset_index(drop=True)
conn.close()
by_sym = {s: g.reset_index(drop=True) for s, g in px.groupby("symbol")}

rows = []
for r in sig.itertuples(index=False):
    g = by_sym.get(r.symbol)
    d = dict(id=r.id, symbol=r.symbol, signal_date=r.signal_date, lookback_n=r.lookback_n,
             strategy_confirmed=r.strategy_confirmed, dedup_conflict=r.dedup_conflict,
             status=r.status, trigger_price=r.trigger_price, current_stop=r.current_stop,
             days_open=r.days_open, resolution_date=r.resolution_date)
    if g is not None:
        di = g.index[g.date == r.signal_date]
        if len(di) and di[0] + 1 < len(g):
            i = di[0]; close_t = g.loc[i, "close"]; nxt = g.loc[i + 1]
            if close_t and close_t > 0 and nxt["open"] and nxt["open"] > 0 and not np.isnan(nxt["open"]):
                d["close_t"] = close_t
                d["gap_pct"] = (nxt["open"] - close_t) / close_t * 100
                d["gap_up"] = d["gap_pct"] > 0
                d["next_low"] = nxt["low"]
                d["fillable_at_close_t"] = (not np.isnan(nxt["low"])) and nxt["low"] <= close_t
    rows.append(d)
res = pd.DataFrame(rows)


def collapse(df):
    return (df.sort_values(["symbol", "signal_date", "lookback_n"])
              .groupby(["symbol", "signal_date"], as_index=False).first())


def add_outcome(df):
    df = df.copy()
    df["resolved"] = (df["status"] == "Stopped") & df["current_stop"].notna()
    df["ret_pct"] = np.where(df["resolved"] & df["trigger_price"].gt(0),
                             (df["current_stop"] - df["trigger_price"]) / df["trigger_price"] * 100, np.nan)
    df["win"] = df["ret_pct"] > 0
    df["loss"] = df["ret_pct"] <= 0
    return df


def report(df, tag):
    ev = add_outcome(collapse(df))
    ev = ev[ev.gap_pct.notna()]
    up = ev[ev.gap_up == True]
    fill = up[up.fillable_at_close_t == True]
    print(f"\n{'='*72}\n{tag}\n{'='*72}")
    print(f"  distinct events w/ gap : {len(ev)}   gap-up: {len(up)} (resolved {int(up.resolved.sum())})   "
          f"gap-up & fillable: {len(fill)} (resolved {int(fill.resolved.sum())})")
    fr = fill[fill.resolved]
    if len(fr):
        nl, nw = int(fr.loss.sum()), int(fr.win.sum())
        print(f"  Q1 FILL-TO-LOSS: {nl}/{len(fr)} = {nl/len(fr)*100:.1f}% of resolved "
              f"({nl/len(fill)*100:.1f}% of all {len(fill)} filled); win {nw} ({nw/len(fr)*100:.1f}%); "
              f"mean exit {fr.ret_pct.mean():+.2f}% median {fr.ret_pct.median():+.2f}%")
    ur = up[up.resolved]
    if len(ur):
        nw, nl = int(ur.win.sum()), int(ur.loss.sum())
        print(f"  Q2 GAP-UP WIN PROB: {nw}/{len(ur)} = {nw/len(ur)*100:.1f}% of resolved "
              f"({nw/len(up)*100:.1f}% of all {len(up)} gap-ups); mean exit {ur.ret_pct.mean():+.2f}%")
    nofill = up[up.fillable_at_close_t != True]
    nfr = nofill[nofill.resolved]
    if len(nfr):
        print(f"  (context) gap-up NEVER retraced to close: {int(nfr.win.sum())}/{len(nfr)} win "
              f"({nfr.win.mean()*100:.1f}%), mean ret {nfr.ret_pct.mean():+.2f}%")


def baseline(df, tag):
    r = add_outcome(collapse(df))
    r = r[r.resolved]
    print(f"[baseline] {tag}: resolved {len(r)}, win {r.win.mean()*100:.1f}% "
          f"({int(r.win.sum())}W/{int(r.loss.sum())}L), mean ret {r.ret_pct.mean():+.2f}%")


baseline(res, "ALL fired (incl dedup_conflict)")
baseline(res[res.dedup_conflict != 1], "ALL fired (excl dedup_conflict)")
report(res, "ALL fired signals (incl. dedup_conflict)")
report(res[res.dedup_conflict != 1], "EXCLUDING dedup_conflict (dashboard convention)")
report(res[(res.dedup_conflict != 1) & (res.strategy_confirmed == 1)], "Strategy Confirmed, excl. dedup_conflict")

out = add_outcome(collapse(res))
cols = ["symbol", "signal_date", "strategy_confirmed", "dedup_conflict", "status", "close_t",
        "trigger_price", "gap_pct", "gap_up", "next_low", "fillable_at_close_t", "current_stop",
        "resolved", "ret_pct", "win", "days_open", "resolution_date"]
path = os.path.join(DATA, "cloud_gap_outcomes.csv")
out[cols].sort_values(["signal_date", "symbol"]).to_csv(path, index=False)
print(f"\njoined detail -> {path}")
