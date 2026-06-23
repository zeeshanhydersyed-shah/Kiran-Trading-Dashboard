import sqlite3
import logging
import sys
import traceback
from datetime import datetime, date
import pandas as pd
import numpy as np
from config import DB_PATH, DFC_SYMBOLS, EXCLUDED_SECTORS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# DB CONNECTION HELPER
# ══════════════════════════════════════════════════════════════════════════════

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA cache_size=-32000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ══════════════════════════════════════════════════════════════════════════════
# KILLED: run_mv_signals() — Minervini screener removed.
# Verdict: N=29 proxy signals over 11 years (3/yr), 86% overlap with BREAKOUT
# setup_log. Actual production screener fires fewer than 5 times per year.
# N too small for statistical validity; no marginal information over BREAKOUT.
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# KILLED: run_stm_signals() — STM screener removed.
# Verdict: 82% overlap with BREAKOUT+PRE_BREAKOUT+Weinstein combined.
# Z-histogram gate (most distinctive feature) has no historical validation.
# Quality logic (uptrend + outperforming + 500k vol) folded into Explorer filter.
# ══════════════════════════════════════════════════════════════════════════════

def _killed_mv_signals() -> dict:
    """
    Compute Minervini signals for the latest date and write to mv_signals table.
    Returns a summary dict: {as_of_date, longs, shorts, watchlist, status}
    """
    log.info("=== run_mv_signals START ===")
    try:
        # STEP A: Load price data
        # Import get_sector_price_data_300d — Minervini needs 200-day EMA
        # 300 trading days = ~420 calendar days — sufficient for EMA200 warmup
        # Use a dedicated query pulling 420 calendar days from prices+sectors
        # (do NOT use get_sector_price_data_60d — too short for EMA200)
        from database import get_index_prices

        conn = get_conn()
        rows = conn.execute("""
            SELECT s.symbol, s.sector, p.date,
                   COALESCE(p.open,   p.close) AS open,
                   COALESCE(p.high,   p.close) AS high,
                   COALESCE(p.low,    p.close) AS low,
                   p.close,
                   COALESCE(p.volume, 0)        AS volume
            FROM sectors s
            JOIN prices p ON p.symbol = s.symbol
            JOIN stock_metadata sm ON sm.symbol = s.symbol
            WHERE sm.is_active = 1
            AND p.date >= date('now', '-600 days')
            ORDER BY s.symbol, p.date
        """).fetchall()
        conn.close()

        if not rows:
            log.error("run_mv_signals: no price data returned")
            return {"status": "error", "message": "no price data"}

        stocks_df = pd.DataFrame([dict(r) for r in rows])
        stocks_df["date"] = pd.to_datetime(stocks_df["date"])
        for col in ("open", "high", "low", "close"):
            stocks_df[col] = pd.to_numeric(stocks_df[col], errors="coerce")
        stocks_df["volume"] = pd.to_numeric(
            stocks_df["volume"], errors="coerce").fillna(0)

        log.info(f"run_mv_signals: loaded {len(stocks_df):,} price rows, "
                 f"{stocks_df['symbol'].nunique()} symbols")

        # STEP B: Load KSE-100 index
        index_rows = get_index_prices("KSE-100")
        if not index_rows:
            log.error("run_mv_signals: no index data")
            return {"status": "error", "message": "no index data"}

        index_df = pd.DataFrame(index_rows)
        index_df["date"] = pd.to_datetime(index_df["date"])
        index_df["idx_close"] = pd.to_numeric(
            index_df["close"], errors="coerce")
        index_df = index_df[["date", "idx_close"]].sort_values("date")

        # STEP C: Build features using existing breakout_signal module
        from breakout_signal import build_features as _mv_build
        from breakout_signal import get_signals as _mv_get

        features_df = _mv_build(stocks_df, index_df)
        as_of_date  = features_df["date"].max().strftime("%Y-%m-%d")

        # ── Market breadth: % of all stocks with close > 20-day EMA ─────────
        _day_all    = features_df[features_df["date"] == features_df["date"].max()]
        _valid      = _day_all["ema20"].notna()
        _above      = (_day_all.loc[_valid, "close"] > _day_all.loc[_valid, "ema20"]).sum()
        mkt_breadth = float(_above / _valid.sum() * 100) if _valid.sum() > 0 else 0.0
        log.info(f"run_mv_signals: mkt_breadth={mkt_breadth:.1f}%")

        # ── Load sector signals (rs_rank, breadth_score per sector) ─────────
        _conn2 = get_conn()
        _latest_sec = _conn2.execute(
            "SELECT MAX(date) FROM sector_signals"
        ).fetchone()[0]
        sector_df_mv = pd.DataFrame()
        if _latest_sec:
            _sec_rows = _conn2.execute(
                "SELECT sector, rs_rank, breadth_score FROM sector_signals WHERE date = ?",
                (_latest_sec,)
            ).fetchall()
            sector_df_mv = pd.DataFrame([dict(r) for r in _sec_rows])
        log.info(f"run_mv_signals: sector_signals date={_latest_sec} "
                 f"rows={len(sector_df_mv)}")

        # ── Load stock ranks (rs_rank, sector_rs_rank per symbol) ───────────
        _latest_ss = _conn2.execute(
            "SELECT MAX(date) FROM stock_signals"
        ).fetchone()[0]
        stock_ranks_df = pd.DataFrame()
        if _latest_ss:
            _ss_rows = _conn2.execute(
                "SELECT symbol, rs_rank, sector_rs_rank FROM stock_signals WHERE date = ?",
                (_latest_ss,)
            ).fetchall()
            stock_ranks_df = pd.DataFrame([dict(r) for r in _ss_rows])
        _conn2.close()
        log.info(f"run_mv_signals: stock_signals date={_latest_ss} "
                 f"rows={len(stock_ranks_df)}")

        watchlist_df, longs_df, shorts_df = _mv_get(
            features_df,
            mkt_breadth=mkt_breadth,
            sector_df=sector_df_mv,
            stock_ranks_df=stock_ranks_df,
        )

        log.info(f"run_mv_signals: as_of_date={as_of_date} "
                 f"longs={len(longs_df)} shorts={len(shorts_df)} "
                 f"watchlist={len(watchlist_df)}")

        # STEP D: Write to mv_signals table
        # Idempotent schema migration — add new columns if not present
        conn = get_conn()
        for _col_def in [
            "ALTER TABLE mv_signals ADD COLUMN rs_rank        INTEGER",
            "ALTER TABLE mv_signals ADD COLUMN sector_rs_rank INTEGER",
            "ALTER TABLE mv_signals ADD COLUMN sector_breadth REAL",
            "ALTER TABLE mv_signals ADD COLUMN mkt_breadth    REAL",
        ]:
            try:
                conn.execute(_col_def)
            except Exception:
                pass  # column already exists

        conn.execute(
            "DELETE FROM mv_signals WHERE as_of_date = ?", (as_of_date,))

        rows_written = 0

        # Write LONG signals
        for _, row in longs_df.iterrows():
            conn.execute("""
                INSERT INTO mv_signals (
                    as_of_date, symbol, sector, signal_type,
                    close, ema20, ema50, ema200,
                    pivot_high, pivot_low, bb_width, high_200d,
                    atr_pct, vol_ratio, rs_rating, rs_score,
                    vol_avg20, market_up, is_dfc,
                    rs_rank, sector_rs_rank, sector_breadth, mkt_breadth
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                as_of_date,
                str(row.get("symbol", "")),
                str(row.get("sector", "")) if pd.notna(row.get("sector")) else None,
                "LONG",
                float(row["close"])      if pd.notna(row.get("close"))      else None,
                float(row["ema20"])      if pd.notna(row.get("ema20"))      else None,
                float(row["ema50"])      if pd.notna(row.get("ema50"))      else None,
                float(row["ema200"])     if pd.notna(row.get("ema200"))     else None,
                float(row["pivot_high"]) if pd.notna(row.get("pivot_high")) else None,
                None,
                float(row["bb_width"])   if pd.notna(row.get("bb_width"))   else None,
                float(row["high_200d"])  if pd.notna(row.get("high_200d"))  else None,
                float(row["atr_pct"])    if pd.notna(row.get("atr_pct"))    else None,
                float(row["vol_ratio"])  if pd.notna(row.get("vol_ratio"))  else None,
                float(row["rs_rating"])  if pd.notna(row.get("rs_rating"))  else None,
                float(row["rs_score"])   if pd.notna(row.get("rs_score"))   else None,
                float(row["vol_avg20"])  if pd.notna(row.get("vol_avg20"))  else None,
                int(bool(row.get("market_up", False))),
                int(bool(row.get("is_dfc", False))),
                int(row["rs_rank"])           if pd.notna(row.get("rs_rank"))          else None,
                int(row["sector_rs_rank"])     if pd.notna(row.get("sector_rs_rank"))   else None,
                float(row["sector_breadth"])   if pd.notna(row.get("sector_breadth"))   else None,
                float(row.get("mkt_breadth", mkt_breadth)),
            ))
            rows_written += 1

        # Write SHORT signals
        for _, row in shorts_df.iterrows():
            conn.execute("""
                INSERT INTO mv_signals (
                    as_of_date, symbol, sector, signal_type,
                    close, ema20, ema50, ema200,
                    pivot_high, pivot_low, bb_width, high_200d,
                    atr_pct, vol_ratio, rs_rating, rs_score,
                    vol_avg20, market_up, is_dfc,
                    mkt_breadth
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                as_of_date,
                str(row.get("symbol", "")),
                str(row.get("sector", "")) if pd.notna(row.get("sector")) else None,
                "SHORT",
                float(row["close"])      if pd.notna(row.get("close"))      else None,
                float(row["ema20"])      if pd.notna(row.get("ema20"))      else None,
                float(row["ema50"])      if pd.notna(row.get("ema50"))      else None,
                float(row["ema200"])     if pd.notna(row.get("ema200"))     else None,
                None,
                float(row["pivot_low"])  if pd.notna(row.get("pivot_low"))  else None,
                float(row["bb_width"])   if pd.notna(row.get("bb_width"))   else None,
                None,
                float(row["atr_pct"])    if pd.notna(row.get("atr_pct"))    else None,
                float(row["vol_ratio"])  if pd.notna(row.get("vol_ratio"))  else None,
                float(row["rs_rating"])  if pd.notna(row.get("rs_rating"))  else None,
                float(row["rs_score"])   if pd.notna(row.get("rs_score"))   else None,
                float(row["vol_avg20"])  if pd.notna(row.get("vol_avg20"))  else None,
                int(bool(row.get("market_up", False))),
                int(bool(row.get("is_dfc", False))),
                float(mkt_breadth),
            ))
            rows_written += 1

        # Write WATCHLIST signals
        for _, row in watchlist_df.iterrows():
            conn.execute("""
                INSERT INTO mv_signals (
                    as_of_date, symbol, sector, signal_type,
                    close, pivot_high, bb_width,
                    atr_pct, vol_ratio, rs_rating, rs_score,
                    vol_avg20, rs_rank, sector_rs_rank, sector_breadth, mkt_breadth
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                as_of_date,
                str(row.get("symbol", "")),
                str(row.get("sector", "")) if pd.notna(row.get("sector")) else None,
                "WATCHLIST",
                float(row["close"])      if pd.notna(row.get("close"))      else None,
                float(row["pivot_high"]) if pd.notna(row.get("pivot_high")) else None,
                float(row["bb_width"])   if pd.notna(row.get("bb_width"))   else None,
                float(row["atr_pct"])    if pd.notna(row.get("atr_pct"))    else None,
                float(row["vol_ratio"])  if pd.notna(row.get("vol_ratio"))  else None,
                float(row["rs_rating"])  if pd.notna(row.get("rs_rating"))  else None,
                float(row["rs_score"])   if pd.notna(row.get("rs_score"))   else None,
                float(row["vol_avg20"])  if pd.notna(row.get("vol_avg20"))  else None,
                int(row["rs_rank"])         if pd.notna(row.get("rs_rank"))         else None,
                int(row["sector_rs_rank"])  if pd.notna(row.get("sector_rs_rank"))  else None,
                float(row["sector_breadth"]) if pd.notna(row.get("sector_breadth")) else None,
                float(row.get("mkt_breadth", mkt_breadth)),
            ))
            rows_written += 1

        # Always write a GATE_STATUS sentinel row so the dashboard can display
        # correct gate state even when 0 signal rows are written for the date.
        _latest_day   = features_df[features_df["date"] == features_df["date"].max()]
        _market_up_val = bool(_latest_day["market_up"].iloc[0]) if len(_latest_day) > 0 else False
        conn.execute("""
            INSERT OR REPLACE INTO mv_signals (as_of_date, symbol, signal_type, market_up, mkt_breadth)
            VALUES (?, '__GATE__', 'GATE_STATUS', ?, ?)
        """, (as_of_date, int(_market_up_val), float(mkt_breadth)))

        conn.commit()
        conn.close()

        log.info(f"_killed_mv_signals: wrote {rows_written} signal rows + 1 GATE_STATUS row")
        log.info("=== _killed_mv_signals COMPLETE ===")
        return {
            "status":       "ok",
            "as_of_date":   as_of_date,
            "longs":        len(longs_df),
            "shorts":       len(shorts_df),
            "watchlist":    len(watchlist_df),
            "rows_written": rows_written,
        }

    except Exception as e:
        log.error(f"_killed_mv_signals FAILED: {e}")
        log.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}


def _killed_stm_signals() -> dict:
    """
    Compute STM signals for the latest date and write to stm_signals table.
    Returns a summary dict: {as_of_date, symbols, status}
    """
    log.info("=== run_stm_signals START ===")
    try:
        # STEP A: Load 60-day price data
        from database import get_sector_price_data_60d_active

        raw = get_sector_price_data_60d_active()
        if not raw:
            log.error("run_stm_signals: no price data")
            return {"status": "error", "message": "no price data"}

        prices_df = pd.DataFrame(raw)
        prices_df["date"] = pd.to_datetime(prices_df["date"])
        for col in ("open", "high", "low", "close"):
            prices_df[col] = pd.to_numeric(prices_df[col], errors="coerce")
        prices_df["volume"] = pd.to_numeric(
            prices_df["volume"], errors="coerce").fillna(0)
        prices_df = prices_df.sort_values(["symbol", "date"])

        log.info(f"run_stm_signals: loaded {len(prices_df):,} rows, "
                 f"{prices_df['symbol'].nunique()} symbols")

        # STEP B: Compute signals using existing function
        # Replicate the exact logic from dashboard.py _compute_stm_signals()
        df = prices_df.copy()
        df = df.groupby("symbol", group_keys=False).tail(60)
        counts = df.groupby("symbol").size()
        df = df[df["symbol"].isin(
            counts[counts >= 50].index)].copy()

        if df.empty:
            log.warning("run_stm_signals: no symbols with >= 50 bars")
            return {"status": "ok", "as_of_date": None, "symbols": 0}

        df = df.sort_values(["symbol", "date"])
        g_close = df.groupby("symbol")["close"]
        df["ma21"] = g_close.transform(
            lambda s: s.rolling(21, min_periods=21).mean())
        df["ma50"] = g_close.transform(
            lambda s: s.rolling(50, min_periods=50).mean())

        df["prev_close"] = df.groupby("symbol")["close"].shift(1)
        hl  = (df["high"] - df["low"]).abs()
        hpc = (df["high"] - df["prev_close"]).abs()
        lpc = (df["low"]  - df["prev_close"]).abs()
        df["tr"] = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        df["atr_14"] = df.groupby("symbol")["tr"].transform(
            lambda s: s.rolling(14, min_periods=14).mean())

        latest_idx = df.groupby("symbol")["date"].idxmax()
        latest = df.loc[latest_idx].reset_index(drop=True)

        last5 = df.groupby("symbol", group_keys=False).tail(5)
        range5 = (
            last5.groupby("symbol")
            .agg(high5=("high", "max"), low5=("low", "min"))
            .reset_index()
        )

        last10 = df.groupby("symbol", group_keys=False).tail(10)
        vol10  = last10.groupby("symbol")["volume"].mean(
        ).reset_index(name="avg_vol_10d")

        result = (
            latest[["symbol", "sector", "date", "close", "low",
                    "ma21", "ma50", "atr_14"]]
            .rename(columns={
                "close": "latest_close",
                "date":  "as_of_date",
                "low":   "day_low"})
            .merge(range5, on="symbol", how="left")
            .merge(vol10,  on="symbol", how="left")
        )

        result["range_5d_pct"] = (
            (result["high5"] - result["low5"])
            / result["low5"] * 100
        ).round(2)
        for c in ("latest_close", "ma21", "ma50"):
            result[c] = result[c].round(2)
        result["atr_pct"] = (
            result["atr_14"] / result["latest_close"] * 100
        ).round(2)
        result = result.drop(
            columns=["high5", "low5", "atr_14"]
        ).dropna(subset=["ma21", "ma50"])

        as_of_date = result["as_of_date"].max()
        if hasattr(as_of_date, "strftime"):
            as_of_date = as_of_date.strftime("%Y-%m-%d")
        else:
            as_of_date = str(as_of_date)[:10]

        log.info(f"run_stm_signals: as_of_date={as_of_date} "
                 f"symbols={len(result)}")

        # STEP C: Write to stm_signals
        conn = get_conn()
        conn.execute(
            "DELETE FROM stm_signals WHERE as_of_date = ?",
            (as_of_date,))

        rows_written = 0
        for _, row in result.iterrows():
            conn.execute("""
                INSERT INTO stm_signals (
                    as_of_date, symbol, sector,
                    latest_close, day_low, ma21, ma50,
                    avg_vol_10d, range_5d_pct, atr_pct
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                as_of_date,
                str(row["symbol"]),
                str(row["sector"]) if pd.notna(row.get("sector")) else None,
                float(row["latest_close"]) if pd.notna(row.get("latest_close")) else None,
                float(row["day_low"])      if pd.notna(row.get("day_low"))      else None,
                float(row["ma21"])         if pd.notna(row.get("ma21"))         else None,
                float(row["ma50"])         if pd.notna(row.get("ma50"))         else None,
                float(row["avg_vol_10d"])  if pd.notna(row.get("avg_vol_10d"))  else None,
                float(row["range_5d_pct"]) if pd.notna(row.get("range_5d_pct")) else None,
                float(row["atr_pct"])      if pd.notna(row.get("atr_pct"))      else None,
            ))
            rows_written += 1

        conn.commit()
        conn.close()

        log.info(f"_killed_stm_signals: wrote {rows_written} rows")
        log.info("=== _killed_stm_signals COMPLETE ===")
        return {
            "status":       "ok",
            "as_of_date":   as_of_date,
            "symbols":      rows_written,
            "rows_written": rows_written,
        }

    except Exception as e:
        log.error(f"_killed_stm_signals FAILED: {e}")
        log.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: run_recovery_signals()
# ══════════════════════════════════════════════════════════════════════════════

def run_recovery_signals() -> dict:
    """
    Compute Recovery Bases signals and write to recovery_signals table.
    Reuses _run_recovery_screener() logic directly.
    Returns a summary dict: {as_of_date, triggered, watchlist, status}
    """
    log.info("=== run_recovery_signals START ===")
    try:
        import sys as _sys
        import os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

        from database import get_sector_price_data_300d_active, get_index_prices

        # ── Replicate _run_recovery_screener() logic exactly ──────────────
        raw = get_sector_price_data_300d_active()
        if not raw:
            log.error("run_recovery_signals: no price data")
            return {"status": "error", "message": "no price data"}

        all_df = pd.DataFrame(raw)
        all_df["date"] = pd.to_datetime(all_df["date"])
        for col in ("open", "high", "low", "close"):
            all_df[col] = pd.to_numeric(all_df[col], errors="coerce")
        all_df["volume"] = pd.to_numeric(
            all_df["volume"], errors="coerce").fillna(0)

        cutoff = all_df["date"].max() - pd.Timedelta(days=420)
        all_df = all_df[all_df["date"] >= cutoff]
        all_df = all_df.sort_values(
            ["symbol", "date"]).reset_index(drop=True)

        as_of_date = all_df["date"].max().strftime("%Y-%m-%d")

        # KSE-100 regime check
        kse_regime_ok = True
        try:
            kse_rows = get_index_prices("KSE-100")
            if kse_rows:
                kse_df = pd.DataFrame(kse_rows)
                kse_df["date"]  = pd.to_datetime(kse_df["date"])
                kse_df["close"] = pd.to_numeric(
                    kse_df["close"], errors="coerce")
                kse_df = kse_df.sort_values("date")
                if len(kse_df) >= 12:
                    kse_regime_ok = (
                        float(kse_df["close"].iloc[-1])
                        >= float(kse_df["close"].iloc[-11])
                    )
        except Exception:
            pass

        all_df = all_df[~all_df["sector"].isin(EXCLUDED_SECTORS)]
        all_df = all_df[~all_df["symbol"].str.match(r"^P\d", na=False)]
        all_df = all_df[all_df["close"] >= 5.0]

        all_dates = sorted(all_df["date"].unique())
        if not all_dates:
            return {"status": "ok", "as_of_date": as_of_date,
                    "triggered": 0, "watchlist": 0}

        latest_date  = all_dates[-1]
        last_5_dates = set(all_dates[-5:]) if len(
            all_dates) >= 5 else set(all_dates)
        today_dt     = pd.Timestamp(latest_date).date()

        def _base_scan(c, from_idx, thr=0.20, max_lb=90):
            hi = lo = c[from_idx]
            start = from_idx
            for i in range(
                from_idx - 1,
                max(from_idx - max_lb, 0) - 1, -1
            ):
                nh = max(hi, c[i])
                nl = min(lo, c[i])
                if (nh - nl) / nl >= thr:
                    break
                hi, lo, start = nh, nl, i
            return start

        watchlist_rows = []
        triggered_rows = []
        triggered_syms = set()

        for sym, grp in all_df.groupby("symbol", sort=False):
            grp = grp.reset_index(drop=True)
            n   = len(grp)
            if n < 60:
                continue

            closes  = grp["close"].values.astype(float)
            opens   = grp["open"].values.astype(float)
            highs   = grp["high"].values.astype(float)
            lows    = grp["low"].values.astype(float)
            volumes = grp["volume"].values.astype(float)
            dates   = grp["date"].values
            sector  = grp["sector"].iloc[0]

            avg_vol_20d = (volumes[-20:].mean()
                          if n >= 20 else volumes.mean())
            if avg_vol_20d < 800_000:
                continue

            vol_s    = pd.Series(volumes)
            vol_ma50 = vol_s.rolling(50, min_periods=30).mean().values
            if np.isnan(vol_ma50[-1]) or vol_ma50[-1] <= 0:
                continue

            trigger_hit = None
            for t in range(max(1, n - 5), n):
                if dates[t] not in last_5_dates:
                    continue
                prev = t - 1
                if prev < 15:
                    continue
                bs     = _base_scan(closes, prev)
                b_days = prev - bs + 1
                if b_days < 8:
                    continue
                b_closes = closes[bs : prev + 1]
                b_high   = b_closes.max()
                b_low    = b_closes.min()
                b_range  = (b_high - b_low) / b_low
                if b_range >= 0.20:
                    continue
                pre      = closes[max(0, bs - 90) : bs]
                if len(pre) < 5:
                    continue
                pre_high = pre.max()
                drawdown = (pre_high - closes[bs]) / pre_high
                if drawdown < 0.30:
                    continue
                # FIX 1: base-relative volume baseline (replaces vol_ma50 in Gates 8 & 9)
                # Use median of the first half (≤10 bars) of the base as baseline,
                # so the denominator reflects volume AFTER the decline stopped, not during it.
                bv        = volumes[bs : prev + 1]
                half_len  = min(10, b_days // 2)
                early_bars = max(1, half_len)
                base_vol_baseline = np.median(volumes[bs : bs + early_bars])
                if base_vol_baseline <= 0:
                    continue
                # Gate 8: volume contraction in last 5 base bars vs base_vol_baseline
                l5v = bv[-5:]
                l5r = l5v / base_vol_baseline
                if not (l5r.mean() < 0.50 and (l5r < 0.60).sum() >= 3):
                    continue
                # Gate 9: prior volume surge within base vs base_vol_baseline
                all_br = bv / base_vol_baseline
                if (all_br > 1.5).sum() < 2:
                    continue
                if vol_ma50[t] <= 0:
                    continue
                vr      = volumes[t] / vol_ma50[t]
                day_rng = highs[t] - lows[t]
                # FIX 2: remove close>open (open is structurally NULL in this dataset);
                # replaced by close>b_high + close in upper 40% of range, which are retained.
                if not (
                    vr >= 2.5
                    and closes[t] > b_high
                    and day_rng > 0
                    and (closes[t] - lows[t]) / day_rng >= 0.40
                ):
                    continue
                trigger_hit = dict(
                    t_date       = pd.Timestamp(dates[t]).date(),
                    t_close      = round(closes[t], 2),
                    t_vol_ratio  = round(vr, 2),
                    b_days       = b_days,
                    b_range_pct  = round(b_range * 100, 1),
                    drawdown_pct = round(drawdown * 100, 1),
                    pre_high     = round(pre_high, 2),
                    current      = round(closes[-1], 2),
                )
                break

            if trigger_hit:
                triggered_rows.append(dict(
                    symbol         = sym,
                    sector         = sector,
                    list_type      = "TRIGGERED",
                    close          = trigger_hit["current"],
                    drawdown_pct   = trigger_hit["drawdown_pct"],
                    base_days      = trigger_hit["b_days"],
                    base_range_pct = trigger_hit["b_range_pct"],
                    avg_vol_m      = round(avg_vol_20d / 1e6, 2),
                    triggered_date = str(trigger_hit["t_date"]),
                    fresh          = int(trigger_hit["t_date"] == today_dt),
                    trigger_close  = trigger_hit["t_close"],
                    trigger_vol_x  = trigger_hit["t_vol_ratio"],
                    current_close  = trigger_hit["current"],
                    move_pct       = round(
                        (trigger_hit["current"] - trigger_hit["t_close"])
                        / trigger_hit["t_close"] * 100, 1),
                    pre_high       = trigger_hit["pre_high"],
                    kse_regime_ok  = int(kse_regime_ok),
                ))
                triggered_syms.add(sym)
                continue

            bs     = _base_scan(closes, n - 1)
            b_days = n - bs
            if b_days < 8:
                continue
            b_closes = closes[bs:]
            b_high   = b_closes.max()
            b_low    = b_closes.min()
            b_range  = (b_high - b_low) / b_low
            if b_range >= 0.20:
                continue
            pre      = closes[max(0, bs - 90) : bs]
            if len(pre) < 5:
                continue
            pre_high = pre.max()
            drawdown = (pre_high - closes[bs]) / pre_high
            if drawdown < 0.30:
                continue
            # FIX 1 (WATCHLIST path): same base-relative baseline as TRIGGERED path
            bv        = volumes[bs:]
            half_len  = min(10, b_days // 2)
            early_bars = max(1, half_len)
            base_vol_baseline = np.median(volumes[bs : bs + early_bars])
            if base_vol_baseline <= 0:
                continue
            # Gate 8: contraction in last 5 base bars
            l5v = bv[-5:]
            l5r = l5v / base_vol_baseline
            if not (l5r.mean() < 0.50 and (l5r < 0.60).sum() >= 3):
                continue
            # Gate 9: prior surge within base
            all_br = bv / base_vol_baseline
            if (all_br > 1.5).sum() < 2:
                continue
            cur_vr = (volumes[-1] / vol_ma50[-1]
                      if vol_ma50[-1] > 0 else 0.0)

            watchlist_rows.append(dict(
                symbol          = sym,
                sector          = sector,
                list_type       = "WATCHLIST",
                close           = round(closes[-1], 2),
                drawdown_pct    = round(drawdown * 100, 1),
                base_days       = b_days,
                base_range_pct  = round(b_range * 100, 1),
                vol_ratio_today = round(cur_vr, 2),
                base_high       = round(b_high, 2),
                dist_pct        = round(
                    (b_high - closes[-1]) / closes[-1] * 100, 1),
                avg_vol_m       = round(avg_vol_20d / 1e6, 2),
                kse_regime_ok   = int(kse_regime_ok),
            ))

        log.info(f"run_recovery_signals: as_of_date={as_of_date} "
                 f"triggered={len(triggered_rows)} "
                 f"watchlist={len(watchlist_rows)}")

        # Write to DB
        conn = get_conn()
        conn.execute(
            "DELETE FROM recovery_signals WHERE as_of_date = ?",
            (as_of_date,))

        rows_written = 0
        all_rows = triggered_rows + watchlist_rows
        for r in all_rows:
            conn.execute("""
                INSERT INTO recovery_signals (
                    as_of_date, symbol, sector, list_type,
                    close, drawdown_pct, base_days,
                    base_range_pct, vol_ratio_today,
                    base_high, dist_pct, avg_vol_m,
                    triggered_date, fresh, trigger_close,
                    trigger_vol_x, current_close, move_pct,
                    pre_high, kse_regime_ok
                ) VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
            """, (
                as_of_date,
                r.get("symbol"),
                r.get("sector"),
                r.get("list_type"),
                r.get("close"),
                r.get("drawdown_pct"),
                r.get("base_days"),
                r.get("base_range_pct"),
                r.get("vol_ratio_today"),
                r.get("base_high"),
                r.get("dist_pct"),
                r.get("avg_vol_m"),
                r.get("triggered_date"),
                r.get("fresh"),
                r.get("trigger_close"),
                r.get("trigger_vol_x"),
                r.get("current_close"),
                r.get("move_pct"),
                r.get("pre_high"),
                r.get("kse_regime_ok"),
            ))
            rows_written += 1

        conn.commit()
        conn.close()

        log.info(f"run_recovery_signals: wrote {rows_written} rows")
        log.info("=== run_recovery_signals COMPLETE ===")
        return {
            "status":       "ok",
            "as_of_date":   as_of_date,
            "triggered":    len(triggered_rows),
            "watchlist":    len(watchlist_rows),
            "rows_written": rows_written,
        }

    except Exception as e:
        log.error(f"run_recovery_signals FAILED: {e}")
        log.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: run_portfolio_signals()
# ══════════════════════════════════════════════════════════════════════════════

def run_portfolio_signals() -> dict:
    """
    Compute Portfolio signals and write to portfolio_signals table.
    Reads sector ranks from sector_signals table (latest date).
    Returns a summary dict: {as_of_date, symbols, status}
    """
    log.info("=== run_portfolio_signals START ===")
    try:
        # STEP A: Load sector ranks from sector_signals (latest date)
        conn = get_conn()
        latest_sector_date = conn.execute(
            "SELECT MAX(date) FROM sector_signals"
        ).fetchone()[0]

        sector_rows = conn.execute("""
            SELECT sector, rs_rank, composite_score
            FROM sector_signals
            WHERE date = ?
            ORDER BY rs_rank
        """, (latest_sector_date,)).fetchall()
        conn.close()

        # Build sector_df matching what dashboard passes in
        sector_df = pd.DataFrame([dict(r) for r in sector_rows])
        if not sector_df.empty:
            sector_df = sector_df.rename(columns={"rs_rank": "rank"})
            # Add momentum label — derive from composite_score
            # Top third = Heating Up, bottom third = Cooling, middle = Neutral
            if "composite_score" in sector_df.columns:
                q33 = sector_df["composite_score"].quantile(0.33)
                q66 = sector_df["composite_score"].quantile(0.66)
                sector_df["momentum"] = sector_df["composite_score"].apply(
                    lambda s: "Heating Up"
                    if s >= q66 else (
                        "Cooling" if s <= q33 else "Neutral"
                    )
                )

        log.info(f"run_portfolio_signals: loaded "
                 f"{len(sector_df)} sector ranks "
                 f"as of {latest_sector_date}")

        # STEP B: Run compute_portfolio_candidates()
        from portfolio import compute_portfolio_candidates

        port_df = compute_portfolio_candidates(sector_df=sector_df)

        if port_df.empty:
            log.warning("run_portfolio_signals: empty result")
            return {"status": "ok", "as_of_date": None, "symbols": 0}

        # Determine as_of_date from latest_date in results
        as_of_date = str(port_df["latest_date"].max())[:10]
        log.info(f"run_portfolio_signals: as_of_date={as_of_date} "
                 f"symbols={len(port_df)}")

        # STEP C: Write to portfolio_signals
        conn = get_conn()
        conn.execute(
            "DELETE FROM portfolio_signals WHERE as_of_date = ?",
            (as_of_date,))

        rows_written = 0
        for _, row in port_df.iterrows():
            conn.execute("""
                INSERT INTO portfolio_signals (
                    as_of_date, symbol, sector,
                    latest_close, latest_date,
                    ma10w, ma30w, dist_from_30w_pct,
                    stage, stage_label,
                    rs_30d, rs_10d, rs_trend,
                    sector_rank, sector_momentum,
                    composite_score, recommendation, rank
                ) VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
            """, (
                as_of_date,
                str(row["symbol"]),
                str(row["sector"])            if pd.notna(row.get("sector"))            else None,
                float(row["latest_close"])    if pd.notna(row.get("latest_close"))      else None,
                str(row["latest_date"])       if pd.notna(row.get("latest_date"))       else None,
                float(row["ma10w"])           if pd.notna(row.get("ma10w"))             else None,
                float(row["ma30w"])           if pd.notna(row.get("ma30w"))             else None,
                float(row["dist_from_30w_pct"]) if pd.notna(row.get("dist_from_30w_pct")) else None,
                int(row["stage"])             if pd.notna(row.get("stage"))             else None,
                str(row["stage_label"])       if pd.notna(row.get("stage_label"))       else None,
                float(row["rs_30d"])          if pd.notna(row.get("rs_30d"))            else None,
                float(row["rs_10d"])          if pd.notna(row.get("rs_10d"))            else None,
                str(row["rs_trend"])          if pd.notna(row.get("rs_trend"))          else None,
                int(row["sector_rank"])       if pd.notna(row.get("sector_rank"))       else None,
                str(row["sector_momentum"])   if pd.notna(row.get("sector_momentum"))   else None,
                float(row["composite_score"]) if pd.notna(row.get("composite_score"))   else None,
                str(row["recommendation"])    if pd.notna(row.get("recommendation"))    else None,
                int(row["rank"])              if pd.notna(row.get("rank"))              else None,
            ))
            rows_written += 1

        conn.commit()
        conn.close()

        log.info(f"run_portfolio_signals: wrote {rows_written} rows")
        log.info("=== run_portfolio_signals COMPLETE ===")
        return {
            "status":       "ok",
            "as_of_date":   as_of_date,
            "symbols":      rows_written,
            "rows_written": rows_written,
        }

    except Exception as e:
        log.error(f"run_portfolio_signals FAILED: {e}")
        log.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: main()
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """
    Run all four signal engines in sequence.
    Each module runs independently — failure of one does not stop others.
    Prints a final summary report.
    """
    log.info("=" * 60)
    log.info("SIGNAL ENGINE START")
    log.info(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    results = {}

    # Run each module independently
    for name, fn in [
        ("recovery_signals",  run_recovery_signals),
        ("portfolio_signals", run_portfolio_signals),
    ]:
        log.info(f"--- Starting {name} ---")
        try:
            results[name] = fn()
        except Exception as e:
            log.error(f"{name} raised uncaught exception: {e}")
            results[name] = {"status": "error", "message": str(e)}

    # Final summary
    log.info("=" * 60)
    log.info("SIGNAL ENGINE COMPLETE — SUMMARY")
    log.info("=" * 60)
    all_ok = True
    for name, r in results.items():
        status = r.get("status", "unknown")
        if status != "ok":
            all_ok = False
        date_s = r.get("as_of_date", "—")
        rows   = r.get("rows_written", r.get("symbols", "—"))
        msg    = r.get("message", "")
        log.info(
            f"  {name:<22} status={status:<6} "
            f"date={date_s}  rows={rows}  {msg}"
        )

    log.info("=" * 60)
    if all_ok:
        log.info("ALL MODULES OK")
    else:
        log.warning("ONE OR MORE MODULES FAILED — check logs above")
    log.info("=" * 60)

    return results


if __name__ == "__main__":
    main()
