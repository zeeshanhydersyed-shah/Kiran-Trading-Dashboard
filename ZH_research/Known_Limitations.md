# Known Limitations — PSX Quantitative Research Platform

> **Purpose:** Honest, standing record of all known limitations of the platform, data, and methodology. Required reading before publishing any finding.  
> **Related:** [Assumption_Register.md](Assumption_Register.md) · [Data_Quality_Policy.md](Data_Quality_Policy.md) · [Bias_Checklist.md](Bias_Checklist.md)

---

## Principle

Every quant platform has limitations. Acknowledging them honestly protects the integrity of every finding. A finding that ignores a relevant limitation is unreliable; a finding that acknowledges limitations and explains why they do not invalidate the conclusion is credible.

---

## Market Structure Limitations

### L-01 — Single Market (PSX Only)
**Limitation:** All research is conducted on PSX data only. PSX is a single emerging market with specific structural characteristics (illiquidity, concentrated sectors, political sensitivity, currency effects).

**Implication:** No finding from PSX research can be generalised to other markets without independent replication. Findings that have been validated in developed markets are not automatically valid here; PSX-specific factors may dominate.

**Scope:** Applies to every study.

---

### L-02 — Short History (6 Years)
**Limitation:** Meaningful data is available from 2020-01-01. This is approximately 6 years of history at the time of platform setup.

**Implication:** Six years may not span a full market cycle on PSX. The 2020–2023 in-sample period includes strong bull-market years. The 2024+ out-of-sample period may not adequately test bear-market performance. Findings about tail events (crashes, regime transitions) are underpowered.

**Scope:** All studies using the full history.

---

### L-03 — TRENDING_DOWN Underrepresentation
**Limitation:** Approximately 90% of PSX trading days in the database fall outside a TRENDING_DOWN regime. Bear market studies have very low N.

**Implication:** Any factor that is theorised to perform differently in bear markets cannot be adequately tested with this data. Confidence will be Weak for all TRENDING_DOWN-stratified studies.

**Scope:** All regime-stratified studies.

---

### L-04 — Survivorship Bias
**Limitation:** The `prices_adjusted` table contains stocks that survived to the current date plus those that were active at some point. Stocks that were delisted before data collection began are absent.

**Implication:** Studies using the full universe may overstate average return because the worst performers (those that went to zero) are underrepresented. The pre-2024 merger (BI data) helps but does not completely resolve this — the BI source also captured active stocks at its collection time.

**Scope:** Long-horizon outcome studies. Stronger bias at longer forward-return windows (OV-06).

---

## Data Limitations

### L-05 — Passive Hold Outcomes Only
**Limitation:** `setup_log` forward returns (OV-01, OV-02, OV-03) are passive fixed-exit calculations. They do not reflect the experience of a trader using a stop-loss.

**Implication:** A setup that declines 8% then recovers to +3% by day 10 is recorded as WINNER (+3%). A real trade with a 6% stop would have been stopped out at −6% and then missed the recovery. Win rates from passive hold studies are systematically higher than what traders would actually achieve.

**Mitigation:** Always report `backtest_setups` outcomes (OV-05) alongside passive hold metrics where available.

**Scope:** All studies using OV-01, OV-02, OV-03, OV-04.

---

### L-06 — No Slippage or Transaction Costs
**Limitation:** All return calculations assume perfect fills at the closing price on the signal date. No slippage, bid-ask spread, brokerage fees, or market impact costs are modelled.

**Implication:** Actual trader returns will be lower than study-reported returns. This effect is larger for less liquid stocks. The `avg_vol_10d > 200000` filter reduces but does not eliminate this issue.

**Scope:** All studies.

---

### L-07 — No Position Sizing
**Limitation:** Forward returns are per-setup, not portfolio-level. No position sizing, correlation, or portfolio concentration effects are modelled.

**Implication:** A study may show that a factor produces 5% average forward return, but if the signals are highly correlated (many signals in the same sector on the same date), a concentrated portfolio would behave very differently from a well-diversified one.

**Scope:** All portfolio simulation interpretations.

---

### L-08 — BREAKOUT Signal Duplication
**Limitation:** Historical `setup_log` BREAKOUT rows include all `bos_flag = 1` days, including day 2, 3, 4 of the same breakout event.

**Implication:** Naive win-rate calculations on BREAKOUT signals are inflated by the easy subsequent days of an already-successful breakout. The "breakout edge" as seen in the data is not the edge available to a trader entering on day 1.

**Mitigation:** See [Data_Quality_Policy.md](Data_Quality_Policy.md) Issue 1 for deduplication approach. Use only day-1 transitions for BREAKOUT factor studies.

**Scope:** All BREAKOUT setup studies.

---

### L-09 — Adjusted Price Look-Ahead
**Limitation:** `prices_adjusted` uses corporate-action factors that are applied retrospectively. When a corporate action occurs today, it adjusts all historical prices backward. This means the adjusted prices available in the research database are slightly different from what would have been available to a trader in real time.

**Implication:** Pivot levels, RS scores, and other price-based indicators computed from `prices_adjusted` may differ marginally from what would have been computed in real time. This is a standard issue with adjusted price databases and is not unique to this platform.

**Scope:** All studies using pre-adjustment-date price data for symbols with confirmed corporate actions.

---

## Methodology Limitations

### L-10 — Single-Factor Interpretation Risk
**Limitation:** Individual factor studies show whether a factor is independently associated with outcomes. They do not establish that the factor causes the outcome, nor do they establish that the factor adds value in a multi-factor context.

**Implication:** A factor with High predictive value in a single-factor study may provide zero marginal value when combined with highly correlated factors. Single-factor findings are necessary but not sufficient for conviction engine construction.

**Scope:** All single-factor studies.

---

### L-11 — Multiple Testing Risk
**Limitation:** With 42+ factors catalogued and 7 outcome variables, the probability of finding a spurious statistically significant result increases with the number of tests performed.

**Implication:** Results that are statistically significant but were not pre-registered, or that represent the "best" result among many tests run, require additional scrutiny. See [Statistical_Guidelines.md](Statistical_Guidelines.md) Section 6 for required corrections.

**Scope:** All studies; higher risk in screening-phase studies.

---

### L-12 — Coarse Regime Classification
**Limitation:** Market regime uses only 3–4 labels (TRENDING_UP, RANGING, TRENDING_DOWN, VOLATILE). Within each label, conditions vary considerably. A mild uptrend and a strong bull run both receive the same TRENDING_UP label.

**Implication:** Regime-stratified studies may be hiding important sub-regime variation. The TRENDING_UP label is not homogeneous.

**Scope:** Regime-stratified studies.

---

### L-13 — No External Data
**Limitation:** This platform uses only price-derived data. No macroeconomic data (interest rates, CPI, FX), no fundamental data (earnings, P/E, debt), and no sentiment data (news, social media) are incorporated.

**Implication:** The conviction engine is a pure price-action system. Factors that depend on fundamentals or macro context are out of scope and cannot be tested here.

**Scope:** All studies and the conviction engine.

---

## Data Limitations — added 2026-09-03 (read-only diff, `KIRAN_CLEANUP_AUDIT.md` §116; census `trading_edge_program/loop_000`)

### L-14 — Corporate-action adjustments are almost entirely unapplied (supersedes the optimistic framing of L-04 / L-09)
**Limitation:** `prices_adjusted` is byte-identical to raw `prices` (within a 1% epsilon on every shared date) for **760 of 904 symbols** — **100% of every symbol whose price history ends before 2024**, and 76% of 2024+ symbols. The review queue `corporate_action_suspects_clean.csv` holds **11,469 detected suspects spanning 2005–2026, every one `review_status = PENDING`** (never reviewed). `apply_price_adjustments.load_events()` applies only (a) auto-detected large bonus events (≥25% single-day drop, pattern-matched — and never validated against an independent record) and (b) rows explicitly set `CONFIRMED` (one exists). **Every cash dividend, rights issue, and sub-25% bonus across 21 years is unadjusted.** On the Postgres backend the ratio is worse (11 of 573 symbols) and the confirm/rebuild path is hard-blocked.

**Implication:** Any study using `prices_adjusted` before 2024 is effectively using **raw** prices. Total-return / dividend-drag analysis is silently wrong; momentum, mean-reversion, breakout, base-tightness and RS-rank signals see a spurious gap-down on every unadjusted ex-date. Volume is **never** adjusted for any event.

**Authoritative treatment:** `trading_edge_program/loop_001..006_5` — a frozen Tier-1 corporate-action spec and an independently-verified 12-name pilot artifact (face-value splits + succession linkage only; bonuses/dividends/rights still out of scope). `loop_007` §15 = the minimum substrate a defensible study needs.

**Scope:** Every study that reads `prices_adjusted`, `stock_signals`, `sector_signals`, or `setup_log` forward returns for any date before ~2024, or for any symbol with an unadjusted corporate action. Production cross-ref: **TR-03**.

---

### L-15 — No point-in-time universe; `stock_metadata` covers half the traded symbols (sharpens L-04)
**Limitation:** `stock_metadata` has **468 rows** against **904 distinct symbols in `prices`** — **436 traded symbols are absent entirely** and are invisible to every screener JOIN through `sectors` / `stock_metadata`. `stock_metadata.listing_date == MIN(prices.date)` for **468 of 468 symbols** — the listing date is *derived from the price data*, not a real listing record, and cannot predate our history. Only **9** symbols are flagged `is_active = 0`, against a traded universe that shrank from **624 (2005)** to **313 (2023)**. There is no `(symbol, date) → in-universe` record; "the tradeable universe on 2015-06-30" cannot be answered. `kse100_constituents` is current-only. `symbol_active_dates` is stale (ends 2026-07-31).

**Implication:** Every backtest that filters via `sectors` / `stock_metadata` silently excludes names that later delisted → systematic upward performance bias, worse at longer horizons. Cross-sectional studies (breadth, RS rank, "N above MA") run over a survivor-only, non-point-in-time population.

**Scope:** All universe-filtered and cross-sectional studies. Production cross-ref: **TR-14**. Also memory `psx_db_schema_notes`.

---

### L-16 — Universe coverage discontinuity at the 2023→2024 boundary
**Limitation:** distinct symbols/year: 2019 = 460, **2020 = 311, 2021 = 393, 2022 = 316, 2023 = 313**, 2024 = 534. Month-level: **Dec-2023 = 292 → Jan-2024 = 454 (+162, +55% overnight)**. Pre-2024 history is the BI-PostgreSQL merge; 2024+ is the ksestocks scraper. 2020–2023 is a genuinely thin window — a name trading continuously 2019–2024 can have a hole in 2020–2023. This straddles the Dev/Validation era boundary used by both era designs currently in use.

**Implication:** Any study spanning the seam sees a ~55% universe expansion that is a data artifact, not a market event — breadth, participation, cross-sectional rank and new-high counts are all discontinuous there.

**Mitigation:** Bound studies to 2024+ or to a fixed explicit symbol list; add a `min_date` guard to study scaffolding. Full treatment: `trading_edge_program/loop_007` §8.

**Scope:** Any study spanning 2023→2024. Notes the 2020–2023 window is thinner than 2005–2019.

---

## Tracking

| ID | Added | Addressed By | Status |
|---|---|---|---|
| L-01 through L-13 | 2026-07-01 | — | Active |
| L-14, L-15, L-16 | 2026-09-03 | `trading_edge_program` LOOP 000–007 (spec + pilot done; full remediation not started) | Active |

*Add new limitations here as they are discovered. Never remove a limitation; mark as "Resolved" with explanation if addressed.*
