"""
Kiran Portfolio Simulation — buy-on-strength execution rules.

Uses the SAME setup signals as backtest.py (Kiran screener, unchanged).
Only the execution rules differ:

  Entry   : signal-day HIGH + 1 PKR        (not resistance + 0.5%)
  Trigger : forward day HIGH >= entry       (intraday breakout, not close)
  Expiry  : forward day LOW  < signal HIGH  (price went back — thesis expired)
  Max SL  : 6% from entry  (setups with wider initial risk are skipped)
  T1      : 1R target — close half the position
  Trail   : remaining half exits when daily close < 10-day MA
  Size    : 1% of portfolio capital at trigger time (dynamic)
  Limit   : no new entries when invested capital >= 99% of portfolio
  Capital : PKR 1,000,000 initial; no margin

Reads : backtest_setups, prices tables  (via database.py)
Writes: sim_portfolio_trades table

Usage:
    python kiran_sim.py
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
        logging.FileHandler("kiran_sim.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

from database import get_conn, init_db
from config import EXCLUDED_SECTORS

# ── Constants ─────────────────────────────────────────────────────────────────
INITIAL_CAPITAL   = 1_000_000.0
RISK_FRAC         = 0.01     # 1% of portfolio risked per trade
MAX_SL_PCT        = 6.0      # maximum allowed SL distance from entry (%)
SL_BUFFER         = 0.01     # SL placed 1% below support level
MAX_INVEST_FRAC   = 0.99     # hard cap: total invested / capital
MAX_TRIGGER_DAYS  = 10       # trading days to wait for breakout trigger
MAX_HOLDING_DAYS  = 80       # force-close after this many days post-trigger


# ═══════════════════════════════════════════════════════════════════════════════
# Database helpers
# ═══════════════════════════════════════════════════════════════════════════════

def init_sim_table():
    """Create (or recreate) sim_portfolio_trades and sim_portfolio_summary tables."""
    with get_conn() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS sim_portfolio_trades;
            CREATE TABLE sim_portfolio_trades (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                setup_date       TEXT NOT NULL,
                symbol           TEXT NOT NULL,
                direction        TEXT DEFAULT 'LONG',
                signal_high      REAL,
                entry_price      REAL NOT NULL,
                stop_loss        REAL NOT NULL,
                target_1r        REAL NOT NULL,
                risk_pct         REAL NOT NULL,
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
            CREATE INDEX IF NOT EXISTS idx_sim_date   ON sim_portfolio_trades (setup_date);
            CREATE INDEX IF NOT EXISTS idx_sim_symbol ON sim_portfolio_trades (symbol);
            CREATE INDEX IF NOT EXISTS idx_sim_exit   ON sim_portfolio_trades (exit_date);
        """)
    logger.info("sim_portfolio_trades table ready.")


def save_sim_trades(rows: list[dict]):
    if not rows:
        return
    cols = [
        "setup_date", "symbol", "direction", "signal_high",
        "entry_price", "stop_loss", "target_1r", "risk_pct",
        "trigger_date", "t1_hit", "exit_date", "exit_price",
        "outcome", "skip_reason", "shares", "position_value",
        "capital_at_entry", "pl_pkr", "realized_r", "portfolio_after",
    ]
    ph  = ", ".join(["?"] * len(cols))
    sql = f"INSERT INTO sim_portfolio_trades ({', '.join(cols)}) VALUES ({ph})"
    with get_conn() as conn:
        conn.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    logger.info("Saved %d sim trade rows.", len(rows))


def get_sim_portfolio_data() -> list[dict]:
    """Return all rows from sim_portfolio_trades, or [] if table absent."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sim_portfolio_trades ORDER BY setup_date, symbol"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════════════════════

def load_setups() -> list[dict]:
    """Load LONG setups from backtest_setups (screener signals, unchanged)."""
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
    """Load all OHLCV prices joined with sectors (excluded sectors filtered out)."""
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
    """Strip internal state keys (prefixed '_') before saving to DB."""
    for k in [k for k in list(trade) if k.startswith("_")]:
        del trade[k]


def _skip_row(srow: dict, high: float, entry: float, sl: float,
              risk_pct: float, reason: str) -> dict:
    return {
        "setup_date":    srow["as_of_date"],
        "symbol":        srow["symbol"],
        "direction":     "LONG",
        "signal_high":   round(high, 2),
        "entry_price":   entry,
        "stop_loss":     sl,
        "target_1r":     round(entry + (entry - sl), 2),
        "risk_pct":      risk_pct,
        "trigger_date":  None, "t1_hit": 0,
        "exit_date":     None, "exit_price": None,
        "outcome":       "Skipped", "skip_reason": reason,
        "shares": None, "position_value": None, "capital_at_entry": None,
        "pl_pkr": None, "realized_r": None, "portfolio_after": None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Main simulation
# ═══════════════════════════════════════════════════════════════════════════════

def run_simulation(setups_list: list[dict], prices_df: pd.DataFrame):
    """
    Chronological portfolio simulation.

    Returns (results: list[dict], final_capital: float).
    Each result dict maps to one row in sim_portfolio_trades.
    """
    # Build per-symbol price lookups
    price_lk   : dict[str, dict[date, tuple]] = defaultdict(dict)   # sym->{date:(H,L,C)}
    price_hist : dict[str, list[tuple]]        = defaultdict(list)   # sym->[(date, close)]

    for row in prices_df.itertuples(index=False):
        d   = row.date
        sym = row.symbol
        price_lk[sym][d]  = (float(row.high), float(row.low), float(row.close))
        price_hist[sym].append((d, float(row.close)))
    # Histories are already sorted (ORDER BY in query)

    all_dates = sorted(prices_df["date"].unique())

    setups_by_date: dict[date, list[dict]] = defaultdict(list)
    for s in setups_list:
        setups_by_date[date.fromisoformat(s["as_of_date"])].append(s)

    # ── Portfolio state ──────────────────────────────────────────────────────
    capital = INITIAL_CAPITAL
    pending : list[dict] = []   # awaiting trigger (no capital committed)
    active  : list[dict] = []   # triggered, capital committed
    results : list[dict] = []   # all completed records

    def total_invested() -> float:
        return sum(t["_pos_val"] for t in active)

    # ── Main date loop ───────────────────────────────────────────────────────
    for today in all_dates:

        # ── 1. Manage active (triggered) trades ──────────────────────────────
        to_close: list[dict] = []

        for trade in active:
            sym  = trade["symbol"]
            p    = price_lk[sym].get(today)
            if not p:
                continue
            _, _, close = p
            trade["_closes"].append(close)

            entry = trade["entry_price"]
            sl    = trade["stop_loss"]
            t1    = trade["target_1r"]
            R     = entry - sl      # 1R in PKR

            if not trade["_t1_hit"]:
                # Phase 2 — watching T1 vs SL
                if close >= t1:
                    trade["_t1_hit"]   = True
                    half_val           = trade["_pos_val"] / 2
                    t1_profit          = (t1 - entry) * trade["_shares"] / 2
                    capital           += half_val + t1_profit
                    trade["_pos_val"] -= half_val
                    trade["_rem_shr"]  = trade["_shares"] / 2
                    trade["_t1_pl"]    = t1_profit
                elif close <= sl:
                    loss_pl = (sl - entry) * trade["_shares"]   # negative
                    trade["_close_pl"] = loss_pl
                    trade["_outcome"]  = "Loss"
                    trade["_exit_px"]  = sl
                    trade["_exit_dt"]  = today
                    to_close.append(trade)
            else:
                # Phase 3 — trailing 10-day MA
                ma10 = sum(trade["_closes"][-10:]) / min(len(trade["_closes"]), 10)
                if close < ma10:
                    trail_pl = (close - entry) * trade["_rem_shr"]
                    trade["_close_pl"] = trail_pl
                    trade["_outcome"]  = "Win_Trail"
                    trade["_exit_px"]  = close
                    trade["_exit_dt"]  = today
                    to_close.append(trade)

            # Force-close if max holding exceeded
            if trade not in to_close:
                trig_d = date.fromisoformat(trade["_trig_dt"])
                if (today - trig_d).days >= MAX_HOLDING_DAYS:
                    rem_pl = (close - entry) * (
                        trade["_rem_shr"] if trade["_t1_hit"] else trade["_shares"]
                    )
                    trade["_close_pl"] = rem_pl
                    trade["_outcome"]  = "Win_Trail" if close > entry else "Loss"
                    trade["_exit_px"]  = close
                    trade["_exit_dt"]  = today
                    to_close.append(trade)

        # Apply all closures; compute portfolio_after once all are settled
        for trade in to_close:
            capital += trade["_pos_val"] + trade["_close_pl"]
        remaining_inv = sum(t["_pos_val"] for t in active if t not in to_close)
        portfolio_now = capital + remaining_inv

        for trade in to_close:
            entry = trade["entry_price"]
            R     = entry - trade["stop_loss"]
            t1_pl = trade.get("_t1_pl", 0.0)
            close_pl = trade["_close_pl"]
            total_pl = t1_pl + close_pl

            r_close = (trade["_exit_px"] - entry) / R
            if trade["_t1_hit"]:
                realized_r = round(0.5 + 0.5 * r_close, 3)
            else:
                realized_r = round(r_close, 3)

            trade.update({
                "trigger_date":  trade["_trig_dt"],
                "t1_hit":        int(trade["_t1_hit"]),
                "exit_date":     trade["_exit_dt"].isoformat(),
                "exit_price":    round(trade["_exit_px"], 2),
                "outcome":       trade["_outcome"],
                "pl_pkr":        round(total_pl, 2),
                "realized_r":    realized_r,
                "portfolio_after": round(portfolio_now, 2),
            })
            active.remove(trade)
            _clean(trade)
            results.append(trade)

        # ── 2. Check pending trades for trigger or expiry ─────────────────────
        to_activate : list[tuple] = []   # (trade, trigger_date)
        to_expire   : list[dict]  = []

        for trade in pending:
            sym      = trade["symbol"]
            p        = price_lk[sym].get(today)
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

            # Trigger has priority over expiry check
            if high >= entry:
                to_activate.append((trade, today))
                continue

            # Price went back below signal-day high — thesis expired
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

        # Activate triggered setups
        for (trade, trig_date) in to_activate:
            pending.remove(trade)

            inv = total_invested()
            if capital > 0 and inv / capital >= MAX_INVEST_FRAC:
                trade["outcome"]     = "Skipped"
                trade["skip_reason"] = f"Capital limit ({inv/capital*100:.0f}% invested)"
                _clean(trade)
                results.append(trade)
                continue

            R        = trade["entry_price"] - trade["stop_loss"]
            risk_amt = capital * RISK_FRAC
            shares   = risk_amt / R
            pos_val  = shares * trade["entry_price"]

            # Cap to 99% ceiling
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

            # Seed 10MA with historical closes up to trigger date
            hist_closes = [c for d, c in price_hist[trade["symbol"]] if d <= trig_date]
            seed_closes = hist_closes[-14:] if hist_closes else []
            trig_close  = price_lk[trade["symbol"]].get(trig_date)
            if trig_close:
                seed_closes.append(trig_close[2])

            trade["shares"]           = round(shares, 4)
            trade["position_value"]   = round(pos_val, 2)
            trade["capital_at_entry"] = round(capital + pos_val, 2)
            trade["trigger_date"]     = trig_date.isoformat()
            # Internal state
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
            sym = srow["symbol"]
            p   = price_lk[sym].get(today)
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
                results.append(_skip_row(srow, high, entry, sl, risk_pct,
                                         f"Risk {risk_pct:.1f}% > {MAX_SL_PCT}% max"))
                continue

            t1 = round(entry + (entry - sl), 2)

            pending.append({
                # Public fields (saved to DB)
                "setup_date":    srow["as_of_date"],
                "symbol":        sym,
                "direction":     "LONG",
                "signal_high":   round(high, 2),
                "entry_price":   entry,
                "stop_loss":     sl,
                "target_1r":     t1,
                "risk_pct":      risk_pct,
                "trigger_date":  None,
                "t1_hit":        0,
                "exit_date":     None,
                "exit_price":    None,
                "outcome":       None,
                "skip_reason":   None,
                "shares":        None,
                "position_value": None,
                "capital_at_entry": None,
                "pl_pkr":        None,
                "realized_r":    None,
                "portfolio_after": None,
                # Internal state
                "_dpend": 0,
            })

    # ── End of date loop — flush remaining positions ─────────────────────────

    # Force-close all still-active trades at last available price
    for trade in list(active):
        sym   = trade["symbol"]
        dates = sorted(price_lk[sym].keys())
        if not dates:
            trade["outcome"] = "Expired"
            _clean(trade)
            results.append(trade)
            continue

        last_d    = dates[-1]
        last_h, _, last_c = price_lk[sym][last_d]
        entry     = trade["entry_price"]
        R         = entry - trade["stop_loss"]
        rem       = trade["_rem_shr"] if trade["_t1_hit"] else trade["_shares"]
        close_pl  = (last_c - entry) * rem
        t1_pl     = trade.get("_t1_pl", 0.0)
        total_pl  = t1_pl + close_pl

        capital += trade["_pos_val"] + close_pl
        r_exit   = (last_c - entry) / R
        if trade["_t1_hit"]:
            realized_r = round(0.5 + 0.5 * r_exit, 3)
        else:
            realized_r = round(r_exit, 3)

        trade.update({
            "trigger_date":  trade["_trig_dt"],
            "t1_hit":        int(trade["_t1_hit"]),
            "exit_date":     last_d.isoformat(),
            "exit_price":    round(last_c, 2),
            "outcome":       "Win_Trail" if last_c > entry else "Loss",
            "pl_pkr":        round(total_pl, 2),
            "realized_r":    realized_r,
            "portfolio_after": round(capital, 2),
        })
        _clean(trade)
        results.append(trade)

    # Mark remaining pending as stale (never triggered)
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
# Summary / reporting
# ═══════════════════════════════════════════════════════════════════════════════

def print_summary(results: list[dict], final_capital: float):
    total    = len(results)
    skipped  = sum(1 for r in results if r.get("outcome") == "Skipped")
    stale    = sum(1 for r in results if r.get("outcome") == "Stale")
    expired  = sum(1 for r in results if r.get("outcome") == "Expired")
    triggered = sum(1 for r in results if r.get("trigger_date"))
    wins     = sum(1 for r in results if r.get("outcome") == "Win_Trail")
    losses   = sum(1 for r in results if r.get("outcome") == "Loss")
    total_pl = sum(r.get("pl_pkr") or 0 for r in results)

    logger.info("=" * 60)
    logger.info("Simulation Summary")
    logger.info("  Total signals    : %d", total)
    logger.info("  Skipped (risk>6%%): %d", skipped)
    logger.info("  Stale / Expired  : %d", stale + expired)
    logger.info("  Triggered        : %d  (%.1f%% of total)",
                triggered, triggered / total * 100 if total else 0)
    logger.info("  Wins (Win_Trail) : %d", wins)
    logger.info("  Losses           : %d", losses)
    if triggered:
        logger.info("  Win rate         : %.1f%%", wins / triggered * 100)
        logger.info("  Loss rate        : %.1f%%", losses / triggered * 100)
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
        logger.error("No LONG setups found in backtest_setups. Run backtest.py first.")
        return

    logger.info("Loading price data...")
    prices_df = load_prices()
    if prices_df.empty:
        logger.error("No price data found.")
        return

    logger.info("Running portfolio simulation...")
    results, final_capital = run_simulation(setups, prices_df)

    logger.info("Saving %d records to sim_portfolio_trades...", len(results))
    save_sim_trades(results)
    print_summary(results, final_capital)


if __name__ == "__main__":
    main()
