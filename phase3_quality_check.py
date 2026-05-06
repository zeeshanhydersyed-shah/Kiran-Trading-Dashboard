"""
Phase 3 — Backtest Dataset Quality Check.

Investigates why results look inflated. Checks:
  1. Class balance
  2. Win rate by time period (is it all one era?)
  3. Win rate by sector (is it all one sector?)
  4. Stock concentration (a few stocks dominating?)
  5. Feature separation (do quality_score/breadth etc. actually predict outcome?)
  6. Labeling sanity (date ordering, impossible outcomes)
  7. Bull market bias quantification

Output: phase3_report.txt
"""

import sqlite3
import logging
import sys
from collections import Counter
from datetime import date

import pandas as pd
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DB_PATH = "psx_data.db"
OUT     = "phase3_report.txt"

lines = []

def h(title):
    sep = "=" * 60
    lines.append(f"\n{sep}")
    lines.append(f"  {title}")
    lines.append(sep)

def p(text=""):
    lines.append(str(text))

def load():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    bt = pd.DataFrame(
        [dict(r) for r in conn.execute("SELECT * FROM backtest_setups").fetchall()]
    )
    px = pd.DataFrame(
        [dict(r) for r in conn.execute(
            "SELECT date, AVG(close) as avg_close FROM prices GROUP BY date ORDER BY date"
        ).fetchall()]
    )
    conn.close()
    bt["as_of_date"]   = pd.to_datetime(bt["as_of_date"])
    bt["trigger_date"] = pd.to_datetime(bt["trigger_date"], errors="coerce")
    bt["outcome_date"] = pd.to_datetime(bt["outcome_date"], errors="coerce")
    px["date"]         = pd.to_datetime(px["date"])
    return bt, px


def main():
    log.info("Loading data...")
    bt, px = load()

    triggered = bt[bt["outcome"].isin(["Win_T2", "Win_T1", "Loss"])].copy()
    wins      = triggered[triggered["outcome"].isin(["Win_T2", "Win_T1"])]
    losses    = triggered[triggered["outcome"] == "Loss"]

    # ── 1. OVERVIEW ──────────────────────────────────────────────────────────
    h("1. OVERVIEW")
    p(f"Total setups         : {len(bt):,}")
    p(f"Triggered (W+L)      : {len(triggered):,}  ({len(triggered)/len(bt)*100:.1f}% of all)")
    p(f"  Win_T2             : {len(bt[bt['outcome']=='Win_T2']):,}")
    p(f"  Win_T1             : {len(bt[bt['outcome']=='Win_T1']):,}")
    p(f"  Loss               : {len(bt[bt['outcome']=='Loss']):,}")
    p(f"  No_Trigger         : {len(bt[bt['outcome']=='No_Trigger']):,}")
    p(f"  Expired            : {len(bt[bt['outcome']=='Expired']):,}")
    p(f"Win rate (triggered) : {len(wins)/len(triggered)*100:.1f}%")
    p(f"Date range           : {bt['as_of_date'].min().date()} to {bt['as_of_date'].max().date()}")
    p(f"Unique symbols       : {bt['symbol'].nunique()}")
    p(f"Unique sectors       : {bt['sector'].nunique()}")

    # ── 2. TEMPORAL CONCENTRATION ────────────────────────────────────────────
    h("2. WIN RATE BY QUARTER (is it all one period?)")
    triggered["quarter"] = triggered["as_of_date"].dt.to_period("Q")
    qtr = (
        triggered.groupby("quarter")
        .agg(total=("outcome","count"),
             wins=("outcome", lambda x: x.isin(["Win_T2","Win_T1"]).sum()))
        .reset_index()
    )
    qtr["win_rate"] = (qtr["wins"] / qtr["total"] * 100).round(1)
    p(f"{'Quarter':<10} {'Setups':>8} {'Wins':>6} {'Win%':>7}")
    p("-" * 36)
    for _, r in qtr.iterrows():
        flag = " <-- HIGH" if r["win_rate"] > 75 else (" <-- LOW" if r["win_rate"] < 50 else "")
        p(f"{str(r['quarter']):<10} {r['total']:>8,} {r['wins']:>6,} {r['win_rate']:>6.1f}%{flag}")

    # ── 3. SECTOR CONCENTRATION ──────────────────────────────────────────────
    h("3. WIN RATE BY SECTOR (is one sector carrying the results?)")
    sec = (
        triggered.groupby("sector")
        .agg(total=("outcome","count"),
             wins=("outcome", lambda x: x.isin(["Win_T2","Win_T1"]).sum()))
        .reset_index()
    )
    sec["win_rate"] = (sec["wins"] / sec["total"] * 100).round(1)
    sec["pct_of_total"] = (sec["total"] / len(triggered) * 100).round(1)
    sec = sec.sort_values("total", ascending=False)
    p(f"{'Sector':<35} {'N':>5} {'% of all':>9} {'Win%':>7}")
    p("-" * 60)
    for _, r in sec.iterrows():
        flag = " <-- DOMINANT" if r["pct_of_total"] > 20 else ""
        p(f"{r['sector']:<35} {r['total']:>5,} {r['pct_of_total']:>8.1f}% {r['win_rate']:>6.1f}%{flag}")

    # ── 4. STOCK CONCENTRATION ───────────────────────────────────────────────
    h("4. TOP 20 SYMBOLS BY SETUP COUNT (concentration check)")
    sym_counts = triggered["symbol"].value_counts().head(20)
    top20_pct  = sym_counts.sum() / len(triggered) * 100
    p(f"Top 20 symbols account for {top20_pct:.1f}% of all triggered setups")
    p()
    p(f"{'Symbol':<12} {'Count':>7} {'% of total':>11}")
    p("-" * 34)
    for sym, cnt in sym_counts.items():
        sym_win_rate = (
            triggered[triggered["symbol"]==sym]["outcome"]
            .isin(["Win_T2","Win_T1"]).mean() * 100
        )
        p(f"{sym:<12} {cnt:>7,} {cnt/len(triggered)*100:>10.1f}%  WR={sym_win_rate:.0f}%")

    # ── 5. FEATURE SEPARATION ────────────────────────────────────────────────
    h("5. FEATURE SEPARATION (do features predict outcome?)")
    features = ["quality_score", "breadth_score", "sector_rank",
                "stock_perf_30d", "stock_perf_10d", "risk_pct",
                "atr_pct", "range_width_pct", "avg_vol_10d", "outcome_days"]
    p(f"{'Feature':<20} {'Wins mean':>12} {'Losses mean':>13} {'Diff':>8} {'Signal?':>9}")
    p("-" * 66)
    for feat in features:
        if feat not in triggered.columns:
            continue
        wm = wins[feat].dropna().mean()
        lm = losses[feat].dropna().mean()
        if lm != 0:
            diff_pct = (wm - lm) / abs(lm) * 100
        else:
            diff_pct = 0
        signal = "YES" if abs(diff_pct) > 10 else "weak"
        p(f"{feat:<20} {wm:>12.2f} {lm:>13.2f} {diff_pct:>7.1f}% {signal:>9}")

    # ── 6. QUALITY SCORE VS WIN RATE ─────────────────────────────────────────
    h("6. WIN RATE BY QUALITY SCORE (are higher scores actually better?)")
    p(f"{'Quality':>8} {'N triggered':>12} {'Win%':>7} {'Predictive?':>12}")
    p("-" * 44)
    prev_wr = None
    for qs in sorted(triggered["quality_score"].dropna().unique()):
        g  = triggered[triggered["quality_score"] == qs]
        gw = g[g["outcome"].isin(["Win_T2","Win_T1"])]
        wr = len(gw)/len(g)*100
        if prev_wr is not None:
            flag = "IMPROVES" if wr > prev_wr + 2 else ("FLAT" if abs(wr-prev_wr)<2 else "WORSE")
        else:
            flag = "--"
        p(f"{int(qs):>8} {len(g):>12,} {wr:>6.1f}% {flag:>12}")
        prev_wr = wr

    # ── 7. LABELING SANITY ───────────────────────────────────────────────────
    h("7. LABELING SANITY CHECKS")
    # trigger_date must be after as_of_date
    bad_trigger = triggered[
        triggered["trigger_date"].notna() &
        (triggered["trigger_date"] <= triggered["as_of_date"])
    ]
    p(f"Trigger date <= as_of_date (look-ahead error) : {len(bad_trigger)}")

    # outcome_date must be after trigger_date
    bad_outcome = triggered[
        triggered["outcome_date"].notna() & triggered["trigger_date"].notna() &
        (triggered["outcome_date"] < triggered["trigger_date"])
    ]
    p(f"Outcome date < trigger date (impossible)       : {len(bad_outcome)}")

    # Trigger on same day as setup (unrealistic same-day fill)
    same_day = triggered[
        triggered["trigger_date"].notna() &
        (triggered["trigger_date"].dt.date == triggered["as_of_date"].dt.date)
    ]
    p(f"Triggered on same day as setup (day 0)         : {len(same_day)}  ({len(same_day)/len(triggered)*100:.1f}%)")
    p("  --> These are setups where price hit entry on the very next close.")
    p("  --> Could be valid (gap up through entry) or indicate entry price")
    p("      was already breached before market open.")

    # Win_T1 on trigger day (price went entry→T1 in one candle)
    t1_same_day = triggered[
        (triggered["outcome"] == "Win_T1") &
        triggered["trigger_date"].notna() & triggered["outcome_date"].notna() &
        (triggered["trigger_date"].dt.date == triggered["outcome_date"].dt.date)
    ]
    p(f"Win_T1 resolved same day as trigger            : {len(t1_same_day)}  ({len(t1_same_day)/max(len(wins),1)*100:.1f}% of wins)")

    # ── 8. BULL MARKET BIAS ──────────────────────────────────────────────────
    h("8. BULL MARKET BIAS — Market index during backtest period")
    if not px.empty:
        px_bt = px[(px["date"] >= bt["as_of_date"].min()) &
                   (px["date"] <= bt["as_of_date"].max())]
        if len(px_bt) >= 2:
            start_px = px_bt.iloc[0]["avg_close"]
            end_px   = px_bt.iloc[-1]["avg_close"]
            mkt_ret  = (end_px - start_px) / start_px * 100
            p(f"Avg market price start : {start_px:.2f}")
            p(f"Avg market price end   : {end_px:.2f}")
            p(f"Market return (period) : {mkt_ret:+.1f}%")
            if mkt_ret > 30:
                p("  --> STRONG BULL MARKET. A long-biased system will look exceptional.")
                p("  --> Win rates are inflated by market direction, not system alpha.")

        # Win rate by half-year to see if it shifts
        p()
        p("Win rate by 6-month period:")
        triggered["half"] = triggered["as_of_date"].dt.to_period("6M")
        h6 = (
            triggered.groupby("half")
            .agg(total=("outcome","count"),
                 wins=("outcome", lambda x: x.isin(["Win_T2","Win_T1"]).sum()))
            .reset_index()
        )
        h6["win_rate"] = (h6["wins"] / h6["total"] * 100).round(1)
        for _, r in h6.iterrows():
            p(f"  {str(r['half']):<12} n={r['total']:>4}  WR={r['win_rate']:.1f}%")

    # ── 9. WHAT ML CAN REALISTICALLY LEARN ───────────────────────────────────
    h("9. ML READINESS ASSESSMENT")
    n_triggered = len(triggered)
    n_wins      = len(wins)
    n_losses    = len(losses)
    balance     = min(n_wins, n_losses) / max(n_wins, n_losses) * 100

    p(f"Triggered sample size    : {n_triggered:,}")
    p(f"Class balance (W:L)      : {n_wins}:{n_losses}  ({balance:.0f}% balanced)")
    p(f"Min recommended for ML   : 300 per class")
    p()
    if n_triggered < 500:
        p("WARNING: Sample too small for reliable ML. Expand backtest period.")
    elif balance < 40:
        p("WARNING: Severely imbalanced classes. Use class weights or SMOTE.")
    elif balance < 60:
        p("CAUTION: Moderately imbalanced. Use class_weight='balanced'.")
    else:
        p("OK: Sample size and balance acceptable for ML training.")
    p()
    p("KEY FINDING — Why equity curve is unrealistic:")
    p(f"  - {mkt_ret:+.1f}% bull market gives every long-biased system artificial tailwind" if not px.empty and len(px_bt)>=2 else "")
    p(f"  - {len(same_day)/len(triggered)*100:.0f}% of triggers fire on day 0 (same close as setup)")
    p( "  - Daily closes only: no intraday wicks, no gap risk, no partial fills")
    p( "  - Survivorship bias: only stocks alive today are in the dataset")
    p( "  - No slippage, no spread, no brokerage")
    p()
    p("RECOMMENDATION:")
    p("  Before ML, split Win_T1 from Win_T2 as separate classes OR")
    p("  collapse to binary: Triggered+Win vs Triggered+Loss.")
    p("  Train on 2024 only, validate on 2025, test on 2026.")


    # ── WRITE REPORT ─────────────────────────────────────────────────────────
    report = "\n".join(lines)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(report)
    log.info("Report written to %s", OUT)
    print(report)


if __name__ == "__main__":
    main()
