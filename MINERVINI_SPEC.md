# Minervini Setup Screener — Confirmed Specification

**Source of truth for Page 17 🏹 Minervini Setup.**
All future code changes to `breakout_signal.py` must be audited against this file.
Last confirmed: 2026-06-10

---

## Shared Conditions (Watchlist + Breakout)

All seven conditions apply to **both** signal types.

| Gate | Rule | Implementation |
|---|---|---|
| **Stage 2** | close > EMA20 > EMA50 > EMA200 | `ewm(span=n, adjust=False)` — NOT rolling SMA |
| **Tight Base** | Bollinger Band width (prior day) ≤ 12% | `(Upper−Lower)/Middle × 100` = `4σ/SMA20 × 100`, shifted 1 bar |
| **No Overhead Supply** | 200-day high ≤ 60-day pivot × 1.05 | 200d rolling max of HIGH column, shifted 1 |
| **RS Rating** | Cross-sectional percentile ≥ 60 | 40%×1yr + 30%×6m + 20%×3m + 10%×1m, ranked daily |
| **Market** | KSE-100 close > 50 SMA | Index uses SMA (not EMA) — intentional |
| **Liquidity** | 20-day avg volume ≥ 100,000 shares | 20d rolling avg, shifted 1 |
| **Volatility** | ATR14 between 1% and 6% of price | ATR14 / close × 100 |

---

## Watchlist Signal (pre-breakout)

Stock is coiling at the trigger — breakout has NOT happened yet.

- All 7 shared conditions pass
- Close is **below** the 60-day pivot high
- Close is **within 3%** of the 60-day pivot high: `(pivot − close) / pivot ≤ 0.03`
- No volume requirement

**Use for:** morning prep, intraday watch, discretionary entry on the actual break.

---

## Breakout Signal (confirmed end-of-day)

Breakout happened today. Enter tomorrow's open if you missed intraday.

- All 7 shared conditions pass
- Close is **above** the 60-day pivot high
- **First break only:** yesterday's close was ≤ pivot high (not a continuation)
- Volume ≥ 2× the 20-day average volume

**Implementation:**
```python
_prev_close = g["close"].transform(lambda s: s.shift(1))
df["bo_long"] = (df["close"] > df["pivot_high"]) & (_prev_close <= df["pivot_high"])
```

---

## Short Signal (DFC symbols only)

Inverse of the long setup. Only PSX-shortable stocks (DFC counters from `config.py`).

| Gate | Rule |
|---|---|
| **Stage 4** | close < EMA20 < EMA50 < EMA200 (EMA stack — not SMA) |
| **First breakdown** | Close below 60-day pivot low, yesterday still above |
| **Tight Base** | BB width (prior day) ≤ 12% |
| **Market** | KSE-100 below 50 SMA (bear regime required) |
| **RS Rating** | ≤ 40 (weakest stocks only) |
| **Liquidity** | 20-day avg volume ≥ 100,000 shares |
| **Volatility** | ATR14 between 1%–6% of price |

**No volume spike requirement on shorts.**

Results sorted by RS rating **ascending** (weakest first).

---

## Pivot High / Low Definition

- 60-day rolling max of **close**, shifted 1 bar (prior day's 60-day high)
- `pivot_high = close.rolling(60, min_periods=60).max().shift(1)`
- `pivot_low  = close.rolling(60, min_periods=60).min().shift(1)`

---

## Parameters (PARAMS dict)

| Key | Value | Meaning |
|---|---|---|
| `min_avg_vol` | 100,000 | Liquidity floor (20d avg vol) |
| `vol_mult` | 2.0 | Breakout volume multiplier (longs only) |
| `rs_min_long` | 60 | RS percentile floor for longs and watchlist |
| `rs_max_short` | 40 | RS percentile ceiling for shorts |
| `atr_min_pct` | 1.0 | Min ATR% |
| `atr_max_pct` | 6.0 | Max ATR% |
| `resist_win` | 60 | Pivot lookback window (days) |
| `bb_max_width` | 12.0 | Max Bollinger Band width % (tight base) |
| `overhead_mult` | 1.05 | Max 200d high as multiple of pivot (5% overhead) |
| `sma_trend` | 50 | Index regime SMA period |

---

## Key Rules for Future Sessions

1. **EMA for stocks, SMA for index.** Stage 2/4 use `ewm()`. Market gate uses `rolling().mean()`. Never swap these.
2. **Shared conditions apply to WATCHLIST too** — not just breakout signals.
3. **First break only.** `bo_long`/`bo_short` must check that yesterday was on the other side of the pivot.
4. **No vol_ok on shorts.** Volume spike is a long-only requirement.
5. **Watchlist RS floor is 60** — same as breakout, because it's a shared condition.
6. **No Overhead is a shared condition** — applies to watchlist candidates too.
7. **Do not add SMA columns.** The only moving averages computed are EMA20, EMA50, EMA200 (stock trend) and SMA50 (index regime). There is no sma20, sma50, sma200 in v2.

---

## Files

| File | Role |
|---|---|
| `breakout_signal.py` | Signal engine — all computation |
| `dashboard.py` | Page 17 UI — calls `build_features()` and `get_signals()` |
| `config.py` | `DFC_SYMBOLS` list for shortable stocks |
| `MINERVINI_SPEC.md` | **This file — source of truth** |
