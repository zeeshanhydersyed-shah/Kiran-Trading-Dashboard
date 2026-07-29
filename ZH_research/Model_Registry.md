# Model Registry — PSX Quantitative Research Platform

> **Purpose:** Authoritative record of every conviction engine version ever produced. Ties each version to the specific study set, weights, and validation results that produced it.  
> **Related:** [Score_Evolution_Roadmap.md](Score_Evolution_Roadmap.md) · [Conviction_Engine_Specification.md](Conviction_Engine_Specification.md) · [Acceptance_Criteria.md](Acceptance_Criteria.md)

---

## Purpose

The Model Registry ensures that every version of the conviction engine is traceable. If a version is later found to have a problem, we can identify exactly which studies it depended on and which factors it used, and audit the problem.

---

## Active Engine Version

| Field | Value |
|---|---|
| Version | V0 (Heuristic, informal) |
| Status | Active |
| Live since | Dashboard launch |
| Description | 4-colour Explorer classification based on BOS flag and RS score |
| Factor set | F-01 (RS Score), F-12 (BOS Flag), F-11 (Pivot Distance) |
| Validation | None — heuristic design |
| Study set | None |
| Known limitations | No calibration, no probability estimates, no regime conditioning |

---

## Version History

### V0 — Heuristic Score

| Field | Value |
|---|---|
| Version ID | V0 |
| Production dates | Dashboard launch → (until V1 replaces it) |
| Factor set | RS Score 20d (F-01), BOS Flag (F-12), Pivot Distance (F-11) |
| Decision logic | Cascade: BOS+RS→Green, NearPivot→Amber, RS+→Blue, else→Gray |
| Weights | None (categorical classification, not weighted) |
| IS validation | None |
| OOS validation | None |
| Acceptance gates | Not applied (pre-research-platform era) |
| Replaced by | Pending — V1 not yet built |
| Retirement date | — |
| Notes | Pre-dates the research platform. Used as baseline to beat. |

---

## Version Template

When a new version is registered, copy this template:

```
### Vx.x — [Name]

| Field | Value |
|---|---|
| Version ID | Vx.x |
| Production dates | [start] → [end or "Current"] |
| Factor set | [list factor IDs and names] |
| Weights | [list factor weights, or link to weight table] |
| Score formula | [formula or link to spec] |
| IS period | [date range] |
| IS win rate spread (Very High vs Low) | [value] |
| IS calibration | [Pass/Fail] |
| OOS period | [date range] |
| OOS N | [count] |
| OOS win rate spread | [value] |
| OOS validation | [Pass/Fail] |
| Acceptance gates passed | [list] |
| Supporting studies | [list study IDs from Evidence_Register.md] |
| Replaced by | [next version, or "N/A"] |
| Retirement date | [date or "—"] |
| Notes | [any known issues or special circumstances] |
```

---

## Pending Versions

| Version | Dependencies | Estimated Start |
|---|---|---|
| V1 | Phase 2 single-factor studies complete (≥5 Moderate+ findings) | Unknown |
| V1.1 | V1 running 90+ trading days in production | Unknown |
| V2 | OOS N ≥ 500 | Unknown |

---

## Registry Rules

1. A version is registered when it enters OOS testing, not when it is deployed
2. The supporting studies list must include all study IDs that contributed a factor or weight to the model
3. Weights are frozen when the version enters OOS testing and may not be adjusted retrospectively
4. A retired version's record is never deleted from this registry
