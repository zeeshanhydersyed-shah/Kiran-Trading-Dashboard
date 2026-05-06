"""
Phase 2 — KIRAN Historical Backtest Engine.

Replays KIRAN's screener rules on every trading date in the DB (point-in-time
correct — only data visible on that date is used).  For each setup generated,
forward prices are used to label the outcome.

Stores results in backtest_setups table.  Resumable: already-processed dates
are skipped.

Usage:
    python backtest.py              # full run from earliest available date
    python backtest.py 2025-01-01  # from a specific start date
"""

import sys
import logging
import sqlite3
from datetime import date, timedelta
from collections import defaultdict

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("backtest.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

from config import EXCLUDED_SECTORS, DFC_SYMBOLS
from database import get_conn, init_db
from kse100_filter import KSE100Filter

# ── Constants (identical to processor.py) ─────────────────────────────────────
MAX_RISK_PCT      = 12.0    # raised from 6%: PSX bases (OGDC/DGKC style) need 10-12% room
REWARD_RATIO      = 2.0
MAX_RANGE_PCT     = 12.0
MIN_QUALITY       = 2
ENTRY_BUFFER_PCT  = 0.005   # 0.5%
SL_BUFFER_PCT     = 0.010   # 1.0%
WARMUP_DAYS       = 40      # trading days needed before first backtest date
MAX_FORWARD_DAYS  = 60      # trading days to look ahead for outcome after trigger
MAX_TRIGGER_DAYS  = 20      # trading days to wait for entry trigger before expiring as Stale_Setup
                            # A base that doesn't break out within ~1 month has evolved —
                            # the original S/R levels, SL, and setup thesis are no longer valid.
MIN_VOL_10D       = 500_000 # 10-day average volume filter (shares)
PERF_30D_MIN      = 15.0    # 30d performance minimum for LONG
PERF_60D_ALT      = 20.0    # 60d alternative — catches post-spike bases

SHORT_MOM = {"Rolling Over", "Falling"}
LONG_MOM  = {"Heating Up", "Cooling Down"}


# ═══════════════════════════════════════════════════════════════════════════════
# DB — backtest_setups table
# ═══════════════════════════════════════════════════════════════════════════════

def init_backtest_table():
    with get_conn() as conn:
        # If table exists but is missing new columns, drop and recreate cleanly
        existing = [
            r[1] for r in conn.execute(
                "PRAGMA table_info(backtest_setups)"
            ).fetchall()
        ]
        if existing:
            needs_reset = False
            reason = ""
            if "realized_r" not in existing or "avg_vol_10d" not in existing:
                needs_reset = True
                reason = "missing columns"
            else:
                # Detect old fixed-target model (Win_T2 → replaced by Win_Trail)
                win_t2 = conn.execute(
                    "SELECT COUNT(*) FROM backtest_setups WHERE outcome = 'Win_T2'"
                ).fetchone()[0]
                if win_t2 > 0:
                    needs_reset = True
                    reason = f"old fixed-target model ({win_t2} Win_T2 rows) — switching to hybrid trail exit"
            if needs_reset:
                logger.info("Schema reset: %s", reason)
                conn.execute("DROP TABLE IF EXISTS backtest_setups")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS backtest_setups (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                as_of_date       TEXT NOT NULL,
                direction        TEXT NOT NULL,
                symbol           TEXT NOT NULL,
                sector           TEXT NOT NULL,
                sector_momentum  TEXT,
                sector_rank      INTEGER,
                breadth_score    REAL,
                stock_perf_30d   REAL,
                stock_perf_60d   REAL,
                stock_perf_10d   REAL,
                latest_close     REAL,
                support_level    REAL,
                resistance_level REAL,
                entry_price      REAL NOT NULL,
                stop_loss        REAL NOT NULL,
                target_1r        REAL,
                target_2r        REAL,
                risk_pct         REAL,
                atr_pct          REAL,
                range_width_pct  REAL,
                range_window     INTEGER,
                quality_score    INTEGER,
                avg_vol_10d      REAL,
                entry_triggered  INTEGER DEFAULT 0,
                trigger_date     TEXT,
                outcome          TEXT,
                outcome_date     TEXT,
                outcome_days     INTEGER,
                realized_r       REAL
            );
            CREATE INDEX IF NOT EXISTS idx_bt_date   ON backtest_setups (as_of_date);
            CREATE INDEX IF NOT EXISTS idx_bt_symbol ON backtest_setups (symbol);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bt_unique
                ON backtest_setups (as_of_date, symbol, direction);

            -- Tracks every date the backtest screener has run, even if 0 setups found.
            -- Prevents wasteful re-processing of zero-setup dates on every self_improve run.
            CREATE TABLE IF NOT EXISTS screened_dates (
                date TEXT PRIMARY KEY
            );
        """)
    logger.info("backtest_setups table ready.")


def get_processed_dates() -> set:
    """Return all dates already screened (including zero-setup dates)."""
    with get_conn() as conn:
        rows = conn.execute("SELECT date FROM screened_dates").fetchall()
    return {r[0] for r in rows}


def mark_date_screened(date_str: str):
    """Record that a date has been screened (idempotent)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO screened_dates (date) VALUES (?)", (date_str,)
        )


def insert_setups(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO backtest_setups (
                as_of_date, direction, symbol, sector,
                sector_momentum, sector_rank, breadth_score,
                stock_perf_30d, stock_perf_60d, stock_perf_10d, latest_close,
                support_level, resistance_level,
                entry_price, stop_loss, target_1r, target_2r,
                risk_pct, atr_pct, range_width_pct, range_window,
                quality_score, avg_vol_10d,
                entry_triggered, trigger_date, outcome, outcome_date, outcome_days,
                realized_r
            ) VALUES (
                :as_of_date, :direction, :symbol, :sector,
                :sector_momentum, :sector_rank, :breadth_score,
                :stock_perf_30d, :stock_perf_60d, :stock_perf_10d, :latest_close,
                :support_level, :resistance_level,
                :entry_price, :stop_loss, :target_1r, :target_2r,
                :risk_pct, :atr_pct, :range_width_pct, :range_window,
                :quality_score, :avg_vol_10d,
                :entry_triggered, :trigger_date, :outcome, :outcome_date, :outcome_days,
                :realized_r
            )""",
            rows,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════════════════════

def load_all_prices() -> pd.DataFrame:
    """Load every (symbol, sector, date, high, low, close, volume) from the DB into memory.
    high/low fall back to close for legacy rows that predate the H/L scrape."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT s.symbol, s.sector, p.date,
                      COALESCE(p.high, p.close) AS high,
                      COALESCE(p.low,  p.close) AS low,
                      p.close, p.volume
               FROM sectors s JOIN prices p ON p.symbol = s.symbol
               ORDER BY s.symbol, p.date"""
        ).fetchall()
    df = pd.DataFrame(rows, columns=["symbol", "sector", "date", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df = df[~df["sector"].isin(EXCLUDED_SECTORS)]
    logger.info("Loaded %d price records for %d symbols.", len(df), df["symbol"].nunique())
    pct_with_vol = (df["volume"].notna() & (df["volume"] > 0)).mean() * 100
    logger.info("Volume coverage: %.1f%% of rows have volume data.", pct_with_vol)
    return df


def get_all_trading_dates(df: pd.DataFrame) -> list[date]:
    return sorted(df["date"].dt.date.unique().tolist())


# ═══════════════════════════════════════════════════════════════════════════════
# Screener logic — identical rules to processor.py, no imports from it
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_perf(df_slice: pd.DataFrame, window: int) -> pd.DataFrame:
    results = []
    for symbol, grp in df_slice.groupby("symbol"):
        grp = grp.sort_values("date").reset_index(drop=True)
        if len(grp) < 2:
            continue
        latest  = grp.iloc[-1]
        base    = grp.iloc[max(0, len(grp) - window - 1)]
        if base["close"] == 0:
            continue
        perf = (latest["close"] - base["close"]) / base["close"] * 100
        results.append({
            "symbol":       symbol,
            "sector":       latest["sector"],
            "latest_close": latest["close"],
            "perf_pct":     round(perf, 2),
        })
    return pd.DataFrame(results)


def _sector_rankings(s30: pd.DataFrame, s10: pd.DataFrame) -> pd.DataFrame:
    if s30.empty:
        return pd.DataFrame()
    p10 = {}
    if not s10.empty:
        for sec, grp in s10.groupby("sector"):
            p10[sec] = round(grp["perf_pct"].mean(), 2)
    rows = []
    for sec, grp in s30.groupby("sector"):
        avg30 = round(grp["perf_pct"].mean(), 2)
        avg10 = p10.get(sec)
        if avg10 is None:
            label = "—"
        elif avg30 >= 0 and avg10 >= 0:
            label = "Heating Up" if avg10 > avg30 else "Cooling Down"
        elif avg30 < 0 and avg10 >= 0:
            label = "Recovering"
        elif avg30 >= 0 and avg10 < 0:
            label = "Rolling Over"
        else:
            label = "Falling" if avg10 < avg30 else "Stabilising"
        rows.append({"sector": sec, "avg_perf_pct": avg30, "avg_10d_pct": avg10, "momentum": label})
    result = pd.DataFrame(rows).sort_values("avg_perf_pct", ascending=False)
    result.insert(0, "rank", range(1, len(result) + 1))
    return result.reset_index(drop=True)


def _breadth(s30: pd.DataFrame, sector_df: pd.DataFrame) -> dict:
    if s30.empty or sector_df.empty:
        return {}
    spct  = round((s30["perf_pct"] > 0).sum() / len(s30) * 100, 1)
    secpct = round((sector_df["avg_perf_pct"] > 0).sum() / len(sector_df) * 100, 1)
    score = round(spct * 0.6 + secpct * 0.4, 1)
    return {"breadth_score": score, "stock_pct_pos": spct, "sector_pct_pos": secpct}


def _atr_pct(closes: list, period: int = 14) -> float:
    if len(closes) < 2:
        return 0.0
    ch = [abs(closes[i] - closes[i-1]) / closes[i-1] * 100
          for i in range(max(1, len(closes) - period), len(closes))]
    return round(sum(ch) / len(ch), 2) if ch else 0.0


SUPPORT_BARS = 10   # recent-swing-low lookback for support (avoids stale crash wicks)


def _consolidation(closes: list, highs: list, lows: list,
                   windows=(5, 7, 10), max_pct=MAX_RANGE_PCT):
    """
    Identify the tightest consolidation range across window sizes.

    Resistance = highest HIGH over the full window  (where price was rejected)
    Support    = lowest  LOW  over last SUPPORT_BARS only (recent swing low,
                 NOT the panic wick from weeks ago that would bloat risk)

    Mirrors trader logic: you draw resistance from the whole base ceiling,
    but your stop goes just below the most recent pivot low.

    Falls back to close-based hi/lo if high/low lists are missing or all-zero.
    """
    best = None
    n = len(closes)
    use_hl = (len(highs) == n and len(lows) == n
              and any(h != c for h, c in zip(highs, closes)))

    for w in sorted(windows):
        if n < w + 1:
            continue
        recent_c = closes[-w:]

        # Resistance: full window ceiling
        res = max(highs[-w:]) if use_hl else max(recent_c)

        # Support: only last SUPPORT_BARS — recent swing low, not old crash
        sup_bars = min(w, SUPPORT_BARS)
        sup = min(lows[-sup_bars:]) if use_hl else min(closes[-sup_bars:])

        if sup == 0:
            continue
        width = (res - sup) / sup * 100
        if width <= max_pct:
            if best is None or width < best["range_width"]:
                best = {"window": w, "support": round(sup, 2),
                        "resistance": round(res, 2), "range_width": round(width, 2),
                        "closes": recent_c}
    return best


def _res_tests(closes, resistance, tol=2.0):
    lo = resistance * (1 - tol / 100)
    return sum(1 for c in closes if lo <= c <= resistance)


def _sup_tests(closes, support, tol=2.0):
    hi = support * (1 + tol / 100)
    return sum(1 for c in closes if support <= c <= hi)


def _declining_highs(closes):
    if len(closes) < 4:
        return False
    mid = len(closes) // 2
    return max(closes[:mid]) > max(closes[mid:])


def _rising_lows(closes):
    if len(closes) < 4:
        return False
    mid = len(closes) // 2
    return min(closes[:mid]) < min(closes[mid:])


def _vol_contraction(closes):
    if len(closes) < 7:
        return False
    def atr(cs):
        ch = [abs(cs[i] - cs[i-1]) / cs[i-1] * 100 for i in range(1, len(cs))]
        return sum(ch) / len(ch) if ch else 0.0
    recent = atr(closes[-6:])
    prior  = atr(closes[-15:-5]) if len(closes) >= 15 else atr(closes[:-5])
    return recent < prior


def _range_pos(close, support, resistance):
    rng = resistance - support
    return (close - support) / rng if rng else 0.5


def run_screener_for_date(as_of_date: date, df_slice: pd.DataFrame,
                          kse_filter: "KSE100Filter | None" = None) -> list[dict]:
    """
    Run KIRAN's exact screener rules on df_slice (prices up to as_of_date).
    Returns list of setup dicts.

    kse_filter: if provided, LONGs are suppressed when KSE-100 < 50MA.
    """
    s30 = _compute_perf(df_slice, 30)
    s10 = _compute_perf(df_slice, 10)
    if s30.empty:
        return []

    sector_df = _sector_rankings(s30, s10)
    b         = _breadth(s30, sector_df)
    b_score   = b.get("breadth_score", 0)

    total   = len(sector_df)
    top_cut = max(1, int(total * 0.35))
    bot_cut = total - max(1, int(total * 0.35))

    sec_mom  = dict(zip(sector_df["sector"], sector_df["momentum"]))
    sec_rank = dict(zip(sector_df["sector"], sector_df["rank"]))
    p10_map  = dict(zip(s10["symbol"], s10["perf_pct"])) if not s10.empty else {}

    # Build price, high, low and volume lists per symbol (sorted by date)
    price_map: dict[str, list] = {}
    high_map:  dict[str, list] = {}
    low_map:   dict[str, list] = {}
    vol_map:   dict[str, float] = {}
    for sym, grp in df_slice.groupby("symbol"):
        grp_s = grp.sort_values("date")
        price_map[sym] = grp_s["close"].tolist()
        high_map[sym]  = grp_s["high"].tolist()  if "high" in grp_s.columns else []
        low_map[sym]   = grp_s["low"].tolist()   if "low"  in grp_s.columns else []
        recent_vol = grp_s["volume"].dropna().tail(10)
        vol_map[sym] = float(recent_vol.mean()) if len(recent_vol) >= 5 else 0.0

    date_str = as_of_date.isoformat()
    setups   = []

    for _, row in s30.iterrows():
        sym    = row["symbol"]
        sector = row["sector"]
        p30    = row["perf_pct"]
        p10    = p10_map.get(sym)
        s_mom  = sec_mom.get(sector, "—")
        s_rank = sec_rank.get(sector, 999)
        closes  = price_map.get(sym, [])
        highs   = high_map.get(sym, [])
        lows    = low_map.get(sym, [])
        avg_vol = vol_map.get(sym, 0.0)

        if p10 is None or len(closes) < 7:
            continue

        # Volume filter — skip thinly traded stocks
        if avg_vol < MIN_VOL_10D:
            continue

        atr    = _atr_pct(closes)
        latest = closes[-1]

        # 60-day performance (alternative qualifier)
        p60 = ((closes[-1] - closes[-61]) / closes[-61] * 100
               if len(closes) >= 61 else None)
        perf_ok_long = (p30 >= PERF_30D_MIN) or (p60 is not None and p60 >= PERF_60D_ALT)

        # ── LONG ──────────────────────────────────────────────────────────────
        # KSE-100 trend gate: only go long when index is above its 50MA
        kse_long_ok = (kse_filter is None or kse_filter.long_allowed(as_of_date))
        if (kse_long_ok and b_score >= 55 and s_rank <= top_cut
                and s_mom in LONG_MOM and perf_ok_long):

            consol = _consolidation(closes, highs, lows)
            if consol:
                res = consol["resistance"]
                sup = consol["support"]
                entry = round(res * (1 + ENTRY_BUFFER_PCT), 2)
                if entry > latest:
                    sl = round(sup * (1 - SL_BUFFER_PCT), 2)
                    risk = round((entry - sl) / entry * 100, 2)
                    if 0 < risk <= MAX_RISK_PCT:
                        R  = entry - sl
                        cc = consol["closes"]
                        pos = _range_pos(latest, sup, res)
                        checks = {
                            "Resistance tested >=2x": _res_tests(cc, res) >= 2,
                            "Declining highs":        _declining_highs(cc),
                            "Vol contracting":        _vol_contraction(closes),
                            "Price pulled back":      0.25 <= pos <= 0.65,
                        }
                        score = sum(checks.values())
                        if score >= MIN_QUALITY:
                            setups.append({
                                "as_of_date":      date_str,
                                "direction":       "LONG",
                                "symbol":          sym,
                                "sector":          sector,
                                "sector_momentum": s_mom,
                                "sector_rank":     int(s_rank),
                                "breadth_score":   b_score,
                                "stock_perf_30d":  p30,
                                "stock_perf_60d":  round(p60, 2) if p60 is not None else None,
                                "stock_perf_10d":  p10,
                                "latest_close":    latest,
                                "support_level":   sup,
                                "resistance_level":res,
                                "entry_price":     entry,
                                "stop_loss":       sl,
                                "target_1r":       round(entry + R, 2),
                                "target_2r":       round(entry + REWARD_RATIO * R, 2),
                                "risk_pct":        risk,
                                "atr_pct":         atr,
                                "range_width_pct": consol["range_width"],
                                "range_window":    consol["window"],
                                "quality_score":   score,
                                "avg_vol_10d":     round(avg_vol),
                            })

        # ── SHORT ─────────────────────────────────────────────────────────────
        short_ok = p30 <= -15.0 or (p30 < 0 and p10 <= -10.0)
        if (sym in DFC_SYMBOLS and s_rank > bot_cut
                and s_mom in SHORT_MOM and p10 < 0 and short_ok):

            consol = _consolidation(closes, highs, lows)
            if consol:
                res = consol["resistance"]
                sup = consol["support"]
                entry = round(sup * (1 - ENTRY_BUFFER_PCT), 2)
                if entry < latest:
                    sl = round(res * (1 + SL_BUFFER_PCT), 2)
                    risk = round((sl - entry) / entry * 100, 2)
                    if 0 < risk <= MAX_RISK_PCT:
                        R  = sl - entry
                        cc = consol["closes"]
                        pos = _range_pos(latest, sup, res)
                        checks = {
                            "Support tested >=2x":   _sup_tests(cc, sup) >= 2,
                            "Rising lows":           _rising_lows(cc),
                            "Vol contracting":       _vol_contraction(closes),
                            "Price near resistance": 0.35 <= pos <= 0.75,
                        }
                        score = sum(checks.values())
                        if score >= MIN_QUALITY:
                            setups.append({
                                "as_of_date":      date_str,
                                "direction":       "SHORT",
                                "symbol":          sym,
                                "sector":          sector,
                                "sector_momentum": s_mom,
                                "sector_rank":     int(s_rank),
                                "breadth_score":   b_score,
                                "stock_perf_30d":  p30,
                                "stock_perf_60d":  round(p60, 2) if p60 is not None else None,
                                "stock_perf_10d":  p10,
                                "latest_close":    latest,
                                "support_level":   sup,
                                "resistance_level":res,
                                "entry_price":     entry,
                                "stop_loss":       sl,
                                "target_1r":       round(entry - R, 2),
                                "target_2r":       round(entry - REWARD_RATIO * R, 2),
                                "risk_pct":        risk,
                                "atr_pct":         atr,
                                "range_width_pct": consol["range_width"],
                                "range_window":    consol["window"],
                                "quality_score":   score,
                                "avg_vol_10d":     round(avg_vol),
                            })

    return setups


# ═══════════════════════════════════════════════════════════════════════════════
# Outcome labeling
# ═══════════════════════════════════════════════════════════════════════════════

def label_outcome(
    direction: str,
    entry: float, sl: float, t1: float, t2: float,
    forward: list[tuple],          # [(date, close), ...] after as_of_date
    hist_closes: list[float],      # recent closes BEFORE as_of_date (seeds 10MA)
    max_days: int = MAX_FORWARD_DAYS,
    max_trigger_days: int = MAX_TRIGGER_DAYS,
) -> dict:
    """
    Hybrid exit model — three phases:

    Phase 1 — Pre-trigger: walk forward up to MAX_TRIGGER_DAYS trading days only.
               Entry not hit within that window → Stale_Setup (setup thesis expired).
               This is distinct from No_Trigger (which was the old unlimited wait).
               A base that hasn't broken out in ~20 trading days has evolved — the
               original S/R levels, SL, and entry thesis are no longer valid.

    Phase 2 — Post-trigger: watch for T1 or SL.
               SL hit first → Loss  (realized_r = -1.0)
               T1 hit first → Phase 3 (book 0.5R on first half, slide stop to BE)

    Phase 3 — Trailing: remaining half trails 10MA with breakeven floor.
               Close <= entry (LONG) or >= entry (SHORT) → Win_T1  (realized_r = 0.5)
               Close crosses 10MA from above (LONG) or below (SHORT) → Win_Trail
                   realized_r = 0.5 + 0.5 * (exit_close - entry) / R_unit   [LONG]
                   realized_r = 0.5 + 0.5 * (entry - exit_close) / R_unit   [SHORT]
               If max_days expires while trailing → exit at last close (Win_Trail)

    t2 is stored in DB for reference but not used as an exit in this model.
    """
    triggered    = False
    trigger_date = None
    t1_hit       = False

    # Rolling close window seeded with recent history for stable 10MA from day 1
    rolling = list(hist_closes[-14:]) if hist_closes else []

    R_unit = (entry - sl) if direction == "LONG" else (sl - entry)
    if R_unit <= 0:
        R_unit = entry * 0.01

    # Split the forward window:
    #   trigger_window: first MAX_TRIGGER_DAYS — entry must fire here or setup is stale
    #   trade_window:   remaining MAX_FORWARD_DAYS after trigger — for trade management
    trigger_window = forward[:max_trigger_days]
    # trade_window is built dynamically once trigger fires

    def _ret(trig_date, out, out_date, out_days, r_val):
        return {
            "entry_triggered": 1,
            "trigger_date":    trig_date.isoformat(),
            "outcome":         out,
            "outcome_date":    out_date.isoformat() if out_date else None,
            "outcome_days":    out_days,
            "realized_r":      r_val,
        }

    # ── Phase 1: trigger watch — MAX_TRIGGER_DAYS only ───────────────────────
    trigger_idx = None
    for idx, (fwd_date, close) in enumerate(trigger_window):
        rolling.append(close)
        if direction == "LONG"  and close >= entry:
            triggered = True; trigger_date = fwd_date; trigger_idx = idx; break
        elif direction == "SHORT" and close <= entry:
            triggered = True; trigger_date = fwd_date; trigger_idx = idx; break

    if not triggered:
        # Entry never fired within the trigger window — thesis expired
        return {"entry_triggered": 0, "trigger_date": None,
                "outcome": "Stale_Setup", "outcome_date": None,
                "outcome_days": None, "realized_r": None}

    # Check immediate SL / T1 on the trigger candle itself
    _, trigger_close = trigger_window[trigger_idx]
    if direction == "LONG"  and trigger_close <= sl:
        return _ret(trigger_date, "Loss", trigger_date, 0, -1.0)
    if direction == "SHORT" and trigger_close >= sl:
        return _ret(trigger_date, "Loss", trigger_date, 0, -1.0)
    if direction == "LONG"  and trigger_close >= t1:
        t1_hit = True
    elif direction == "SHORT" and trigger_close <= t1:
        t1_hit = True

    # ── Phase 2 + 3: trade management after trigger ────────────────────────
    post_trigger = forward[trigger_idx + 1 : trigger_idx + 1 + max_days]

    for fwd_date, close in post_trigger:
        rolling.append(close)

        if not t1_hit:
            # Phase 2: watching T1 vs SL
            if direction == "LONG":
                if close >= t1:
                    t1_hit = True
                elif close <= sl:
                    days = (fwd_date - trigger_date).days
                    return _ret(trigger_date, "Loss", fwd_date, days, -1.0)
            else:
                if close <= t1:
                    t1_hit = True
                elif close >= sl:
                    days = (fwd_date - trigger_date).days
                    return _ret(trigger_date, "Loss", fwd_date, days, -1.0)
        else:
            # Phase 3: T1 hit — trailing on 10MA with breakeven floor
            ma10 = sum(rolling[-10:]) / min(len(rolling), 10)
            days = (fwd_date - trigger_date).days

            if direction == "LONG":
                if close <= entry:
                    r_trail = max(0.0, (close - entry) / R_unit)
                    return _ret(trigger_date, "Win_T1", fwd_date, days,
                                round(0.5 + 0.5 * r_trail, 3))
                if close < ma10:
                    r_trail = (close - entry) / R_unit
                    return _ret(trigger_date, "Win_Trail", fwd_date, days,
                                round(0.5 + 0.5 * r_trail, 3))
            else:
                if close >= entry:
                    r_trail = max(0.0, (entry - close) / R_unit)
                    return _ret(trigger_date, "Win_T1", fwd_date, days,
                                round(0.5 + 0.5 * r_trail, 3))
                if close > ma10:
                    r_trail = (entry - close) / R_unit
                    return _ret(trigger_date, "Win_Trail", fwd_date, days,
                                round(0.5 + 0.5 * r_trail, 3))

    # ── Post-trigger window exhausted ────────────────────────────────────────
    if not t1_hit:
        return {"entry_triggered": 1,
                "trigger_date":  trigger_date.isoformat(),
                "outcome":       "Expired",
                "outcome_date":  None, "outcome_days": None, "realized_r": None}

    # T1 hit but trail never fired — exit at last available close
    last_date, last_close = post_trigger[-1] if post_trigger else (trigger_date, entry)
    r_trail = ((last_close - entry) if direction == "LONG" else (entry - last_close)) / R_unit
    days    = (last_date - trigger_date).days
    return _ret(trigger_date, "Win_Trail", last_date, days,
                round(0.5 + 0.5 * r_trail, 3))


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    override_start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None

    init_db()
    init_backtest_table()

    # ── KSE-100 trend filter (point-in-time correct) ──────────────────────────
    kse_filter = KSE100Filter()
    if kse_filter._available():
        summary = kse_filter.kse100_summary()
        logger.info("KSE-100 filter loaded. Latest: close=%.0f  MA50=%.0f  above_MA50=%s",
                    summary.get("close", 0), summary.get("ma50", 0) or 0,
                    summary.get("above_ma50"))
    else:
        logger.warning("KSE-100 filter: no index data found — filter disabled. "
                       "Run backfill_index.py to populate.")

    # ── Load all prices into memory ───────────────────────────────────────────
    logger.info("Loading all price data into memory...")
    full_df = load_all_prices()
    if full_df.empty:
        logger.error("No price data found. Run backfill_history.py first.")
        return

    all_dates    = get_all_trading_dates(full_df)
    done_dates   = get_processed_dates()

    if len(all_dates) <= WARMUP_DAYS:
        logger.error("Not enough trading dates for warmup (%d needed).", WARMUP_DAYS)
        return

    # Dates we can actually run (need WARMUP_DAYS of history before)
    runnable_dates = all_dates[WARMUP_DAYS:]

    # Dates that still have enough forward data for labeling (leave last 30 out)
    # Outcomes near today will be "Expired" anyway, include them but flag
    if override_start:
        runnable_dates = [d for d in runnable_dates if d >= override_start]

    remaining = [d for d in runnable_dates if d.isoformat() not in done_dates]

    logger.info(
        "Runnable dates: %d  |  Already done: %d  |  To process: %d",
        len(runnable_dates), len(done_dates), len(remaining),
    )

    if not remaining:
        logger.info("All dates already processed. Nothing to do.")
        _print_summary()
        return

    # ── Build forward price lookup: symbol -> [(date, close)] sorted ──────────
    fwd_map: dict[str, list] = {}
    for sym, grp in full_df.groupby("symbol"):
        fwd_map[sym] = [(r.date.date(), r.close) for r in grp.sort_values("date").itertuples()]

    # ── Main loop ─────────────────────────────────────────────────────────────
    total        = len(remaining)
    total_setups = 0
    batch        = []

    for idx, as_of in enumerate(remaining, 1):
        # Price data visible on as_of date
        df_slice = full_df[full_df["date"].dt.date <= as_of].copy()

        setups = run_screener_for_date(as_of, df_slice, kse_filter)

        # Build symbol→close-list from df_slice for 10MA seeding (closes only)
        hist_map: dict[str, list] = {
            sym: grp.sort_values("date")["close"].tolist()
            for sym, grp in df_slice.groupby("symbol")
        }

        # Label each setup's outcome using the hybrid exit model
        for s in setups:
            sym        = s["symbol"]
            fwd_prices = [(d, c) for d, c in fwd_map.get(sym, []) if d > as_of]
            # Historical closes up to as_of_date — seeds 10MA for the trailing phase
            hist       = hist_map.get(sym, [])
            outcome    = label_outcome(
                s["direction"],
                s["entry_price"], s["stop_loss"],
                s["target_1r"],   s["target_2r"],
                fwd_prices,
                hist,
            )
            s.update(outcome)
            # realized_r is now set inside label_outcome for all outcomes
            batch.append(s)

        total_setups += len(setups)

        # Always mark the date as screened (even if 0 setups found)
        mark_date_screened(as_of.isoformat())

        # Flush every 10 dates
        if idx % 10 == 0 or idx == total:
            insert_setups(batch)
            batch = []
            pct = idx / total * 100
            logger.info(
                "Progress: %d/%d dates (%.0f%%)  |  Setups so far: %d",
                idx, total, pct, total_setups,
            )

    # Flush remainder
    if batch:
        insert_setups(batch)

    logger.info("=" * 60)
    logger.info("Backtest engine complete.")
    _print_summary()
    logger.info("=" * 60)


def _print_summary():
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM backtest_setups").fetchone()[0]
        by_out = conn.execute(
            "SELECT outcome, COUNT(*) FROM backtest_setups GROUP BY outcome ORDER BY COUNT(*) DESC"
        ).fetchall()
        by_dir = conn.execute(
            "SELECT direction, outcome, COUNT(*) FROM backtest_setups "
            "GROUP BY direction, outcome ORDER BY direction, COUNT(*) DESC"
        ).fetchall()

    logger.info("Total setups in backtest_setups: %d", total)
    logger.info("Outcome breakdown:")
    for row in by_out:
        logger.info("  %-15s  %d", row[0] or "NULL", row[1])
    logger.info("By direction:")
    for row in by_dir:
        logger.info("  %-6s  %-15s  %d", row[0], row[1] or "NULL", row[2])


if __name__ == "__main__":
    main()
