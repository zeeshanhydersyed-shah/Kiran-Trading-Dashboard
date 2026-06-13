"""
Daily sector signals hook for the PSX pipeline.

append_latest_sector_signals() is called from cmd_update() in main.py after
the regime hook. It pulls 60 trading days of warmup data, recomputes per-stock
indicators, aggregates to sector level, and upserts a row per sector for the
latest scraped date into sector_signals.
"""

import logging
import sqlite3

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DB = "psx_data.db"
WARMUP = 60  # trading days of price history for indicator warm-up


def _minmax_norm(series: pd.Series) -> pd.Series:
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - mn) / (mx - mn)


def append_latest_sector_signals() -> None:
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
                    "regime": regime,
                    "composite_score": None,  # filled in Step 9
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
                     regime, composite_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    finally:
        conn.close()
