# Market Structure Diagnostic — 2015-2026

**Status:** DIAGNOSTIC / DESCRIPTIVE ONLY — not a confirmatory finding, not a hypothesis test on `fwd_return_10d`, not a new trading signal. Filed as a standalone document rather than a section within `PRE_BREAKOUT_Specification_v1.0.md` — **flagging this choice explicitly**: this diagnostic is not specific to the PRE_BREAKOUT construct, it characterizes PSX market structure project-wide, and is equally relevant to BREAKOUT or any other future construct's own OOS behavior. It is referenced from, but does not live inside, the PRE_BREAKOUT spec.
**Filed:** 2026-07-10
**Motivation:** two independent, unrelated constructs — ROC/volume velocity (PRE_BREAKOUT Phase 4c) and Stealth Relative Strength (PRE_BREAKOUT Phase 5) — both held through Development (2015-2019) and Validation (2020-2022), then reversed specifically in OOS (2023-2026). A pattern recurring across independent hypotheses suggests something structural may have shifted in the market itself around 2023, rather than each finding being independently spurious. This document characterizes what changed, if anything, using existing tables only — it does not re-test or re-litigate the killed findings (Sections 9-12 of the PRE_BREAKOUT spec, or S-002/S-003/S-004), beyond reusing the existing "adverse index day" (≤-1.5%) definition where directly useful.

---

## 1. Regime Distribution Shift

Annual % breakdown of `market_regime` classifications (`INSUFFICIENT_DATA` rows excluded):

| Year | TRENDING_UP | RANGING | VOLATILE | TRENDING_DOWN |
|---|---|---|---|---|
| 2015 | 37.8% | 45.0% | 15.3% | 2.0% |
| 2016 | 64.1% | 27.0% | 0.0% | 8.9% |
| 2017 | 23.3% | 26.5% | 26.9% | 23.3% |
| 2018 | 8.9% | 42.7% | 18.7% | 29.7% |
| 2019 | 8.9% | 30.8% | 16.6% | 43.7% |
| 2020 | 36.3% | 25.9% | 32.3% | 5.6% |
| 2021 | 30.8% | 46.6% | 18.2% | 4.5% |
| 2022 | 2.8% | 56.9% | 0.8% | 39.5% |
| 2023 | 37.8% | 39.0% | 11.4% | 11.8% |
| 2024 | 74.0% | 15.0% | 11.0% | 0.0% |
| 2025 | 70.8% | 8.0% | 21.2% | 0.0% |
| 2026* | 48.0% | 1.6% | 50.4% | 0.0% |

*2026 is a **partial year** (125 trading days recorded, roughly through early July, vs ~250 for a full year) — its 50.4% VOLATILE reading is a smaller-sample figure and should not be treated as a stable annual rate.

**Naive comparison (as first computed):** 2015-2022 mean VOLATILE% = 16.1%, 2023+ mean = 23.5% — looks like a real increase. **But this is entirely an artifact of including partial-year 2026 in the average.** Excluding 2026 (2023-2025 only): mean VOLATILE% = (11.4+11.0+21.2)/3 = **14.5%** — actually *slightly lower* than the 2015-2022 average of 16.1%, not higher. **Corrected finding: once the partial 2026 year is treated appropriately, there is no meaningful increase in VOLATILE-regime frequency in the OOS era** — 2023 and 2024 were in fact calmer by this measure than several pre-2023 years (2017: 26.9%, 2020: 32.3%). 2025 alone (21.2%) sits within the normal pre-2023 range. 2026's elevated reading is a real, current observation but is a half-year data point, not evidence of a stable new normal.

---

## 2. Cross-Sectional Dispersion / Correlation

Daily cross-sectional standard deviation of returns (dispersion) and average pairwise correlation of daily returns, computed from the 247-symbol universe, by year:

| Year | Cross-sec daily std (%) | Avg pairwise correlation |
|---|---|---|
| 2015 | 2.849 | 0.207 |
| 2016 | 3.072 | 0.141 |
| 2017 | 2.609 | 0.253 |
| 2018 | 2.740 | 0.231 |
| 2019 | 3.315 | 0.275 |
| 2020 | 3.405 | 0.269 |
| 2021 | 3.020 | 0.190 |
| 2022 | 2.841 | 0.226 |
| 2023 | 2.950 | 0.196 |
| 2024 | 3.246 | 0.142 |
| 2025 | 3.068 | 0.190 |
| 2026* | 2.984 | n/a (insufficient days for a stable full-year correlation matrix) |

2015-2022 avg: cross-sec std=2.98%, avg pairwise corr=**0.224**. 2023-2025 avg (excluding data-insufficient 2026): cross-sec std=2.95% (essentially unchanged), avg pairwise corr=**0.176**.

**Finding: cross-sectional dispersion (daily return spread) is essentially flat across the whole period — no break.** **Average pairwise correlation is, if anything, somewhat *lower* in 2023-2025 than in 2015-2022 (0.176 vs 0.224), not higher.** This directly addresses the task's framing: PI's earlier observation that PSX shows unusually high cross-sectional correlation vs US equities is **supported as a persistent, whole-period characteristic** (correlation never drops below ~0.14 in any year, well above typical US single-stock-universe correlations of ~0.10-0.15) — but **the correlation has not intensified further in the recent era; it has mildly eased.**

---

## 3. Liquidity Profile Over Time

| Year | Avg daily eligible symbols (avg_vol_10d≥200k) | Avg daily total market volume (shares) | Top-10 symbol volume share |
|---|---|---|---|
| 2015 | 83.7 | 194,664,845 | 44.5% |
| 2016 | 91.6 | 223,371,737 | 42.2% |
| 2017 | 88.8 | 197,400,482 | 45.1% |
| 2018 | 84.5 | 168,078,356 | 40.7% |
| 2019 | 79.2 | 143,214,389 | 45.0% |
| 2020 | 103.9 | 301,854,753 | 43.4% |
| 2021 | 110.6 | 426,210,436 | 46.8% |
| 2022 | 92.8 | 212,037,542 | 45.1% |
| 2023 | 103.5 | 297,982,040 | 43.7% |
| 2024 | 126.5 | 477,851,543 | 41.0% |
| 2025 | 141.5 | 642,958,542 | 43.3% |
| 2026* | 140.1 | 652,087,792 | 43.1% |

**Finding: liquidity has expanded steadily and continuously across the whole 2015-2026 period — no sharp 2023 inflection.** Eligible-symbol count and total volume both trend upward gradually (with normal year-to-year noise, e.g. the 2018-2019 dip and 2022 pullback, both pre-dating any 2023 break). **Concentration into fewer names has NOT increased** — top-10 volume share is remarkably stable across all 12 years, oscillating in a tight 40.7%-46.8% band with no directional trend. This looks like gradual secular market growth (plausibly amplified by the bull market documented in Section 4), not a structural break.

---

## 4. KSE-100 Index-Level Behavior

| Year | Annual return | Daily std (volatility) | Adverse days (≤-1.5%) | Trading days |
|---|---|---|---|---|
| 2015 | +1.03% | 0.92% | 11 | 249 |
| 2016 | +43.87% | 0.74% | 2 | 248 |
| 2017 | -16.10% | 1.15% | 19 | 249 |
| 2018 | -8.95% | 1.06% | 18 | 246 |
| 2019 | +7.21% | 1.17% | 23 | 247 |
| 2020 | +5.69% | 1.53% | 22 | 251 |
| 2021 | +0.36% | 0.94% | 14 | 247 |
| 2022 | -9.95% | 0.97% | 16 | 248 |
| 2023 | **+53.01%** | 1.06% | 10 | 246 |
| 2024 | **+78.04%** | 1.15% | 11 | 246 |
| 2025 | **+48.75%** | 1.30% | 12 | 250 |
| 2026* | +2.78% | 2.20% | 18 | 125 (partial year) |

**This is the clearest, most identifiable break in the entire diagnostic.** Starting in 2023, KSE-100 entered an extraordinary, sustained multi-year bull run: **+53% (2023), +78% (2024), +48.75% (2025)** — a compounded ~4x move over three years, versus a choppy, roughly range-bound 2015-2022 (annual returns from -16% to +44%, no comparable sustained trend). This is independently corroborated by external reporting (Section 6).

Daily volatility (std) is modestly higher in 2023-2025 (avg 1.17%, excluding partial 2026) vs 2015-2022 (avg 1.06%) — a real but not dramatic increase. **Adverse-day (≤-1.5%) frequency is actually *lower* in 2023-2025** (avg 11.0/yr) **than in 2015-2022** (avg 15.6/yr) — despite higher realized volatility, large single-day *drops* became less frequent, consistent with a market driven by sustained upside rather than crash-like turbulence. (2026's partial-year figures — 2.20% daily std, 18 adverse days in just 125 days — are elevated and worth watching, but are a half-year sample, not a confirmed annual rate.)

---

## 5. Sector Composition / Concentration

Global top-5 sectors by total traded volume, 2015-2026: **Technology & Communication, Commercial Banks, Power Generation & Distribution, Cement, Food & Personal Care Products.**

| Year | Fixed global-top5 share | Annually-reranked top5 share | Top sector that year |
|---|---|---|---|
| 2015 | 53.1% | 56.7% | Cement |
| 2016 | 51.0% | 56.1% | Technology & Communication |
| 2017 | 45.3% | 55.4% | Technology & Communication |
| 2018 | 50.1% | 58.2% | Chemical |
| 2019 | 57.3% | 57.3% | Cement |
| 2020 | 55.7% | 58.1% | Cement |
| 2021 | 58.7% | 61.9% | Technology & Communication |
| 2022 | 54.3% | 59.1% | Technology & Communication |
| 2023 | 56.1% | 59.2% | Technology & Communication |
| 2024 | 55.5% | 56.3% | Technology & Communication |
| 2025 | 57.1% | 57.1% | Technology & Communication |
| 2026* | 55.7% | 56.8% | Power Generation & Distribution |

2015-2022 avg: fixed-top5=53.2%, annually-reranked-top5=57.8%. 2023+ avg: fixed-top5=56.1%, annually-reranked-top5=57.4%.

**Finding: no meaningful concentration break.** The annually-reranked top-5 share is essentially flat (57.8% → 57.4%); the fixed-global-top5 share ticks up modestly (53.2% → 56.1%) but this is a small, gradual shift, not a discontinuity. Technology & Communication has been the (or a) leading sector by volume in most years since 2016, continuously — no sharp reshuffling coincides with 2023.

---

## 6. External Context (factual, web-search-verified, light touch)

Two well-documented, dated, verifiable structural events bracket the 2023 boundary:

1. **PKR currency devaluation, January 26, 2023.** Pakistan removed informal controls on the exchange rate, and the rupee dropped sharply as markets adjusted to market-determined levels — part of IMF program conditions requiring the exchange rate to float to market levels. The rupee fell to record lows (reported ~PKR 307/USD later in 2023) after having been roughly 115/USD in 2018. ([CNN](https://www.cnn.com/2023/01/26/investing/rupee-drops-markets-adjust/index.html))
2. **Sustained IMF-program-driven bull market, mid-2023 onward.** After an initially turbulent 2023 (PSX fell over 2,300 points amid political/economic uncertainty), the market began a historic, sustained rally — KSE-100 rising from roughly 40,000 points in mid-2023 to an all-time intraday high above 151,000 within about two years, reportedly PSX's best-performing-market ranking in FY24. Reported drivers: 11% export growth, 9% remittance growth, and inflation falling from a peak of 38.0% (May 2023) to 11.8% (May 2024), alongside IMF Stand-By Arrangement/EFF program stabilization. ([Business Recorder — economic turnaround](https://www.brecorder.com/news/40379536/psx-sees-exceptional-performance-amid-pakistans-economic-turnaround-whats-next), [Business Recorder — FY24 best performer](https://www.brecorder.com/news/40310436), [Express Tribune — rupee slide](https://tribune.com.pk/story/2433857/rupee-slide-inflation-pull-psx-deep-into-red))
3. **Circuit breaker / price-band widening, 2024 (mechanical, directly relevant to return-threshold-based signals).** SECP approved a gradual enhancement of PSX's security-wise circuit breaker (price cap/floor), increasing it by 0.5% every fortnight starting May 27, 2024 through July 22, 2024, until reaching the current ±10% band (up from a narrower prior band, reported at points along the way as 7.5%/8.5%). This is a **concrete, dated, mechanical change to the daily-return-generating process itself** — a wider allowed daily price band mechanically permits larger single-day moves than were structurally possible before mid-2024, directly relevant to any signal built on daily-return thresholds (adverse-index-day cutoffs, ROC). ([Mettis Global](https://mettisglobal.news/psx-to-increase-circuit-breakers-to-10/), [AUGAF](https://augaf.com/psx-plans-to-gradually-enhanced-the-security-wise-circuit-breaker-to-10/))
4. Minor SECP rulebook amendments in February and April 2023 (e.g., a new "PRIDE" clause definition, centralized gateway portal clause) were also identified but appear to be administrative/procedural, not obviously price-action-relevant — noted for completeness, not weighted in the synthesis below.

Sources: see inline links above; all four items are directly reported by named, dated news sources, not inferred or speculated.

---

## 7. Synthesis

**Is there a clear structural break around 2023, or gradual/no change? Answer: mixed — one clear, well-corroborated break at the index/macro level; no comparable break in cross-sectional market microstructure.**

- **NOT broken / continuous or stable:** Regime-classifier VOLATILE frequency (once the partial 2026 year is handled correctly), cross-sectional dispersion, average pairwise correlation (if anything mildly *lower* post-2023, not higher), liquidity concentration (top-10 share flat throughout), and sector concentration (essentially flat, same leading sectors throughout). None of these five measures shows a sharp, unambiguous inflection at 2023 — they show either flat/stable behavior or gradual, continuous drift that predates 2023 as much as it postdates it.
- **Genuinely broken, clearly, with external corroboration:** **KSE-100's own trend/return behavior.** 2023-2025 was an extraordinary, sustained, multi-year bull run (+53%/+78%/+49%), a sharp departure from the choppier, range-bound 2015-2022 period, independently verified by external reporting and tied to a specific, dated macro sequence: the January 2023 currency devaluation, followed by IMF-program-driven disinflation and stabilization. Daily volatility rose modestly; large single-day drops (adverse days) became *less* frequent, consistent with a strong-uptrend regime rather than crisis-like turbulence.
- **A separate, concrete mechanical change:** PSX's circuit breaker price band was deliberately widened (to ±10%) in a dated 2024 SECP-approved process — a structural change to the return-generating process itself, independent of any macro narrative.

**Honest conclusion:** this is not a case of "everything about PSX's market structure changed in 2023." The cross-sectional structure that factor tests actually depend on — how differently individual stocks move relative to each other (correlation, dispersion, concentration) — looks stable or continuous across the whole 12-year window. What clearly and sharply changed is the **index-level trend regime**: OOS (2023-2026) coincides with a real, historic, macro-driven bull market, plus a genuine mechanical widening of allowed daily price moves in 2024. Both are plausible, evidence-consistent candidate explanations for why signals calibrated on 2015-2022 behavior (a more balanced up/ranging/down environment) diverge in 2023+ — a sustained one-directional bull market compresses the *relative* edge of any differentiating signal even where absolute returns are higher across the board, and a wider circuit breaker band changes the very return distribution that daily-return-threshold-based signals (adverse-day counts, ROC) are computed against. **This diagnostic does not test or claim that these are the specific cause of the Phase 4c/Phase 5 reversals** — establishing that causal link would require a further, separate, out-of-scope test. It reports what changed, factually: a clear macro/trend-level break, not a clear cross-sectional microstructure break.

---

## Reproducibility

Script: `market_structure_diagnostic.py` (project root). Read-only against `market_regime`, `prices_adjusted`, `stock_signals`, `index_prices`, `sectors`. No production writes. Tables saved to `diag_regime_by_year.csv`, `diag_dispersion_by_year.csv`, `diag_liquidity_by_year.csv`, `diag_index_by_year.csv`, `diag_sector_concentration_by_year.csv`. External context (Section 6) verified via web search, sources cited inline.
