# Vision — PSX Breakout Research Project

> **Status:** Active  
> **Established:** 2026-07-01  
> **Owner:** Zeeshan Hyder Syed

---

## Project Objective

Build an evidence-based breakout conviction framework for the Pakistan Stock Exchange (PSX) grounded entirely in historical data — not assumptions, intuition, or borrowed rules from other markets.

Every signal, filter, threshold, and weight in the final system must be traceable to a documented empirical finding.

---

## Long-Term Vision

A conviction engine that evaluates any stock setup on the Explorer page and returns:

- A probability estimate of breakout success at a defined forward horizon
- The key factors driving the rating (positive and negative)
- A historical context: "X% of setups with similar conditions produced positive returns at 20 days"

The engine should replace subjective judgment with structured, repeatable analysis — while remaining interpretable to a discretionary trader.

---

## Guiding Principles

| # | Principle |
|---|---|
| 1 | **Evidence first.** No factor enters the system without empirical validation on PSX data. |
| 2 | **One question at a time.** Each study addresses one clearly defined research question. |
| 3 | **Document everything.** Every finding, including null results, is recorded in Research_Log.md. |
| 4 | **Earn complexity.** Add a new layer only after the previous one is fully understood. |
| 5 | **Preserve what works.** Existing screeners producing good results are not disrupted. |
| 6 | **Acknowledge limitations.** Sample size, regime dependency, and data gaps are stated openly. |

---

## Success Criteria

- [ ] All existing factors in `stock_signals` have been individually studied against 10d and 20d forward returns
- [ ] At least three robust multi-factor combinations have been identified and documented
- [ ] All findings are stratified by market regime
- [ ] A conviction score or rating framework has been designed based solely on validated factors
- [ ] The framework has been tested out-of-sample (second half of the date range)
- [ ] Results are integrated into the Explorer page without breaking existing functionality

---

## Things We Will Not Do

- Add new technical indicators before existing ones are fully studied
- Borrow thresholds from US or other markets without PSX validation
- Optimise thresholds on the full dataset and call the result "evidence"
- Treat win rate alone as proof of edge (magnitude and consistency matter equally)
- Implement any feature whose predictive value is rated Unknown or Low
- Disrupt the existing screeners, gates, or trade log

---

## Future Direction

_To be populated as research findings accumulate._

- [ ] Placeholder: Regime-conditional conviction adjustments
- [ ] Placeholder: Sector rotation timing signals
- [ ] Placeholder: Volume profile integration
- [ ] Placeholder: Historical analog matching

---

*This document is the permanent charter. Update the Success Criteria and Future Direction sections as milestones are reached.*
