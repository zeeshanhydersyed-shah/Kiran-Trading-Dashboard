"""
Run multiple simulation variants to isolate which changes improve returns.

Variants tested:
  v1  (baseline)   SL=6%  T1=1R   risk=1%flat
  v3               SL=8%  T1=1R   tiered sizing (score4=2% score3=1.5%)
  v4               SL=6%  T1=1R   score>=3 filter only, tiered sizing
  v5               SL=8%  T1=1R   score>=3 filter, tiered sizing
  v6               SL=6%  T1=1R   no split exit: trail full position from entry

Results printed for comparison — no DB writes.
"""

import sys, logging
from datetime import date
from collections import defaultdict
import pandas as pd

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

from database import get_conn, init_db
from config import EXCLUDED_SECTORS

INITIAL_CAPITAL  = 1_000_000.0
SL_BUFFER        = 0.01
MAX_INVEST_FRAC  = 0.99
MAX_TRIGGER_DAYS = 10
MAX_HOLDING_DAYS = 80


def load_setups():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT as_of_date, symbol, sector, support_level, quality_score "
            "FROM backtest_setups WHERE direction='LONG' ORDER BY as_of_date, symbol"
        ).fetchall()
    return [dict(r) for r in rows]


def load_prices():
    excl_ph = ",".join(["?"] * len(EXCLUDED_SECTORS))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT p.symbol, p.date, COALESCE(p.high,p.close) high, "
            f"COALESCE(p.low,p.close) low, p.close "
            f"FROM prices p JOIN sectors s ON s.symbol=p.symbol "
            f"WHERE s.sector NOT IN ({excl_ph}) ORDER BY p.symbol, p.date",
            list(EXCLUDED_SECTORS),
        ).fetchall()
    df = pd.DataFrame(rows, columns=["symbol","date","high","low","close"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def run(setups_list, prices_df,
        max_sl_pct=6.0,
        t1_r=1.0,
        min_quality=0,
        risk_by_score=None,
        default_risk=0.01,
        no_split=False):
    """
    Generic simulation engine parameterised by the variant settings.
    no_split=True: trail the full position from entry (no T1 partial exit).
    """
    if risk_by_score is None:
        risk_by_score = {}

    def rfrac(score):
        return risk_by_score.get(score, default_risk)

    price_lk   = defaultdict(dict)
    price_hist = defaultdict(list)
    for row in prices_df.itertuples(index=False):
        price_lk[row.symbol][row.date] = (float(row.high), float(row.low), float(row.close))
        price_hist[row.symbol].append((row.date, float(row.close)))

    all_dates = sorted(prices_df["date"].unique())
    setups_by_date = defaultdict(list)
    for s in setups_list:
        setups_by_date[date.fromisoformat(s["as_of_date"])].append(s)

    capital  = INITIAL_CAPITAL
    pending  = []
    active   = []
    results  = []

    def total_inv():
        return sum(t["_pv"] for t in active)

    for today in all_dates:
        to_close = []

        for trade in active:
            p = price_lk[trade["sym"]].get(today)
            if not p:
                continue
            _, _, close = p
            trade["cls"].append(close)
            entry = trade["entry"]
            sl    = trade["sl"]
            t1    = trade["t1"]
            R     = entry - sl

            if no_split:
                ma10 = sum(trade["cls"][-10:]) / min(len(trade["cls"]), 10)
                if close < ma10:
                    trade.update(_pl=(close - entry)*trade["sh"], _out="Win_Trail", _ep=close, _ed=today)
                    to_close.append(trade)
                elif close <= sl:
                    trade.update(_pl=(sl - entry)*trade["sh"], _out="Loss", _ep=sl, _ed=today)
                    to_close.append(trade)
            else:
                if not trade["t1hit"]:
                    if close >= t1:
                        trade["t1hit"] = True
                        hv = trade["_pv"] / 2
                        t1p = (t1 - entry) * trade["sh"] / 2
                        capital += hv + t1p
                        trade["_pv"] -= hv
                        trade["rem"] = trade["sh"] / 2
                        trade["t1pl"] = t1p
                    elif close <= sl:
                        trade.update(_pl=(sl - entry)*trade["sh"], _out="Loss", _ep=sl, _ed=today)
                        to_close.append(trade)
                else:
                    ma10 = sum(trade["cls"][-10:]) / min(len(trade["cls"]), 10)
                    if close < ma10:
                        trail_pl = (close - entry) * trade["rem"]
                        trade.update(_pl=trail_pl, _out="Win_Trail", _ep=close, _ed=today)
                        to_close.append(trade)

            if trade not in to_close:
                if (today - trade["td"]).days >= MAX_HOLDING_DAYS:
                    rem = trade.get("rem", trade["sh"]) if (not no_split and trade.get("t1hit")) else trade["sh"]
                    trade.update(_pl=(close-entry)*rem,
                                 _out="Win_Trail" if close>entry else "Loss",
                                 _ep=close, _ed=today)
                    to_close.append(trade)

        for t in to_close:
            capital += t["_pv"] + t["_pl"]
        rem_inv = sum(t["_pv"] for t in active if t not in to_close)

        for t in to_close:
            entry = t["entry"]; R = entry - t["sl"]
            t1pl  = t.get("t1pl", 0.0)
            totpl = t1pl + t["_pl"]
            r_ex  = (t["_ep"] - entry) / R
            if not no_split and t.get("t1hit"):
                rr = round(t1_r * 0.5 + 0.5 * r_ex, 3)
            else:
                rr = round(r_ex, 3)
            results.append({
                "trigger_date": t["td"].isoformat(),
                "outcome": t["_out"],
                "pl_pkr": round(totpl, 2),
                "realized_r": rr,
                "quality_score": t["qs"],
            })
            active.remove(t)

        # pending
        to_act = []; to_exp = []
        for trade in pending:
            p = price_lk[trade["sym"]].get(today)
            if not p:
                trade["dp"] += 1
                if trade["dp"] > MAX_TRIGGER_DAYS:
                    results.append({"outcome": "Stale"})
                    to_exp.append(trade)
                continue
            high, low, close = p
            if high >= trade["entry"]:
                to_act.append((trade, today)); continue
            if low < trade["sigh"]:
                results.append({"outcome": "Stale"})
                to_exp.append(trade); continue
            trade["dp"] += 1
            if trade["dp"] > MAX_TRIGGER_DAYS:
                results.append({"outcome": "Stale"})
                to_exp.append(trade)

        for t in to_exp:
            pending.remove(t)

        for (trade, trig_date) in to_act:
            pending.remove(trade)
            inv = total_inv()
            if capital > 0 and inv / capital >= MAX_INVEST_FRAC:
                results.append({"outcome": "Skipped_cap"})
                continue
            qs      = trade["qs"]
            R       = trade["entry"] - trade["sl"]
            shares  = capital * rfrac(qs) / R
            pv      = shares * trade["entry"]
            max_a   = capital * MAX_INVEST_FRAC - inv
            if pv > max_a:
                shares = max_a / trade["entry"]
                pv = shares * trade["entry"]
            if shares < 0.001 or pv < 1.0:
                results.append({"outcome": "Skipped_small"})
                continue
            capital -= pv
            hist = [c for d, c in price_hist[trade["sym"]] if d <= trig_date]
            seed = hist[-14:] if hist else []
            tc   = price_lk[trade["sym"]].get(trig_date)
            if tc:
                seed.append(tc[2])
            trade.update(_pv=pv, sh=shares, rem=shares,
                         t1hit=False, t1pl=0.0, cls=seed[:], td=trig_date, _pl=0.0)
            active.append(trade)

        # new signals
        for srow in setups_by_date.get(today, []):
            qs  = srow.get("quality_score") or 2
            if min_quality > 0 and qs < min_quality:
                results.append({"outcome": "Skipped_qs"})
                continue
            sym = srow["symbol"]
            p   = price_lk[sym].get(today)
            if not p:
                continue
            high, _, _ = p
            if high <= 0:
                continue
            entry = round(high + 1.0, 2)
            sup   = srow.get("support_level") or 0
            if sup <= 0:
                continue
            sl = round(sup * (1 - SL_BUFFER), 2)
            if sl >= entry:
                continue
            risk_pct = (entry - sl) / entry * 100
            if risk_pct > max_sl_pct:
                results.append({"outcome": "Skipped_risk"})
                continue
            t1 = round(entry + t1_r * (entry - sl), 2)
            pending.append({"sym": sym, "qs": qs, "sigh": high,
                            "entry": entry, "sl": sl, "t1": t1, "dp": 0})

    # flush active
    for trade in list(active):
        dates = sorted(price_lk[trade["sym"]].keys())
        if not dates:
            results.append({"outcome": "Expired"}); continue
        _, _, lc = price_lk[trade["sym"]][dates[-1]]
        entry = trade["entry"]; R = entry - trade["sl"]
        rem = trade.get("rem", trade["sh"]) if (not no_split and trade.get("t1hit")) else trade["sh"]
        cp  = (lc - entry) * rem
        t1pl = trade.get("t1pl", 0.0)
        capital += trade["_pv"] + cp
        r_ex = (lc - entry) / R
        if not no_split and trade.get("t1hit"):
            rr = round(t1_r * 0.5 + 0.5 * r_ex, 3)
        else:
            rr = round(r_ex, 3)
        results.append({
            "outcome": "Win_Trail" if lc > entry else "Loss",
            "pl_pkr": round(t1pl + cp, 2),
            "realized_r": rr,
            "quality_score": trade["qs"],
        })
    for t in pending:
        results.append({"outcome": "Stale"})

    return results, capital


def summarise(label, results, final_cap):
    trig = [r for r in results if r.get("trigger_date") or
            r.get("outcome") in ("Win_Trail", "Loss")]
    wins = sum(1 for r in trig if r.get("outcome") == "Win_Trail")
    loss = sum(1 for r in trig if r.get("outcome") == "Loss")
    tot  = len(trig)
    pl   = sum(r.get("pl_pkr") or 0 for r in results)
    ret  = (final_cap - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    wr   = wins / tot * 100 if tot else 0
    avg_r = sum(r.get("realized_r") or 0 for r in trig) / tot if tot else 0
    print(f"  {label:<40s}  triggered={tot:>4d}  win={wr:>5.1f}%  "
          f"P/L=PKR {pl:>+10.0f}  return={ret:>+6.1f}%  avgR={avg_r:>+5.2f}")


def main():
    init_db()
    logger.info("Loading data...")
    setups    = load_setups()
    prices_df = load_prices()

    TIERED = {4: 0.02, 3: 0.015}

    variants = [
        ("v1  baseline  SL=6% T1=1R flat1%",
         dict(max_sl_pct=6, t1_r=1.0, min_quality=0, risk_by_score={}, default_risk=0.01)),
        ("v3  SL=8% T1=1R tiered",
         dict(max_sl_pct=8, t1_r=1.0, min_quality=0, risk_by_score=TIERED, default_risk=0.01)),
        ("v4  SL=6% score>=3 tiered",
         dict(max_sl_pct=6, t1_r=1.0, min_quality=3, risk_by_score=TIERED, default_risk=0.015)),
        ("v5  SL=8% score>=3 tiered",
         dict(max_sl_pct=8, t1_r=1.0, min_quality=3, risk_by_score=TIERED, default_risk=0.015)),
        ("v6  SL=6% T1=1R no-split trail",
         dict(max_sl_pct=6, t1_r=1.0, min_quality=0, risk_by_score={}, default_risk=0.01, no_split=True)),
        ("v7  SL=8% T1=1R no-split trail",
         dict(max_sl_pct=8, t1_r=1.0, min_quality=0, risk_by_score={}, default_risk=0.01, no_split=True)),
        ("v8  SL=8% T1=1R flat1% (isolate SL only)",
         dict(max_sl_pct=8, t1_r=1.0, min_quality=0, risk_by_score={}, default_risk=0.01)),
        ("v9  SL=10% T1=1R flat1%",
         dict(max_sl_pct=10, t1_r=1.0, min_quality=0, risk_by_score={}, default_risk=0.01)),
        ("v10 SL=6% T1=1R risk=2% flat",
         dict(max_sl_pct=6, t1_r=1.0, min_quality=0, risk_by_score={}, default_risk=0.02)),
    ]

    print("\nVariant comparison (2020-2026, 1M initial capital)")
    print("-" * 100)
    for label, kwargs in variants:
        res, cap = run(setups, prices_df, **kwargs)
        summarise(label, res, cap)
    print("-" * 100)


if __name__ == "__main__":
    main()
