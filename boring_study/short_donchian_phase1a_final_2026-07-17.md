# Short-Side Donchian Breakdown — Phase 1a: Stop-Loss Discovery (Final)
**Date:** 2026-07-17  
**Status:** COMPLETE  
**Objective:** Empirically determine optimal stop-loss level on DFC-eligible (shortable) PSX symbols, tested separately by lookback period.

---

## Methodology

### Entry Signal (Breakdown)
```
close[t] < MIN(low[t-N..t-1]) × 0.99
```
- **Lookback periods:** N ∈ {10, 20, 40, 60, 120} — **tested separately, not pooled**
- **Data source:** `prices_adjusted` table
- **Universe:** DFC-eligible symbols only (106 symbols, shortable on PSX)
- **Eligibility:** Date index ≥ 20 within each symbol's history

### Race Mechanics
- **Horizon:** 90 trading days max (entry+1 to entry+90)
- **Targets (SHORT):** -5%, -10%, -20%, -30%, -50%
- **Stop-loss levels tested:** -3%, -4%, -5%, -6%, -7%, -8%, -10%
- **Outcome:** Binary — TP hit before SL or not
- **Tie rule:** Both hit on same day → stop wins (conservative)

### Control Group
- **Method:** One random non-breakdown entry per breakdown occurrence
- **Pool:** Same symbol, same date-index range (≥ 20), excluded flagged breakdown dates
- **Seed:** 42 (reproducible)

---

## Data Summary

| Lookback | Breakdowns | Controls | Symbols w/ BOs |
|----------|-----------|----------|---|
| N=10 | 20,352 | 20,352 | 105/106 |
| N=20 | 14,450 | 14,450 | 105/106 |
| N=40 | 9,991 | 9,991 | 104/106 |
| N=60 | 8,069 | 8,069 | 104/106 |
| N=120 | 5,580 | 5,580 | 100/106 |
| **TOTAL** | **58,442** | **58,442** | — |

---

## Results: SL Optimization by Lookback

**Primary outcome measure:** TP-hit rate at -10% target vs. -6% SL (following long-side study's primary outcome).

### Edge by SL Level (Target = -10%)

#### N=10
| SL | BO TP% | Ctrl TP% | Edge |
|----|--------|---------|------|
| -10% | 0.34% | 0.13% | 0.21% |
| -8% | 0.48% | 0.18% | 0.30% |
| -7% | 0.61% | 0.21% | 0.41% |
| -6% | 0.74% | 0.23% | 0.51% |
| -5% | 1.05% | 0.30% | 0.75% |
| **-4%** | **2.84%** | **0.51%** | **2.33%** |
| **-3%** | **3.37%** | **0.67%** | **2.71%** ← Optimal |

#### N=20
| SL | BO TP% | Ctrl TP% | Edge |
|----|--------|---------|------|
| -10% | 0.41% | 0.14% | 0.27% |
| -6% | 0.89% | 0.23% | 0.66% |
| **-4%** | **3.43%** | **0.51%** | **2.92%** |
| **-3%** | **3.99%** | **0.63%** | **3.37%** ← Optimal |

#### N=40
| SL | BO TP% | Ctrl TP% | Edge |
|----|--------|---------|------|
| -10% | 0.54% | 0.15% | 0.39% |
| -6% | 1.17% | 0.22% | 0.95% |
| **-4%** | **4.37%** | **0.51%** | **3.86%** |
| **-3%** | **5.01%** | **0.64%** | **4.37%** ← Optimal |

#### N=60 (SELECTED FOR PHASE 1b)
| SL | BO TP% | Ctrl TP% | Edge |
|----|--------|---------|------|
| -10% | 0.66% | 0.10% | 0.56% |
| -6% | 1.41% | 0.25% | 1.16% |
| **-4%** | **5.18%** | **0.47%** | **4.71%** |
| **-3%** | **5.86%** | **0.62%** | **5.24%** ← Optimal |

#### N=120
| SL | BO TP% | Ctrl TP% | Edge |
|----|--------|---------|------|
| -10% | 0.88% | 0.13% | 0.75% |
| -6% | 1.77% | 0.27% | 1.51% |
| **-4%** | **6.82%** | **0.52%** | **6.31%** |
| **-3%** | **7.57%** | **0.64%** | **6.94%** ← Optimal |

---

## Key Finding: Monotonic Edge Increase with Lookback Period

**At optimal SL (-3%), edge by lookback:**

```
N=10:   2.71% edge
N=20:   3.37% edge (+24% vs N=10)
N=40:   4.37% edge (+61% vs N=10)
N=60:   5.24% edge (+93% vs N=10)  ← SELECTED
N=120:  6.94% edge (+156% vs N=10)
```

**Interpretation:**
- Longer-term support/resistance breakdowns are far more predictive than short-term noise
- The 120-day low is a stronger, more meaningful level than the 10-day low
- Signal strength grows monotonically; no inflection point or peak

---

## Full Matrix at Recommended SL (-3%)

### N=60 (Selected for Phase 1b)

| Target | BO TP% | Ctrl TP% | Edge | BO/Ctrl Ratio |
|--------|--------|---------|------|---|
| -5% | 6.73% | 0.82% | 5.97% | 8.2× |
| **-10%** | **5.86%** | **0.62%** | **5.24%** | **9.4×** |
| -20% | 4.09% | 0.35% | 3.82% | 11.7× |
| -30% | 3.08% | 0.12% | 3.02% | 25.7× |
| -50% | 1.41% | 0.04% | 1.38% | 35.3× |

**Note:** Control group hit rates are extremely low at distant targets (-30%, -50%), showing that random entries rarely produce large moves. The breakdown group's edge is most robust at -5% and -10% targets.

---

## Recommendation for Phase 1b

**Selected parameters:**
- **Lookback:** N=60
- **Stop-loss:** -3%
- **Target (primary):** -10%
- **Breakdown occurrences:** 8,069
- **Edge:** 5.24%

**Rationale:**
- Strongest meaningful signal among the tested lookbacks (N=120 is stronger but rarer; N=40 is weaker)
- Balances signal strength with trade frequency
- Good alignment with intermediate-term swing/position trading horizon

---

## Phase 1b Planned Work

With N=60 data locked:

1. **Statistical tests:** Mann-Whitney U, Cliffs delta (full distribution)
2. **Forward returns:** Mean/median at horizons 5d, 10d, 20d, 30d, 60d, 90d
3. **RS heterogeneity:** Does edge vary by stock relative strength decile?
4. **Replication:** Cross-check with 20-day panel for robustness

---

## Artifacts

- **Script:** `short_donchian_phase1a_by_lookback.py` (breakdown detection, control matching, SL sweep per lookback)
- **Output:** `phase1a_by_lookback_output.txt` (raw results)
- **This document:** Final summary and decision lock

---

## Notes for Future Reference

- **All lookbacks recommend -3% SL** — no divergence by N value
- **Tie rule:** Conservative (stop wins on same-day hits) — any edge detected is robust to this assumption
- **Sample sizes:** 5K–20K per group per lookback — stable TP rates
- **No lookahead bias:** Forward window strictly t+1 onward
- **Comparison to longs:** N=60 shorts edge (5.24%) is ~57% of longs edge (9.2%), but at 2× tighter stop (-3% vs -6%)

