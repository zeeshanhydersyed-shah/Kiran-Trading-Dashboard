"""
Daily sector signals hook for the PSX pipeline.

append_latest_sector_signals() is called from cmd_update() in main.py after
the regime hook. It pulls 60 trading days of warmup data, recomputes per-stock
indicators, aggregates to sector level, and upserts a row per sector for the
latest scraped date into sector_signals.
"""

import logging
import os
import sqlite3

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DB = "psx_data.db"
WARMUP = 70  # trading days — 70 gives EMA50 enough history
_PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")


def _ensure_sector_stage_columns(conn: sqlite3.Connection) -> None:
    """Add sector stage columns to sector_signals if they don't exist yet."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(sector_signals)").fetchall()}
    new_cols = {
        "sector_ema50":        "REAL",
        "sector_above_ema":    "INTEGER",
        "sector_ema_slope":    "REAL",
        "sector_stage":        "TEXT",
        "sector_pivot_dist_pct": "REAL",
        "sector_rs_new_high":  "INTEGER",
    }
    for col, dtype in new_cols.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE sector_signals ADD COLUMN {col} {dtype}")
    conn.commit()


def _minmax_norm(series: pd.Series) -> pd.Series:
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - mn) / (mx - mn)


def _compute_flow_signals_pg(date_str: str) -> None:
    """PG equivalent of compute_flow_signals(): reads market_flows from Supabase,
    runs the same pandas rolling-net computation, writes flow_* back via PG UPDATE.
    Silent no-op when market_flows is empty.
    """
    from database_pg import get_market_flows_pg, update_sector_flow_signals_pg

    flow_raw = get_market_flows_pg(date_str)
    if not flow_raw:
        return

    df = pd.DataFrame(flow_raw)
    if df.empty:
        return

    df["sector_upper"] = df["sector"].str.strip().str.upper()
    df["psx_sector"]   = df["sector_upper"].map(_FLOW_TO_PSX)
    df = df.dropna(subset=["psx_sector"])
    if df.empty:
        return

    df["client_upper"] = df["client_type"].str.strip().str.upper()
    df["bucket"] = df["client_upper"].apply(
        lambda c: "SMART"  if c in _FLOW_SMART
             else "RETAIL" if c in _FLOW_RETAIL
             else "UNKNOWN"
    )

    daily = (
        df.groupby(["date", "psx_sector", "bucket"])["net_value"]
        .sum()
        .reset_index()
    )
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values(["psx_sector", "bucket", "date"])

    pivot = daily.pivot_table(
        index=["date", "psx_sector"],
        columns="bucket",
        values="net_value",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    pivot.columns.name = None
    for col in ["SMART", "RETAIL", "UNKNOWN"]:
        if col not in pivot.columns:
            pivot[col] = 0.0

    pivot = pivot.sort_values(["psx_sector", "date"])

    for bucket, col_5d, col_20d in [
        ("SMART",  "flow_smart_net_5d",  "flow_smart_net_20d"),
        ("RETAIL", "flow_retail_net_5d", "flow_retail_net_20d"),
    ]:
        pivot[col_5d]  = pivot.groupby("psx_sector")[bucket].transform(
            lambda x: x.rolling(5,  min_periods=1).sum()
        )
        pivot[col_20d] = pivot.groupby("psx_sector")[bucket].transform(
            lambda x: x.rolling(20, min_periods=1).sum()
        )

    def _direction(row):
        s5, s20 = row["flow_smart_net_5d"], row["flow_smart_net_20d"]
        if s5 > 0 and s20 > 0:   return "ACCUMULATING"
        if s5 < 0 and s20 < 0:   return "DISTRIBUTING"
        if s5 > 0 and s20 < 0:   return "RECOVERING"
        if s5 < 0 and s20 > 0:   return "FADING"
        return "NEUTRAL"

    pivot["flow_direction"] = pivot.apply(_direction, axis=1)
    pivot["date_str"] = pivot["date"].dt.date.astype(str)
    today_rows = pivot[pivot["date_str"] == date_str]

    flow_updates = [
        {
            "sector":              row["psx_sector"],
            "flow_smart_net_5d":   row["flow_smart_net_5d"],
            "flow_smart_net_20d":  row["flow_smart_net_20d"],
            "flow_retail_net_5d":  row["flow_retail_net_5d"],
            "flow_retail_net_20d": row["flow_retail_net_20d"],
            "flow_direction":      row["flow_direction"],
        }
        for _, row in today_rows.iterrows()
    ]
    update_sector_flow_signals_pg(date_str, flow_updates)


def _append_latest_sector_signals_pg() -> None:
    """PG-backed equivalent of append_latest_sector_signals().

    Reads all inputs from Supabase, runs the same computation, writes back via PG helpers.
    active_stocks_on_date is absent from Supabase — active symbols come from
    stock_metadata.is_active instead (same fallback the SQLite path already uses).
    """
    from database_pg import (
        get_prices_adjusted_max_date_pg,
        get_sector_signals_count_for_date_pg,
        get_prices_warmup_with_sector_pg,
        get_kse100_warmup_pg,
        get_regime_for_date_pg,
        get_market_cap_pg,
        get_active_symbols_pg,
        get_sector_signals_prev_ranks_sector_pg,
        get_sector_rs_history_pg,
        write_sector_signals_batch_pg,
    )

    # ── Step 1 — find target date ─────────────────────────────────────────────
    target_date = get_prices_adjusted_max_date_pg()
    if not target_date:
        logger.warning("Sector signals hook (PG): no data in prices_adjusted.")
        return

    if get_sector_signals_count_for_date_pg(target_date) > 0:
        logger.info("Sector signals already up to date for %s (PG).", target_date)
        return

    # ── Step 2 — 60-day price warmup ─────────────────────────────────────────
    prices_rows = get_prices_warmup_with_sector_pg(target_date)
    if not prices_rows:
        logger.warning("Sector signals hook (PG): no price data found.")
        return
    prices = pd.DataFrame(prices_rows)

    # ── Step 3 — KSE-100 for same window ─────────────────────────────────────
    kse_rows = get_kse100_warmup_pg(target_date)
    kse100 = pd.DataFrame(kse_rows) if kse_rows else pd.DataFrame(columns=["date", "kse_close"])

    # ── Step 4 — supporting tables ────────────────────────────────────────────
    regime       = get_regime_for_date_pg(target_date)
    mcap         = get_market_cap_pg()
    active_symbols = get_active_symbols_pg()

    # ── Step 5 — per-stock indicators (pure pandas — identical to SQLite path) ─
    prices = prices.sort_values(["symbol", "date"])
    prices["ema20"] = prices.groupby("symbol")["close"].transform(
        lambda x: x.ewm(span=20, adjust=False).mean()
    )
    prices["prev_close"]    = prices.groupby("symbol")["close"].shift(1)
    prices["daily_return"]  = (prices["close"] - prices["prev_close"]) / prices["prev_close"]
    prices["close_20d_ago"] = prices.groupby("symbol")["close"].shift(20)
    prices["close_50d_ago"] = prices.groupby("symbol")["close"].shift(50)
    prices["return_20d"]    = (prices["close"] - prices["close_20d_ago"]) / prices["close_20d_ago"]
    prices["return_50d"]    = (prices["close"] - prices["close_50d_ago"]) / prices["close_50d_ago"]
    prices["vol_20d_avg"]   = prices.groupby("symbol")["volume"].transform(
        lambda x: x.rolling(20, min_periods=5).mean()
    )

    kse100 = kse100.sort_values("date")
    kse100["kse_20d_ago"]    = kse100["kse_close"].shift(20)
    kse100["kse_50d_ago"]    = kse100["kse_close"].shift(50)
    kse100["kse_return_20d"] = (kse100["kse_close"] - kse100["kse_20d_ago"]) / kse100["kse_20d_ago"]
    kse100["kse_return_50d"] = (kse100["kse_close"] - kse100["kse_50d_ago"]) / kse100["kse_50d_ago"]
    kse_row     = kse100[kse100["date"] == target_date]
    kse_ret_20  = float(kse_row["kse_return_20d"].iloc[0]) if not kse_row.empty else np.nan
    kse_ret_50  = float(kse_row["kse_return_50d"].iloc[0]) if not kse_row.empty else np.nan

    # ── Step 6 — filter to target date ───────────────────────────────────────
    day_data = prices[prices["date"] == target_date].copy()

    # ── Step 7 — prev ranks + RS history ─────────────────────────────────────
    prev_ranks       = get_sector_signals_prev_ranks_sector_pg(target_date)
    sector_rs_20d_max = get_sector_rs_history_pg(target_date)

    # ── Step 7b — sector price index EMA50 / stage (no DDL needed in PG mode) ─
    sector_stage_data: dict = {}
    _all_sectors_ts = sorted(prices["sector"].dropna().unique())

    for _sec in _all_sectors_ts:
        _sec_hist = prices[prices["sector"] == _sec].copy()
        _syms     = _sec_hist["symbol"].unique()

        _w = pd.Series({s: mcap.get(s, 0) for s in _syms})
        _w_total = _w.sum()
        if _w_total <= 0:
            _w = pd.Series({s: 1.0 / len(_syms) for s in _syms})
        else:
            _w = _w / _w_total

        _piv = _sec_hist.pivot_table(index="date", columns="symbol", values="close")
        _piv = _piv.ffill()
        _w_aligned = _w.reindex(_piv.columns).fillna(0)
        _w_aligned = _w_aligned / _w_aligned.sum()
        _idx = (_piv * _w_aligned).sum(axis=1)

        if len(_idx) < 5 or _idx.iloc[0] == 0:
            sector_stage_data[_sec] = {
                "sector_ema50": None, "sector_above_ema": None,
                "sector_ema_slope": None, "sector_stage": None,
                "sector_pivot_dist_pct": None,
            }
            continue
        _idx  = _idx / _idx.iloc[0] * 100
        _ema50 = _idx.ewm(span=50, adjust=False).mean()

        _cur_idx = _idx.get(target_date)
        _cur_ema = _ema50.get(target_date)

        if _cur_idx is None or _cur_ema is None or _cur_ema == 0:
            sector_stage_data[_sec] = {
                "sector_ema50": None, "sector_above_ema": None,
                "sector_ema_slope": None, "sector_stage": None,
                "sector_pivot_dist_pct": None,
            }
            continue

        _above = bool(_cur_idx > _cur_ema)
        _ema_vals = _ema50.dropna()
        if len(_ema_vals) >= 6:
            _slope    = float(_ema_vals.iloc[-1] - _ema_vals.iloc[-6])
            _slope_pos = _slope > 0
        else:
            _slope    = None
            _slope_pos = None

        if _slope_pos is not None:
            if _above and _slope_pos:      _stage = "Stage 2"
            elif _above and not _slope_pos: _stage = "Stage 3"
            elif not _above and not _slope_pos: _stage = "Stage 4"
            else:                           _stage = "Stage 1"
        else:
            _stage = None

        _recent_high = float(_idx.iloc[-20:].max()) if len(_idx) >= 20 else float(_idx.max())
        _pivot_dist  = (_recent_high - float(_cur_idx)) / float(_cur_idx) * 100

        sector_stage_data[_sec] = {
            "sector_ema50":          round(float(_cur_ema), 2),
            "sector_above_ema":      1 if _above else 0,
            "sector_ema_slope":      round(float(_slope), 4) if _slope is not None else None,
            "sector_stage":          _stage,
            "sector_pivot_dist_pct": round(_pivot_dist, 2),
        }

    # ── Step 8 — compute sector metrics ──────────────────────────────────────
    sectors = sorted(day_data["sector"].unique())
    sector_rs_scores = {}

    for sector in sectors:
        sector_day = day_data[
            (day_data["sector"] == sector) &
            (day_data["symbol"].isin(active_symbols))
        ].copy()

        if len(sector_day) < 2:
            continue

        weights = sector_day["symbol"].map(mcap)
        if weights.isna().all():
            weights = pd.Series([1.0 / len(sector_day)] * len(sector_day), index=sector_day.index)
        else:
            weights = weights.fillna(weights.mean())
            total   = weights.sum()
            weights = weights / total if total > 0 else pd.Series(
                [1.0 / len(sector_day)] * len(sector_day), index=sector_day.index
            )

        valid_20 = sector_day["return_20d"].notna()
        if valid_20.sum() >= 2:
            w20 = weights[valid_20]; w20 = w20 / w20.sum()
            rs_20 = (sector_day.loc[valid_20, "return_20d"] * w20).sum()
            rs_20 = (rs_20 - kse_ret_20) * 100 if not np.isnan(kse_ret_20) else np.nan
        else:
            rs_20 = np.nan

        valid_50 = sector_day["return_50d"].notna()
        if valid_50.sum() >= 2:
            w50 = weights[valid_50]; w50 = w50 / w50.sum()
            rs_50 = (sector_day.loc[valid_50, "return_50d"] * w50).sum()
            rs_50 = (rs_50 - kse_ret_50) * 100 if not np.isnan(kse_ret_50) else np.nan
        else:
            rs_50 = np.nan

        above_ema = (sector_day["close"] > sector_day["ema20"]).sum()
        breadth   = (above_ema / len(sector_day)) * 100

        advancers = (sector_day["daily_return"] > 0).sum()
        decliners = (sector_day["daily_return"] < 0).sum()
        adr       = (advancers / decliners) if decliners > 0 else np.nan

        valid_vol = sector_day["vol_20d_avg"].notna() & (sector_day["vol_20d_avg"] > 0)
        if valid_vol.sum() >= 2:
            vol_today = sector_day.loc[valid_vol, "volume"].mean()
            vol_avg   = sector_day.loc[valid_vol, "vol_20d_avg"].mean()
            vol_ratio = vol_today / vol_avg if vol_avg > 0 else np.nan
        else:
            vol_ratio = np.nan

        sector_rs_scores[sector] = {
            "rs_score_20": rs_20, "rs_score_50": rs_50,
            "breadth_score": breadth, "adv_dec_ratio": adr, "vol_ratio": vol_ratio,
        }

    valid_sectors = {s: v for s, v in sector_rs_scores.items() if not np.isnan(v["rs_score_20"])}
    ranked = sorted(valid_sectors, key=lambda s: valid_sectors[s]["rs_score_20"], reverse=True)
    ranks  = {s: i + 1 for i, s in enumerate(ranked)}

    rows = []
    for sector, vals in sector_rs_scores.items():
        rs_rank      = ranks.get(sector)
        rs_rank_prev = prev_ranks.get(sector)

        rs_infl = 0
        if (rs_rank is not None and rs_rank_prev is not None
                and rs_rank < rs_rank_prev
                and not np.isnan(vals["rs_score_20"])
                and vals["rs_score_20"] > 0):
            rs_infl = 1

        rs_new_high = 0
        rs_today    = vals["rs_score_20"]
        if not np.isnan(rs_today):
            hist_max = sector_rs_20d_max.get(sector)
            if hist_max is None or float(rs_today) >= float(hist_max):
                rs_new_high = 1

        rows.append({
            "date": target_date,
            "sector": sector,
            "rs_score_20": None if np.isnan(vals["rs_score_20"]) else round(float(vals["rs_score_20"]), 4),
            "rs_score_50": None if np.isnan(vals["rs_score_50"]) else round(float(vals["rs_score_50"]), 4),
            "rs_rank":      rs_rank,
            "rs_rank_prev": rs_rank_prev,
            "breadth_score": round(float(vals["breadth_score"]), 2),
            "adv_dec_ratio": None if np.isnan(vals["adv_dec_ratio"]) else round(float(vals["adv_dec_ratio"]), 4),
            "vol_ratio":     None if np.isnan(vals["vol_ratio"]) else round(float(vals["vol_ratio"]), 4),
            "rs_inflection": rs_infl,
            "rs_new_high":   rs_new_high,
            "regime":        regime,
            "composite_score": None,
            **sector_stage_data.get(sector, {
                "sector_ema50": None, "sector_above_ema": None,
                "sector_ema_slope": None, "sector_stage": None,
                "sector_pivot_dist_pct": None,
            }),
        })

    if not rows:
        logger.warning("Sector signals hook (PG): no sector rows computed for %s.", target_date)
        return

    # ── Step 9 — composite_score ──────────────────────────────────────────────
    result_df = pd.DataFrame(rows)
    result_df["rs_norm"] = _minmax_norm(result_df["rs_score_20"].fillna(result_df["rs_score_20"].mean()))
    result_df["br_norm"] = _minmax_norm(result_df["breadth_score"])
    result_df["vr_norm"] = _minmax_norm(result_df["vol_ratio"].fillna(result_df["vol_ratio"].mean()))
    result_df["composite_score"] = (
        result_df["rs_norm"] * 0.5
        + result_df["br_norm"] * 0.3
        + result_df["vr_norm"] * 0.2
    ).round(4)

    # ── Step 10 — write ───────────────────────────────────────────────────────
    rows_written = write_sector_signals_batch_pg(result_df.to_dict("records"))
    logger.info("Sector signals appended (PG): %s — %d sectors written", target_date, rows_written)

    # ── Step 12 — flow enrichment ─────────────────────────────────────────────
    try:
        _compute_flow_signals_pg(target_date)
    except Exception as _fe:
        logger.warning("compute_flow_signals_pg failed for %s: %s", target_date, _fe)


def append_latest_sector_signals() -> None:
    if _PG_URL:
        _append_latest_sector_signals_pg()
        return
    conn = sqlite3.connect(DB)
    try:
        # ------------------------------------------------------------------
        # Step 1 — find target date
        # ------------------------------------------------------------------
        row = conn.execute("SELECT MAX(date) FROM prices_adjusted").fetchone()
        if not row or row[0] is None:
            logger.warning("Sector signals hook: no data in prices_adjusted.")
            return
        target_date = row[0]

        already = conn.execute(
            "SELECT COUNT(*) FROM sector_signals WHERE date = ?", (target_date,)
        ).fetchone()[0]
        if already > 0:
            logger.info("Sector signals already up to date for %s.", target_date)
            return

        # ------------------------------------------------------------------
        # Step 2 — load 60-day warmup window of stock prices
        # ------------------------------------------------------------------
        prices = pd.read_sql_query(
            """
            SELECT pa.date, pa.symbol, pa.close, pa.volume, sm.sector
            FROM prices_adjusted pa
            JOIN stock_metadata sm ON pa.symbol = sm.symbol
            WHERE pa.date IN (
                SELECT DISTINCT date FROM prices_adjusted
                WHERE date <= ?
                ORDER BY date DESC
                LIMIT 60
            )
              AND pa.close IS NOT NULL
              AND pa.close > 0
              AND sm.sector IS NOT NULL
            ORDER BY pa.symbol, pa.date
            """,
            conn,
            params=(target_date,),
        )

        if prices.empty:
            logger.warning("Sector signals hook: no price data found for warmup window.")
            return

        # ------------------------------------------------------------------
        # Step 3 — load KSE-100 for same window
        # ------------------------------------------------------------------
        kse100 = pd.read_sql_query(
            """
            SELECT date, close AS kse_close
            FROM index_prices
            WHERE symbol = 'KSE-100'
              AND date IN (
                  SELECT DISTINCT date FROM prices_adjusted
                  WHERE date <= ?
                  ORDER BY date DESC
                  LIMIT 60
              )
            ORDER BY date
            """,
            conn,
            params=(target_date,),
        )

        # ------------------------------------------------------------------
        # Step 4 — load supporting tables
        # ------------------------------------------------------------------
        regime_row = conn.execute(
            "SELECT regime FROM market_regime WHERE date = ?", (target_date,)
        ).fetchone()
        regime = regime_row[0] if regime_row else None

        mcap_df = pd.read_sql_query("SELECT symbol, market_cap_m FROM stock_market_cap", conn)
        mcap = dict(zip(mcap_df["symbol"], mcap_df["market_cap_m"]))

        active_df = pd.read_sql_query(
            "SELECT symbol FROM active_stocks_on_date WHERE trading_date = ?",
            conn,
            params=(target_date,),
        )
        if active_df.empty:
            logger.warning(
                "active_stocks_on_date has no rows for %s — "
                "falling back to full stock_metadata universe", target_date
            )
            active_df = pd.read_sql_query(
                "SELECT symbol FROM stock_metadata WHERE is_active = 1",
                conn,
            )
        active_symbols = set(active_df["symbol"])

        # ------------------------------------------------------------------
        # Step 5 — pre-compute per-stock indicators
        # ------------------------------------------------------------------
        prices = prices.sort_values(["symbol", "date"])

        prices["ema20"] = prices.groupby("symbol")["close"].transform(
            lambda x: x.ewm(span=20, adjust=False).mean()
        )
        prices["prev_close"] = prices.groupby("symbol")["close"].shift(1)
        prices["daily_return"] = (prices["close"] - prices["prev_close"]) / prices["prev_close"]
        prices["close_20d_ago"] = prices.groupby("symbol")["close"].shift(20)
        prices["close_50d_ago"] = prices.groupby("symbol")["close"].shift(50)
        prices["return_20d"] = (prices["close"] - prices["close_20d_ago"]) / prices["close_20d_ago"]
        prices["return_50d"] = (prices["close"] - prices["close_50d_ago"]) / prices["close_50d_ago"]
        prices["vol_20d_avg"] = prices.groupby("symbol")["volume"].transform(
            lambda x: x.rolling(20, min_periods=5).mean()
        )

        # KSE-100 returns for target date
        kse100 = kse100.sort_values("date")
        kse100["kse_20d_ago"] = kse100["kse_close"].shift(20)
        kse100["kse_50d_ago"] = kse100["kse_close"].shift(50)
        kse100["kse_return_20d"] = (
            (kse100["kse_close"] - kse100["kse_20d_ago"]) / kse100["kse_20d_ago"]
        )
        kse100["kse_return_50d"] = (
            (kse100["kse_close"] - kse100["kse_50d_ago"]) / kse100["kse_50d_ago"]
        )
        kse_row = kse100[kse100["date"] == target_date]
        kse_ret_20 = float(kse_row["kse_return_20d"].iloc[0]) if not kse_row.empty else np.nan
        kse_ret_50 = float(kse_row["kse_return_50d"].iloc[0]) if not kse_row.empty else np.nan

        # ------------------------------------------------------------------
        # Step 6 — filter to target date
        # ------------------------------------------------------------------
        day_data = prices[prices["date"] == target_date].copy()

        # ------------------------------------------------------------------
        # Step 7 — get previous rs_rank for each sector
        # ------------------------------------------------------------------
        prev_rank_rows = conn.execute(
            """
            SELECT sector, rs_rank FROM sector_signals
            WHERE date = (
                SELECT MAX(date) FROM sector_signals WHERE date < ?
            )
            """,
            (target_date,),
        ).fetchall()
        prev_ranks = {r[0]: r[1] for r in prev_rank_rows}

        # 20-day max rs_score_20 per sector — for sector_rs_new_high flag
        rs_history_rows = conn.execute(
            """
            SELECT sector, MAX(rs_score_20)
            FROM sector_signals
            WHERE date < ? AND date >= DATE(?, '-30 days')
            GROUP BY sector
            """,
            (target_date, target_date),
        ).fetchall()
        sector_rs_20d_max = {r[0]: r[1] for r in rs_history_rows}

        # ------------------------------------------------------------------
        # Step 7b — sector price index time series → EMA50 → stage
        # ------------------------------------------------------------------
        _ensure_sector_stage_columns(conn)

        sector_stage_data: dict = {}
        _all_sectors_ts = sorted(prices["sector"].dropna().unique())

        for _sec in _all_sectors_ts:
            _sec_hist = prices[prices["sector"] == _sec].copy()
            _syms = _sec_hist["symbol"].unique()

            # Market-cap weights — fixed (today's weights applied to whole series)
            _w = pd.Series({s: mcap.get(s, 0) for s in _syms})
            _w_total = _w.sum()
            if _w_total <= 0:
                _w = pd.Series({s: 1.0 / len(_syms) for s in _syms})
            else:
                _w = _w / _w_total

            # Pivot: rows=date cols=symbol, weighted sum → sector index
            _piv = _sec_hist.pivot_table(index="date", columns="symbol", values="close")
            _piv = _piv.ffill()
            _w_aligned = _w.reindex(_piv.columns).fillna(0)
            _w_aligned = _w_aligned / _w_aligned.sum()
            _idx = (_piv * _w_aligned).sum(axis=1)

            # Normalise to base=100 at window start
            if len(_idx) < 5 or _idx.iloc[0] == 0:
                sector_stage_data[_sec] = {
                    "sector_ema50": None, "sector_above_ema": None,
                    "sector_ema_slope": None, "sector_stage": None,
                    "sector_pivot_dist_pct": None,
                }
                continue
            _idx = _idx / _idx.iloc[0] * 100

            # EMA50
            _ema50 = _idx.ewm(span=50, adjust=False).mean()

            _cur_idx = _idx.get(target_date)
            _cur_ema = _ema50.get(target_date)

            if _cur_idx is None or _cur_ema is None or _cur_ema == 0:
                sector_stage_data[_sec] = {
                    "sector_ema50": None, "sector_above_ema": None,
                    "sector_ema_slope": None, "sector_stage": None,
                    "sector_pivot_dist_pct": None,
                }
                continue

            _above = bool(_cur_idx > _cur_ema)

            # Slope: 5-bar change in EMA50
            _ema_vals = _ema50.dropna()
            if len(_ema_vals) >= 6:
                _slope = float(_ema_vals.iloc[-1] - _ema_vals.iloc[-6])
                _slope_pos = _slope > 0
            else:
                _slope = None
                _slope_pos = None

            # Weinstein 4-stage from two booleans
            if _slope_pos is not None:
                if _above and _slope_pos:
                    _stage = "Stage 2"
                elif _above and not _slope_pos:
                    _stage = "Stage 3"
                elif not _above and not _slope_pos:
                    _stage = "Stage 4"
                else:
                    _stage = "Stage 1"
            else:
                _stage = None

            # Distance from recent 20-day pivot high (breakout proximity)
            _recent_high = float(_idx.iloc[-20:].max()) if len(_idx) >= 20 else float(_idx.max())
            _pivot_dist = (_recent_high - float(_cur_idx)) / float(_cur_idx) * 100

            sector_stage_data[_sec] = {
                "sector_ema50":        round(float(_cur_ema), 2),
                "sector_above_ema":    1 if _above else 0,
                "sector_ema_slope":    round(float(_slope), 4) if _slope is not None else None,
                "sector_stage":        _stage,
                "sector_pivot_dist_pct": round(_pivot_dist, 2),
            }

        # ------------------------------------------------------------------
        # Step 8 — compute sector metrics
        # ------------------------------------------------------------------
        sectors = sorted(day_data["sector"].unique())
        sector_rs_scores = {}

        for sector in sectors:
            sector_day = day_data[
                (day_data["sector"] == sector) &
                (day_data["symbol"].isin(active_symbols))
            ].copy()

            if len(sector_day) < 2:
                continue

            # Market-cap weights, equal-weight fallback for NULLs
            weights = sector_day["symbol"].map(mcap)
            if weights.isna().all():
                weights = pd.Series(
                    [1.0 / len(sector_day)] * len(sector_day),
                    index=sector_day.index,
                )
            else:
                weights = weights.fillna(weights.mean())
                total = weights.sum()
                weights = (
                    weights / total
                    if total > 0
                    else pd.Series(
                        [1.0 / len(sector_day)] * len(sector_day),
                        index=sector_day.index,
                    )
                )

            # RS score 20d
            valid_20 = sector_day["return_20d"].notna()
            if valid_20.sum() >= 2:
                w20 = weights[valid_20]
                w20 = w20 / w20.sum()
                sector_ret_20 = (sector_day.loc[valid_20, "return_20d"] * w20).sum()
                rs_20 = (sector_ret_20 - kse_ret_20) * 100 if not np.isnan(kse_ret_20) else np.nan
            else:
                rs_20 = np.nan

            # RS score 50d
            valid_50 = sector_day["return_50d"].notna()
            if valid_50.sum() >= 2:
                w50 = weights[valid_50]
                w50 = w50 / w50.sum()
                sector_ret_50 = (sector_day.loc[valid_50, "return_50d"] * w50).sum()
                rs_50 = (sector_ret_50 - kse_ret_50) * 100 if not np.isnan(kse_ret_50) else np.nan
            else:
                rs_50 = np.nan

            # Breadth: % stocks above EMA-20
            above_ema = (sector_day["close"] > sector_day["ema20"]).sum()
            breadth = (above_ema / len(sector_day)) * 100

            # Adv/dec ratio
            advancers = (sector_day["daily_return"] > 0).sum()
            decliners = (sector_day["daily_return"] < 0).sum()
            adr = (advancers / decliners) if decliners > 0 else np.nan

            # Volume ratio
            valid_vol = sector_day["vol_20d_avg"].notna() & (sector_day["vol_20d_avg"] > 0)
            if valid_vol.sum() >= 2:
                vol_today = sector_day.loc[valid_vol, "volume"].mean()
                vol_avg = sector_day.loc[valid_vol, "vol_20d_avg"].mean()
                vol_ratio = vol_today / vol_avg if vol_avg > 0 else np.nan
            else:
                vol_ratio = np.nan

            sector_rs_scores[sector] = {
                "rs_score_20": rs_20,
                "rs_score_50": rs_50,
                "breadth_score": breadth,
                "adv_dec_ratio": adr,
                "vol_ratio": vol_ratio,
            }

        # Rank by rs_score_20 (1 = strongest)
        valid_sectors = {
            s: v for s, v in sector_rs_scores.items() if not np.isnan(v["rs_score_20"])
        }
        ranked = sorted(valid_sectors, key=lambda s: valid_sectors[s]["rs_score_20"], reverse=True)
        ranks = {s: i + 1 for i, s in enumerate(ranked)}

        # Build rows list
        rows = []
        for sector, vals in sector_rs_scores.items():
            rs_rank = ranks.get(sector)
            rs_rank_prev = prev_ranks.get(sector)

            rs_infl = 0
            if (
                rs_rank is not None
                and rs_rank_prev is not None
                and rs_rank < rs_rank_prev
                and not np.isnan(vals["rs_score_20"])
                and vals["rs_score_20"] > 0
            ):
                rs_infl = 1

            # sector_rs_new_high: today's rs_score_20 >= 20-day max (RS at new relative high)
            rs_new_high = 0
            rs_today = vals["rs_score_20"]
            if not np.isnan(rs_today):
                hist_max = sector_rs_20d_max.get(sector)
                if hist_max is None or float(rs_today) >= float(hist_max):
                    rs_new_high = 1

            rows.append(
                {
                    "date": target_date,
                    "sector": sector,
                    "rs_score_20": None if np.isnan(vals["rs_score_20"]) else round(float(vals["rs_score_20"]), 4),
                    "rs_score_50": None if np.isnan(vals["rs_score_50"]) else round(float(vals["rs_score_50"]), 4),
                    "rs_rank": rs_rank,
                    "rs_rank_prev": rs_rank_prev,
                    "breadth_score": round(float(vals["breadth_score"]), 2),
                    "adv_dec_ratio": None if np.isnan(vals["adv_dec_ratio"]) else round(float(vals["adv_dec_ratio"]), 4),
                    "vol_ratio": None if np.isnan(vals["vol_ratio"]) else round(float(vals["vol_ratio"]), 4),
                    "rs_inflection": rs_infl,
                    "rs_new_high": rs_new_high,
                    "regime": regime,
                    "composite_score": None,  # filled in Step 9
                    **sector_stage_data.get(sector, {
                        "sector_ema50": None, "sector_above_ema": None,
                        "sector_ema_slope": None, "sector_stage": None,
                        "sector_pivot_dist_pct": None,
                    }),
                }
            )

        if not rows:
            logger.warning("Sector signals hook: no sector rows computed for %s.", target_date)
            return

        # ------------------------------------------------------------------
        # Step 9 — compute composite_score (min-max within this date)
        # ------------------------------------------------------------------
        result_df = pd.DataFrame(rows)

        result_df["rs_norm"] = _minmax_norm(result_df["rs_score_20"].fillna(result_df["rs_score_20"].mean()))
        result_df["br_norm"] = _minmax_norm(result_df["breadth_score"])
        result_df["vr_norm"] = _minmax_norm(result_df["vol_ratio"].fillna(result_df["vol_ratio"].mean()))

        result_df["composite_score"] = (
            result_df["rs_norm"] * 0.5
            + result_df["br_norm"] * 0.3
            + result_df["vr_norm"] * 0.2
        ).round(4)

        # ------------------------------------------------------------------
        # Step 10 — INSERT OR REPLACE all sector rows
        # ------------------------------------------------------------------
        cur = conn.cursor()
        rows_written = 0
        for _, r in result_df.iterrows():
            cur.execute(
                """
                INSERT OR REPLACE INTO sector_signals
                    (date, sector, rs_score_20, rs_score_50, rs_rank, rs_rank_prev,
                     breadth_score, adv_dec_ratio, vol_ratio, rs_inflection,
                     regime, composite_score,
                     sector_ema50, sector_above_ema, sector_ema_slope,
                     sector_stage, sector_pivot_dist_pct, sector_rs_new_high)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["date"],
                    r["sector"],
                    r["rs_score_20"],
                    r["rs_score_50"],
                    r["rs_rank"],
                    r["rs_rank_prev"],
                    r["breadth_score"],
                    r["adv_dec_ratio"],
                    r["vol_ratio"],
                    int(r["rs_inflection"]),
                    r["regime"],
                    float(r["composite_score"]),
                    r.get("sector_ema50"),
                    r.get("sector_above_ema"),
                    r.get("sector_ema_slope"),
                    r.get("sector_stage"),
                    r.get("sector_pivot_dist_pct"),
                    int(r.get("rs_new_high", 0)),
                ),
            )
            rows_written += 1
        conn.commit()

        # ------------------------------------------------------------------
        # Step 11 — log result
        # ------------------------------------------------------------------
        logger.info(
            "Sector signals appended: %s — %d sectors written", target_date, rows_written
        )

        # ------------------------------------------------------------------
        # Step 12 — enrich sector_signals rows with flow signal data
        # ------------------------------------------------------------------
        try:
            compute_flow_signals(conn, target_date)
        except Exception as _fe:
            logger.warning("compute_flow_signals failed for %s: %s", target_date, _fe)

    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# FLOW SIGNAL INTEGRATION
# Reads market_flows → computes smart/retail rolling nets → writes to sector_signals
# Smart Money  : Foreign Corporates (FIPI) | Banks/DFI, NBFC, Insurance (LIPI)
# Not Smart    : Foreign Individuals, Overseas Pakistanis (FIPI) | Individuals,
#                Broker Proprietary Trading (LIPI)
# Unknown      : Mutual Funds, Companies, Other Organizations (LIPI) — tracked,
#                not weighted in signals until patterns are established
# ═══════════════════════════════════════════════════════════════════════════════

_FLOW_TO_PSX = {
    "CEMENT":                   "CEMENT",
    "FERTILIZER":               "FERTILIZER",
    "FERTILISERS":              "FERTILIZER",
    "FERTILIZERS":              "FERTILIZER",
    "FOOD":                     "FOOD & PERSONAL CARE PRODUCTS",
    "FOOD & PERSONAL CARE":     "FOOD & PERSONAL CARE PRODUCTS",
    "FOOD AND PERSONAL CARE":   "FOOD & PERSONAL CARE PRODUCTS",
    "E&PS":                     "OIL & GAS EXPLORATION COMPANIES",
    "E&P":                      "OIL & GAS EXPLORATION COMPANIES",
    "E & PS":                   "OIL & GAS EXPLORATION COMPANIES",
    "OIL & GAS EXPLORATION":    "OIL & GAS EXPLORATION COMPANIES",
    "OMCS":                     "OIL & GAS MARKETING COMPANIES",
    "OMC":                      "OIL & GAS MARKETING COMPANIES",
    "OIL MARKETING":            "OIL & GAS MARKETING COMPANIES",
    "OIL & GAS MARKETING":      "OIL & GAS MARKETING COMPANIES",
    "IPPS":                     "POWER GENERATION & DISTRIBUTION",
    "IPP":                      "POWER GENERATION & DISTRIBUTION",
    "POWER":                    "POWER GENERATION & DISTRIBUTION",
    "POWER GEN":                "POWER GENERATION & DISTRIBUTION",
    "BANKS":                    "COMMERCIAL BANKS",
    "BANK":                     "COMMERCIAL BANKS",
    "COMM. BANKS":              "COMMERCIAL BANKS",
    "TECH":                     "TECHNOLOGY & COMMUNICATION",
    "TECHNOLOGY":               "TECHNOLOGY & COMMUNICATION",
    "TECH. & COMM.":            "TECHNOLOGY & COMMUNICATION",
    "TEXTILE":                  "TEXTILE COMPOSITE",
    "TEXTILE COMP.":            "TEXTILE COMPOSITE",
    "TEXTILE COMPOSITE":        "TEXTILE COMPOSITE",
    "AUTO":                     "AUTOMOBILE ASSEMBLER",
    "AUTOMOBILE":               "AUTOMOBILE ASSEMBLER",
    "PHARMA":                   "PHARMACEUTICALS",
    "STEEL":                    "STEEL & ALLIED PRODUCTS",
    "CHEMICALS":                "CHEMICALS",
}

# Smart money — institutional capital with informational edge
_FLOW_SMART = {
    "FOREIGN CORPORATES",       # FIPI — informed foreign institutional
    "BANKS / DFI",              # LIPI — principal capital, balance sheet buyers
    "NBFC",                     # LIPI — principal capital
    "INSURANCE COMPANIES",      # LIPI — long-horizon institutional
}

# Retail / noise — high volume, not informationally driven
_FLOW_RETAIL = {
    "FOREIGN INDIVIDUALS",      # FIPI — diaspora/speculative
    "OVERSEAS PAKISTANI",       # FIPI — diaspora/sentiment
    "INDIVIDUALS",              # LIPI — retail
    "BROKER PROPRIETARY TRADING",  # LIPI — short-term, noise
}

# Unknown — tracked raw, not classified until patterns emerge
_FLOW_UNKNOWN = {
    "MUTUAL FUNDS",
    "COMPANIES",
    "OTHER ORGANIZATIONS",
}


def compute_flow_signals(conn, date_str: str) -> None:
    """
    Reads market_flows for all REGULAR market dates up to date_str.
    Computes 5d and 20d rolling smart-money and retail nets per sector.
    Writes flow_smart_net_5d, flow_smart_net_20d, flow_retail_net_5d,
    flow_retail_net_20d, flow_direction into sector_signals for date_str.

    Safe to call when market_flows is empty — silently returns, no crash.
    Skips sectors that cannot be mapped to a PSX sector name.
    """
    try:
        df = pd.read_sql("""
            SELECT date, sector, client_type, net_value
            FROM market_flows
            WHERE market_type = 'REGULAR'
              AND date <= ?
            ORDER BY date
        """, conn, params=(date_str,))
    except Exception:
        return  # market_flows not yet populated — silent skip

    if df.empty:
        return

    # Normalise and map sector names
    df["sector_upper"] = df["sector"].str.strip().str.upper()
    df["psx_sector"]   = df["sector_upper"].map(_FLOW_TO_PSX)
    df = df.dropna(subset=["psx_sector"])

    if df.empty:
        return

    # Classify client types
    df["client_upper"] = df["client_type"].str.strip().str.upper()
    df["bucket"] = df["client_upper"].apply(
        lambda c: "SMART"   if c in _FLOW_SMART
             else "RETAIL"  if c in _FLOW_RETAIL
             else "UNKNOWN"
    )

    # Daily net per sector per bucket
    daily = (
        df.groupby(["date", "psx_sector", "bucket"])["net_value"]
        .sum()
        .reset_index()
    )
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values(["psx_sector", "bucket", "date"])

    # Pivot so each bucket is a column
    pivot = daily.pivot_table(
        index=["date", "psx_sector"],
        columns="bucket",
        values="net_value",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    pivot.columns.name = None
    for col in ["SMART", "RETAIL", "UNKNOWN"]:
        if col not in pivot.columns:
            pivot[col] = 0.0

    pivot = pivot.sort_values(["psx_sector", "date"])

    # Rolling 5d and 20d per sector
    for bucket, col_5d, col_20d in [
        ("SMART",  "flow_smart_net_5d",  "flow_smart_net_20d"),
        ("RETAIL", "flow_retail_net_5d", "flow_retail_net_20d"),
    ]:
        pivot[col_5d]  = (pivot.groupby("psx_sector")[bucket]
                               .transform(lambda x: x.rolling(5,  min_periods=1).sum()))
        pivot[col_20d] = (pivot.groupby("psx_sector")[bucket]
                               .transform(lambda x: x.rolling(20, min_periods=1).sum()))

    # Flow direction — based on smart money only
    def _direction(row):
        s5  = row["flow_smart_net_5d"]
        s20 = row["flow_smart_net_20d"]
        if s5 > 0 and s20 > 0:
            return "ACCUMULATING"
        elif s5 < 0 and s20 < 0:
            return "DISTRIBUTING"
        elif s5 > 0 and s20 < 0:
            return "RECOVERING"
        elif s5 < 0 and s20 > 0:
            return "FADING"
        else:
            return "NEUTRAL"

    pivot["flow_direction"] = pivot.apply(_direction, axis=1)

    # Write only today's rows into sector_signals
    pivot["date_str"] = pivot["date"].dt.date.astype(str)
    today_rows = pivot[pivot["date_str"] == date_str]

    for _, row in today_rows.iterrows():
        conn.execute("""
            UPDATE sector_signals
            SET flow_smart_net_5d   = ?,
                flow_smart_net_20d  = ?,
                flow_retail_net_5d  = ?,
                flow_retail_net_20d = ?,
                flow_direction      = ?
            WHERE date   = ?
              AND sector = ?
        """, (
            row["flow_smart_net_5d"],
            row["flow_smart_net_20d"],
            row["flow_retail_net_5d"],
            row["flow_retail_net_20d"],
            row["flow_direction"],
            date_str,
            row["psx_sector"],
        ))
    conn.commit()
