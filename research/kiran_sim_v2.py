"""
Kiran Portfolio Simulation v2 — optimised execution rules.

Changes vs v1 (kiran_sim.py):
  1. MAX_SL_PCT raised 6% -> 8%  (unlocks ~900 additional setups)
  2. Tiered position sizing by quality_score:
       score == 4  ->  2.0% capital risk per trade
       score == 3  ->  1.5% capital risk per trade
       score <= 2  ->  1.0% capital risk per trade  (unchanged)
  3. T1 raised to 1.5R  (sell half at 1.5R, trail remainder on 10-day MA)

Everything else — entry rule, expiry rule, SL placement, trailing MA exit,
99% cap, no margin — is identical to v1.

Results saved to: sim_portfolio_trades_v2

Usage:
    python kiran_sim_v2.py
"""

import sys
import logging
from datetime import date
from collections import defaultdict

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("kiran_sim_v2.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

from database import get_conn, init_db
from config import EXCLUDED_SECTORS

# ── Constants ─────────────────────────────────────────────────────────────────
INITIAL_CAPITAL   = 1_000_000.0
MAX_SL_PCT        = 8.0      # raised from 6% → 8%
SL_BUFFER         = 0.01
MAX_INVEST_FRAC   = 0.99
MAX_TRIGGER_DAYS  = 10
MAX_HOLDING_DAYS  = 80
T1_R              = 1.5      # raised from 1R → 1.5R

# Tiered risk fractions by quality_score
RISK_BY_SCORE = {4: 0.02, 3: 0.015}   # score<=2 defaults to 0.01
DEFAULT_RISK  = 0.01


def _risk_frac(score: int) -> float:
    return RISK_BY_SCORE.get(score, DEFAULT_RISK)


# ═══════════════════════════════════════════════════════════════════════════════
# Database helpers
# ═══════════════════════════════════════════════════════════════════════════════

def init_sim_table():
    with get_conn() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS sim_portfolio_trades_v2;
            CREATE TABLE sim_portfolio_trades_v2 (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                setup_date       TEXT NOT NULL,
                symbol           TEXT NOT NULL,
                direction        TEXT DEFAULT 'LONG',
                quality_score    INTEGER,
                signal_high      REAL,
                entry_price      REAL NOT NULL,
                stop_loss        REAL NOT NULL,
                target_1r        REAL NOT NULL,
                risk_pct         REAL NOT NULL,
                risk_frac        REAL,
                trigger_date     TEXT,
                t1_hit           INTEGER DEFAULT 0,
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
            CREATE INDEX IF NOT EXISTS idx_sim2_date   ON sim_portfolio_trades_v2 (setup_date);
            CREATE INDEX IF NOT EXISTS idx_sim2_symbol ON sim_portfolio_trades_v2 (symbol);
            CREATE INDEX IF NOT EXISTS idx_sim2_exit   ON sim_portfolio_trades_v2 (exit_date);
        """)
    logger.info("sim_portfolio_trades_v2 table ready.")


def save_sim_trades(rows: list[dict]):
    if not rows:
        return
    cols = [
        "setup_date", "symbol", "direction", "quality_score", "signal_high",
        "entry_price", "stop_loss", "target_1r", "risk_pct", "risk_frac",
        "trigger_date", "t1_hit", "exit_date", "exit_price",
        "outcome", "skip_reason", "shares", "position_value",
        "capital_at_entry", "pl_pkr", "realized_r", "portfolio_after",
    ]
    ph  = ", ".join(["?"] * len(cols))
    sql = f"INSERT INTO sim_portfolio_trades_v2 ({', '.join(cols)}) VALUES ({ph})"
    with get_conn() as conn:
        conn.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    logger.info("Saved %d sim trade rows.", len(rows))


# ═══════════════════════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════════════════════

def load_setups() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT as_of_date, symbol, sector, support_level, quality_score
               FROM backtest_setups
               WHERE direction = 'LONG'
               ORDER BY as_of_date, symbol"""
        ).fetchall()
    setups = [dict(r) for r in rows]
    logger.info("Loaded %d LONG setups from backtest_setups.", len(setups))
    return setups


def load_prices() -> pd.DataFrame:
    excl_ph = ",".join(["?"] * len(EXCLUDED_SECTORS))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT p.symbol, p.date,
                       COALESCE(p.high,  p.close) AS high,
                       COALESCE(p.low,   p.close) AS low,
                       p.close
                FROM prices p
                JOIN sectors s ON s.symbol = p.symbol
                WHERE s.sector NOT IN ({excl_ph})
                ORDER BY p.symbol, p.date""",
            list(EXCLUDED_SECTORS),
        ).fetchall()
    df = pd.DataFrame(rows, columns=["symbol", "date", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    logger.info("Loaded %d price rows for %d symbols.", len(df), df["symbol"].nunique())
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# Simulation helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _clean(trade: dict):
    for k in [k for k in list(trade) if k.startswith("_")]:
        del trade[k]


def _skip_row(srow: dict, high: float, entry: float, sl: float,
              risk_pct: float, score: int, reason: str) -> dict:
    return {
        "setup_date":       srow["as_of_date"],
        "symbol":           srow["symbol"],
        "direction":        "LONG",
        "quality_score":    score,
        "signal_high":      round(high, 2),
        "entry_price":      entry,
        "stop_loss":        sl,
        "target_1r":        round(entry + T1_R * (entry - sl), 2),
        "risk_pct":         risk_pct,
        "risk_frac":        _risk_frac(score),
        "trigger_date":     None, "t1_hit": 0,
        "exit_date":        None, "exit_price": None,
        "outcome":          "Skipped", "skip_reason": reason,
        "shares": None, "position_value": None, "capital_at_entry": None,
        "pl_pkr": None, "realized_r": None, "portfolio_after": None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Main simulation
# ═══════════════════════════════════════════════════════════════════════════════

def run_simulation(setups_list: list[dict], prices_df: pd.DataFrame):
    price_lk   : dict[str, dict[date, tuple]] = defaultdict(dict)
    price_hist : dict[str, list[tuple]]        = defaultdict(list)

    for row in prices_df.itertuples(index=False):
        d   = row.date
        sym = row.symbol
        price_lk[sym][d]  = (float(row.high), float(row.low), float(row.close))
        price_hist[sym].append((d, float(row.close)))

    all_dates = sorted(prices_df["date"].unique())

    setups_by_date: dict[date, list[dict]] = defaultdict(list)
    for s in setups_list:
        setups_by_date[date.fromisoformat(s["as_of_date"])].append(s)

    capital = INITIAL_CAPITAL
    pending : list[dict] = []
    active  : list[dict] = []
    results : list[dict] = []

    def total_invested() -> float:
        return sum(t["_pos_val"] for t in active)

    for today in all_dates:

        # ── 1. Manage active trades ───────────────────────────────────────────
        to_close: list[dict] = []

        for trade in active:
            sym = trade["symbol"]
            p   = price_lk[sym].get(today)
            if not p:
                continue
            _, _, close = p
            trade["_closes"].append(close)

            entry = trade["entry_price"]
            sl    = trade["stop_loss"]
            t1    = trade["target_1r"]   # = entry + T1_R * R
            R     = entry - sl

            if not trade["_t1_hit"]:
                if close >= t1:
                    trade["_t1_hit"]   = True
                    half_val           = trade["_pos_val"] / 2
                    t1_profit          = (t1 - entry) * trade["_shares"] / 2
                    capital           += half_val + t1_profit
                    trade["_pos_val"] -= half_val
                    trade["_rem_shr"]  = trade["_shares"] / 2
                    trade["_t1_pl"]    = t1_profit
                elif close <= sl:
                    trade["_close_pl"] = (sl - entry) * trade["_shares"]
                    trade["_outcome"]  = "Loss"
                    trade["_exit_px"]  = sl
                    trade["_exit_dt"]  = today
                    to_close.append(trade)
            else:
                ma10 = sum(trade["_closes"][-10:]) / min(len(trade["_closes"]), 10)
                if close < ma10:
                    trail_pl = (close - entry) * trade["_rem_shr"]
                    trade["_close_pl"] = trail_pl
                    trade["_outcome"]  = "Win_Trail"
                    trade["_exit_px"]  = close
                    trade["_exit_dt"]  = today
                    to_close.append(trade)

            if trade not in to_close:
                trig_d = date.fromisoformat(trade["_trig_dt"])
                if (today - trig_d).days >= MAX_HOLDING_DAYS:
                    rem = trade["_rem_shr"] if trade["_t1_hit"] else trade["_shares"]
                    rem_pl = (close - entry) * rem
                    trade["_close_pl"] = rem_pl
                    trade["_outcome"]  = "Win_Trail" if close > entry else "Loss"
                    trade["_exit_px"]  = close
                    trade["_exit_dt"]  = today
                    to_close.append(trade)

        for trade in to_close:
            capital += trade["_pos_val"] + trade["_close_pl"]
        remaining_inv = sum(t["_pos_val"] for t in active if t not in to_close)
        portfolio_now = capital + remaining_inv

        for trade in to_close:
            entry    = trade["entry_price"]
            R        = entry - trade["stop_loss"]
            t1_pl    = trade.get("_t1_pl", 0.0)
            close_pl = trade["_close_pl"]
            total_pl = t1_pl + close_pl

            r_close = (trade["_exit_px"] - entry) / R
            if trade["_t1_hit"]:
                realized_r = round(T1_R * 0.5 + 0.5 * r_close, 3)
            else:
                realized_r = round(r_close, 3)

            trade.update({
                "trigger_date":    trade["_trig_dt"],
                "t1_hit":          int(trade["_t1_hit"]),
                "exit_date":       trade["_exit_dt"].isoformat(),
                "exit_price":      round(trade["_exit_px"], 2),
                "outcome":         trade["_outcome"],
                "pl_pkr":          round(total_pl, 2),
                "realized_r":      realized_r,
                "portfolio_after": round(portfolio_now, 2),
            })
            active.remove(trade)
            _clean(trade)
            results.append(trade)

        # ── 2. Check pending for trigger or expiry ────────────────────────────
        to_activate: list[tuple] = []
        to_expire:   list[dict]  = []

        for trade in pending:
            sym = trade["symbol"]
            p   = price_lk[sym].get(today)
            if not p:
                trade["_dpend"] += 1
                if trade["_dpend"] > MAX_TRIGGER_DAYS:
                    trade["outcome"]     = "Stale"
                    trade["skip_reason"] = "Trigger window expired"
                    to_expire.append(trade)
                continue

            high, low, close = p
            entry    = trade["entry_price"]
            sig_high = trade["signal_high"]

            if high >= entry:
                to_activate.append((trade, today))
                continue

            if low < sig_high:
                trade["outcome"]     = "Stale"
                trade["skip_reason"] = "Price went back below signal high"
                to_expire.append(trade)
                continue

            trade["_dpend"] += 1
            if trade["_dpend"] > MAX_TRIGGER_DAYS:
                trade["outcome"]     = "Stale"
                trade["skip_reason"] = "Trigger window expired"
                to_expire.append(trade)

        for t in to_expire:
            pending.remove(t)
            _clean(t)
            results.append(t)

        for (trade, trig_date) in to_activate:
            pending.remove(trade)

            inv = total_invested()
            if capital > 0 and inv / capital >= MAX_INVEST_FRAC:
                trade["outcome"]     = "Skipped"
                trade["skip_reason"] = f"Capital limit ({inv/capital*100:.0f}% invested)"
                _clean(trade)
                results.append(trade)
                continue

            score    = trade.get("quality_score") or 2
            rf       = _risk_frac(score)
            R        = trade["entry_price"] - trade["stop_loss"]
            risk_amt = capital * rf
            shares   = risk_amt / R
            pos_val  = shares * trade["entry_price"]

            max_allowed = capital * MAX_INVEST_FRAC - inv
            if pos_val > max_allowed:
                shares  = max_allowed / trade["entry_price"]
                pos_val = shares * trade["entry_price"]

            if shares < 0.001 or pos_val < 1.0:
                trade["outcome"]     = "Skipped"
                trade["skip_reason"] = "Position too small after capital cap"
                _clean(trade)
                results.append(trade)
                continue

            capital -= pos_val

            hist_closes = [c for d, c in price_hist[trade["symbol"]] if d <= trig_date]
            seed_closes = hist_closes[-14:] if hist_closes else []
            trig_close  = price_lk[trade["symbol"]].get(trig_date)
            if trig_close:
                seed_closes.append(trig_close[2])

            trade["shares"]           = round(shares, 4)
            trade["position_value"]   = round(pos_val, 2)
            trade["capital_at_entry"] = round(capital + pos_val, 2)
            trade["trigger_date"]     = trig_date.isoformat()
            trade["risk_frac"]        = rf
            trade["_trig_dt"]  = trig_date.isoformat()
            trade["_shares"]   = shares
            trade["_rem_shr"]  = shares
            trade["_pos_val"]  = pos_val
            trade["_t1_hit"]   = False
            trade["_t1_pl"]    = 0.0
            trade["_closes"]   = seed_closes[:]

            active.append(trade)

        # ── 3. Add new setup signals from today ───────────────────────────────
        for srow in setups_by_date.get(today, []):
            sym   = srow["symbol"]
            score = srow.get("quality_score") or 2
            p     = price_lk[sym].get(today)
            if not p:
                continue
            high, low, close = p
            if high <= 0:
                continue

            entry = round(high + 1.0, 2)
            sup   = srow.get("support_level") or 0
            if sup <= 0:
                continue
            sl = round(sup * (1 - SL_BUFFER), 2)
            if sl >= entry:
                continue

            risk_pct = round((entry - sl) / entry * 100, 2)
            if risk_pct > MAX_SL_PCT:
                results.append(_skip_row(srow, high, entry, sl, risk_pct, score,
                                         f"Risk {risk_pct:.1f}% > {MAX_SL_PCT}% max"))
                continue

            t1 = round(entry + T1_R * (entry - sl), 2)

            pending.append({
                "setup_date":       srow["as_of_date"],
                "symbol":           sym,
                "direction":        "LONG",
                "quality_score":    score,
                "signal_high":      round(high, 2),
                "entry_price":      entry,
                "stop_loss":        sl,
                "target_1r":        t1,
                "risk_pct":         risk_pct,
                "risk_frac":        _risk_frac(score),
                "trigger_date":     None,
                "t1_hit":           0,
                "exit_date":        None,
                "exit_price":       None,
                "outcome":          None,
                "skip_reason":      None,
                "shares":           None,
                "position_value":   None,
                "capital_at_entry": None,
                "pl_pkr":           None,
                "realized_r":       None,
                "portfolio_after":  None,
                "_dpend": 0,
            })

    # ── End: flush remaining active positions ─────────────────────────────────
    for trade in list(active):
        sym   = trade["symbol"]
        dates = sorted(price_lk[sym].keys())
        if not dates:
            trade["outcome"] = "Expired"
            _clean(trade)
            results.append(trade)
            continue

        last_d       = dates[-1]
        _, _, last_c = price_lk[sym][last_d]
        entry        = trade["entry_price"]
        R            = entry - trade["stop_loss"]
        rem          = trade["_rem_shr"] if trade["_t1_hit"] else trade["_shares"]
        close_pl     = (last_c - entry) * rem
        t1_pl        = trade.get("_t1_pl", 0.0)
        total_pl     = t1_pl + close_pl

        capital += trade["_pos_val"] + close_pl
        r_exit   = (last_c - entry) / R
        if trade["_t1_hit"]:
            realized_r = round(T1_R * 0.5 + 0.5 * r_exit, 3)
        else:
            realized_r = round(r_exit, 3)

        trade.update({
            "trigger_date":    trade["_trig_dt"],
            "t1_hit":          int(trade["_t1_hit"]),
            "exit_date":       last_d.isoformat(),
            "exit_price":      round(last_c, 2),
            "outcome":         "Win_Trail" if last_c > entry else "Loss",
            "pl_pkr":          round(total_pl, 2),
            "realized_r":      realized_r,
            "portfolio_after": round(capital, 2),
        })
        _clean(trade)
        results.append(trade)

    for trade in list(pending):
        if not trade.get("outcome"):
            trade["outcome"]     = "Stale"
            trade["skip_reason"] = "Simulation ended before trigger"
        _clean(trade)
        results.append(trade)

    logger.info("Simulation complete. %d records. Final capital: PKR %.0f",
                len(results), capital)
    return results, capital


# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════

def print_summary(results: list[dict], final_capital: float):
    total     = len(results)
    skipped   = sum(1 for r in results if r.get("outcome") == "Skipped")
    stale     = sum(1 for r in results if r.get("outcome") in ("Stale", "Expired"))
    triggered = sum(1 for r in results if r.get("trigger_date"))
    wins      = sum(1 for r in results if r.get("outcome") == "Win_Trail")
    losses    = sum(1 for r in results if r.get("outcome") == "Loss")
    total_pl  = sum(r.get("pl_pkr") or 0 for r in results)

    # Score breakdown of triggered trades
    by_score = {2: {"t": 0, "w": 0}, 3: {"t": 0, "w": 0}, 4: {"t": 0, "w": 0}}
    for r in results:
        if r.get("trigger_date") and r.get("outcome") in ("Win_Trail", "Loss"):
            s = r.get("quality_score") or 2
            if s in by_score:
                by_score[s]["t"] += 1
                if r["outcome"] == "Win_Trail":
                    by_score[s]["w"] += 1

    logger.info("=" * 60)
    logger.info("Simulation v2 Summary")
    logger.info("  MAX_SL_PCT       : %.0f%%  (v1: 6%%)", MAX_SL_PCT)
    logger.info("  T1 target        : %.1fR  (v1: 1.0R)", T1_R)
    logger.info("  Risk fractions   : score4=2%% score3=1.5%% score2=1%%")
    logger.info("  Total signals    : %d", total)
    logger.info("  Skipped (risk>8%%): %d", skipped)
    logger.info("  Stale / Expired  : %d", stale)
    logger.info("  Triggered        : %d  (%.1f%% of total)",
                triggered, triggered / total * 100 if total else 0)
    logger.info("  Wins (Win_Trail) : %d", wins)
    logger.info("  Losses           : %d", losses)
    if triggered:
        logger.info("  Win rate         : %.1f%%", wins / triggered * 100)
        logger.info("  Loss rate        : %.1f%%", losses / triggered * 100)
    logger.info("  -- By quality score (triggered only) --")
    for s in [4, 3, 2]:
        d = by_score[s]
        wr = d["w"] / d["t"] * 100 if d["t"] else 0
        logger.info("    Score %d: %d trades  %.0f%% win rate", s, d["t"], wr)
    logger.info("  Total P&L        : PKR %+.0f", total_pl)
    logger.info("  Initial capital  : PKR %.0f", INITIAL_CAPITAL)
    logger.info("  Final capital    : PKR %.0f", final_capital)
    logger.info("  Return           : %+.1f%%",
                (final_capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100)
    logger.info("=" * 60)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    init_db()
    init_sim_table()

    logger.info("Loading setup signals from backtest_setups...")
    setups = load_setups()
    if not setups:
        logger.error("No LONG setups found. Run backtest.py first.")
        return

    logger.info("Loading price data...")
    prices_df = load_prices()
    if prices_df.empty:
        logger.error("No price data found.")
        return

    logger.info("Running portfolio simulation v2...")
    results, final_capital = run_simulation(setups, prices_df)

    logger.info("Saving %d records to sim_portfolio_trades_v2...", len(results))
    save_sim_trades(results)
    print_summary(results, final_capital)


if __name__ == "__main__":
    main()
