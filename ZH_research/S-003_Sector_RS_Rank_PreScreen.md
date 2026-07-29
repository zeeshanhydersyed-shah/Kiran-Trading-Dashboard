# S-003 — Test: `sector_rs_rank ≤ 5` as a Pre-Screen Filter (Audit Finding A2)

**Status:** CLOSED — 🔴 **DEAD** (reversed direction, statistically significant but practically negligible effect size)
**Filed:** 2026-07-09
**Researcher:** Quantitative Analyst
**Reviewer:** Independent Quantitative Reviewer (PI)
**Population:** `stock_signals` — full universe, NOT conditioned on `bos_flag`/`active_resistance`/`breakout_event`
**Database:** psx_data.db

**See also:** [S-004_RS_Rank_LiveSystem_Reconciliation.md](S-004_RS_Rank_LiveSystem_Reconciliation.md) — clarifies that `sec_global_rank` (a separate, sector-level field also used by the Weinstein Watchlist toggle and by `weinstein_combined_backtest.py`'s `≤8` gate) is a different construct from `sector_rs_rank` tested here, and is unaffected by this verdict.

---

## 1. What this document is

Tests the Explorer page's "Weinstein Watchlist" toggle's `sector_rs_rank ≤ 5` condition (audit finding **A2**, prior session) as a standalone pre-screen: does it predict better forward returns *before* any breakout/pre-breakout status is considered? Distinct from, and does not re-touch:
- **RS_LEADER_SECTOR** — a different, standalone, already-dead setup type.
- **S-002** — RS tested as a POST-breakout quality score (also dead). This study tests the same rank field in a structurally different role (pre-screen vs. post-selection quality), on a population that is explicitly *not* setup-type-conditioned at all.

---

## 2. Methodology

### 2.1 Population

```sql
SELECT symbol, date, sector_rs_rank
FROM stock_signals
WHERE avg_vol_10d > 200000
  AND sector_rs_rank IS NOT NULL
```

297,640 rows, 257 symbols, 2015-01-01 → 2026-07-09 — matches the live Weinstein filter's own liquidity gate exactly (`avg_vol_10d > 200_000`), no other conditioning.

### 2.2 Forward return

`stock_signals` has no `fwd_return_10d` column (that field lives only on `setup_log`, which this population deliberately bypasses). Computed fresh using `compute_forward_returns.py`'s exact existing formula — `(close at entry+10 trading days − close at entry) / close at entry × 100`, sourced from `prices_adjusted` — reused verbatim, same as S-002, not a new formula.

| | N |
|---|---|
| Valid `fwd_return_10d` | 296,010 / 297,640 (99.5%) |
| Window not yet closed | 1,630 |
| No matching `prices_adjusted` row | 0 |

### 2.3 Split and tests

Two groups: `sector_rs_rank ≤ 5` vs. `sector_rs_rank > 5` (exact live-filter cutoff). Same test battery as S-002: Mann-Whitney U (two-sided, and one-sided testing the live filter's implicit assumption `≤5 > >5`), Welch's t-test, Cliff's delta (computed via the MWU U-statistic for exactness at this row count rather than an O(n₁×n₂) pairwise loop, which would be intractable at N≈300K).

### 2.4 Eras

Same three-era boundaries as prior project studies (S-001): Development 2015-01-01→2019-12-31, Validation 2020-01-01→2022-12-31, OOS 2023-01-01→2026-12-31.

---

## 3. Results — full population (all eras combined)

| Group | N | Mean fwd10 | Median fwd10 | Std |
|---|---|---|---|---|
| `sector_rs_rank ≤ 5` | 144,918 | **+0.59%** | -0.53% | 11.53 |
| `sector_rs_rank > 5` | 151,092 | **+0.92%** | -0.13% | 10.56 |

**Mean delta (≤5 minus >5): -0.33 percentage points** — the "stronger sector" group underperforms, not outperforms.

| Test | Result |
|---|---|
| Mann-Whitney U, two-sided | p < 0.000001 |
| Mann-Whitney U, one-sided (≤5 > >5, the live filter's implicit assumption) | p = 1.000000 |
| Welch's t-test, two-sided | t = -7.99, p < 0.000001 |
| Cliff's delta (≤5 vs >5) | -0.0334 (negligible by convention, |δ|<0.147) |

**Statistically significant, wrong direction, negligible effect size.** At N≈296K, even a very small true difference clears conventional significance thresholds — the p-values reflect that scale, not a meaningful predictive edge. The one-sided test in the *hypothesized* direction returns p=1.0: there is no evidence whatsoever that `≤5` outperforms `>5`; if anything the reverse is true.

---

## 4. Per-rank-value breakdown

| sector_rs_rank | N | Mean fwd10 | Median fwd10 | Std |
|---|---|---|---|---|
| 1 | 32,579 | +0.59% | -0.74% | 13.86 |
| 2 | 31,266 | +0.46% | -0.73% | 11.71 |
| 3 | 30,508 | +0.60% | -0.39% | 10.56 |
| 4 | 28,585 | +0.59% | -0.37% | 10.10 |
| 5 | 21,980 | +0.77% | -0.36% | 10.45 |
| 6 | 20,565 | +0.77% | -0.25% | 9.97 |
| 7 | 17,594 | +0.70% | -0.25% | 10.20 |
| 8 | 15,826 | +0.70% | -0.31% | 9.83 |
| 9 | 14,323 | +0.87% | -0.16% | 10.06 |
| 10+ | 82,784 | **+1.05%** | -0.04% | 10.99 |

**No cliff or step-function at rank 5** (or anywhere else). The mean return rises gently and close to monotonically from rank 1 (+0.59%) to the 10+ bucket (+1.05%) — the opposite of what a "top-5 sector is better" screen would predict. There is no threshold value where a discrete jump favors low ranks; the trend, such as it is, runs the other way across the entire range.

---

## 5. Era-consistency check

| Era | N (≤5) | Mean (≤5) | N (>5) | Mean (>5) | Mean Δ | MWU two-sided p | Cliff's δ |
|---|---|---|---|---|---|---|---|
| Development (2015-2019) | 57,060 | +0.08% | 51,706 | +0.45% | -0.36 | <0.000001 | -0.0302 |
| Validation (2020-2022) | 37,931 | +0.02% | 40,503 | +0.39% | -0.37 | <0.000001 | -0.0362 |
| OOS (2023-2026) | 49,927 | +1.62% | 58,883 | +1.70% | -0.08 | <0.000001 | -0.0262 |

**Direction is consistent across all three eras — `≤5` never outperforms `>5` in any era.** Development and Validation are both individually significant on Welch's t-test too (t=-6.24, p<0.000001 and t=-4.74, p=0.000002 respectively); OOS's mean gap narrows to -0.08pp and is not significant on the t-test (t=-1.09, p=0.278), though the MWU rank-based test remains significant there too (consistent with S-001's observation that OOS often shows higher dispersion that mean-based tests are more sensitive to than rank-based ones). No era shows the hypothesized positive direction.

---

## 6. Classification

**DEAD — reversed direction.** Not "no effect": across the full population and independently within all three eras, `sector_rs_rank ≤ 5` shows a *negative* mean-return delta versus `sector_rs_rank > 5`, is statistically significant in the full population and two of three eras, and the per-rank breakdown shows a gentle, near-monotonic trend running the opposite way from rank 1 through the 10+ bucket — not a threshold effect at 5 or anywhere else. The effect size is small (Cliff's δ ≈ -0.03, "negligible" by convention) and should not be read as "sector_rs_rank>5 is a strong buy signal" — but there is no evidence supporting the live filter's `≤5` condition as a return-improving pre-screen, and mild evidence it points the wrong way.

**Practical note (not a recommendation — reviewer's call):** this specific condition is one of seven ANDed in the Weinstein Watchlist toggle; this result says nothing about the combined filter's performance, only that `sector_rs_rank ≤ 5` in isolation does not carry the directional edge the filter's construction implies.

---

## 7. Limitations

1. **Small effect size despite large N** — statistical significance at N≈300K does not imply the gap is economically meaningful; Cliff's δ ≈ -0.03 in every cut is below the conventional "negligible" threshold.
2. **No control for co-occurring conditions** — this tests `sector_rs_rank` alone, per task scope; the live filter combines it with 6 other conditions (sector stage, EMA150, rank_change, near_pivot_days, liquidity) whose joint effect is not addressed here.
3. **Overlapping 10-day windows** — as with S-002, forward-return windows for the same symbol on adjacent dates overlap heavily; standard errors on very large N here are likely understated by both tests used (neither MWU nor Welch's t-test accounts for this within-symbol serial correlation). This affects the *precision* of the significance claim, not the sign/direction of the observed gap.
4. **Single, bounded test** — per task constraint, no additional candidate variables or filters were explored beyond the specified cutoff (5) and per-rank breakdown.

---

## 8. Reproducibility

Script: `sector_rs_rank_prescreen_test.py` (project root). Read-only — no production writes, no dashboard/code changes.
