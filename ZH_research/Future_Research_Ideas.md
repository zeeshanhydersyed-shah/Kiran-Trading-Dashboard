# Future Research Ideas — PSX Quantitative Research Platform

> **Purpose:** Captures exploratory ideas that are too speculative or premature for the Research Backlog. No commitment to pursue these; ideas are preserved for future review.  
> **Related:** [Research_Backlog.md](Research_Backlog.md) · [Research_Pipeline.md](Research_Pipeline.md)

---

## Distinction From Research Backlog

The Research Backlog contains ideas that are ready to be studied with current data. This document captures ideas that require:
- Data not yet available in the platform
- Methods not yet developed
- A longer time horizon of live data
- Conceptual development before they are researchable

---

## Platform Extension Ideas

### FRI-01 — Fundamental Data Overlay
**Idea:** Add valuation data (P/E, P/B, EPS growth) to the factor set. Test whether fundamental conditions improve or degrade the signal of technical factors.

**Current blocker:** No fundamental data source for PSX in the current pipeline.

**Relevance:** Weinstein's original methodology is purely price/volume. However, combining price action with fundamental quality (Minervini-style) could improve conviction.

---

### FRI-02 — Options Flow as Sentiment
**Idea:** If PSX options data becomes available, use put/call ratios or unusual options activity as a forward-sentiment factor.

**Current blocker:** PSX options market is small and thinly traded; data availability unknown.

---

### FRI-03 — News Sentiment Factor
**Idea:** Build a news/announcement sentiment factor using PSX company announcements. Test whether positive news releases near breakout signals improve outcomes.

**Current blocker:** No structured news data currently available. Would require NLP pipeline.

---

### FRI-04 — Seasonal / Calendar Effects
**Idea:** Test whether certain months, budget cycle periods, or Ramadan/Eid-related trading patterns create systematic return anomalies on PSX.

**Researching when:** After base-rate characterisation study (S-001) is complete and annual variation is visible.

---

### FRI-05 — Inter-Market Correlation
**Idea:** Use correlation between PSX and other emerging markets (India, Turkey, Saudi Arabia) as a regime modifier. When PSX is moving independently of peers, signals may be different quality.

**Current blocker:** No peer market data in the current pipeline.

---

### FRI-06 — Earnings Season Filter
**Idea:** Filter out setups where a company's earnings announcement falls within the forward return window. These setups may have a binary outcome driven by the announcement, not by the technical setup quality.

**When researchable:** Requires earnings calendar data for PSX companies. After base studies are complete.

---

## Methodological Research Ideas

### FRI-07 — Bayesian Updating Model
**Idea:** Instead of a fixed-weight conviction engine, build a Bayesian model that updates factor weights as new OOS data arrives. The engine would self-calibrate over time.

**Current blocker:** Requires significantly more OOS data than will be available at V1 launch. Long-term (Phase 6+).

---

### FRI-08 — Regime Forecasting
**Idea:** Instead of conditioning on the current regime, predict what the regime will be 5 days into the future. If the regime is about to change, a signal quality assessment based on the current regime is misleading.

**Current blocker:** Would require a separate regime forecasting model with its own validation requirements.

---

### FRI-09 — Network / Contagion Analysis
**Idea:** Model inter-stock correlations within sectors. If one stock breaks out, does it predict breakouts in the same sector within the next 5–10 days?

**Relevance:** Could identify whether sector momentum is contagious or concentrated in one leader.

---

## Long-Term Platform Ideas

### FRI-10 — Paper Trading Simulation
**Idea:** Run the conviction engine in real-time paper trading mode. Track which high-conviction signals were not taken and what they returned. Quantify the "cost" of missed signals.

**When feasible:** After V1 conviction engine is deployed and the daily pipeline is stable.

---

### FRI-11 — Multi-Market Extension
**Idea:** Extend the platform to US or Saudi markets. Test whether PSX-validated factors generalise. The code architecture already supports this; it would require new data sources.

**Long-term:** After PSX conviction engine is fully validated (Phase 5+).

---

*Review this document quarterly. Ideas that become ready to study should be moved to [Research_Backlog.md](Research_Backlog.md).*
