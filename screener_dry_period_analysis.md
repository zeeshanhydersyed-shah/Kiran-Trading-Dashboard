# Minervini Setup Screener — Signal Drought Analysis
*Generated: 2026-06-05 | Source: breakout_signal.py run against merged_psx_data.csv*
*Live analysis period: 2021-01-01 → 2026-06-04 (65 months, 1,339 trading days)*

> **Note on 2020 data:** The screener's indicators (EMA200, 200-day pivot, BB width) require ~200 days of history to stabilise. Signals from 2020 are unreliable warm-up noise and are excluded from all statistics below.

---

## Screener Entry Criteria

*Derived from 9 confirmed real trades (DGKC×2, FFC×3, UBL×2, TPLP, POWER — 2021–2026). No sector filter is used.*

### LONG — Shared Conditions (Watchlist + Breakout)

| # | Condition | Rule |
|---|-----------|------|
| 1 | **Stage 2** | close > EMA20 > EMA50 > EMA200 (full uptrend stack) |
| 2 | **Tight base** | Bollinger Band width (prior day) ≤ 12% |
| 3 | **No overhead supply** | 200-day high ≤ pivot high × 1.15 |
| 4 | **RS Rating** | Cross-sectional percentile ≥ 60 (avg 74 across 9 trades) |
| 5 | **Market regime** | KSE-100 close > EMA50 |
| 6 | **Liquidity** | 20-day avg volume ≥ 100,000 shares |
| 7 | **Volatility** | ATR14 between 1% and 6% of price |

**Watchlist signal adds:** close below pivot but within 3% of it (coiling, not yet broken)

**Breakout signal adds:** close above 60-day pivot high (first break only) + volume ≥ 2× 20-day avg

### SHORT — Conditions

| # | Condition | Rule |
|---|-----------|------|
| 1 | **DFC eligibility** | Symbol must be on the DFC (short-selling eligible) list |
| 2 | **Stage 4** | Inverted EMA stack (EMA20 < EMA50 < EMA200) |
| 3 | **First break down** | Close below 60-day pivot low for the first time |
| 4 | **Tight base** | BB width ≤ 12% (prior day) |
| 5 | **Market regime** | KSE-100 below EMA50 |
| 6 | **RS Rating** | ≤ 40 |

> Volume is NOT required for shorts — breakdowns occur on low/frozen volume.

---

## Signal Frequency (2021–2026)

| Signal Type | Days Active | % of Trading Days |
|-------------|-------------|-------------------|
| **Any signal** (Watchlist + Breakout + Short) | 673 / 1,339 | **50.3%** |
| Watchlist only | 584 / 1,339 | 43.6% |
| Breakout Long only | 198 / 1,339 | 14.8% |
| Short only | 28 / 1,339 | 2.1% |

The screener is active on roughly **1 in 2 trading days** when counting watchlist signals. Confirmed breakouts are far rarer at 1 in 7 days.

---

## Dry Period Summary (Material Droughts ≥ 5 Calendar Days)

### Any Signal (Watchlist + Breakout + Short)

| Metric | Value |
|--------|-------|
| Material dry periods | 57 |
| **Longest drought** | **99 days (14.1 weeks)** — May 6 → Aug 12, 2022 |
| Average drought | 13.4 calendar days (~2 weeks) |
| Median drought | 7 calendar days (~1 week) |
| Frequency | Once every **~1.1 months** |

### Watchlist Only

| Metric | Value |
|--------|-------|
| Material dry periods | 50 |
| **Longest drought** | **99 days (14.1 weeks)** — May 6 → Aug 12, 2022 |
| Average drought | 17.5 calendar days (~2.5 weeks) |
| Median drought | 10 calendar days |
| Frequency | Once every **~1.3 months** |

### Breakout Long Only

| Metric | Value |
|--------|-------|
| Material dry periods | 75 |
| **Longest drought** | **126 days (18 weeks)** — Apr 27 → Aug 30, 2022 |
| Average drought | 19.6 calendar days |
| Median drought | 11 calendar days |
| Frequency | Once every **~0.9 months** |
| **Currently ongoing** | **119 days (since Feb 6, 2026) — no confirmed breakout in ~4 months** |

---

## All Material Dry Periods — Any Signal (≥ 5 Calendar Days)

| # | Start | End | Cal Days | Weeks | Trading Days |
|---|-------|-----|----------|-------|--------------|
| 1 | 2022-05-06 | 2022-08-12 | **99** | **14.1** | 66 |
| 2 | 2026-02-19 | 2026-04-17 | **58** | **8.3** | 40 |
| 3 | 2021-11-22 | 2021-12-31 | 40 | 5.7 | 30 |
| 4 | 2022-09-02 | 2022-10-10 | 39 | 5.6 | 27 |
| 5 | 2023-03-13 | 2023-04-19 | 38 | 5.4 | 26 |
| 6 | 2022-12-02 | 2022-12-26 | 25 | 3.6 | 17 |
| 7 | 2022-02-21 | 2022-03-16 | 24 | 3.4 | 18 |
| 8 | 2022-11-03 | 2022-11-24 | 22 | 3.1 | 15 |
| 9 | 2022-12-28 | 2023-01-18 | 22 | 3.1 | 16 |
| 10 | 2023-06-08 | 2023-06-23 | 16 | 2.3 | 12 |
| 11 | 2023-12-14 | 2023-12-29 | 16 | 2.3 | 11 |
| 12 | 2025-05-19 | 2025-06-03 | 16 | 2.3 | 11 |
| 13 | 2022-08-16 | 2022-08-30 | 15 | 2.1 | 11 |
| 14 | 2025-04-28 | 2025-05-12 | 15 | 2.1 | 10 |
| 15 | 2025-11-12 | 2025-11-25 | 14 | 2.0 | 10 |
| 16 | 2026-05-08 | 2026-05-21 | 14 | 2.0 | 10 |
| 17 | 2023-05-25 | 2023-06-05 | 12 | 1.7 | 8 |
| 18 | 2023-09-11 | 2023-09-22 | 12 | 1.7 | 10 |
| 19 | 2022-03-18 | 2022-03-28 | 11 | 1.6 | 6 |
| 20 | 2025-01-03 | 2025-01-13 | 11 | 1.6 | 7 |
| 21–57 | *(various)* | *(various)* | 5–10 | 0.7–1.4 | 2–7 |

*Full list available on request.*

---

## All Material Dry Periods — Breakout Long Only (≥ 5 Calendar Days, Top 15)

| # | Start | End | Cal Days | Weeks | Trading Days | Notes |
|---|-------|-----|----------|-------|--------------|-------|
| 1 | 2022-04-27 | 2022-08-30 | **126** | **18.0** | 80 | PSX correction |
| 2 | 2026-02-06 | 2026-06-04 | **119** | **17.0** | 77 | **[ONGOING]** |
| 3 | 2022-11-03 | 2023-01-25 | 84 | 12.0 | 59 | Bear phase |
| 4 | 2021-03-02 | 2021-05-06 | 66 | 9.4 | 47 | |
| 5 | 2021-08-25 | 2021-10-20 | 57 | 8.1 | 40 | |
| 6 | 2022-09-01 | 2022-10-21 | 51 | 7.3 | 37 | |
| 7 | 2023-03-13 | 2023-05-02 | 51 | 7.3 | 31 | |
| 8 | 2022-02-10 | 2022-03-30 | 49 | 7.0 | 34 | |
| 9 | 2021-11-22 | 2022-01-06 | 46 | 6.6 | 34 | |
| 10 | 2023-08-25 | 2023-10-04 | 41 | 5.9 | 28 | |
| 11 | 2025-05-19 | 2025-06-23 | 36 | 5.1 | 23 | |
| 12 | 2023-05-04 | 2023-06-06 | 34 | 4.9 | 24 | |
| 13 | 2021-07-28 | 2021-08-23 | 27 | 3.9 | 17 | |
| 14 | 2024-02-02 | 2024-02-28 | 27 | 3.9 | 17 | |
| 15 | 2023-02-14 | 2023-03-09 | 24 | 3.4 | 18 | |

---

## Practical Takeaways

1. **Watchlist signals are the day-to-day heartbeat.** They fire on 44% of days. A 2-week watchlist drought is normal; beyond 6 weeks is uncommon (only happened twice in 5 years: May–Aug 2022 and Feb–Apr 2026).

2. **Confirmed breakouts are rare by design.** Only 14.8% of days produce a breakout signal. Expect gaps of 2–4 weeks between breakout alerts routinely, and gaps of 2–4 months during bear or correction phases.

3. **The current breakout drought (since Feb 6, 2026) is the second-longest on record** at 119 days — only the May–Aug 2022 correction (126 days) was longer. This is not a screener malfunction; it reflects tight market conditions or stocks failing the volume/overhead/RS gates.

4. **Shorts are extremely rare (2% of days).** Do not rely on shorts to fill long signal gaps — the screener went completely short-signal-free for 784 days (Mar 2023 → Apr 2025) and is currently in another short drought since Nov 2025.

5. **The worst environment was 2022.** Between the correction (Apr–Aug 2022), the bear phase (Sep–Oct 2022), and the post-bear chop (Nov 2022 – Jan 2023), the screener was near-silent for most of 9 months — especially for confirmed breakouts.

6. **After a long drought, signals cluster.** When regime conditions normalise (KSE-100 reclaims EMA50, stocks rebuild tight bases), a burst of watchlist and breakout signals typically follows within 1–2 weeks.
