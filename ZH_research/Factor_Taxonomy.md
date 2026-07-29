# Factor Taxonomy — PSX Quantitative Research Platform

> **Purpose:** Classification of all factors by type, scope, and research role. Helps identify which factors are likely to be correlated, which measure distinct phenomena, and how they should be combined.  
> **Related:** [Factor_Catalog.md](Factor_Catalog.md) · [Factor_Interaction_Matrix.md](Factor_Interaction_Matrix.md)

---

## Taxonomy Dimensions

Factors are classified across four dimensions:

| Dimension | Categories |
|---|---|
| **Scope** | Stock-level · Sector-level · Market-level |
| **Type** | Momentum · Trend · Volatility · Volume · Structure · Context |
| **Form** | Binary (0/1) · Ordinal (rank) · Continuous (ratio/score) · Categorical |
| **Independence** | Primary · Derived (computed from another factor on this platform) |

---

## Dimension 1 — Scope

### Stock-Level (F-01 to F-20, F-41, F-42)
Measure conditions specific to one stock. Vary independently across stocks on the same date.

### Sector-Level (F-21 to F-36)
Measure conditions of the sector the stock belongs to. Stocks in the same sector share these values on the same date.

### Market-Level (F-37 to F-40)
Measure the overall market condition. All stocks share these values on the same date.

**Research implication:** Market-level and sector-level factors are moderating variables — they do not vary across stocks on the same date. They define the environment within which stock-level factors operate.

---

## Dimension 2 — Type

### Momentum
Measures the rate of change or trend acceleration of relative performance.

| Factor ID | Factor Name |
|---|---|
| F-03 | RS Rank (Global) |
| F-05 | Rank Change |
| F-06 | Sector RS Rank |
| F-01 | RS Score 20d |
| F-02 | RS Score 50d |
| F-41 | RS Score Acceleration |
| F-26 | RS Inflection |
| F-32 | Sector RS New High |

### Trend
Measures the directional state of price relative to moving averages.

| Factor ID | Factor Name |
|---|---|
| F-13 | Stage 2 Bull |
| F-14 | Close Above EMA50 |
| F-15 | EMA50 Slope Positive |
| F-16 | Close Above EMA150 |
| F-17 | EMA150 Slope Positive |
| F-28 | Sector Stage |
| F-29 | Sector Above EMA |
| F-30 | Sector EMA Slope |
| F-37 | Market Regime |

### Volatility / Base Quality
Measures the degree of price compression and consolidation.

| Factor ID | Factor Name |
|---|---|
| F-07 | Base Tightness (BBW%) |
| F-18 | Base Duration |
| F-39 | KSE-100 ATR% |

### Volume
Measures trading activity relative to history.

| Factor ID | Factor Name |
|---|---|
| F-08 | Volume Contraction |
| F-09 | Average Volume 10d |
| F-25 | Sector Volume Ratio |
| F-42 | Volume on BOS Day |
| F-33 | Smart Money Net 5d |
| F-34 | Smart Money Net 20d |
| F-35 | Retail Net 20d |
| F-36 | Flow Direction |

### Structure / Price Level
Measures the stock's position relative to technical reference levels.

| Factor ID | Factor Name |
|---|---|
| F-10 | Pivot High |
| F-11 | Pivot Distance % |
| F-12 | BOS Flag |
| F-19 | Overhead Clear |
| F-20 | Near Pivot Days |
| F-31 | Sector Pivot Distance |

### Context / Market Condition
Measures the background environment, not the stock or sector itself.

| Factor ID | Factor Name |
|---|---|
| F-37 | Market Regime |
| F-38 | Regime Duration |
| F-39 | KSE-100 ATR% |
| F-40 | KSE-100 Return 20d |

### Composite
Weighted combinations of other factors.

| Factor ID | Factor Name | Components |
|---|---|---|
| F-27 | Sector Composite Score | F-21 (50%) + F-23 (30%) + F-25 (20%) |

---

## Dimension 3 — Form

| Form | Factor IDs | Research Note |
|---|---|---|
| **Binary** | F-12, F-13, F-14, F-15, F-16, F-17, F-19, F-26, F-29, F-32 | Use 2×2 tables and win-rate splits |
| **Ordinal** | F-03, F-06, F-22 | Use decile/quintile splits; avoid treating as continuous |
| **Continuous** | F-01, F-02, F-05, F-07, F-08, F-09, F-11, F-18, F-20, F-23–F-25, F-27, F-30–F-31, F-38–F-42 | Use quantile analysis; test for linearity |
| **Categorical** | F-28, F-36, F-37 | Use group comparison; one-hot for interaction studies |

---

## Dimension 4 — Independence

### Primary Factors
Cannot be derived from another factor in this catalog:
F-01, F-07, F-09, F-10, F-12, F-16, F-19, F-23, F-25, F-33, F-34, F-37, F-39, F-40

### Derived Factors (computed from primary factors)
| Derived Factor | Primary Input(s) |
|---|---|
| F-02 (RS Score 50d) | Same formula as F-01 at longer lag |
| F-03 (RS Rank) | F-01 ranked cross-sectionally |
| F-05 (Rank Change) | F-03, F-04 |
| F-06 (Sector RS Rank) | F-01 ranked within sector |
| F-11 (Pivot Distance %) | F-10, price |
| F-12 (BOS Flag) | F-11 |
| F-13 (Stage 2 Bull) | EMA20, EMA50, EMA200, price — all derived from price |
| F-14, F-15 | EMA50 + price |
| F-16, F-17 | EMA150 + price |
| F-18 (Base Duration) | F-07 (consecutive count) |
| F-20 (Near Pivot Days) | F-11 (consecutive count) |
| F-22 (Sector RS Rank) | F-21 ranked cross-sector |
| F-26 (RS Inflection) | F-22 change + F-21 sign |
| F-27 (Composite Score) | F-21, F-23, F-25 |
| F-28 (Sector Stage) | F-29, F-30 |
| F-41 (RS Acceleration) | F-01, F-02 |

**Research implication:** Pairs of derived factors share a common ancestor. Test only one from each derivation chain as a primary predictor; use others for robustness checks.

---

## Correlation Risk Map

Factor pairs that are likely to share substantial predictive information:

| Pair | Risk Level | Reason |
|---|---|---|
| F-01 and F-03 | High | Rank is a transform of score |
| F-01 and F-05 | Medium | Rank change is the derivative of rank |
| F-07 and F-18 | High | Duration counts consecutive days of tightness |
| F-11 and F-20 | High | Both measure proximity to pivot over time |
| F-13 and F-16 | High | Stage 2 Bull requires EMA150 condition |
| F-14 and F-13 | High | EMA50 above is a sub-condition of Stage 2 |
| F-22 and F-28 | Medium | Strong sectors tend to be Stage 2 |
| F-21 and F-27 | High | Composite score is 50% RS score |

---

*Factor IDs must match exactly the IDs in [Factor_Catalog.md](Factor_Catalog.md). Update this document when new factors are added to the catalog.*
