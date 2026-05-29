"""
stm_sr_integration.py
─────────────────────
S/R Zone enrichment layer for the STM Screener.

PURPOSE
    After the STM screener filters symbols down to its short-list, this module
    runs per-symbol S/R zone analysis and answers one specific question:
        "Is this stock building a narrow range at or under a resistance zone?"

    That condition — tight range + resistance overhead — is the coiling signal.
    Without zone context a tight range is just a quiet stock. With it, it's
    compressed energy at a known level.

WHAT IT ADDS TO THE STM TABLE
    Column          Meaning
    ──────────────  ────────────────────────────────────────────────────────
    dist_to_r_pct   % distance from current close to the nearest resistance
                    zone floor (zone.low).  0 means price is AT the zone.
                    Negative means price is INSIDE the zone.
    r_zone_strength Zone strength 0-100 (pivots + recency-weighted touches
                    + volume confirmation).
    r_zone_touches  How many times price has tested that zone.
    in_r_zone       True when price is currently sitting inside the zone
                    body — the most powerful coil position.
    coiling         True when: 5d range ≤ 5%  AND  dist to resistance ≤ 5%
                    AND  zone strength ≥ 35.  Flags the "building pressure"
                    condition you described.

HOW TO USE IN dashboard.py
    See the "DASHBOARD INTEGRATION" section at the bottom of this file for
    the exact lines to add/change. Nothing in the existing screener logic
    is removed or broken — we only ADD columns to the result df and
    display them.

APPLYING TO OTHER PAGES LATER
    Any page that has a DataFrame with ['symbol', 'latest_close',
    'range_5d_pct'] can call enrich_stm_with_sr_zones().
    Explorer, Support Reversals, Setups — all candidates.
"""

import pandas as pd
import numpy as np
from support_resistance_channels_improved import ImprovedSupportResistanceChannels


# ── PSX-tuned SR analyzer ─────────────────────────────────────────────────────
# volume_filter=False  → PSX mid/small caps are often thinly traded; the volume
#                        gate at 70% of 20-bar avg wipes out real pivots on those
#                        symbols. Turn it off here; volume column still used for
#                        the strength score weighting.
# base_channel_width_pct=4.0 → tighter than the 5% default; PSX stocks can
#                        move fast so we want zones to be meaningful, not wide.
# loopback_period=250  → ~1 year of trading days, catches major S/R without
#                        going so far back that ancient levels pollute the result.
# max_channels=8       → more zones per symbol gives a better chance of finding
#                        the nearest one above current price.

_SR = ImprovedSupportResistanceChannels(
    pivot_period=10,
    base_channel_width_pct=4.0,
    atr_period=14,
    trend_period=50,
    max_channels=8,
    min_strength=1,
    loopback_period=250,
    volume_filter=False,
    merge_nearby_zones=True,
    adaptive_pivots=True,
)

# Coiling thresholds — easy to tune without touching logic
COIL_MAX_RANGE_5D_PCT   = 5.0   # 5-day range must be ≤ this
COIL_MAX_DIST_TO_R_PCT  = 5.0   # price must be within this % of resistance floor
COIL_MIN_ZONE_STRENGTH  = 35.0  # zone must have at least this strength (0-100)
MIN_BARS_FOR_SR         = 60    # skip S/R if symbol has fewer than this many bars


# ── Core helpers ──────────────────────────────────────────────────────────────

def _get_nearest_resistance(zones, current_price: float):
    """
    Return the zone whose floor (zone.low) is closest to and strictly above
    the current price — i.e. the nearest overhead resistance.

    Returns (zone, dist_pct) where dist_pct = (zone.low - price) / price * 100
    Returns (None, None) if no zone exists above current price.

    NOTE: the SR library's classify_zone() uses inverted naming:
        type='support'    → zone is ABOVE current price (overhead = real resistance)
        type='resistance' → zone is BELOW current price (floor = real support)
    We ignore zone.type here and use positional logic instead to avoid
    that confusion.
    """
    overhead = [z for z in zones if z.low > current_price]
    if not overhead:
        return None, None
    nearest = min(overhead, key=lambda z: z.low - current_price)
    dist_pct = (nearest.low - current_price) / current_price * 100
    # Round to 1 decimal — avoids a 0.00 display when zone floor is extremely close
    return nearest, round(dist_pct, 1)


def _empty_sr_row() -> dict:
    """Fallback row when S/R analysis cannot be computed."""
    return {
        'dist_to_r_pct':   None,
        'r_zone_strength': None,
        'r_zone_touches':  None,
        'in_r_zone':       False,
        'coiling':         False,
    }


# ── Main enrichment function ──────────────────────────────────────────────────

def enrich_stm_with_sr_zones(result: pd.DataFrame, prices_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich an STM result DataFrame with S/R zone context.

    Parameters
    ----------
    result : pd.DataFrame
        Output of _run_stm_screener() — the filtered LONG (or SHORT) candidates.
        Must contain columns: symbol, latest_close, range_5d_pct.
    prices_raw : pd.DataFrame
        Full OHLCV price history — pass load_stm_prices() from dashboard.py.
        Passed explicitly to avoid a circular import (dashboard importing
        stm_sr_integration which re-imports dashboard).

    Returns
    -------
    pd.DataFrame
        Same DataFrame with 5 new columns appended:
        dist_to_r_pct, r_zone_strength, r_zone_touches, in_r_zone, coiling.

    Notes
    -----
    - Runs S/R analysis only on symbols that passed STM filters (typically
      5-25 stocks), so performance impact is negligible.
    - Errors on individual symbols are silently caught and filled with nulls
      so the rest of the table still renders.
    """
    if result.empty:
        return result

    if prices_raw.empty:
        return result

    records = []

    for _, row in result.iterrows():
        sym           = row['symbol']
        current_price = float(row['latest_close'])
        range_5d      = float(row.get('range_5d_pct', 99.0))

        # Slice this symbol's full price history
        sym_df = (
            prices_raw[prices_raw['symbol'] == sym]
            .sort_values('date')
            .reset_index(drop=True)
        )

        if len(sym_df) < MIN_BARS_FOR_SR:
            records.append(_empty_sr_row())
            continue

        # SR library requires 'open' — fall back to close if column is absent
        # (local SQLite prices table doesn't store open; Supabase may or may not)
        if 'open' not in sym_df.columns:
            sym_df = sym_df.copy()
            sym_df['open'] = sym_df['close']

        try:
            zones = _SR.calculate_zones(sym_df)
        except Exception as e:
            import traceback
            print(f"[SR] {sym}: zone calc failed — {e}\n{traceback.format_exc()}")
            records.append(_empty_sr_row())
            continue

        if not zones:
            records.append(_empty_sr_row())
            continue

        # Is price currently inside any zone? (strongest coil position)
        # Use positional check — don't rely on z.type (see _get_nearest_resistance note)
        in_r_zone = any(z.low <= current_price <= z.high for z in zones)

        if in_r_zone:
            # Price is sitting inside a zone — "In Zone" column covers this.
            # dist_to_r_pct is intentionally None (shows as — in the table).
            active = next(
                (z for z in zones if z.low <= current_price <= z.high),
                None
            )
            dist_pct = None  # Already inside zone; no meaningful distance to show
            zone_str = round(active.strength, 1) if active else None
            zone_tch = active.touches if active else None
            coiling   = range_5d <= COIL_MAX_RANGE_5D_PCT  # In zone + tight = strong coil
        else:
            nearest, dist_pct = _get_nearest_resistance(zones, current_price)

            if nearest is None:
                # Price is above all detected zones — no resistance overhead
                records.append(_empty_sr_row())
                continue

            zone_str = round(nearest.strength, 1)
            zone_tch = nearest.touches
            coiling  = (
                range_5d  <= COIL_MAX_RANGE_5D_PCT  and
                dist_pct  <= COIL_MAX_DIST_TO_R_PCT  and
                zone_str  >= COIL_MIN_ZONE_STRENGTH
            )

        records.append({
            'dist_to_r_pct':   dist_pct,
            'r_zone_strength': zone_str,
            'r_zone_touches':  zone_tch,
            'in_r_zone':       in_r_zone,
            'coiling':         coiling,
        })

    sr_df = pd.DataFrame(records, index=result.index)
    return pd.concat([result, sr_df], axis=1)


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD INTEGRATION — exact changes for dashboard.py
# ══════════════════════════════════════════════════════════════════════════════
#
# STEP 1 — Add import near the top of dashboard.py (after other local imports):
#
#     from stm_sr_integration import enrich_stm_with_sr_zones
#
#
# STEP 2 — In the LONG tab block (around line 4224), after:
#
#     result  = stm["result"]
#     kse_30d = stm["kse_30d"]
#     n_passed = len(result)
#
#     # Auto-save LONG picks
#     _stm_key = f"stm_saved_{id(result)}"
#     if not st.session_state.get(_stm_key) and not result.empty:
#         ...
#         auto_save_stm_picks(picks)
#         st.session_state[_stm_key] = True
#
#   ADD THESE LINES (after auto-save, before the metrics row):
#
#     # ── Enrich with S/R zone context ──────────────────────────────────────
#     if not result.empty:
#         with st.spinner("Analysing S/R zones…"):
#             result = enrich_stm_with_sr_zones(result, load_stm_prices())
#
#
# STEP 3 — In the qual_scores loop, change the 4-point score to 5-point:
#
#   BEFORE:
#     qs = int(
#         (row.get("rs", 0.0) > 5.0)
#       + (row.get("range_5d_pct", 99.) <= 5.0)
#       + (0 < row.get("dist_21ma_pct", 99.) <= 5.0)
#       + (row.get("risk_pct", 99.) <= 3.0)
#     )
#
#   AFTER:
#     qs = int(
#         (row.get("rs", 0.0) > 5.0)
#       + (row.get("range_5d_pct", 99.) <= 5.0)
#       + (0 < row.get("dist_21ma_pct", 99.) <= 5.0)
#       + (row.get("risk_pct", 99.) <= 3.0)
#       + bool(row.get("coiling", False))        # ← NEW: coiling at resistance
#     )
#
#
# STEP 4 — In the disp column selection, add the new columns:
#
#   BEFORE:
#     disp = result[[
#         "symbol", "sector", "as_of_date", "latest_close",
#         "rs", "perf_30d", "range_5d_pct", "avg_vol_10d",
#         "ma21", "ma50", "dist_21ma_pct",
#         "stop_loss", "risk_pct", "target_2r", "tradeable",
#     ]].copy()
#
#   AFTER:
#     _has_sr = "dist_to_r_pct" in result.columns
#     _sr_cols = ["dist_to_r_pct", "r_zone_strength", "in_r_zone"] if _has_sr else []
#     disp = result[[
#         "symbol", "sector", "as_of_date", "latest_close",
#         "rs", "perf_30d", "range_5d_pct", "avg_vol_10d",
#         "ma21", "ma50", "dist_21ma_pct",
#         "stop_loss", "risk_pct", "target_2r", "tradeable",
#     ] + _sr_cols].copy()
#
#
# STEP 5 — Update the column rename list to match:
#
#   BEFORE:
#     disp.columns = ["Symbol","Sector","As Of","Close","RS %","30d %","5d Rng %",
#                     "Vol(K)","21MA","50MA","Dist21MA%","SL","Risk%","T2R","Trade","Score","ML%"]
#
#   AFTER:
#     _base_cols = ["Symbol","Sector","As Of","Close","RS %","30d %","5d Rng %",
#                   "Vol(K)","21MA","50MA","Dist21MA%","SL","Risk%","T2R","Trade","Score","ML%"]
#     _sr_disp_cols = ["Dist R%","R Str","In Zone"] if _has_sr else []
#     disp.columns = _base_cols + _sr_disp_cols
#
#
# STEP 6 — Update the caption to mention the new Score range and columns:
#
#   BEFORE:
#     st.caption("SL = 1% below day low · T2R = 2R target · ML% = LightGBM win probability · Picks auto-saved to Trade Log")
#
#   AFTER:
#     st.caption(
#         "SL = 1% below day low · T2R = 2R target · ML% = LightGBM win probability · "
#         "Score 0-5 (5th pt = Coiling at resistance) · "
#         "Dist R% = % to nearest resistance zone · R Str = zone strength 0-100 · "
#         "Picks auto-saved to Trade Log"
#     )
#
#
# STEP 7 — Add a coiling highlight section below the table:
#
#     coil_rows = result[result.get("coiling", pd.Series(False, index=result.index))]
#     if not coil_rows.empty:
#         st.markdown("#### 🔥 Coiling at Resistance")
#         st.caption(
#             "These symbols have a tight 5-day range building within 5% of a confirmed "
#             "resistance zone. Highest-conviction STM setups — watch for volume expansion."
#         )
#         for _, r in coil_rows.iterrows():
#             in_z   = "🔴 Inside zone" if r.get("in_r_zone") else f"{r.get('dist_to_r_pct', '?'):.1f}% below"
#             st.markdown(
#                 f"**{r['symbol']}** — Close: {r['latest_close']:.2f} · "
#                 f"RS: {r['rs']:+.1f}% · Zone: {in_z} · "
#                 f"Zone Str: {r.get('r_zone_strength', '—')} · Risk: {r['risk_pct']:.1f}%"
#             )
#
# ══════════════════════════════════════════════════════════════════════════════
