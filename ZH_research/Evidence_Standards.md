# Evidence Standards — PSX Quantitative Research Platform

> **Purpose:** Defines the exact criteria a finding must meet before it can be recorded in [Evidence_Register.md](Evidence_Register.md). Companion to [Research_Governance.md](Research_Governance.md) and [Validation_Framework.md](Validation_Framework.md).  
> **Related:** [Evidence_Register.md](Evidence_Register.md) · [Validation_Framework.md](Validation_Framework.md) · [Research_Standards.md](Research_Standards.md)

---

## What Counts as Evidence

Evidence is a **specific, quantified, reproducible finding** about the relationship between one or more factors and a defined outcome variable, derived from a completed study on PSX historical data.

Evidence is **not**:
- A published finding from another market (US, UK, etc.) applied without PSX validation
- A practitioner rule of thumb (even from respected sources)
- A hypothesis not yet tested
- A pattern visible in a chart review
- A result from a study with fewer than 30 observations per group

---

## Minimum Requirements for Evidence Registration

All of the following must be satisfied:

- [ ] Parent study (`S-xxx`) is marked `Complete` in [Research_Log.md](Research_Log.md)
- [ ] Methodology was pre-specified before data was examined
- [ ] All items in [Bias_Checklist.md](Bias_Checklist.md) are resolved (no outstanding ❌)
- [ ] Finding is stated with quantified effect size (not directional description alone)
- [ ] Baseline comparison is included
- [ ] N ≥ 30 per group
- [ ] Limitations of the finding are stated

---

## Confidence Level Criteria

### Strong

All must be true:
- N ≥ 200 per group in the study
- Effect is consistent across ≥ 2 market regimes
- Out-of-sample validation passed (Tier 3 in [Validation_Framework.md](Validation_Framework.md))
- Effect size: Δ win rate ≥ 5pp **and** Δ mean return ≥ 1.5%
- No material ⚠️ items in the Bias Checklist

### Moderate

All must be true:
- N ≥ 50 per group
- Effect is directionally consistent across ≥ 1 regime
- Temporal stability check passed (Tier 2)
- Effect size: Δ win rate ≥ 5pp **or** Δ mean return ≥ 1.0%
- No ❌ items in the Bias Checklist

### Weak

Remaining cases that nonetheless deserve recording:
- N ≥ 30 per group
- Finding is directional (consistent direction, even if small)
- All ❌ items resolved
- Effect size below Moderate thresholds **or** result is single-regime only

**Weak evidence is not used in the conviction engine.** It is recorded to guide future replication studies.

---

## What Evidence Records Must Include

When writing an Evidence Register entry, the finding statement must include:

1. **The factor** — exact name and threshold or split
2. **The setup type** — which of the four setup types was studied
3. **The regime scope** — "All regimes" or specify
4. **The outcome variable** — e.g., 20d forward return
5. **The key numbers** — win rate for each group, N for each group, mean return delta
6. **The study reference** — `S-xxx`

**Example of an acceptable evidence statement:**
> "For BREAKOUT setups in TRENDING_UP regime, `rs_rank ≤ 20` was associated with a 20d win rate of 61% (N=203) vs 48% (N=891) for `rs_rank > 20`, a delta of +13pp. Mean 20d return: +4.1% vs +2.2% (S-003)."

**Example of an unacceptable evidence statement:**
> "High RS rank stocks do better on breakouts."

---

## Evidence Lifecycle

```
Finding produced by Study (S-xxx)
     │
     ▼
Evidence candidate — does it meet minimum requirements?
     │
    Yes → Assign E-xxx, set status Active
     │
     ▼
Future study confirms finding → confidence upgrades (note in register)
     │
Future study contradicts finding → set status Under Review
     │
Contradicting study completes:
  ├── Original upheld → restore Active
  └── Original superseded → set status Superseded, link to new E-xxx
```

---

## Evidence That Should NOT Be Registered

| Situation | Action |
|---|---|
| Null result (factor does not predict outcome) | Mark hypothesis `Rejected`; do not create evidence entry |
| Inconclusive result (insufficient N) | Mark hypothesis `Inconclusive`; flag for replication |
| OOS validation failed | Demote to Weak; note limitation; do not use in engine |
| Result driven by one outlier period | Flag as non-robust; require replication before registering |
| Result only present in one sector | Label clearly as sector-specific; Weak confidence maximum |
