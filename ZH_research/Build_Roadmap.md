# Build Roadmap — PSX Breakout Research Project

> **Principle:** Each phase must be substantially complete before the next begins.  
> **Status key:** `✅ Complete` · `🔄 In Progress` · `⏳ Planned` · `⛔ Blocked`

---

## Phase 1 — System Audit

| Field | Detail |
|---|---|
| **Status** | ✅ Complete |
| **Objective** | Understand exactly what the existing system contains before any research begins. |

### Deliverables
- [x] Full inventory of Explorer page display fields
- [x] Full inventory of hidden/loaded-but-not-displayed fields
- [x] Database table inventory (all tables, row counts, schemas)
- [x] Complete list of existing technical indicators and their formulas
- [x] Complete list of existing derived metrics
- [x] Complete list of existing scores, ratings, and classifications
- [x] Execution flow of the Explorer page documented
- [x] Research assets identified and assessed

### Notes
> System audit completed 2026-07-01. Findings recorded in Claude_Findings.md.

---

## Phase 2 — Research Planning

| Field | Detail |
|---|---|
| **Status** | ✅ Complete |
| **Objective** | Define the research agenda, identify all testable factors, and establish methodology standards before touching any data. |

### Deliverables
- [x] All research factors documented with hypotheses (Data_Dictionary.md)
- [x] All outcome variables evaluated for suitability
- [x] Catalogue of research questions created (Questions.md)
- [x] Factor interactions prioritised
- [x] Research risks documented
- [x] Research roadmap agreed
- [x] Research workspace created

### Notes
> Research planning completed 2026-07-01. Research workspace initialised.

---

## Phase 3 — Individual Factor Studies

| Field | Detail |
|---|---|
| **Status** | ⏳ Planned |
| **Objective** | Measure the predictive power of each factor in isolation against 10d and 20d forward returns from `setup_log`. |

### Deliverables
- [ ] Baseline win rates and return distributions for all four setup types
- [ ] Binary factor study: BOS, overhead_clear, stage2_bull, close_above_ema150, ema150_slope_pos
- [ ] Continuous factor study: rs_score_20, rs_rank, rank_change, base_tightness, base_duration, near_pivot_days, pivot_distance_pct, vol_contraction
- [ ] Sector factor study: sector_stage, sec_global_rank, breadth_score
- [ ] Each study recorded in Research_Log.md
- [ ] Findings table: factor → predictive value rating (Low / Medium / High)

### Notes
> _To be populated._

---

## Phase 4 — Multi-Factor Interaction Studies

| Field | Detail |
|---|---|
| **Status** | ⏳ Planned |
| **Objective** | Identify factor combinations that produce materially better outcomes than individual factors alone. |

### Deliverables
- [ ] Top binary factor 2×2 and 2×2×2 interaction tables
- [ ] Continuous factor quantile combinations (top factors from Phase 3)
- [ ] Identification of combinations with adequate N (> 50 observations per cell)
- [ ] Each study recorded in Research_Log.md

### Notes
> Dependent on Phase 3 completion.

---

## Phase 5 — Market Regime Analysis

| Field | Detail |
|---|---|
| **Status** | ⏳ Planned |
| **Objective** | Determine whether factor predictive power is regime-dependent and identify regime-specific rules. |

### Deliverables
- [ ] All Phase 3 and 4 findings stratified by market regime
- [ ] Regime-specific win rate baselines for each setup type
- [ ] Identification of factors that work across all regimes vs regime-specific factors
- [ ] Regime_days analysis: does breakout success change depending on how long the regime has persisted?
- [ ] Each study recorded in Research_Log.md

### Notes
> Requires joining `market_regime` to `setup_log` by date.

---

## Phase 6 — Historical Similarity Research

| Field | Detail |
|---|---|
| **Status** | ⏳ Planned |
| **Objective** | Find historical setups with conditions most similar to a current setup and use their outcomes as a probability reference. |

### Deliverables
- [ ] Definition of a "similarity metric" across the validated factor set
- [ ] Prototype lookup: given a current setup, find the N most similar historical setups
- [ ] Distribution of outcomes for matched historical setups
- [ ] Assessment of whether similarity-matched outcomes are more predictive than factor-only models

### Notes
> This phase is exploratory. Success is not assumed.

---

## Phase 7 — Conviction Engine Design

| Field | Detail |
|---|---|
| **Status** | ⏳ Planned |
| **Objective** | Synthesise Phase 3–6 findings into a single conviction framework with defined ratings and interpretations. |

### Deliverables
- [ ] Factor weights derived from Phase 3–5 evidence (not assumed)
- [ ] Conviction rating scale defined (e.g., 1–5 or Low/Medium/High/Very High)
- [ ] Calibration: does a "High" conviction rating actually produce meaningfully better outcomes?
- [ ] Out-of-sample validation: second half of date range
- [ ] Full documentation of the conviction algorithm in Data_Dictionary.md

### Notes
> No implementation until this phase is complete and validated.

---

## Phase 8 — Explorer Integration

| Field | Detail |
|---|---|
| **Status** | ⏳ Planned |
| **Objective** | Integrate the validated conviction engine into the Explorer page without disrupting existing functionality. |

### Deliverables
- [ ] Conviction score displayed in the information block
- [ ] Factor breakdown visible on demand (collapsible)
- [ ] Historical context line: "X% of N similar setups produced positive returns at 20d"
- [ ] All existing screeners and filters preserved
- [ ] No changes to existing signal logic

### Notes
> Implementation begins only after Phase 7 produces a validated, documented conviction framework.
