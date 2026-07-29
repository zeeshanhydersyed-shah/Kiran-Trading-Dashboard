# Research Glossary — PSX Quantitative Research Platform

> **Purpose:** Authoritative definitions of every technical term used in this research platform. When a term is used in a document, it has exactly the meaning defined here.  
> **Related:** [Data_Dictionary.md](Data_Dictionary.md) · [Naming_Conventions.md](Naming_Conventions.md)

---

## Notation

- **Bold** = the term being defined
- `code font` = a specific column name, table name, or code symbol
- [→ Document] = cross-reference to related document

---

## A

**Accepted Assumption**
An assumption that is accepted without explicit validation, typically because it is widely held in the domain and the cost of violation is low. Documented in [Assumption_Register.md](Assumption_Register.md).

**Additive Score**
A conviction score model where the total score is a weighted sum of individual factor scores. V1 of the conviction engine uses this architecture.

**Adjusted Prices**
OHLCV data from `prices_adjusted` where historical prices have been retroactively adjusted for corporate actions (stock splits, rights issues, dividends). All technical indicators and RS calculations in this platform use adjusted prices.

**ATR (Average True Range)**
A volatility measure: the average of `max(high − low, |high − prev_close|, |low − prev_close|)` over N periods. Used in `market_regime` as `atr_20` (20-day ATR) and `atr_pct` (ATR as % of close).

---

## B

**Base Duration (base_duration)**
A consecutive day counter: the number of unbroken days where `base_tightness < 12`. Resets to 0 when `base_tightness ≥ 12`. Factor F-18.

**Base Rate**
The overall win rate for all setups of a given type, without any factor conditioning. The starting probability before factors are applied. [→ Probability_Framework.md]

**Base Tightness (base_tightness)**
A proxy for Bollinger Band Width computed as: `4 × stddev(close_20d) / mean(close_20d) × 100`. Lower values indicate tighter price consolidation. Factor F-07.

**Bias**
A systematic error that causes a study's results to be consistently wrong in one direction. See [Bias_Checklist.md](Bias_Checklist.md) for all biases tracked on this platform.

**Binary Factor**
A factor that takes only the values 0 or 1. Examples: BOS Flag (F-12), Stage 2 Bull (F-13), Overhead Clear (F-19).

**BOS (Breakout of Structure)**
The event where closing price exceeds the confirmed pivot high. Recorded as `bos_flag = 1` in `stock_signals`. The BOS date is the first day the close exceeds the pivot high. [→ Data_Dictionary.md]

**Breadth Score (breadth_score)**
The percentage of stocks in a sector that are trading above their 20-day EMA. Sector-level factor F-23. Ranges 0–100.

**BREAKOUT (setup_type)**
A setup type in `setup_log` where `bos_flag = 1` and `avg_vol_10d > 200,000`. Historically includes all BOS days; daily hook uses transition-day only.

---

## C

**Calibration**
The degree to which a score's stated probability matches the empirically observed win rate. A well-calibrated score of 70 corresponds to an observed 70% win rate.

**Chronological Split**
The requirement that in-sample data precede out-of-sample data in time. Prevents look-ahead bias. This platform uses 2023-12-31 as the split date.

**Composite Score**
A sector-level factor computed as `0.5×rs_norm + 0.3×breadth_norm + 0.2×vol_norm` (min-max normalised within each date). Factor F-27.

**Confidence Level**
A qualitative assessment of how much evidence supports a finding. Levels: Strong (N≥200), Moderate (N≥50), Weak (N≥30). Defined in [Evidence_Standards.md](Evidence_Standards.md).

**Conviction Engine**
The end product of this research platform — a scoring system that rates signal quality using validated factors. [→ Conviction_Engine_Specification.md]

**Conviction Score**
The integer 0–100 output of the conviction engine for a given signal on a given date.

---

## D

**Data Quality Assessment**
A required pre-study check confirming that the data to be used is complete, uncontaminated, and correctly filtered. Defined in [Data_Quality_Policy.md](Data_Quality_Policy.md).

**Derived Factor**
A factor computed from another factor already in the catalog. Example: RS Rank (F-03) is derived from RS Score (F-01). Defined in [Factor_Taxonomy.md](Factor_Taxonomy.md).

---

## E

**Effect Size**
The magnitude of a factor's relationship with an outcome, independent of sample size. Common measures: win-rate difference (in percentage points), mean return difference (in %).

**EMA (Exponential Moving Average)**
A moving average where more recent prices receive higher weight. Computed with a decay factor of `2 / (period + 1)`. All EMAs in this platform use a 3× period warmup for stability.

**Evidence**
A documented finding from a completed study, recorded in [Evidence_Register.md](Evidence_Register.md). Evidence is the only basis for adjusting the conviction engine.

**EV (Expected Value)**
The probability-weighted average outcome. `EV = P(WIN) × avg_win_return + P(LOSS) × avg_loss_return`.

---

## F

**Factor**
A measurable, quantitative attribute of a stock, sector, or market that is tested for a relationship with forward returns. All factors are catalogued in [Factor_Catalog.md](Factor_Catalog.md).

**False Discovery**
A statistically significant finding that is, in reality, a chance result. Risk increases with the number of tests performed (multiple testing problem).

**Forward Return**
The percentage change in a stock's price over a fixed number of trading days following the signal date. Primary outcome variables. [→ Outcome_Definitions.md]

---

## G

**Gate**
A defined test that must be passed before the next stage of research or deployment begins. Six gates defined in [Acceptance_Criteria.md](Acceptance_Criteria.md).

---

## H

**Hypothesis**
A specific, falsifiable prediction about the relationship between a factor and an outcome. Registered in [Hypotheses.md](Hypotheses.md) before data is examined.

---

## I

**In-Sample (IS)**
Data from 2020-01-01 to 2023-12-31, used to develop and validate factor hypotheses.

**Independence (factor)**
Two factors are independent if knowing the value of one provides no information about the value of the other. Highly correlated factors are not independent. [→ Factor_Taxonomy.md]

---

## K

**KSE-100**
The benchmark index for all RS calculations on this platform. The KSE-100 represents the 100 largest companies on the Pakistan Stock Exchange by market capitalisation.

---

## L

**Lift**
The ratio of the conditional win rate (given a favourable factor value) to the unconditional base rate. Lift > 1 means the factor improves outcomes relative to the base. Lift = 1 means no effect.

**Look-Ahead Bias**
A form of data leakage where a factor calculation inadvertently uses data that was not available at the signal date. All factors in this platform are designed to avoid look-ahead bias; confirmed in [Assumption_Register.md](Assumption_Register.md).

---

## M

**Market Regime**
A classification of the broad market environment based on KSE-100 trend and volatility: TRENDING_UP, RANGING, TRENDING_DOWN, VOLATILE. Stored in `market_regime`. [→ Market_Regime_Framework.md]

**Minimum Sample Size**
The floor N required to make a claim. N < 30: insufficient. N ≥ 30: Weak. N ≥ 50: Moderate. N ≥ 200: Strong.

---

## N

**Near Pivot Days (near_pivot_days)**
A consecutive day counter: the number of unbroken days where `0 ≤ pivot_distance_pct ≤ 15`. Resets when the stock moves away from the pivot. Factor F-20.

**Null Result**
A study finding where no material relationship was found between the factor and the outcome. Null results are logged in the Evidence Register with the same rigour as positive findings.

---

## O

**Outcome Variable**
The dependent variable in a study — the thing being predicted. Defined in [Outcome_Definitions.md](Outcome_Definitions.md).

**Overhead Clear (overhead_clear)**
Binary factor F-19. Equals 1 if `max(high, 200 days) ≤ pivot_high × 1.15`. Indicates the stock is not deeply below a major prior high.

**Out-of-Sample (OOS)**
Data from 2024-01-01 onwards, reserved for validation only. Never used to design, fit, or calibrate factors.

---

## P

**Passive Hold**
A return calculation that assumes the position is held for exactly N trading days with no stop-loss or management. OV-01, OV-02, OV-03 are passive-hold outcomes.

**Pivot High**
The most recently confirmed local price maximum using a 10-bar left/10-bar right window. Stored as `pivot_high` in `stock_signals`. Computed from `prices_adjusted`. Factor F-10.

**Pivot Distance % (pivot_distance_pct)**
The distance from current close to the pivot high: `(pivot_high − close) / pivot_high × 100`. Positive = below pivot. Negative = above pivot (BOS). Factor F-11.

**PRE_BREAKOUT (setup_type)**
A setup type where `pivot_distance_pct BETWEEN 0 AND 3` AND `base_tightness < 8` AND `avg_vol_10d > 200,000`. The stock is approaching but has not yet exceeded the pivot.

**Pre-Registration**
Recording a hypothesis, methodology, and expected result before examining the data that will be used to test it. Required by [Research_Standards.md](Research_Standards.md).

**Primary Factor**
A factor that is not derived from another factor in this catalog. Listed in [Factor_Taxonomy.md](Factor_Taxonomy.md).

---

## R

**Realized R**
The risk-adjusted outcome metric: `(exit − entry) / (entry − stop)`. Positive = profit in units of initial risk. Available in `backtest_setups` as OV-05.

**Regime**
See Market Regime.

**Relative Strength (RS) Score**
The arithmetic difference in percentage returns between a stock and the KSE-100 over a given period. `rs_score_20 = stock_20d_return% − KSE100_20d_return%`. Factor F-01.

**Reproducibility**
The ability for another researcher to re-run a study and obtain the same result. Requirements defined in [Reproducibility_Policy.md](Reproducibility_Policy.md).

**RQ (Research Question)**
The broader question a study is intended to answer. One RQ can be addressed by multiple studies. Part of the RQ→H→S→E→D traceability chain. [→ Naming_Conventions.md]

---

## S

**setup_log**
The primary research table in `psx_data.db`. Contains 205,821 rows, each representing a dated signal for a stock with factor values and forward return outcomes.

**setup_type**
The classification of the signal: `BREAKOUT`, `PRE_BREAKOUT`, `RS_LEADER_MARKET`, or `RS_LEADER_SECTOR`.

**Stage 2 Bull (stage2_bull)**
Binary factor F-13. Equals 1 if `close > EMA20 > EMA50 > EMA200`. Indicates the stock is in a Weinstein Stage 2 uptrend (price above a rising EMA stack).

**Statistical Significance**
A measure of how likely an observed result would occur by chance. Conventional threshold: p < 0.05. Does not imply practical significance or replicability.

**Stratification**
Dividing the study population into subgroups (by regime, sector, setup type) and reporting results for each subgroup separately.

**Study**
A formal investigation of a hypothesis using `setup_log` data. Each study is registered with an ID (S-xxx), follows the protocol in [Research_Workflow.md](Research_Workflow.md), and produces an Evidence entry.

---

## V

**Validation**
Testing a finding on data that was not used to develop it. The gold standard is OOS validation. See [Validation_Framework.md](Validation_Framework.md).

**Violated Assumption**
An assumption that has been found to be false. Triggers a review of all dependent studies. Tracked in [Assumption_Register.md](Assumption_Register.md).

---

## W

**Weinstein Stage Analysis**
A technical analysis methodology that classifies stocks (and sectors) into four stages based on their relationship to moving averages: Stage 1 (basing), Stage 2 (advancing), Stage 3 (topping), Stage 4 (declining). This platform applies the methodology to PSX stocks and sectors.

**Win Rate**
The percentage of setups that produce a positive outcome (OV-04 = WINNER, i.e., `fwd_return_10d > 0`).

---

*Update this glossary when new terms are introduced or when existing definitions are refined. Every term used in a research document should be defined here.*
