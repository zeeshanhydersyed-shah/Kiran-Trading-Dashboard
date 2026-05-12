"""
Kiran Portfolio Simulation v3 — The Complete System.

Rules:
  Regime filter : KSE-100 daily close > 50-day MA  → long bias active
                  KSE-100 daily close < 50-day MA  → no new entries (sit out)
  Signal source : backtest_setups (same Kiran STM-style screener, unchanged)
  Entry         : signal-day HIGH + 1 PKR (buy on strength)
  Trigger       : forward HIGH >= entry price
  Expiry        : forward LOW  < signal-day HIGH (thesis expired)
  SL            : support_level * 0.99  (max 6% from entry, else skip)
  Exit          : daily close < 20-day MA  (trail full position, no T1 split)
  Sizing        : 1% of portfolio capital per trade
  Cap           : no new entries when invested >= 99% of capital
  Initial cap   : PKR 1,000,000

Saves results to: sim_portfolio_trades_v3
"""

import sys
import logging
from datetime import date
from collections import defaultdict

import pandas as pd
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("kiran_sim_v3.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

from database import get_conn, init_db
from config import EXCLUDED_SECTORS

# ── Constants ─────────────────────────────────────────────────────────────────
INITIAL_CAPITAL   = 1_000_000.0
RISK_FRAC         = 0.01
MAX_SL_PCT        = 6.0
SL_BUFFER         = 0.01
MAX_INVEST_FRAC   = 0.99
MAX_TRIGGER_DAYS  = 10
MAX_HOLDING_DAYS  = 120   # extended — 20MA trail should exit well before this
TRAIL_MA          = 20    # 20-day MA for exit
KSE_MA_PERIOD     = 50    # regime filter MA period


# ═══════════════════════════════════════════════════════════════════════════════
# Database helpers
# ═══════════════════════════════════════════════════════════════════════════════

def init_sim_table():
    with get_conn() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS sim_portfolio_trades_v3;
            CREATE TABLE sim_portfolio_trades_v3 (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                setup_date       TEXT NOT NULL,
                symbol           TEXT NOT NULL,
                direction        TEXT DEFAULT 'LONG',
                signal_high      REAL,
                entry_price      REAL NOT NULL,
                stop_loss        REAL NOT NULL,
                risk_pct         REAL NOT NULL,
                regime_active    INTEGER DEFAULT 1,
                trigger_date     TEXT,
                exit_date        TEXT,
                exit_price       REAL,
                outcome          TEXT,
                skip_reason      TEXT,
                shares           REAL,
                position_value   REAL,
                capital_at_entry REAL,
                pl_pkr           REAL,
                realized_r       REAL,
                portfolio_after  REAL
            );
            CREATE INDEX IF NOT EXISTS idx_v3_date   ON sim_portfolio_trades_v3 (setup_date);
            CREATE INDEX IF NOT EXISTS idx_v3_symbol ON sim_portfolio_trades_v3 (symbol);
        """)
    logger.info("sim_portfolio_trades_v3 table ready.")


def save_sim_trades(rows: list[dict]):
    if not rows:
        return
    cols = [
        "setup_date", "symbol", "direction", "signal_high",
        "entry_price", "stop_loss", "risk_pct", "regime_active",
        "trigger_date", "exit_date", "exit_price",
        "outcome", "skip_reason", "shares", "position_value",
        "capital_at_entry", "pl_pkr", "realized_r", "portfolio_after",
    ]
    ph  = ", ".join(["?"] * len(cols))
    sql = f"INSERT INTO sim_portfolio_trades_v3 ({', '.join(cols)}) VALUES ({ph})"
    with get_conn() as conn:
        conn.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    logger.info("Saved %d rows to sim_portfolio_trades_v3.", len(rows))


# ═══════════════════════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════════════════════

def load_setups() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT as_of_date, symbol, sector, support_level, quality_score "
            "FROM backtest_setups WHERE direction='LONG' ORDER BY as_of_date, symbol"
        ).fetchall()
    setups = [dict(r) for r in rows]
    logger.info("Loaded %d LONG setups.", len(setups))
    return setups


def load_prices() -> pd.DataFrame:
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
    logger.info("Loaded %d price rows for %d symbols.", len(df), df["symbol"].nunique())
    return df


def load_kse100() -> dict[date, float]:
    """Return {date: close} for KSE-100."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, close FROM index_prices "
            "WHERE symbol='KSE-100' AND close IS NOT NULL ORDER BY date"
        ).fetchall()
    return {date.fromisoformat(r[0]): float(r[1]) for r in rows}


def build_regime_map(kse_prices: dict[date, float]) -> dict[date, bool]:
    """
    Returns {date: is_long_regime} where True = KSE-100 close > 50d MA.
    """
    dates  = sorted(kse_prices.keys())
    closes = [kse_prices[d] for d in dates]
    regime = {}
    for i, d in enumerate(dates):
        window = closes[max(0, i - KSE_MA_PERIOD + 1): i + 1]
        ma50   = sum(window) / len(window)
        regime[d] = closes[i] > ma50
    return regime


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _clean(trade: dict):
    for k in [k for k in list(trade) if k.startswith("_")]:
        del trade[k]


# ═══════════════════════════════════════════════════════════════════════════════
# Simulation
# ═══════════════════════════════════════════════════════════════════════════════

def run_simulation(setups_list, prices_df, regime_map):

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

    # Track regime stats
    days_in_regime  = 0
    days_out_regime = 0

    def total_inv():
        return sum(t["_pv"] for t in active)

    for today in all_dates:
        in_regime = regime_map.get(today, True)   # default True if no index data
        if in_regime:
            days_in_regime  += 1
        else:
            days_out_regime += 1

        # ── 1. Manage active trades (exits regardless of regime) ──────────────
        to_close = []
        for trade in active:
            p = price_lk[trade["symbol"]].get(today)
            if not p:
                continue
            _, _, close = p
            trade["_cls"].append(close)

            entry = trade["entry_price"]
            sl    = trade["stop_loss"]
            R     = entry - sl

            # Trail exit: daily close < 20-day MA
            ma20 = sum(trade["_cls"][-TRAIL_MA:]) / min(len(trade["_cls"]), TRAIL_MA)
            if close < ma20:
                trade.update(_pl=(close - entry) * trade["_sh"],
                             _out="Win_Trail" if close > entry else "Loss",
                             _ep=close, _ed=today)
                to_close.append(trade)
            elif close <= sl:
                trade.update(_pl=(sl - entry) * trade["_sh"],
                             _out="Loss", _ep=sl, _ed=today)
                to_close.append(trade)

            if trade not in to_close:
                trig_d = date.fromisoformat(trade["_td"])
                if (today - trig_d).days >= MAX_HOLDING_DAYS:
                    trade.update(_pl=(close - entry) * trade["_sh"],
                                 _out="Win_Trail" if close > entry else "Loss",
                                 _ep=close, _ed=today)
                    to_close.append(trade)

        for t in to_close:
            capital += t["_pv"] + t["_pl"]
        rem_inv = sum(t["_pv"] for t in active if t not in to_close)
        port_now = capital + rem_inv

        for t in to_close:
            entry = t["entry_price"]
            R     = entry - t["stop_loss"]
            rr    = round((t["_ep"] - entry) / R, 3) if R > 0 else 0.0
            t.update({
                "trigger_date":    t["_td"],
                "exit_date":       t["_ed"].isoformat(),
                "exit_price":      round(t["_ep"], 2),
                "outcome":         t["_out"],
                "pl_pkr":          round(t["_pl"], 2),
                "realized_r":      rr,
                "portfolio_after": round(port_now, 2),
            })
            active.remove(t)
            _clean(t)
            results.append(t)

        # ── 2. Pending: check trigger / expiry ────────────────────────────────
        to_act = []; to_exp = []
        for trade in pending:
            p = price_lk[trade["symbol"]].get(today)
            if not p:
                trade["_dp"] += 1
                if trade["_dp"] > MAX_TRIGGER_DAYS:
                    trade.update(outcome="Stale", skip_reason="Trigger window expired")
                    to_exp.append(trade)
                continue
            high, low, close = p
            if high >= trade["entry_price"]:
                to_act.append((trade, today)); continue
            if low < trade["signal_high"]:
                trade.update(outcome="Stale", skip_reason="Price below signal high")
                to_exp.append(trade); continue
            trade["_dp"] += 1
            if trade["_dp"] > MAX_TRIGGER_DAYS:
                trade.update(outcome="Stale", skip_reason="Trigger window expired")
                to_exp.append(trade)

        for t in to_exp:
            pending.remove(t); _clean(t); results.append(t)

        for (trade, trig_date) in to_act:
            pending.remove(trade)
            inv = total_inv()
            if capital > 0 and inv / capital >= MAX_INVEST_FRAC:
                trade.update(outcome="Skipped", skip_reason="Capital limit")
                _clean(trade); results.append(trade); continue

            R       = trade["entry_price"] - trade["stop_loss"]
            shares  = capital * RISK_FRAC / R
            pv      = shares * trade["entry_price"]
            max_a   = capital * MAX_INVEST_FRAC - inv
            if pv > max_a:
                shares = max_a / trade["entry_price"]; pv = shares * trade["entry_price"]
            if shares < 0.001 or pv < 1.0:
                trade.update(outcome="Skipped", skip_reason="Position too small")
                _clean(trade); results.append(trade); continue

            capital -= pv

            # Seed 20MA with pre-trigger history
            hist = [c for d, c in price_hist[trade["symbol"]] if d <= trig_date]
            seed = hist[-25:] if hist else []
            tc   = price_lk[trade["symbol"]].get(trig_date)
            if tc: seed.append(tc[2])

            trade.update(
                shares=round(shares, 4),
                position_value=round(pv, 2),
                capital_at_entry=round(capital + pv, 2),
                trigger_date=trig_date.isoformat(),
                _pv=pv, _sh=shares, _cls=seed[:], _td=trig_date.isoformat(),
            )
            active.append(trade)

        # ── 3. New signals today — only if regime is long-biased ─────────────
        if in_regime:
            for srow in setups_by_date.get(today, []):
                sym = srow["symbol"]
                p   = price_lk[sym].get(today)
                if not p: continue
                high, _, _ = p
                if high <= 0: continue

                entry = round(high + 1.0, 2)
                sup   = srow.get("support_level") or 0
                if sup <= 0: continue
                sl = round(sup * (1 - SL_BUFFER), 2)
                if sl >= entry: continue

                risk_pct = (entry - sl) / entry * 100
                if risk_pct > MAX_SL_PCT:
                    results.append({
                        "setup_date": srow["as_of_date"], "symbol": sym,
                        "direction": "LONG", "signal_high": round(high, 2),
                        "entry_price": entry, "stop_loss": sl,
                        "risk_pct": round(risk_pct, 2), "regime_active": 1,
                        "outcome": "Skipped", "skip_reason": f"Risk {risk_pct:.1f}%>{MAX_SL_PCT}%",
                    })
                    continue

                pending.append({
                    "setup_date": srow["as_of_date"], "symbol": sym,
                    "direction": "LONG", "signal_high": round(high, 2),
                    "entry_price": entry, "stop_loss": sl,
                    "risk_pct": round(risk_pct, 2), "regime_active": 1,
                    "trigger_date": None, "exit_date": None, "exit_price": None,
                    "outcome": None, "skip_reason": None,
                    "shares": None, "position_value": None, "capital_at_entry": None,
                    "pl_pkr": None, "realized_r": None, "portfolio_after": None,
                    "_dp": 0,
                })
        else:
            # Regime off — record skipped signals for transparency
            for srow in setups_by_date.get(today, []):
                sym = srow["symbol"]
                p   = price_lk[sym].get(today)
                if not p: continue
                high, _, _ = p
                entry = round(high + 1.0, 2)
                sup   = srow.get("support_level") or 0
                if sup <= 0: continue
                sl    = round(sup * (1 - SL_BUFFER), 2)
                if sl >= entry: continue
                risk_pct = (entry - sl) / entry * 100
                results.append({
                    "setup_date": srow["as_of_date"], "symbol": sym,
                    "direction": "LONG", "signal_high": round(high, 2),
                    "entry_price": entry, "stop_loss": sl,
                    "risk_pct": round(risk_pct, 2), "regime_active": 0,
                    "outcome": "Skipped", "skip_reason": "Regime off (KSE-100 below 50d MA)",
                })

    # ── Flush active at end ───────────────────────────────────────────────────
    for trade in list(active):
        sym   = trade["symbol"]
        dates = sorted(price_lk[sym].keys())
        if not dates:
            trade["outcome"] = "Expired"; _clean(trade); results.append(trade); continue
        _, _, lc = price_lk[sym][dates[-1]]
        entry = trade["entry_price"]; R = entry - trade["stop_loss"]
        pl    = (lc - entry) * trade["_sh"]
        capital += trade["_pv"] + pl
        rr    = round((lc - entry) / R, 3) if R > 0 else 0.0
        trade.update(
            trigger_date=trade["_td"], exit_date=dates[-1].isoformat(),
            exit_price=round(lc, 2),
            outcome="Win_Trail" if lc > entry else "Loss",
            pl_pkr=round(pl, 2), realized_r=rr,
            portfolio_after=round(capital, 2),
        )
        _clean(trade); results.append(trade)

    for trade in list(pending):
        if not trade.get("outcome"):
            trade["outcome"] = "Stale"; trade["skip_reason"] = "Sim ended"
        _clean(trade); results.append(trade)

    logger.info("Simulation complete. %d records. Final capital: PKR %.0f",
                len(results), capital)
    logger.info("Days in long regime: %d  |  Days out (sat out): %d",
                days_in_regime, days_out_regime)
    return results, capital, days_in_regime, days_out_regime


# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════

def print_summary(results, final_cap, days_in, days_out):
    triggered = [r for r in results if r.get("trigger_date")]
    wins   = [r for r in triggered if r.get("outcome") == "Win_Trail"]
    losses = [r for r in triggered if r.get("outcome") == "Loss"]
    skipped_regime = sum(1 for r in results
                         if (r.get("skip_reason") or "").startswith("Regime"))
    skipped_risk   = sum(1 for r in results
                         if "Risk" in (r.get("skip_reason") or ""))
    stale  = sum(1 for r in results if r.get("outcome") == "Stale")
    total_pl = sum(r.get("pl_pkr") or 0 for r in results)

    avg_win_r  = sum(r.get("realized_r") or 0 for r in wins)  / len(wins)  if wins  else 0
    avg_loss_r = sum(r.get("realized_r") or 0 for r in losses)/ len(losses) if losses else 0

    # Avg holding days for winners
    win_holds = []
    for r in wins:
        try:
            td = date.fromisoformat(r["trigger_date"])
            ed = date.fromisoformat(r["exit_date"])
            win_holds.append((ed - td).days)
        except Exception:
            pass
    avg_hold = sum(win_holds) / len(win_holds) if win_holds else 0

    total_days = days_in + days_out
    logger.info("=" * 65)
    logger.info("Simulation v3  —  Complete System")
    logger.info("  Regime filter    : KSE-100 > 50d MA")
    logger.info("  Exit rule        : Daily close < 20d MA (full position)")
    logger.info("  SL cap           : %.0f%%   Risk/trade: 1%%", MAX_SL_PCT)
    logger.info("-" * 65)
    logger.info("  Regime days IN   : %d (%.0f%% of period)",
                days_in, days_in/total_days*100 if total_days else 0)
    logger.info("  Regime days OUT  : %d (%.0f%% of period — sitting in cash)",
                days_out, days_out/total_days*100 if total_days else 0)
    logger.info("  Signals skipped (regime off) : %d", skipped_regime)
    logger.info("  Signals skipped (risk >6%%)  : %d", skipped_risk)
    logger.info("  Stale (never triggered)      : %d", stale)
    logger.info("-" * 65)
    logger.info("  Triggered trades : %d", len(triggered))
    logger.info("  Wins (Win_Trail) : %d  avg %.2fR  avg hold %d days",
                len(wins), avg_win_r, avg_hold)
    logger.info("  Losses           : %d  avg %.2fR", len(losses), avg_loss_r)
    if triggered:
        logger.info("  Win rate         : %.1f%%", len(wins)/len(triggered)*100)
    logger.info("  Total P&L        : PKR %+.0f", total_pl)
    logger.info("  Initial capital  : PKR %.0f", INITIAL_CAPITAL)
    logger.info("  Final capital    : PKR %.0f", final_cap)
    logger.info("  Total return     : %+.1f%%",
                (final_cap - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100)
    # Rough CAGR (2020-01-01 to 2026-05-12 = ~6.36 years)
    years = 6.36
    cagr  = ((final_cap / INITIAL_CAPITAL) ** (1 / years) - 1) * 100
    logger.info("  Approx CAGR      : %+.1f%%", cagr)
    logger.info("=" * 65)

    # Year-by-year breakdown
    logger.info("\nYear-by-year P&L (triggered trades only):")
    logger.info("  %-6s  %6s  %4s  %4s  %7s  %8s", "Year", "Trades", "Wins", "Loss", "WinRate", "P/L PKR")
    logger.info("  " + "-" * 48)
    from collections import defaultdict
    by_year = defaultdict(lambda: {"t": 0, "w": 0, "l": 0, "pl": 0.0})
    for r in triggered:
        try:
            yr = date.fromisoformat(r["trigger_date"]).year
        except Exception:
            continue
        by_year[yr]["t"] += 1
        if r["outcome"] == "Win_Trail": by_year[yr]["w"] += 1
        elif r["outcome"] == "Loss":    by_year[yr]["l"] += 1
        by_year[yr]["pl"] += r.get("pl_pkr") or 0
    for yr in sorted(by_year.keys()):
        d  = by_year[yr]
        wr = d["w"] / d["t"] * 100 if d["t"] else 0
        logger.info("  %-6d  %6d  %4d  %4d  %6.0f%%  %+8.0f",
                    yr, d["t"], d["w"], d["l"], wr, d["pl"])


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    init_db()
    init_sim_table()

    setups    = load_setups()
    prices_df = load_prices()
    kse_px    = load_kse100()

    if not kse_px:
        logger.error("No KSE-100 index data. Cannot apply regime filter.")
        return

    regime_map = build_regime_map(kse_px)
    days_bull = sum(1 for v in regime_map.values() if v)
    days_bear = sum(1 for v in regime_map.values() if not v)
    logger.info("Regime map built: %d bull days / %d bear days (KSE-100 vs 50d MA)",
                days_bull, days_bear)

    results, final_cap, days_in, days_out = run_simulation(
        setups, prices_df, regime_map
    )

    save_sim_trades(results)
    print_summary(results, final_cap, days_in, days_out)


if __name__ == "__main__":
    main()
