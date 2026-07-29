# Market Regime Framework — PSX Quantitative Research Platform

> **Purpose:** Defines how market regimes are classified on this platform, how they are used in research, and what is known about their distribution on PSX.  
> **Related:** [Factor_Catalog.md](Factor_Catalog.md) · [Outcome_Definitions.md](Outcome_Definitions.md) · [Factor_Taxonomy.md](Factor_Taxonomy.md)

---

## Regime Source

All regime data comes from the `market_regime` table in `psx_data.db`.

| Column | Description |
|---|---|
| `date` | Trading date (primary key) |
| `close` | KSE-100 closing value |
| `ema_20` | KSE-100 EMA(20) |
| `ema_50` | KSE-100 EMA(50) |
| `ema_200` | KSE-100 EMA(200) |
| `atr_20` | 20-day ATR of KSE-100 |
| `atr_pct` | ATR as % of close |
| `return_20d` | KSE-100 20-day return % |
| `regime` | Classification label (text) |
| `regime_days` | Consecutive days in current regime |

---

## Regime Classification

The exact classification logic is implemented in the pipeline. The documented regime labels are:

| Label | General Interpretation |
|---|---|
| `TRENDING_UP` | KSE-100 in confirmed uptrend; bullish environment |
| `RANGING` | KSE-100 in sideways consolidation; mixed environment |
| `TRENDING_DOWN` | KSE-100 in confirmed downtrend; bearish environment |
| `VOLATILE` | Elevated volatility; directional trend unclear |

> **Note:** The exact EMA-based rules producing these labels should be confirmed from `weinstein.py` or the regime computation code before writing them into research methodology. Do not assume the rules from general knowledge.

---

## PSX Regime Distribution (Historical)

Based on prior system analysis (not from a formal study):

| Regime | Approximate Frequency |
|---|---|
| TRENDING_UP | ~60–65% of trading days |
| RANGING | ~20–25% |
| TRENDING_DOWN | ~10–11% |
| VOLATILE | ~5% (if applicable) |

> This distribution is an approximation. A formal study (S-xxx) should characterise the exact distribution from `market_regime` before regime-stratified research begins.

---

## Research Usage Rules

### Rule 1 — Regime is a Stratifier, Not a Feature

Regime is used to split results by market condition, not as a predictive feature of an individual stock's outcome. A single stock's forward return on one day is affected by regime; regime does not cause that individual outcome.

### Rule 2 — Stratify Before Combining

In every study, report results overall first, then stratified by regime. Never report only the overall result when regime-conditional differences exist.

### Rule 3 — Minimum N per Regime Cell

If a regime subgroup produces fewer than 30 observations for the studied setup type:
- Report the subgroup result but flag it as Weak
- Do not draw conclusions from sub-30 cells
- TRENDING_DOWN studies are expected to have low N; state this explicitly

### Rule 4 — Joining Regime to Signals

To join regime to a signal in `setup_log`:
```
join market_regime on setup_log.setup_date = market_regime.date
```
Note: The regime on the signal date reflects the regime that was active when the signal occurred, not the regime during the forward return window.

### Rule 5 — Regime Tenure (regime_days)

`regime_days` measures how long the current regime has been active. A setup occurring 5 days into a TRENDING_UP regime is qualitatively different from one occurring after 200 consecutive days. This variable is available for research as F-38.

---

## Known Limitations

- TRENDING_DOWN has very few trading days in the available history (~11%). Studies stratified by this regime will consistently have low N.
- Regime changes are detected with a lag (EMA-based). A transition from RANGING to TRENDING_UP is only confirmed several days after it begins. Signals near regime transition dates should be treated with additional caution.
- Regime labels are coarse — "RANGING" covers both low-volatility sideways markets and high-volatility whipsaw markets, which may have different implications for breakout quality.

---

## Future Research

- [ ] Formal characterisation study: distribution of regimes by year from 2020–2026
- [ ] Regime-duration effect: does longer TRENDING_UP duration improve or degrade breakout quality?
- [ ] Transition-zone effect: do breakouts occurring within the first 10 days of a new regime behave differently from mid-regime breakouts?
