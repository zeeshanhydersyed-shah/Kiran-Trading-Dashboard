# Factor Catalog — PSX Quantitative Research Platform

> **Purpose:** Complete reference for every factor available for research. One row per factor. Populated from the system audit.  
> **Related:** [Factor_Taxonomy.md](Factor_Taxonomy.md) · [Data_Quality_Policy.md](Data_Quality_Policy.md) · [Outcome_Definitions.md](Outcome_Definitions.md)  
> **Note:** Predictive Value is set to `Unknown` until a study completes. Updated by referencing the completing study (S-xxx).

---

## Stock-Level Factors (from `stock_signals`)

| ID | Factor Name | Column | Source Table | Formula (Summary) | Type | Predictive Value | Study |
|---|---|---|---|---|---|---|---|
| F-01 | RS Score 20d | `rs_score_20` | `stock_signals` | Stock 20d return% − KSE-100 20d return% | Continuous | Unknown | — |
| F-02 | RS Score 50d | `rs_score_50` | `stock_signals` | Stock 50d return% − KSE-100 50d return% | Continuous | Unknown | — |
| F-03 | RS Rank (Global) | `rs_rank` | `stock_signals` | Ordinal rank by `rs_score_20` across universe (1 = best) | Ordinal | Unknown | — |
| F-04 | RS Rank Previous | `rs_rank_prev` | `stock_signals` | Prior day's `rs_rank` | Ordinal | — | — |
| F-05 | Rank Change | `rank_change` | `stock_signals` | `rs_rank_prev − rs_rank` (positive = improved) | Continuous | Unknown | — |
| F-06 | Sector RS Rank | `sector_rs_rank` | `stock_signals` | Ordinal rank by `rs_score_20` within sector (1 = best in sector) | Ordinal | Unknown | — |
| F-07 | Base Tightness (BBW%) | `base_tightness` | `stock_signals` | `4 × stddev(close_20d) / mean(close_20d) × 100` | Continuous | Unknown | — |
| F-08 | Volume Contraction | `vol_contraction` | `stock_signals` | `avg_vol_10d / avg_vol_50d × 100` | Continuous | Unknown | — |
| F-09 | Average Volume 10d | `avg_vol_10d` | `stock_signals` | Mean daily volume over 10 trading days | Continuous | Unknown | — |
| F-10 | Pivot High | `pivot_high` | `stock_signals` | Most recent confirmed pivot high (10-bar left/right window) | Price level | — | — |
| F-11 | Pivot Distance % | `pivot_distance_pct` | `stock_signals` | `(pivot_high − close) / pivot_high × 100` | Continuous | Unknown | — |
| F-12 | BOS Flag | `bos_flag` | `stock_signals` | 1 if `close > pivot_high` (pivot_distance_pct < 0) | Binary | Unknown | — |
| F-13 | Stage 2 Bull | `stage2_bull` | `stock_signals` | 1 if `close > EMA20 > EMA50 > EMA200` | Binary | Unknown | — |
| F-14 | Close Above EMA50 | `close_above_ema50` | `stock_signals` | 1 if `close > EMA(50)` | Binary | Unknown | — |
| F-15 | EMA50 Slope Positive | `ema50_slope_pos` | `stock_signals` | 1 if `EMA50(today) > EMA50(5d ago)` | Binary | Unknown | — |
| F-16 | Close Above EMA150 | `close_above_ema150` | `stock_signals` | 1 if `close > EMA(150)` | Binary | Unknown | — |
| F-17 | EMA150 Slope Positive | `ema150_slope_pos` | `stock_signals` | 1 if `EMA150(today) > EMA150(5d ago)` | Binary | Unknown | — |
| F-18 | Base Duration | `base_duration` | `stock_signals` | Consecutive days where `base_tightness < 12` | Integer (days) | Unknown | — |
| F-19 | Overhead Clear | `overhead_clear` | `stock_signals` | 1 if `max(high, 200d) ≤ pivot_high × 1.15` | Binary | Unknown | — |
| F-20 | Near Pivot Days | `near_pivot_days` | `stock_signals` | Consecutive days where `0 ≤ pivot_distance_pct ≤ 15` | Integer (days) | Unknown | — |

---

## Sector-Level Factors (from `sector_signals`)

| ID | Factor Name | Column | Source Table | Formula (Summary) | Type | Predictive Value | Study |
|---|---|---|---|---|---|---|---|
| F-21 | Sector RS Score 20d | `rs_score_20` | `sector_signals` | Sector 20d return% − KSE-100 20d return% (market-cap weighted) | Continuous | Unknown | — |
| F-22 | Sector RS Rank | `rs_rank` | `sector_signals` | Ordinal rank of sector by `rs_score_20` (1 = best sector) | Ordinal | Unknown | — |
| F-23 | Sector Breadth Score | `breadth_score` | `sector_signals` | % of stocks in sector above their 20d EMA | Continuous (0–100) | Unknown | — |
| F-24 | Adv/Dec Ratio | `adv_dec_ratio` | `sector_signals` | Advancing stocks / Declining stocks in sector | Continuous | Unknown | — |
| F-25 | Sector Volume Ratio | `vol_ratio` | `sector_signals` | Today's sector volume / sector 20d avg volume | Continuous | Unknown | — |
| F-26 | RS Inflection | `rs_inflection` | `sector_signals` | 1 if sector `rs_rank` improved AND `rs_score_20 > 0` | Binary | Unknown | — |
| F-27 | Sector Composite Score | `composite_score` | `sector_signals` | `0.5×rs_norm + 0.3×breadth_norm + 0.2×vol_norm` (min-max within date) | Continuous (0–1) | Unknown | — |
| F-28 | Sector Stage | `sector_stage` | `sector_signals` | Stage 1/2/3/4 based on sector price index vs EMA50 and slope | Categorical | Unknown | — |
| F-29 | Sector Above EMA | `sector_above_ema` | `sector_signals` | 1 if sector price index > sector EMA50 | Binary | Unknown | — |
| F-30 | Sector EMA Slope | `sector_ema_slope` | `sector_signals` | 5-bar change in sector EMA50 | Continuous | Unknown | — |
| F-31 | Sector Pivot Distance | `sector_pivot_dist_pct` | `sector_signals` | Sector index distance from 20d pivot high | Continuous | Unknown | — |
| F-32 | Sector RS New High | `sector_rs_new_high` | `sector_signals` | 1 if `rs_score_20 ≥ 20d max(rs_score_20)` | Binary | Unknown | — |
| F-33 | Smart Money Net 5d | `flow_smart_net_5d` | `sector_signals` | Rolling 5d net flow for institutional/smart money | Continuous | Unknown | — |
| F-34 | Smart Money Net 20d | `flow_smart_net_20d` | `sector_signals` | Rolling 20d net flow for institutional/smart money | Continuous | Unknown | — |
| F-35 | Retail Net 20d | `flow_retail_net_20d` | `sector_signals` | Rolling 20d net retail flow | Continuous | Unknown | — |
| F-36 | Flow Direction | `flow_direction` | `sector_signals` | ACCUMULATING / DISTRIBUTING / RECOVERING / FADING / NEUTRAL | Categorical | Unknown | — |

---

## Market-Level Factors (from `market_regime`)

| ID | Factor Name | Column | Source Table | Formula (Summary) | Type | Predictive Value | Study |
|---|---|---|---|---|---|---|---|
| F-37 | Market Regime | `regime` | `market_regime` | Classification based on KSE-100 EMA stack | Categorical | Unknown | — |
| F-38 | Regime Duration | `regime_days` | `market_regime` | Consecutive days in current regime | Integer (days) | Unknown | — |
| F-39 | KSE-100 ATR% | `atr_pct` | `market_regime` | 20-day ATR / close × 100 | Continuous | Unknown | — |
| F-40 | KSE-100 Return 20d | `return_20d` | `market_regime` | 20-day return of KSE-100 index | Continuous | Unknown | — |

---

## Derived / Computed Factors (not in database; computed during research)

| ID | Factor Name | Derived From | Definition | Used In Study | Notes |
|---|---|---|---|---|---|
| F-41 | RS Score Acceleration | F-01, F-02 | `rs_score_20 − rs_score_50` — positive = recent acceleration | — | Not in DB; compute at research time |
| F-42 | Volume on BOS Day | `prices_adjusted.volume` | Single-day volume on the BOS signal date | — | Not in `setup_log`; join required |

---

## Predictive Value Key

| Value | Meaning |
|---|---|
| `Unknown` | Not yet studied |
| `None` | Studied; no predictive relationship found |
| `Low` | Weak association; Δ < 3pp win rate or < 0.5% return delta |
| `Moderate` | Material association; meets [Statistical_Guidelines.md](Statistical_Guidelines.md) thresholds |
| `High` | Strong association; Strong confidence per [Evidence_Standards.md](Evidence_Standards.md) |

---

*Update the Predictive Value and Study columns as studies complete. Do not update based on intuition.*
