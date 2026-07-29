# Master Research Plan — PSX Quantitative Research Platform

> **Version:** 1.0 · **Date:** 2026-07-01  
> **Horizon:** 12–24 months  
> **Purpose:** Primary governing document for the entire research program. Defines what will be studied, in what order, to what standard, and how the Conviction Engine will be built from the evidence.  
> **This document takes precedence** when there is ambiguity about sequencing or priority. All other documents in this workspace are referenced from here and serve as supporting detail.

---

## 1. Executive Overview

### Mission

Build a Conviction Engine for the PSX Explorer page that assigns an evidence-based score to every breakout and pre-breakout signal, drawn from 205,821 historical setups spanning 2020–2026. The score must be:

- **Grounded:** every component traceable to a completed study with documented evidence
- **Calibrated:** score levels correspond to empirically observed win-rate ranges
- **Honest:** no factor enters without Moderate or higher confidence; limitations are explicit
- **Useful:** deployed to the Explorer page and visible to the trader before a decision is made

### Starting Point

The platform is in Phase 1 (Foundation). The documentation architecture is complete. No studies have been conducted. The database is fully populated. The first study can begin immediately.

### End Point

A deployed conviction score on the Explorer page, supported by a validated study set, with a live monitoring plan and defined failure criteria.

### What Success Looks Like

Twelve months from now: the V1 Conviction Engine is in production, all foundation factors are validated, and OOS data from 2024 is confirming — or refining — the in-sample findings. Twenty-four months from now: the engine has 12 months of live performance data, V1.1 regime-conditional weights are under development, and the Historical Similarity feature is in design.

---

## 2. Research Principles

This program is governed by the standards defined in the existing documentation. Rather than repeating those standards here, this plan references them by location.

| Principle | Governing Document |
|---|---|
| Pre-registration required before data examination | [Research_Standards.md](Research_Standards.md) |
| Minimum N thresholds (30/50/200) | [Statistical_Guidelines.md](Statistical_Guidelines.md) |
| In-sample / out-of-sample split fixed at 2023-12-31 | [Validation_Framework.md](Validation_Framework.md) |
| Null results recorded with equal rigour | [Evidence_Standards.md](Evidence_Standards.md) |
| No factor enters the engine without evidence | [Conviction_Engine_Specification.md](Conviction_Engine_Specification.md) |
| All studies pass the bias checklist | [Bias_Checklist.md](Bias_Checklist.md) |
| All studies pass the review checklist before closing | [Research_Review_Checklist.md](Research_Review_Checklist.md) |
| Known limitations are acknowledged in every finding | [Known_Limitations.md](Known_Limitations.md) |

**One overriding rule:** The OOS period (2024-01-01 onwards) is never examined for any study until the IS study is complete and the finding is recorded. Premature OOS inspection is the single most dangerous bias on this platform.

---

## 3. Research Inventory

The following research areas have been identified. Each area contains one or more studies that must be executed.

### 3.1 Base Rate Characterisation
**What it covers:** The unconditional win rates, return distributions, and N counts for each setup type. This is the foundation for all subsequent research — every finding is expressed relative to the base rate.

**Key questions:**
- What is the win rate (OV-04) for each of the four setup types?
- What is the mean and median forward return (OV-01, OV-02) for each setup type?
- How does the base rate vary by year? Is there trend or seasonality?
- How are setups distributed across sectors and regimes?

**Factors involved:** None — this is unconditional characterisation.

---

### 3.2 Relative Strength / Momentum
**What it covers:** Whether stocks with superior relative strength at the time of the signal produce better forward outcomes than those with weaker relative strength.

**Factors:** F-01 (RS Score 20d), F-02 (RS Score 50d), F-03 (RS Rank), F-05 (Rank Change), F-06 (Sector RS Rank), F-41 (RS Acceleration)

**Key questions:**
- Does RS rank at signal time predict 10d and 20d forward return?
- Is the RS score linearly related to outcomes, or does a threshold exist?
- Does improving RS rank (rank change) add information beyond the current rank level?
- Does short-term RS acceleration (F-41: rs_20 minus rs_50) predict outcomes?

---

### 3.3 Trend Structure (Weinstein Stage)
**What it covers:** Whether a stock's position within the Weinstein four-stage framework at the time of the signal predicts forward outcomes.

**Factors:** F-13 (Stage 2 Bull), F-14 (Close Above EMA50), F-15 (EMA50 Slope Positive), F-16 (Close Above EMA150), F-17 (EMA150 Slope Positive)

**Key questions:**
- Do Stage 2 Bull stocks (F-13) produce meaningfully better outcomes than non-Stage 2 stocks?
- Does the full EMA stack (20 > 50 > 200) add value over simply being above EMA150?
- Is EMA slope confirmation (F-15, F-17) additive to the price-vs-EMA binary?

---

### 3.4 Base Quality (Volatility / Consolidation)
**What it covers:** Whether the tightness and duration of a consolidation phase before the signal predicts breakout quality.

**Factors:** F-07 (Base Tightness), F-18 (Base Duration), F-08 (Volume Contraction)

**Key questions:**
- Do stocks with tighter bases (lower F-07) produce better breakout outcomes?
- Does the length of the consolidation (F-18) matter independently of tightness?
- Does declining volume during the base (F-08) predict better post-breakout outcomes?

---

### 3.5 Price Structure (Pivot / Overhead)
**What it covers:** The stock's position relative to its pivot high and whether historical overhead supply affects outcomes.

**Factors:** F-10 (Pivot High), F-11 (Pivot Distance %), F-12 (BOS Flag), F-19 (Overhead Clear), F-20 (Near Pivot Days)

**Key questions:**
- Does the absence of overhead supply (F-19) improve BREAKOUT outcomes?
- Does a longer accumulation near the pivot (F-20) predict better breakouts?
- For PRE_BREAKOUT setups, does the proximity to the pivot (within 1% vs within 3%) predict different outcomes?

---

### 3.6 Volume Behaviour
**What it covers:** Whether volume conditions at and around the signal date are predictive of forward outcomes.

**Factors:** F-08 (Volume Contraction), F-09 (Average Volume 10d), F-42 (Volume on BOS Day)

**Key questions:**
- Does BOS day volume (F-42) correlate with 10d and 20d forward returns?
- Is high BOS volume alone sufficient, or does it require prior volume contraction?
- Does the absolute volume level (F-09) independently predict outcomes beyond the liquidity filter already applied?

---

### 3.7 Market Regime Conditioning
**What it covers:** Whether the broad market environment at the time of the signal moderates the predictive value of all other factors.

**Factors:** F-37 (Market Regime), F-38 (Regime Duration), F-39 (KSE-100 ATR%), F-40 (KSE-100 Return 20d)

**Key questions:**
- Do base rates differ materially across TRENDING_UP, RANGING, and TRENDING_DOWN regimes?
- Which individual factors are most regime-sensitive (predictive only in some regimes)?
- Does the duration of the current regime (F-38) affect signal quality?
- Does market volatility (F-39) moderate any factor's predictive value?

**Note:** Regime conditioning is both a standalone research area and a cross-cutting layer that must be applied to every other research area. It is studied twice: once as a standalone factor, and once as a moderator across all validated single-factor findings.

---

### 3.8 Sector Alignment
**What it covers:** Whether a stock's sector conditions at the time of the signal predict forward outcomes, and whether being in a strong sector amplifies the stock's own signals.

**Factors:** F-22 (Sector RS Rank), F-23 (Sector Breadth Score), F-27 (Sector Composite Score), F-28 (Sector Stage), F-29 (Sector Above EMA), F-32 (Sector RS New High)

**Key questions:**
- Do stocks in Weinstein Stage 2 sectors produce better breakout outcomes than those in Stage 1/3/4 sectors?
- Is sector RS rank (F-22) additive to stock RS rank (F-03)?
- Does sector breadth (F-23) predict the durability of individual stock breakouts?

---

### 3.9 Factor Interactions
**What it covers:** Whether pairs of validated factors have multiplicative (superadditive) or dampening (subadditive) effects when combined.

**Interaction pairs:** Defined in [Factor_Interaction_Matrix.md](Factor_Interaction_Matrix.md), Tier 1 through Tier 3.

**Key questions:**
- Do stocks that are both RS leaders AND in Stage 2 outperform either condition alone?
- Is the combination of a tight base AND near-pivot position the most predictive state?
- Does overhead clear multiply the Stage 2 effect, or is it independent?

**Dependency:** Cannot begin until the individual factor studies confirm which factors are worth combining. No interaction study opens before both constituent single-factor studies are complete.

---

### 3.10 Conviction Engine Assembly
**What it covers:** Combining validated single-factor and interaction findings into a single weighted score.

**Key questions:**
- What weights should each validated factor receive, proportional to its effect size?
- Does the linear additive model (weighted sum) produce better calibration than equal weighting?
- Are there any factors that are individually validated but provide zero marginal value in the combined model (full redundancy)?

**Dependency:** All foundation single-factor studies and at least the Tier 1 interaction studies must be complete.

---

### 3.11 Probability Calibration
**What it covers:** Ensuring the conviction score's numeric levels correspond to empirically observed win rates.

**Key questions:**
- Does a score of 70 correspond to approximately 70% observed win rate?
- Does the score discriminate across the full range (0–100), or does it cluster in a narrow band?
- What are the empirical win rates for each of the four score bands (Low/Moderate/High/Very High)?

**Dependency:** Requires the V1 engine to be constructed and applied to the in-sample population.

---

### 3.12 Out-of-Sample Validation
**What it covers:** Testing whether the IS findings replicate in the 2024+ OOS period.

**Key questions:**
- Do factor directions (positive/negative predictive value) hold in OOS?
- Is the win-rate spread between Very High and Low conviction preserved in OOS?
- Are there any factors that reverse direction OOS (potential overfitting)?

**Dependency:** The OOS period must not be examined until IS studies are complete and the factor set is finalised.

---

### 3.13 Historical Similarity Engine
**What it covers:** A lookup system that finds the N most similar historical setups for any live signal, displaying their outcomes as context alongside the conviction score.

**Key questions:**
- What similarity metric (weighted Euclidean distance over normalised factors) produces coherent groupings?
- Does the set of N=10 most similar setups produce a win rate that tracks the conviction score?

**Dependency:** Requires the V1 factor set and weights (the normalisation reference must be finalised). Designed in [Historical_Similarity_Design.md](Historical_Similarity_Design.md).

---

## 4. Dependency Graph

The following dependency structure governs sequencing. A later stage cannot begin until the stages it depends on are substantially complete.

```
STAGE 0 — FOUNDATION (Complete)
  Documentation architecture, governance, factor catalog,
  outcome definitions, data quality policy, assumption register.
  ▼

STAGE 0.5 — DATASET VALIDATION (New — must complete before Stage 1)
  D-001: Dataset Health Report
    Missing values, NULL rates, symbol coverage over time,
    sector coverage, data completeness across date range.
  D-002: Outcome Variable Validation
    Forward return correctness, look-ahead check,
    incomplete recent rows (window not yet closed), holiday handling.
  D-003: Sample Independence Assessment
    Effective independent N per setup type.
    Quantify autocorrelation in repeated signals per symbol.
  D-004: Market Coverage Analysis (can run parallel with Stage 1)
    What fraction of the PSX universe ever generates a setup?
    Concentration and representativeness of the setup universe.
  D-005: Temporal Stability Assessment (can run parallel with Stage 1)
    Structural breaks in setup frequency or quality over time.

  Gate: D-001 through D-003 must be closed before Stage 1 opens.
  Rationale: Factor research on an unvalidated dataset produces
  overconfident findings. Uncertainty reduction first.
  ▼

STAGE 1 — BASE RATE CHARACTERISATION
  Unconditional win rates, return distributions, N counts
  for all four setup types, stratified by year and regime.
  (No hypothesis to disprove — pure descriptive statistics.)
  Must complete BEFORE all other stages.
  ▼

STAGE 2 — SINGLE-FACTOR STUDIES (can run in parallel within the stage)
  │
  ├── Relative Strength (RS Score, RS Rank, RS Acceleration)
  ├── Trend Structure (Stage 2, EMA conditions)
  ├── Base Quality (Tightness, Duration, Volume Contraction)
  ├── Price Structure (Overhead Clear, Near Pivot Days)
  ├── Volume Behaviour (BOS Volume, Volume Contraction)
  └── Market Regime (standalone regime effect on all setups)
  ▼

STAGE 3 — SECTOR STUDIES (parallel with late Stage 2)
  Sector Stage, Sector RS Rank, Sector Breadth.
  Can begin as soon as base rate study is complete.
  ▼

STAGE 4 — REGIME CONDITIONING (cross-cutting layer)
  Apply regime stratification to every Stage 2 finding.
  Identify which factors are regime-sensitive.
  Begins after Stage 2 core RS and Stage studies are complete.
  ▼

STAGE 5 — FACTOR INTERACTION STUDIES
  Tier 1 interactions (highest priority pairs).
  Tier 2 interactions (structural pairs).
  Cannot begin until both constituent Stage 2 studies are complete.
  ▼

STAGE 6 — CONVICTION ENGINE V1 CONSTRUCTION
  Assign weights from effect sizes. Build additive score.
  Run IS calibration check.
  Depends on Stage 4 and Tier 1 interactions from Stage 5.
  ▼

STAGE 7 — OUT-OF-SAMPLE VALIDATION
  Apply V1 engine to 2024+ data.
  Confirm direction and spread.
  First time OOS data is examined.
  ▼

STAGE 8 — PROBABILITY CALIBRATION
  Map score levels to empirical win rates.
  Recalibrate if mapping is non-monotonic.
  Depends on Stage 7 OOS validation passing.
  ▼

STAGE 9 — HISTORICAL SIMILARITY ENGINE
  Build the N-nearest-historical-analogues lookup.
  Depends on Stage 6 factor set and weights.
  Can run in parallel with Stage 7–8.
  ▼

STAGE 10 — EXPLORER INTEGRATION
  Conviction score and historical similarity displayed
  on the Explorer page.
  Depends on all acceptance gates in Acceptance_Criteria.md passing.
  ▼

STAGE 11 — LIVE MONITORING AND V1.1 DESIGN
  90-day post-deployment monitoring.
  Design of regime-conditional weights for V1.1.
  Continuous — runs in parallel with ongoing research.
```

---

## 5. Prioritized Research Roadmap

Studies are ranked by a composite of four criteria:

| Criterion | Weight | Rationale |
|---|---|---|
| **Impact** | High | How directly does this study inform the conviction engine? |
| **Dependency unlock** | High | Does completing this unblock many other studies? |
| **Business value** | Medium | Does the trader benefit even without a full engine? |
| **Difficulty** | Medium | Does the study require complex methodology or just clean queries? |

### Priority Tier 1 — Must Complete First (blocking)

| Study ID | Title | Impact | Unlocks | Effort |
|---|---|---|---|---|
| S-001 | Base Rate Characterisation | Critical | All other studies | Low |
| S-002 | RS Rank vs 10d Forward Return (BREAKOUT) | Critical | IX-01, IX-04, IX-05, engine | Low |
| S-003 | Stage 2 Condition vs 10d Forward Return (BREAKOUT) | Critical | IX-02, IX-08, IX-15, engine | Low |
| S-004 | Market Regime Effect on Base Rates | High | Stage 4 (all regime conditioning) | Low |

### Priority Tier 2 — High Impact, Early

| Study ID | Title | Impact | Unlocks | Effort |
|---|---|---|---|---|
| S-005 | Base Tightness vs 10d Forward Return | High | IX-03, IX-06 | Low |
| S-006 | Overhead Clear vs 10d Forward Return | High | IX-02, IX-11 | Low |
| S-007 | Near Pivot Days vs 10d Forward Return | High | IX-03, IX-07 | Low |
| S-008 | Sector Stage vs Stock-Level Outcomes | High | IX-10, IX-15 | Medium |
| S-009 | RS Rank vs 10d Return — All Setup Types (not just BREAKOUT) | High | Engine breadth | Medium |

### Priority Tier 3 — Important, After Tier 1–2

| Study ID | Title | Impact | Unlocks | Effort |
|---|---|---|---|---|
| S-010 | BOS Day Volume vs Forward Return | Medium | IX-13 | Medium |
| S-011 | RS Acceleration (rs_20 minus rs_50) vs Forward Return | Medium | Engine refinement | Low |
| S-012 | Sector RS Rank vs Stock Outcomes | Medium | Multi-factor work | Medium |
| S-013 | Volume Contraction vs Forward Return | Medium | IX-06, IX-13 | Low |
| S-014 | BREAKOUT Signal Deduplication Analysis | Medium | Methodology fix | Medium |
| S-015 | 5d vs 10d vs 20d Horizon Comparison (same factors) | Medium | OV choice for engine | Medium |

### Priority Tier 4 — Interaction Studies (after Tier 1–3 complete)

| Study ID | Title | Prerequisite Studies |
|---|---|---|
| S-020 | RS Rank × Market Regime (IX-01) | S-002, S-004 |
| S-021 | Stage 2 × Overhead Clear (IX-02) | S-003, S-006 |
| S-022 | Base Tightness × Near Pivot Days (IX-03) | S-005, S-007 |
| S-023 | Sector Stage × RS Rank (IX-04) | S-002, S-008 |
| S-024 | RS Score × Market Regime (IX-05) | S-002, S-004 |

### Priority Tier 5 — Engine and Calibration

| Study ID | Title | Prerequisite |
|---|---|---|
| S-030 | V1 Factor Weight Calibration | Tier 1–4 complete |
| S-031 | V1 IS Calibration Check | S-030 |
| S-032 | V1 OOS Validation | S-031 passes Gate 2 |
| S-033 | Probability Calibration | S-032 passes Gate 3 |

---

## 6. Milestone Plan

### Milestone 0 — Foundation Complete ✅
**Definition:** All governance, standards, and documentation architecture is in place.  
**Status:** Complete as of 2026-07-01.

---

### Milestone 0.5 — Dataset Validated
**Definition:** The research dataset is confirmed trustworthy for empirical research. Missing values are characterised, outcome variables are verified correct, and the effective independent sample size is known.

**What is studied:** D-001 (Dataset Health), D-002 (Outcome Validation), D-003 (Sample Independence)

**Rationale:** Factor research on an unvalidated dataset produces overconfident findings. These studies reduce uncertainty about the research instrument before any factor is studied. This is how institutional research programs operate — the dataset is not assumed; it is verified.

**What will be known after Milestone 0.5:**
- NULL rates and missing value patterns across all key columns
- Whether forward returns contain any look-ahead contamination
- Whether recent rows with unclosed windows have been correctly excluded
- The effective independent N for each setup type (true statistical power)
- Whether any columns have structural anomalies that require correction

**Milestone complete when:** D-001, D-002, and D-003 are closed with Evidence Register entries. Any data quality issues found are documented in Data_Quality_Policy.md. A "Dataset Validation Summary" paragraph is added to this section confirming the dataset is fit for factor research.

---

### Milestone 1 — Base Rates Established
**Definition:** The unconditional performance characteristics of all four setup types are documented, reviewed, and recorded in the Evidence Register.

**What is studied:** S-001 (Base Rate Characterisation)

**What will be known after Milestone 1:**
- Win rates per setup type (BREAKOUT, PRE_BREAKOUT, RS_LEADER_MARKET, RS_LEADER_SECTOR)
- Mean and median 10d and 20d forward returns per setup type
- Annual variation in base rates (2020, 2021, 2022, 2023 in-sample)
- Distribution of setups by market regime
- Distribution of setups by sector

**Milestone complete when:** S-001 is closed, evidence recorded in Evidence Register, base rate table added to Data_Dictionary.md.

---

### Milestone 2 — Core Factors Validated
**Definition:** The six most impactful single-factor studies are complete. Each has a recorded finding with confidence level.

**What is studied:** S-002 (RS Rank), S-003 (Stage 2), S-004 (Market Regime), S-005 (Base Tightness), S-006 (Overhead Clear), S-007 (Near Pivot Days)

**What will be known after Milestone 2:**
- Which of the six core factors are predictive, at what confidence level
- Direction and magnitude of each factor's effect
- Which factors are regime-sensitive (from S-004)
- Provisional ranking of factors by effect size (input to engine weights)

**Milestone complete when:** All six studies are closed with Evidence Register entries and Factor Catalog predictive values updated.

---

### Milestone 3 — Sector and Volume Validated
**Definition:** Sector-level and volume-based factors have completed studies.

**What is studied:** S-008 (Sector Stage), S-010 (BOS Volume), S-012 (Sector RS Rank), S-013 (Volume Contraction)

**What will be known after Milestone 3:**
- Whether sector-level factors add value beyond stock-level factors
- Whether volume behaviour is predictive independently of the other factors
- First indication of which research areas to prioritise in interaction studies

**Milestone complete when:** All four studies closed with evidence entries.

---

### Milestone 4 — Regime Conditioning Complete
**Definition:** The regime-conditioning layer has been applied across all validated single-factor findings from Milestones 2 and 3.

**What is studied:** Regime-stratified re-analysis of each Milestone 2–3 study; standalone S-004 regime effect study.

**What will be known after Milestone 4:**
- Which factors are regime-universal (predictive in all regimes) vs regime-specific
- Provisional regime adjustment factors for the V1.1 engine (documented even if not yet implemented)
- Whether any factor reverses direction in a specific regime (risk flag for engine)

**Milestone complete when:** A Regime Conditioning Summary document is produced (one page per factor) and added to the Evidence Register.

---

### Milestone 5 — Tier 1 Interaction Studies Complete
**Definition:** The five highest-priority factor combinations have been studied.

**What is studied:** S-020 through S-024 (Tier 1 interactions: IX-01 through IX-05)

**What will be known after Milestone 5:**
- Whether the most important factor pairs produce additive, superadditive, or redundant effects
- The definitive factor set for V1 engine construction (no more single-factor unknowns blocking the engine)
- Any interaction that reveals a factor should be removed from the engine (full redundancy)

**Milestone complete when:** All five studies closed with evidence entries and Factor Interaction Matrix updated.

---

### Milestone 6 — Conviction Engine V1 Constructed
**Definition:** The V1 additive weighted conviction engine is built, weight-assigned, and passes the IS calibration check (Gate 2 in Acceptance_Criteria.md).

**What is studied:** S-030 (weight calibration), S-031 (IS calibration check)

**What will be known after Milestone 6:**
- The full factor set and weights for V1
- Whether the score is monotonically increasing in IS win rate
- Whether the discrimination spread (Very High vs Low) meets the ≥10pp threshold in-sample

**Milestone complete when:** S-030 and S-031 are closed. V1 is registered in Model_Registry.md. Gates 1 and 2 of Acceptance_Criteria.md are marked Pass.

---

### Milestone 7 — OOS Validation Complete
**Definition:** V1 is applied to the 2024-01-01 onwards data. OOS win-rate spread is confirmed. All factor directions hold in OOS.

**What is studied:** S-032 (OOS Validation), S-033 (Probability Calibration)

**What will be known after Milestone 7:**
- Whether V1 generalises beyond the IS period
- Whether any factor reverses direction in OOS (failure criterion)
- Calibrated score-to-win-rate mapping for all four score bands
- Gates 3–6 of Acceptance_Criteria.md status

**Milestone complete when:** S-032 and S-033 closed. All six acceptance gates marked Pass. OOS validation result added to Model_Registry.md.

---

### Milestone 8 — Historical Similarity Engine
**Definition:** The historical analogue lookup is implemented and validated to produce coherent groupings (similar factor profiles → similar outcomes).

**What is studied:** Historical Similarity Engine design validation

**Milestone complete when:** The feature design is finalised, the methodology is validated, and the engine is ready for development.

---

### Milestone 9 — Explorer Integration
**Definition:** The V1 conviction score and (optionally) historical similarity are visible on the Explorer page. All monitoring infrastructure is in place.

**Milestone complete when:** Conviction score is live in production. Monitoring plan is active. Failure criteria are being tracked.

---

### Milestone 10 — V1.1 Design (12-month horizon)
**Definition:** After 90+ days of live V1 operation, the regime-conditional weight design for V1.1 is complete and ready for study.

**Milestone complete when:** V1.1 factor weight candidates are documented, and sufficient OOS data exists to begin V1.1 design studies.

---

## 7. Deliverables

| Milestone | Deliverable | Location |
|---|---|---|
| M0 | Complete documentation architecture (32 documents) | `ZH_research/` |
| M1 | Base rate table with win rates per setup type by year and regime | Evidence_Register.md |
| M1 | Updated Factor Catalog — base rate entries | Factor_Catalog.md |
| M2 | Six evidence entries (one per core factor) | Evidence_Register.md |
| M2 | Updated Factor Catalog — predictive value for F-01, F-03, F-07, F-12, F-13, F-19, F-20 | Factor_Catalog.md |
| M3 | Four evidence entries (sector and volume factors) | Evidence_Register.md |
| M4 | Regime Conditioning Summary (one paragraph per factor) | Evidence_Register.md (or dedicated sub-document) |
| M5 | Five interaction evidence entries | Evidence_Register.md |
| M5 | Updated Factor Interaction Matrix (completed rows) | Factor_Interaction_Matrix.md |
| M6 | V1 engine factor weights table | Model_Registry.md |
| M6 | IS calibration chart (score band → observed IS win rate) | Model_Registry.md |
| M7 | OOS validation results (direction, spread, N per band) | Model_Registry.md |
| M7 | Calibrated score-to-win-rate mapping | Model_Registry.md |
| M8 | Historical Similarity methodology document | Historical_Similarity_Design.md (updated) |
| M9 | Live V1 engine in Explorer page | Application code (out of scope for this workspace) |
| M9 | Monitoring dashboard baseline metrics | Research_Log.md |
| M10 | V1.1 design document | Score_Evolution_Roadmap.md (updated) |

---

## 8. Success Criteria

### Milestone 1 Success
- Base rates are established for all four setup types
- N is sufficient in each cell (N ≥ 200 per setup type)
- Annual variation is visible (year-by-year breakdown exists)
- The base rate table is referenced in all subsequent studies

### Milestone 2 Success
- All six studies have evidence entries
- Each entry has an assigned confidence level (Weak/Moderate/Strong)
- At least three factors achieve Moderate or Strong confidence
- No factor shows a directional finding based on fewer than 30 observations per group
- All six studies have passed the Research Review Checklist

### Milestone 3 Success
- Sector and volume factor predictive values are documented
- It is clear whether sector factors add value beyond stock factors (additive or redundant)
- The Factor Catalog is fully updated through M3

### Milestone 4 Success
- Every validated factor from M2–M3 has a regime-conditional result
- At least two factors are identified as regime-sensitive (or it is confirmed that no factors are)
- The regime conditioning results are internally consistent (no contradictions)

### Milestone 5 Success
- All five Tier 1 interaction studies complete with evidence entries
- For each pair: the interaction effect is quantified (additive, superadditive, or redundant)
- The engine factor set is finalised — no ambiguity about what goes in

### Milestone 6 Success
- V1 score is monotonically increasing in IS win rate
- Very High scores have IS win rate at least 10pp above Low scores
- Score distribution is not degenerate (no single band captures > 70% of signals)
- V1 is registered in Model_Registry.md with full documentation

### Milestone 7 Success
- OOS win rate spread (Very High vs Low) is ≥ 10pp
- No factor reverses direction OOS
- OOS overall win rate is within ±10pp of IS overall win rate
- All six acceptance gates in Acceptance_Criteria.md are marked Pass

### Milestone 8 Success
- Similar factor profiles (distance score < threshold) produce similar outcome distributions
- The similarity lookup does not expose any look-ahead bias (historical setups are always older than the live signal)

### Milestone 9 Success
- Conviction score visible on Explorer page
- Failure criteria monitoring is active
- Trader can access a plain-language explanation of what the score means

### Milestone 10 Success
- V1 has run for at least 90 trading days with satisfactory FC monitoring results
- V1.1 candidate weights are documented
- A V1.1 development study plan exists in Research_Pipeline.md

---

## 9. Risks

### Risk Register — Program Level

The following risks are specific to the overall research program and supplement the limitations documented in [Known_Limitations.md](Known_Limitations.md).

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| PR-01 | OOS data (2024+) is too thin to validate the engine (N < 200) | Medium | High | Begin OOS validation only when 2 years of OOS data exist. If N is insufficient, extend the IS period. |
| PR-02 | No factor achieves Moderate confidence after Milestone 2 | Low | Critical | If this occurs, the conviction engine framework requires redesign. The research stops and findings are documented as negative. New research areas (fundamental data, news) would need to be considered. |
| PR-03 | PSX market structure changes materially during the research period | Low | High | Monitor the base rate rolling window. If win rates in the live period diverge from IS by > 10pp, investigate before proceeding. |
| PR-04 | Research fatigue — loss of sustained attention over 12–24 months | Medium | High | Milestone structure keeps the program chunked into achievable blocks. M1 and M2 are designed to produce visible results within 1–2 months. |
| PR-05 | Factor interactions are all redundant — no superadditive combinations found | Medium | Medium | The engine can still be built from independent single factors. Redundancy findings are documented and the engine uses the subset with non-zero marginal value. |
| PR-06 | BREAKOUT signal duplication (L-08) inflates win rates and research sequencing is compromised | High | High | S-014 (Deduplication Analysis) must be completed before M2 conclusions are drawn. If deduplication changes the win rate by > 5pp, all M2 studies must be rerun on the deduplicated population. |
| PR-07 | The OOS period (2024+) is characterised by a regime not represented in IS | Medium | Medium | Regime distribution in OOS should be verified in S-001. TRENDING_DOWN observations in OOS will be flagged. |
| PR-08 | Conviction Engine V1 fails Gate 3 (OOS validation) | Medium | High | Return to Stage 5 (interactions) and identify which factor(s) are causing degradation. Remove or reduce-weight that factor and re-run OOS. |

**Cross-reference:** Known limitations L-01 through L-13 are the standing data and market risks. Program risks PR-01 through PR-08 are the execution-level risks. Both sets must be considered when interpreting any finding.

---

## 10. Recommended Research Sequence

The following is the actual order in which studies should be conducted. This sequence maximises learning, minimises wasted effort, and respects the dependency graph.

### Immediate — Month 1: Dataset Validation First

**Step 0: D-001 — Dataset Health Report (before any factor study)**

Characterise the research instrument before using it. Missing values, NULL rates, symbol coverage over time, sector distribution, date range completeness. Any anomaly found here changes the methodology for every subsequent study. Cannot be deferred.

**Step 0b: D-002 — Outcome Variable Validation**

Confirm that `fwd_return_10d`, `fwd_return_20d`, and `fwd_return_5d` are computed correctly. Check that no look-ahead contamination exists. Confirm that rows where the window hasn't yet closed are identifiable and excluded. Holiday/non-trading-day handling confirmed.

**Step 0c: D-003 — Sample Independence Assessment**

Quantify serial correlation: how many consecutive BREAKOUT rows typically share a single breakout event? Extend to all four setup types. The result defines the effective independent N and directly determines the confidence levels that can be claimed throughout the entire research program.

---

### Months 1–2: First Factor Studies (after D-001 through D-003 close)

**Step 1: S-001 — Base Rate Characterisation (first)**

Run this before anything else. It establishes the denominator for every subsequent win-rate comparison. Without the base rate, no other finding can be interpreted. Effort is low; impact on everything downstream is maximum.

- Query all `setup_log` rows where `fwd_return_10d IS NOT NULL`
- Compute win rate (OV-04), mean return (OV-01), median return, N for each setup type
- Stratify by year (2020, 2021, 2022, 2023) and by market regime
- Record in Evidence Register as E-001

**Step 2: S-014 — BREAKOUT Deduplication Analysis (second)**

Before studying BREAKOUT factors, quantify the duplication problem. Compute the win rate on: (a) all BREAKOUT rows; (b) first-day-only BREAKOUT rows (transition day). Measure the difference. If the difference is > 3pp, all BREAKOUT studies must use the deduplicated population. If < 3pp, the raw population is acceptable. This takes one session and potentially changes the methodology of six subsequent studies.

---

### Near-Term — Months 2–4

**Step 3: S-002 — RS Rank vs 10d Return (BREAKOUT)**

The single factor most likely to be validated. RS rank is the clearest theoretical predictor. Study on BREAKOUT setups first (the largest and most studied population). Use the deduplicated population if S-014 required it. Result will inform engine weight and unlock four Tier 1 interaction studies.

**Step 4: S-003 — Stage 2 Condition vs 10d Return (BREAKOUT)**

Second in priority because Stage 2 is the other cornerstone of the framework. Closely related to RS rank but measures trend structure rather than momentum. Both studies can run in consecutive sessions — they share the same population.

**Step 5: S-004 — Market Regime Effect on Base Rates**

Study the regime effect immediately after RS and Stage 2 are confirmed, because the regime is the most important stratifier for all subsequent work. Knowing the regime effect on base rates allows all future studies to be interpreted in the right context.

---

### Short-Term — Months 3–5

**Steps 6–8: S-005, S-006, S-007 — Base Quality, Overhead Clear, Near Pivot Days**

These three studies can be run in quick succession — all use the BREAKOUT population and a simple factor-quartile-vs-outcome methodology. They are lower analytical complexity than the first three studies and should be completable within 2–3 sessions each.

**Step 9: S-009 — RS Rank vs Return across All Setup Types**

Once RS is validated on BREAKOUT, test whether the same effect holds for PRE_BREAKOUT, RS_LEADER_MARKET, and RS_LEADER_SECTOR. This is a breadth study using S-002's methodology. A consistent effect across all four types strengthens the factor's claim to engine inclusion.

---

### Medium-Term — Months 5–8

**Steps 10–13: S-008, S-010, S-012, S-013 — Sector and Volume Studies**

These require slightly more data engineering (joining sector_signals to setup_log, computing BOS day volume). They are grouped here because they can share setup work. The sector studies (S-008, S-012) address whether the engine needs a sector layer.

**Step 14: Regime Conditioning Layer (Milestone 4)**

Apply regime stratification retrospectively to all validated single-factor findings from Steps 3–13. This is not a single study but a systematic re-analysis. The goal is to identify which factors are regime-universal vs regime-specific.

---

### Months 8–12

**Steps 15–19: Tier 1 Interaction Studies (S-020 through S-024)**

Study the five highest-priority factor combinations. These take more analytical effort because they require 2×2 (or 2×4) tables and interaction terms. The sequencing mirrors Tier 1 priority: IX-01 (RS × Regime) first, then IX-02 (Stage 2 × Overhead), then IX-03 (Base Tightness × Near Pivot).

**Step 20: S-030 — V1 Weight Calibration**

Assign weights to the validated factors proportional to their effect sizes. Document the weight rationale. Build the score formula.

**Step 21: S-031 — IS Calibration Check**

Apply V1 to the in-sample population. Verify monotonicity. Verify discrimination. Adjust weights if needed (document adjustments and rationale).

---

### Months 12–18

**Step 22: S-032 — OOS Validation (the most important single test)**

Open the 2024+ data for the first time. Apply V1. Check direction, spread, calibration. This is the moment of truth for the entire research program. Allow a full month of analysis and documentation. Do not rush.

**Step 23: S-033 — Probability Calibration**

After OOS validation, calibrate the score-to-win-rate mapping using the combined IS + OOS population. Produce the final calibrated score levels.

---

### Months 15–20 (parallel track)

**Step 24: Historical Similarity Engine Validation**

Once the factor set and weights are finalised (after S-030), the historical similarity methodology can be validated independently of OOS testing. These two work streams can run in parallel.

---

### Month 20–24

**Steps 25+: Explorer Integration, Live Monitoring, V1.1 Design**

The research program transitions from study-mode to monitoring-mode. Research continues on V1.1 design (regime-conditional weights) using the live data accumulating in 2025–2026.

---

## Sequencing Consistency Review

The following potential sequencing problems have been identified and resolved:

| Problem | Resolution |
|---|---|
| BREAKOUT duplication inflates M2 win rates if not caught early | S-014 is placed immediately after S-001, before any BREAKOUT factor study |
| Regime conditioning is cross-cutting but regime study (S-004) appears in Tier 1 | S-004 is run third (after S-002 and S-003) to ensure regime data is available before the cross-cutting layer begins |
| Tier 1 interactions depend on both constituent studies being complete | Interaction studies are placed in Months 8–12, after all core single-factor studies are expected to be closed |
| OOS data may be insufficient at Month 12 | OOS validation is placed at Month 12–18; if N < 200, it is delayed, not forced |
| Historical Similarity requires finalised factor weights | It begins only after S-030 (weight calibration) is complete, placed on a parallel track from Month 15 |
| Regime conditioning of individual factors (M4) comes before interaction studies (M5) | Correct — knowing which factors are regime-sensitive informs which interaction pairs are most important to study |
| Volume studies (S-010, S-013) require BOS-day price joins not pre-computed in setup_log | These are placed in the medium-term phase (Months 5–8) when methodology is more mature; not in the critical early path |

---

*This document is the primary governing document for the research program. Review and update the milestone status and Research_Pipeline.md at the start of each research session.*  
*Next review date: Upon opening first study (S-001).*
