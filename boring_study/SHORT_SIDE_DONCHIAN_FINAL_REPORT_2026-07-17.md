# Short-Side Donchian Breakdown Study — Final Report
**Date:** 2026-07-17  
**Status:** CLOSED — Not Deployable  
**Decision:** Put on hold indefinitely. Edge exists only in crisis periods (2008-2009), not in normal markets.

---

## Executive Summary

Attempted to extend the successful long-side Donchian Breakout study (validated edge: 9.2%) to short positions on PSX. Three comprehensive phases conducted, followed by stress-test battery to verify robustness.

**Result:** Strategy failed stress testing. The apparent 9.89% edge in `TRENDING_DOWN` regime was entirely driven by the 2008-2009 global financial crisis. In normal market conditions (2011-2026), the edge collapses to ~1% and is not statistically significant.

**Conclusion:** The strategy is not deployable as a real trading system.

---

## Phase 1a: Stop-Loss Optimization (by Lookback)

**Objective:** Determine optimal fixed SL across N ∈ {10, 20, 40, 60, 120} lookback periods.

**Methodology:**
- Universe: 106 DFC-eligible (shortable) symbols
- Entry: Breakdown `close[t] < MIN(low[t-N..t-1]) × 0.99`
- SL sweep: {-3%, -4%, -5%, -6%, -7%, -8%, -10%}
- TP targets: {-5%, -10%, -20%, -30%, -50%}
- Outcome: TP-before-SL race (binary)
- Control: Matched random same-stock non-breakdown entries, seed=42

**Results:**

| Lookback | Breakdowns | Edge @ -3% SL | Optimal SL | Status |
|----------|-----------|--------------|-----------|--------|
| N=10 | 20,352 | 2.71% | -3% | Weak |
| N=20 | 14,450 | 3.37% | -3% | Moderate |
| N=40 | 9,991 | 4.37% | -3% | Good |
| **N=60** | **8,069** | **5.24%** | **-3%** | **Selected** |
| N=120 | 5,580 | 6.94% | -3% | Strongest (but rare) |

**Key Finding:** Edge grows monotonically with lookback. Longer-term support/resistance breaks are stronger signals. **N=60 selected as primary for Phase 1b** (balance of signal strength and frequency).

**All lookbacks recommend -3% SL** (no variation by N).

---

## Phase 1b: Target Profit Optimization (Full Sample)

**Objective:** Determine optimal take-profit level from historical data distribution (not assume -10%).

**Methodology:**
- Sample: 8,069 N=60 breakdowns + 8,069 matched controls (full, no RS filtering)
- Analyze MFE (max favorable excursion) distribution among winning trades
- Test TP-race at targets: {-5%, -8%, -10%, -12%, -15%, -20%, -25%, -30%}
- Locked SL: -3%

**Results: Edge by Target (Primary Outcome = -10%)**

| Target | BO TP% | Ctrl TP% | Edge | BO/Ctrl Ratio |
|--------|--------|----------|------|---|
| -5% | 6.74% | 0.83% | **5.91%** | 8.1× |
| -8% | 6.16% | 0.73% | **5.43%** | 8.4× |
| **-10%** | **5.86%** | **0.64%** | **5.22%** | **9.1×** |
| -15% | 5.02% | 0.42% | 4.60% | 11.9× |
| -20% | 4.14% | 0.35% | 3.79% | 11.8× |
| -30% | 3.15% | 0.19% | 2.96% | 16.6× |

**Algorithm recommendation:** TP = -30% (max Edge × RR score)  
**Practical recommendation:** TP = -10% to -15% (strong edge, reasonable hit rate, not overly loose)

**MFE Distribution (Winners Only):**
- Only 90/8,069 (0.9%) of breakdowns avoid the -3% SL
- Among those 90: median MFE = -4.99% (still losing money on average)
- True "winners" = trades that hit TP before SL, not trades that survive

**Locked for Phase 1c:** TP = -15% (primary), TP = -10% (sensitivity)

---

## Phase 1c: Regime & Sector Analysis

**Objective:** Identify regime and sector combinations with strong, replicable edges.

**Methodology:**
- N=60 breakdowns, TP = -15% (primary) and -10% (sensitivity)
- SL = -3%
- Split by: Market regime (from `market_regime` table) and stock sector
- Cross-check: N=20 lookback for replication

**Results by Regime (TP=-15%, SL=-3%):**

| Regime | Edge | BO Rate | Sample | p-value | Status |
|--------|------|---------|--------|---------|--------|
| **TRENDING_DOWN** | **9.89%** | **10.49%** | **2,955** | **<0.000001** | ✓ Strong |
| VOLATILE | 2.63% | 3.11% | 2,573 | <0.000001 | Moderate |
| TRENDING_UP | 0.84% | 1.11% | 541 | 0.003 | Weak |
| RANGING | -0.08% | 0.47% | 1,898 | 0.737 | Neutral |

**Top 5 Sectors (TP=-15%, SL=-3%):**

| Sector | Edge | BO Rate | Sample | Status |
|--------|------|---------|--------|--------|
| INSURANCE | 12.30% | 13.11% | 122 | Exceptional |
| COMMERCIAL BANKS | 9.74% | 9.94% | 1,006 | Strong + Large |
| CABLE & ELECTRICAL GOODS | 9.51% | 9.51% | 284 | Strong |
| OIL & GAS EXPLORATION | 7.61% | 7.61% | 368 | Strong |
| TEXTILE COMPOSITE | 7.00% | 8.23% | 243 | Strong |

**Replication (N=60 vs N=20):**
- Overall edge: N=60 = 4.60%, N=20 = 2.77% (39.8% divergence — doesn't replicate)
- By regime: Patterns hold across lookbacks (regime is more robust than overall edge)

**Sensitivity Check (TP=-10% vs -15%):**
- TRENDING_DOWN: 10.77% edge (slightly better than -15%)
- Generally confirms -10% is viable alternative

---

## Stress Test Battery

### Test #1: Time-Based Walk-Forward (CRITICAL) ❌

**Finding:** Edge is entirely driven by 2008-2009 crisis.

| Period | Trades | Edge | Status |
|--------|--------|------|--------|
| 2008 | 749 | 34.58% | ✓ Pass |
| 2009 | 241 | 27.94% | ✓ Pass |
| 2011-2023 | 2,000+ | ~0% | ✗ FAIL |
| 2024 YTD | — | — | No data |

**Diagnosis:** The 9.89% TRENDING_DOWN edge is a **historical artifact** from the global financial crisis (15+ years old). In normal market conditions, edge = 0%.

**Verdict:** FATAL FLAW. Strategy does not replicate to recent data.

### Test #4: Sector Concentration

**Finding:** Edge is not concentrated in just 2 sectors.

- Full TRENDING_DOWN: 9.89% edge
- Excluding Insurance & Banks: 7.83% edge
- Verdict: PASS (edge holds above 4% threshold)

### Remaining Tests

- **Test #2 (Regime look-ahead bias):** Requires schema audit of `market_regime` table (deferred)
- **Test #3 (SL sensitivity):** Requires re-race computation at -2%, -5% levels (deferred)
- **Test #5 (Black swan distribution):** Pending return distribution analysis (deferred)
- **Test #6 (RS heterogeneity):** Requires subsample analysis within TRENDING_DOWN (deferred)

---

## Focused Reality Check (Post-2011, Sector Downtrend Filter)

**Objective:** Final validation using post-2011 data only, target sectors, realistic sector-level downtrend filter.

**Methodology:**
- Data: 2011-2026 only
- Sectors: Insurance, Commercial Banks, Oil & Gas, Cable & Electrical Goods
- Entry: N=60 Donchian breakdown
- Filter: Stock's sector must be in downtrend (sector_rs_rank > 50, below median)
- Exit: TP = -10%, SL = -3%

**Results: FAILURE**

| Metric | Value |
|--------|-------|
| Breakdowns found | 197 |
| Breakout TP hit rate | 1.02% (2/197) |
| Control TP hit rate | 0.00% (0/197) |
| **Edge** | **1.02%** |
| p-value | 0.156 (NOT significant) |
| **Verdict** | **FAIL** |

**Interpretation:** When you remove the crisis period and apply realistic trading conditions, the edge completely disappears. The strategy has **zero edge** in normal markets.

---

## Summary of Experiments

| Phase | Experiment | Finding | Status |
|-------|-----------|---------|--------|
| 1a | SL optimization by lookback | N=60 @ -3% optimal; edge grows with lookback | ✓ Completed |
| 1b | TP optimization (full sample) | -15% and -10% are practical targets | ✓ Completed |
| 1c | Regime & sector analysis | TRENDING_DOWN shows 9.89% edge; Insure/Banks lead | ✓ Completed |
| ST1 | Time-based walk-forward | Edge only exists in 2008-2009 (FATAL) | ✓ Completed |
| ST4 | Sector concentration | Edge not concentrated in 2 sectors | ✓ Completed |
| Focus | Post-2011 + sector filter | Edge collapses to 1% (NOT significant) | ✓ Completed |

---

## Why This Strategy Failed

1. **Historical Accident:** The only tradeable edge was during the 2008-2009 global financial crisis when market crashed 40%+. Breakdown strategy worked because support levels were breaking due to panic/capitulation.

2. **No Replication in Normal Markets:** 2011-2026 data shows edge ≈ 0%. The regime/sector patterns detected in Phase 1c are confounded by the crisis period.

3. **Tight Entry Signal:** Only 8,069 breakdowns in 16 years on 106 DFC symbols (N=60). With realistic sector-downtrend filtering, only 197 trades. With 1% hit rate, strategy is not tradeable.

4. **Asymmetry vs Longs:** Longs had 9.2% edge, shorts had "9.89%" (actually 1% in normal times). Markets are structurally biased upward; shorts are harder to trade.

---

## Artifacts Generated

- `short_donchian_phase1a_by_lookback.py` — SL optimization script
- `short_donchian_phase1a_final_2026-07-17.md` — Phase 1a documentation
- `short_donchian_phase1b_tp_optimization.py` — TP optimization script
- `short_donchian_phase1c_regime_sector.py` — Regime/sector analysis script
- `short_donchian_phase1c_stress_tests.py` — Stress test battery (partial)
- `short_donchian_focused_sector_downtrend.py` — Final focused reality check
- `short_panel_60d_phase1b.csv` — Phase 1b panel (TP outcomes)
- `short_panel_20d_phase1b.csv` — N=20 cross-check panel
- `short_panel_60d_phase1c.csv` — Phase 1c panel (regime/sector data)
- `short_panel_20d_phase1c.csv` — N=20 phase 1c panel

---

## Recommendations for Future Work

If revisiting short-side trading on PSX:

1. **Different mechanism:** Breakdowns may not work; consider:
   - Support-reversal patterns (like the long-side study found)
   - Volume-based breakdown confirmation
   - Order-flow or institutional-activity signals

2. **Avoid regime-based selection:** Our regime patterns were confounded by the crisis period. Use fundamentals or technical momentum instead.

3. **Accept lower edges:** PSX shorts are inherently harder than longs (upward bias). Target 3-5% edge, not 9%+.

4. **Sector focus:** If pursuing shorts, restrict to Financial sector (banks, insurance) which showed highest edges. But be aware this is macro-sensitive (rate environment).

---

## Closure

**Project Status:** CLOSED — Not Deployable  
**Hold Duration:** Indefinite (pending new ideas or major market regime shift)  
**Lessons Learned:** 
- Historical backtests can mask crisis-period artifacts
- Stress testing is essential before deployment
- Walk-forward analysis catches illusions early
- Longs and shorts behave asymmetrically; don't assume symmetry

**Next Steps:** Focus resources on other opportunities (e.g., long-side regime/sector refinements, support-reversal short patterns, or entirely new mechanisms).

---

**Report prepared:** 2026-07-17  
**Prepared by:** Claude Code  
**Project:** Kiran PSX Trading Dashboard — Boring Study (Short-Side Thread)
