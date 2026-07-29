# S-001 — Factor Study: Pivot-Distance-Pct Band for BREAKOUT

**Status:** CLOSED — 🔴 **TERMINATED** (H-001, 2026-07-03 — Development-era null, pre-registration cross-era condition not met; supersedes the earlier "🟡 Provisional Accept" verdict below, which is preserved as the original record — see Addendum C)  
**Filed:** 2026-07-03  
**Researcher:** Quantitative Analyst  
**Reviewer:** Independent Quantitative Reviewer (PI)  
**Population:** setup_log BREAKOUT, certified population (fwd_return_10d IS NOT NULL)  
**Database:** psx_data.db, snapshot reference Certified_Dataset_v1.0

---

## 1. Hypothesis

**H-001 (revised):** Among BREAKOUT setups, setups where `pivot_distance_pct ∈ [−18.51, −9.53]` (the close is roughly 10–18% above the breakout pivot, corresponding to the Development-era fourth quintile by extension magnitude) generate a higher mean `fwd_return_10d` than the BREAKOUT complement.

**Sign convention (confirmed):**  
`pivot_distance_pct = (pivot_high − close) / pivot_high × 100`  
- Positive: close is below the pivot (PRE_BREAKOUT territory)  
- Negative: close is above the pivot (BREAKOUT territory)  
- More negative = more extended above the pivot

**Supersedes:** H-001 (original, registered with band [4, 8]%, positive values — sign-inverted; zero BREAKOUT rows fall in that range; retired).

**Band selection:** The final band [−18.51, −9.53] was not pre-registered. It was selected via quintile exploration on Development data only (IS/OOS rule preserved). The original sign-corrected candidate [−8, −4] failed the Development quintile check (negative delta, p = 0.78); the Q4 band was identified as the performance peak in Development and locked before Validation was examined. See Section 3.

---

## 2. Data and Methodology

### 2.1 Population Queries

**Group A (no JOIN required):**
```sql
SELECT pivot_distance_pct, fwd_return_5d, fwd_return_10d, fwd_return_20d
FROM setup_log
WHERE setup_type = 'BREAKOUT'
  AND fwd_return_10d IS NOT NULL
  AND pivot_distance_pct IS NOT NULL
  AND setup_date BETWEEN '<era_start>' AND '<era_end>'
```

### 2.2 Era Boundaries

| Era         | Date Range          | N (BREAKOUT, non-NULL pdp) |
|-------------|---------------------|---------------------------|
| Development | 2015-01-01 → 2019-12-31 | 17,763                |
| Validation  | 2020-01-01 → 2022-12-31 | 11,604                |
| OOS         | 2023-01-01 → 2026-12-31 | 19,409                |

Note: N here counts BREAKOUT rows with both `fwd_return_10d IS NOT NULL` and `pivot_distance_pct IS NOT NULL`. This is a subset of the full certified population (203,996) restricted to BREAKOUT type and non-NULL pivot_distance_pct.

### 2.3 Statistical Tests

**Primary test:** Mann-Whitney U (one-sided, band > complement). Non-parametric; chosen because `fwd_return_10d` distributions have heavy tails and the complement group is heterogeneous (it pools Q1+Q2+Q3+Q5 — see Section 3.4 for implication).

**Secondary test:** Welch's t-test (one-sided), reported alongside MWU. The two tests can diverge when the mean is pulled by outliers without a shift in rank distribution; both results are reported explicitly and divergences are flagged.

**Significance threshold:** p < 0.05 (one-sided) for "pass." p < 0.01 reported as strong.

---

## 3. Part A — Development Era (2015–2019)

### 3.1 Full Distribution

| Statistic | Value |
|-----------|-------|
| N         | 17,763 |
| min pdp   | −255.26 |
| p5        | −40.75 |
| p25       | −15.38 |
| p50       | −7.03 |
| p75       | −2.88 |
| p90       | −1.12 |
| max pdp   | −0.004 |
| mean pdp  | −12.47 |

All BREAKOUT rows have negative `pivot_distance_pct`, confirming all breakout closes are above the pivot. The distribution is highly left-skewed: the extreme tail (Q5, down to −255) consists of stocks that broke out many periods ago and are now far extended, or are the result of pivot levels that were never updated.

### 3.2 Quintile Table

Quintile direction: Q1 = least extended (closest to zero), Q5 = most extended (most negative). N ≈ 3,552 per quintile.

| Q  | N    | pdp min   | pdp max   | mean 10d | med 10d | Win% | std 10d | mean 5d | mean 20d |
|----|------|-----------|-----------|----------|---------|------|---------|---------|----------|
| Q1 | 3,552 | −2.26    | −0.004    | 0.8915  | 0.0000  | 49.9% | 8.69  | 0.4917  | 1.7079  |
| Q2 | 3,552 | −5.13    | −2.26     | 0.8628  | −0.2285 | 48.5% | 9.07  | 0.4537  | 1.8763  |
| Q3 | 3,552 | −9.53    | −5.14     | 0.9366  | −0.3666 | 47.6% | 10.11 | 0.3354  | 1.5852  |
| Q4 | 3,552 | −18.51   | −9.53     | **1.3006** | 0.0000 | **49.9%** | 10.95 | 0.6394 | **2.4795** |
| Q5 | 3,555 | −255.26  | −18.52    | 0.8021  | −0.8047 | 46.1% | 14.29 | 0.5309  | 0.8106  |

**Pattern assessment:** Performance is **not monotonic**. The relationship is non-linear: Q1–Q3 are roughly flat (~0.86–0.94), Q4 peaks sharply (1.30), then Q5 falls back (0.80). There is a distinct single-quintile peak at Q4, not a smooth gradient. The original [−8, −4] band spans Q2–Q3, which are the two flattest quintiles. The performance gap between Q4 and all other quintiles is visible across mean 10d, win rate, and mean 20d (Q4 = 2.48 vs Q1 = 1.71, Q5 = 0.81).

### 3.3 Candidate Band — Original [−8, −4] Check

| Metric       | Band [−8,−4] | Complement | Delta |
|--------------|-------------|------------|-------|
| N            | 3,698        | 14,065     |       |
| mean 10d     | 0.7837      | 1.0047     | −0.22 |
| median 10d   | −0.4318     | −0.1770    |       |
| Win%         | 47.1%       | 48.8%      |       |
| MWU p (one-sided, band > comp) | — | — | 0.783 |

**Result: FAILED.** The [−8, −4] band underperforms the complement on every metric. p = 0.783 — no evidence band > complement. This band is retired.

### 3.4 Selected Band — Q4: [−18.51, −9.53]

**Selection rationale:** Q4 is the only quintile with a clearly elevated mean (1.30 vs ~0.86–0.94 for Q1–Q3) and the highest 20d return (2.48). It is selected as the band for validation. The selection is data-driven on Development data only — no Validation or OOS data was examined before this selection.

**Complement composition note:** The complement (N=14,211) pools Q1+Q2+Q3+Q5. This is not a coherent single group; it mixes tight breakouts (Q1, close just above pivot) with very extended ones (Q5, 18%+ above pivot). Mean comparisons interpret as "Q4 vs everything else," which is valid for screening purposes but should not be read as Q4 vs a homogeneous baseline.

| Metric       | Band Q4 [−18.51,−9.53] | Complement | Delta |
|--------------|------------------------|------------|-------|
| N            | 3,552                  | 14,211     |       |
| mean 10d     | **1.3006**             | 0.8732     | +0.43 |
| median 10d   | 0.0000                 | −0.2981    | +0.30 |
| Win%         | 49.9%                  | 48.0%      | +1.9pp |
| std 10d      | 10.95                  | 10.77      |       |
| mean 5d      | 0.6394                 | 0.4529     | +0.19 |
| mean 20d     | **2.4795**             | 1.4949     | +0.98 |
| MWU p (band > comp) | —              | —          | **0.0240** |
| t-test p (band > comp) | —           | —          | **0.0175** |

**Part A conclusion:** Q4 band outperforms complement. Both MWU and t-test significant at p < 0.05. Effect is consistent across 5d, 10d, 20d horizons (delta grows with horizon). Band selected and locked for Validation.

---

## 4. Part B — Validation Checkpoint (2020–2022)

Band [−18.51, −9.53] applied without modification. No inspection of Validation data preceded this test.

### 4.1 Quintile Table (Validation)

| Q  | N    | pdp min   | pdp max   | mean 10d | med 10d | Win% |
|----|------|-----------|-----------|----------|---------|------|
| Q1 | 2,320 | −2.30   | −0.00     | 0.5376  | −1.0429 | 43.1% |
| Q2 | 2,320 | −5.41   | −2.30     | 1.2718  | 0.0000  | 49.7% |
| Q3 | 2,320 | −10.47  | −5.41     | 1.3551  | −0.2056 | 48.8% |
| Q4 | 2,320 | −21.12  | −10.47    | **2.1867** | 0.5800 | **52.8%** |
| Q5 | 2,324 | −256.06 | −21.14    | 1.7861  | 0.0000  | 49.9% |

Q4 is again the peak quintile (mean 2.19, win rate 52.8%). Q1 is the weakest (43.1%). Rank ordering shifted slightly from Development (Q3 now ahead of Q2) but Q4 remains the top performer.

### 4.2 Band vs Complement Test (Validation)

| Metric       | Band Q4 [−18.51,−9.53] | Complement | Delta |
|--------------|------------------------|------------|-------|
| N            | 2,280                  | 9,324      |       |
| mean 10d     | **2.1529**             | 1.2502     | **+0.90** |
| median 10d   | 0.7590                 | −0.3929    | +1.15 |
| Win%         | 53.1%                  | 47.8%      | +5.3pp |
| std 10d      | 12.57                  | 13.28      |       |
| mean 5d      | 1.2706                 | 0.7325     | +0.54 |
| mean 20d     | 3.5427                 | 2.4133     | +1.13 |
| MWU p (band > comp) | —              | —          | **< 0.001** |
| t-test p (band > comp) | —           | —          | **0.0017** |

**Validation verdict: PASSED.**

The Development-era finding holds and is stronger in Validation:
- Mean delta increased from +0.43 (Dev) to +0.90 (Val)
- Median delta grew from +0.30 to +1.15
- Win rate advantage widened from +1.9pp to +5.3pp
- Both statistical tests significant at p < 0.002

Same direction, stronger magnitude, stronger significance. Proceeding to OOS.

---

## 5. Part C — OOS (2023–2026)

Band [−18.51, −9.53] applied unchanged.

### 5.1 Quintile Table (OOS)

| Q  | N    | pdp min   | pdp max   | mean 10d | med 10d | Win% |
|----|------|-----------|-----------|----------|---------|------|
| Q1 | 3,881 | −2.75   | −0.00     | 1.7162  | 0.1827  | 50.9% |
| Q2 | 3,881 | −6.46   | −2.75     | 1.7108  | 0.3205  | 51.7% |
| Q3 | 3,881 | −12.09  | −6.46     | **2.4656** | 0.2951 | 51.4% |
| Q4 | 3,881 | −22.66  | −12.09    | 1.7361  | 0.0000  | 49.8% |
| Q5 | 3,885 | −374.89 | −22.66    | 1.7289  | −1.4291 | 44.2% |

**OOS quintile shift:** The peak moves from Q4 to Q3 in OOS. Q4 (the selected band's approximate region) is mid-table. Q5 remains the weakest quintile. This is evidence of partial decay — the specific Q4 advantage from Development and Validation is less pronounced in OOS.

### 5.2 Band vs Complement Test (OOS)

| Metric       | Band Q4 [−18.51,−9.53] | Complement | Delta |
|--------------|------------------------|------------|-------|
| N            | 4,171                  | 15,238     |       |
| mean 10d     | 2.0806                 | 1.8143     | **+0.27** |
| median 10d   | 0.2072                 | −0.1086    | +0.32 |
| Win%         | 50.9%                  | 49.3%      | +1.6pp |
| std 10d      | 14.07                  | 14.45      |       |
| mean 5d      | 0.9253                 | 0.9035     | +0.02 |
| mean 20d     | 3.5343                 | 3.0566     | +0.48 |
| MWU p (band > comp) | —              | —          | **0.0326** |
| t-test p (band > comp) | —           | —          | 0.1445 |

**OOS assessment: MIXED.**

- Direction preserved: mean delta = +0.27 (vs +0.43 Dev, +0.90 Val). Positive but attenuated.
- MWU significant at p = 0.033; t-test not significant (p = 0.14).
- Divergence between MWU and t-test signals: MWU detects a shift in the rank distribution; t-test is overwhelmed by the high std (14+) and the delta is too small relative to noise for a mean comparison.
- Win rate advantage = +1.6pp (vs +1.9pp Dev, +5.3pp Val) — narrowed substantially.
- 20d horizon still shows +0.48 delta, which may indicate the edge is real but delayed or diluted in the post-2023 regime.

---

## 6. Cross-Era Summary

| Era         | N (band) | mean 10d (band) | mean 10d (comp) | Delta | MWU p  | t-test p | Verdict     |
|-------------|----------|-----------------|-----------------|-------|--------|----------|-------------|
| Development | 3,552    | 1.30            | 0.87            | +0.43 | 0.024  | 0.018    | PASS        |
| Validation  | 2,280    | 2.15            | 1.25            | +0.90 | <0.001 | 0.002    | PASS (strong) |
| OOS         | 4,171    | 2.08            | 1.81            | +0.27 | 0.033  | 0.145    | MIXED       |

**Observations:**

1. **Direction is preserved across all three eras.** Band Q4 outperforms its complement on mean 10d in every era. No era shows a negative delta.

2. **Magnitude decays in OOS.** The delta peaks in Validation (+0.90) and falls sharply in OOS (+0.27). This is a classic out-of-sample attenuation pattern — not unexpected, but the degree of attenuation (−70% from Val to OOS) is notable.

3. **Statistical confidence is era-dependent.** The finding is robust in Dev and Val; in OOS, the rank-based test (MWU) remains significant but the mean-based test does not. This reflects both smaller delta and higher volatility in OOS (std ~14 vs ~10–11 in Dev).

4. **The Q4 peak is not stable across eras.** In Development and Validation, Q4 is the clear top quintile. In OOS, the peak shifts to Q3 (approximately −12 to −6). This suggests the optimal extension range drifts over time and no single band can be expected to remain dominant across market regimes.

5. **The original [−8, −4] band failed in Development** (negative delta, p = 0.78) and is not further considered. It is formally retired.

---

## 7. IS/OOS Discipline Compliance

| Rule | Compliance |
|------|------------|
| Band selected in Development only | ✓ |
| Validation examined only after band locked | ✓ |
| OOS examined only after Validation passed | ✓ |
| No re-tuning after Validation | ✓ |
| No pooling across eras | ✓ |
| Complement heterogeneity disclosed | ✓ |
| Band selection method (quintile exploration) documented | ✓ |
| OOS quintile shift (peak moved to Q3) disclosed | ✓ |

**Deviations from original registration:**
- Band changed from [−8, −4] to [−18.51, −9.53] after Development quintile exploration revealed the [−8, −4] sign-corrected band performed below complement. The change was made within Development, constitutes Development-era threshold selection (permitted), and is fully documented.
- The band boundaries are Development quintile cutoffs (P60 and P80 of `pivot_distance_pct` in that era), not arbitrary round numbers.

---

## 8. Limitations

1. **Complement is heterogeneous.** The Q4 complement pools tight breakouts (Q1, 0–2.3% above pivot), moderate (Q2–Q3), and highly extended (Q5, >18.5% above). A true counterfactual should compare Q4 to a specific alternative band, not the union of all others.

2. **Quintile boundaries are era-specific.** The boundaries [−18.51, −9.53] are Development quintile cutoffs. In Validation the corresponding Q4 range is [−21.12, −10.47] and in OOS it is [−22.66, −12.09]. The fixed band captures slightly different proportions of each era's distribution. In Val the band undercuts Q4's own range slightly; in OOS the band sits in Q3–Q4 territory. This partially explains the OOS attenuation.

3. **OOS quintile peak shift.** The strongest performance in OOS is in Q3 (−12 to −6), not Q4. If the study were re-run as an adaptive rolling band, results might be stronger. However, adaptive tuning is not permitted under IS/OOS discipline.

4. **No regime stratification.** The three-era split absorbs regime variation broadly, but results are not stratified by `regime` column (TRENDING_UP vs RANGING vs VOLATILE vs TRENDING_DOWN). The OOS attenuation may be regime-driven; this is an open question for follow-on studies.

5. **Survivorship bias.** The certified population contains only symbols that survived to have forward return data computed. Delisted symbols (100 rows excluded as per EXP-0002) may disproportionately fall in certain extension bands.

---

## 9. Conclusion

**H-001 (revised) is provisionally supported with attenuation in OOS.**

The Q4 pivot-distance band (−18.51% to −9.53%, approximately 10–18% extended above the breakout pivot) shows a consistent positive advantage over the BREAKOUT complement across all three eras. The finding is statistically robust in Development and Validation, and directionally preserved in OOS with attenuated magnitude.

The original hypothesis band [−8, −4] (close is 4–8% above pivot) is not supported and is retired.

The OOS result is mixed enough that this finding should not be used as a standalone entry signal. The band identifies a favorable sub-population, not a standalone trading signal.

---

## 10. Recommended Evidence Register Entry

*(For PI/reviewer approval — not self-approved)*

| Field            | Value |
|------------------|-------|
| Evidence ID      | E-001 |
| Study            | S-001 |
| Hypothesis       | H-001 (revised) |
| Factor           | pivot_distance_pct band [−18.51, −9.53] |
| Setup Type       | BREAKOUT |
| Finding          | Band outperforms complement: +0.43pp Dev, +0.90pp Val, +0.27pp OOS (mean 10d) |
| Direction        | Consistent positive across all three eras |
| Statistical Status | Dev: MWU p=0.024; Val: MWU p<0.001; OOS: MWU p=0.033, t-test p=0.145 |
| Confidence       | Moderate — robust through Validation, attenuated in OOS |
| Status           | Provisional Accept — awaiting PI review |
| Open Questions   | (1) OOS Q3 peak shift — is the optimal band drifting? (2) Regime stratification may explain OOS attenuation. (3) Complement heterogeneity — consider Q4 vs Q1 only as cleaner test. |
| Recommended Next Step | S-001a: stratify Q4 vs Q1 (tight breakouts only) to test whether Q4 advantage is driven by avoiding tight breakouts or seeking moderate extension specifically |

---

# S-001 Diagnostic Addendum

**Filed:** 2026-07-03
**Researcher:** Quantitative Analyst
**Reviewer:** Independent Quantitative Reviewer (PI)
**Scope:** Response to four reviewer concerns on S-001 before any Evidence Register entry is considered. Covers Task 1 (multiple-comparison disclosure), Task 2 (median/outlier-robustness check), Task 3 (S-001a: Q4 vs Q1, Development + Validation only).

**OOS handling:** Task 2 recomputes descriptive statistics (median, trimmed mean, winsorized mean) on the *same* frozen-band-vs-complement partition already opened and tested in Sections 4–6 of the base study — no new threshold, no new test, no re-opening of OOS under a redefined band. Task 3 is confined to Development and Validation only, per reviewer instruction; **OOS was not queried for Task 3.**

This addendum does not update the Evidence Register recommendation in Section 10. That decision remains with the reviewer/PI.

---

## 11. Task 1 — Multiple Comparison Disclosure

Five quintiles (Q1–Q5) were computed on Development data and the best-performing one (Q4) was selected post hoc, then tested against the complement. This is a "select the best of 5" procedure, not a single pre-registered test, and the reported p-values do not account for that selection.

**Bonferroni correction:** adjusted α = 0.05 / 5 = **0.01**.

| Test (Development, Q4 vs complement) | Reported p | vs. uncorrected α=0.05 | vs. Bonferroni α=0.01 |
|---|---|---|---|
| Mann-Whitney U (one-sided) | 0.0216–0.024* | Significant | **NOT significant** |
| Welch's t-test (one-sided) | 0.0162–0.018* | Significant | **NOT significant** |

*Two values shown because this addendum's independently re-run extraction (frozen band, exact boundary arithmetic) gives p=0.0216/0.0162, marginally different from the originally filed 0.024/0.018 due to boundary rounding in the frozen band definition (±0.01 pdp at the edges shifts ~4 rows in/out of Q4). The discrepancy is immaterial to the conclusion below.

**Plain statement:** Neither the MWU nor the t-test result for Q4 survives a Bonferroni correction for testing 5 quintiles and picking the best one. At the corrected threshold, **the Development-era result would be classified as NOT significant.** The original write-up's "PASS" verdict in Part A reflects only the uncorrected, single-comparison view. Under a multiple-comparison-aware view, Development alone does not clear the bar — it took Validation's much stronger, independently-computed result (MWU p<0.001, t-test p=0.0012, still passing Bonferroni's 0.01 threshold) to keep this hypothesis alive after Development.

**Implication:** the fact that Validation passed even the corrected threshold on its own is the only reason this survives Task 1's scrutiny at all. If Validation had come back marginal (like Development), the honest conclusion after correction would be that no quintile survived selection scrutiny.

---

## 12. Task 2 — Median and Outlier-Robustness Check

Uses the frozen Development-derived band [−18.51, −9.53] vs. its complement, applied unmodified to each era (same partition as Sections 4.2 / 5.2 / 6 of the base study — not a re-run against a new threshold).

### 12.1 Median comparison (all three eras)

| Era | Q4 median | Complement median | Delta (median) | Delta (mean, for reference) |
|---|---|---|---|---|
| Development | 0.0000 | −0.2990 | **+0.30** | +0.44 |
| Validation | 0.8046 | −0.3932 | **+1.20** | +0.90 |
| OOS | 0.2079 | −0.1088 | **+0.32** | +0.27 |

The median delta is positive in all three eras and is not smaller than the mean delta in any era — in Validation and OOS it is actually *larger* than the mean delta. This is the opposite of what a purely magnitude/outlier-driven effect would look like (a magnitude-driven effect typically shows a large mean delta but a near-zero or inconsistent median delta). The median result does not support the "large-winner artifact" explanation on its own.

### 12.2 Trimmed mean (1% each tail) and winsorized mean (1% each tail)

| Era | Q4 trimmed(1%) | Comp trimmed(1%) | Delta trimmed | Q4 winsor(1%) | Comp winsor(1%) | Delta winsor | Delta raw mean |
|---|---|---|---|---|---|---|---|
| Development | 1.0889 | 0.6612 | +0.4277 | 1.2251 | 0.7958 | +0.4292 | +0.4381 |
| Validation | 1.9754 | 1.0213 | **+0.9542** | 2.1340 | 1.1958 | +0.9382 | +0.9036 |
| OOS | 1.7607 | 1.4342 | **+0.3266** | 2.0294 | 1.6793 | **+0.3501** | +0.2683 |

In every era, the trimmed/winsorized delta is close to (Dev, Val) or **larger than** (OOS) the raw mean delta. Removing the top/bottom 1% did not shrink the effect — in OOS it actually grew (+0.27 raw → +0.33–0.35 trimmed/winsorized). This means the OOS mean comparison was, if anything, being *held down* by extreme-tail losses in the complement group, not inflated by extreme wins in Q4.

### 12.3 Symmetric extreme-trim sensitivity (drop top/bottom k observations from each group)

| Era | k=5 | k=10 | k=20 |
|---|---|---|---|
| Development | +0.409 | +0.384 | +0.339 |
| Validation | +0.899 | +0.885 | +0.834 |
| OOS | +0.242 | +0.250 | +0.178 |

The delta erodes gradually as more extreme observations are removed (expected — trimming removes real signal along with noise) but **remains positive at every trim level in every era**, including OOS at k=20 (+0.178, off a base of +0.268). There is no trim level at which the sign flips.

### 12.4 Direct outlier check (top/bottom 5 raw values, Q4 vs. complement)

| Era | Q4 top 5 | Q4 bottom 5 | Comp top 5 | Comp bottom 5 |
|---|---|---|---|---|
| Development | 111.98, 76.65, 72.25, 72.13, 63.97 | −31.42, −40.89, −44.90, −49.64, −50.61 | 133.80, 115.47, 113.95, 109.38, 96.94 | −49.83, −50.99, −55.08, −75.90, −78.19 |
| Validation | 94.15, 78.60, 77.24, 70.79, 66.58 | −43.04, −43.69, −44.09, −52.94, −57.13 | 248.80, 232.02, 128.62, 116.76, 112.34 | −69.22, −70.37, −71.34, −72.72, −76.27 |
| OOS | 150.27, 130.80, 122.70, 114.41, 113.39 | −82.23, −82.34, −83.33, −89.47, −90.13 | 159.54, 159.37, 150.32, 150.31, 142.82 | −89.85, −90.02, −90.87, −98.58, −98.69 |

Notably, **the most extreme values in every era belong to the complement, not to Q4** (e.g. Validation complement's +248.8% and +232.0% dwarf anything in Q4). If the finding were an artifact of a few lucky Q4 outliers, we would expect Q4's tail to be fatter than the complement's. It is not — the complement's tail is fatter in every era, and yet Q4 still wins on mean, median, and trimmed comparisons. This further undercuts the "large-winner artifact" hypothesis.

### 12.5 Task 2 conclusion

**The mean-return advantage for Q4 does NOT appear to be substantially driven by a small number of extreme returns.** All four checks (median, trimmed mean, winsorized mean, symmetric extreme-trim) point the same direction: the effect survives outlier removal at comparable or larger magnitude in Development and Validation, and — counterintuitively — the OOS effect is *understated* by the raw mean because the complement group carries larger tail losses than Q4 in that era. This reframes the Task 3 (Section 5.2 base study) OOS MWU/t-test divergence: it is not that Q4's OOS mean is being flattered by outliers, but that the complement's mean is being pulled by its own tail, narrowing the visible raw-mean gap. See Section 13 for the direct test of this mechanism.

---

## 13. Task 3 — S-001a: Q4 vs Q1 Diagnostic (Development + Validation ONLY — OOS not touched)

Purpose: determine whether the Q4-vs-pooled-complement advantage in the base study reflects Q4 being genuinely better than *tight* breakouts (Q1) specifically, or whether it mainly reflects Q4 beating the moderate/extreme quintiles (Q2, Q3, Q5) while looking similar to Q1.

Quintile boundaries are era-specific (as originally defined in Sections 3.2 and 4.1 of the base study — Q1 = least extended, Q4 = fourth quintile by extension).

### 13.1 Development (2015–2019)

| Group | N | Mean 10d | Median 10d | Win% |
|---|---|---|---|---|
| Q4 | 3,552 | 1.3024 | 0.0000 | 49.9% |
| Q1 | 3,555 | 0.8883 | 0.0000 | 49.9% |
| **Delta** | | **+0.4142** | **0.0000** | **+0.01pp** |

**MWU p (Q4 > Q1, one-sided) = 0.5681 — NOT significant.**
**t-test p (Q4 > Q1, one-sided) = 0.0387 — marginally significant.**

Win rates are identical (49.9% vs 49.9%) and medians are identical (0.00 vs 0.00). The rank-based test finds **no evidence** that Q4's return distribution is shifted above Q1's. The mean-based test is only marginally significant, and per Section 12's diagnosis, mean-based tests here are sensitive to tail composition rather than a broad distributional shift. **In Development, Q4 and Q1 are statistically indistinguishable on the primary (rank-based) test.** This confirms the reviewer's concern: the Development-era Q4-vs-complement advantage documented in the base study is not evidence that Q4 beats *tight breakouts specifically* — it more likely reflects Q4 outperforming the moderate/extreme quintiles (Q2, Q3, Q5), which is a narrower and weaker claim than "avoid tight breakouts, seek moderate extension."

### 13.2 Validation (2020–2022)

| Group | N | Mean 10d | Median 10d | Win% |
|---|---|---|---|---|
| Q4 | 2,320 | 2.1591 | 0.5670 | 52.7% |
| Q1 | 2,324 | 0.5320 | −1.0360 | 43.2% |
| **Delta** | | **+1.6271** | **+1.6031** | **+9.51pp** |

**MWU p (Q4 > Q1, one-sided) < 0.0001 — highly significant.**
**t-test p (Q4 > Q1, one-sided) < 0.0001 — highly significant.**

In sharp contrast to Development, Validation shows a large, consistent gap on every metric: mean, median, and win rate all favor Q4 by a wide margin, and both tests agree at high significance. This is a genuine distributional shift, not a mean/outlier artifact — the median gap (+1.60) is nearly as large as the mean gap (+1.63), and the win-rate gap (+9.5pp) is the largest seen anywhere in this diagnostic.

### 13.3 Task 3 conclusion

**The Q4-vs-Q1 relationship is not stable across eras.** Development shows no significant Q4 vs Q1 edge on the rank-based test (and only a marginal mean-based edge); Validation shows a strong, unambiguous edge on every metric. This means:

1. The reviewer's concern #2 is **confirmed for Development specifically**: Q1 and Q4 have identical win rates and medians there, and the apparent Q4 advantage over the *pooled* complement in that era is being driven by Q4 beating Q2/Q3/Q5, not by Q4 beating tight breakouts.
2. The reviewer's concern is **not confirmed for Validation**: there, Q4 genuinely and substantially outperforms Q1 by every measure, not just the mean.
3. Combined with Task 1 (Development fails Bonferroni correction on its own) and Task 2 (OOS mean-comparison was actually *understated*, not inflated, by tail composition), the overall picture is: **Development's contribution to H-001 is the weakest link in the chain** — it does not survive multiple-comparison correction, and its internal Q4-vs-Q1 contrast does not survive a rank-based test. Validation is the era carrying the strongest and most robust evidence for this hypothesis. OOS (per the base study, unchanged here) shows attenuated but directionally consistent support.

---

## 14. Addendum Summary Table

| Concern | Investigated | Verdict |
|---|---|---|
| 1. Multiple-comparison inflation (5 quintiles, best selected) | Bonferroni correction applied to Development p-values | **Development result does NOT survive correction** (p=0.016–0.022 vs α=0.01). Validation independently clears the corrected bar. |
| 2. Q1/Q4 identical win rates, mean-driven apparent edge | Median + Q4-vs-Q1 direct test (Dev, Val) | **Confirmed in Development** (Q4 vs Q1 not significant on MWU, medians identical). **Not confirmed in Validation** (large, significant, multi-metric gap). |
| 3. OOS MWU-significant / t-test-not-significant divergence | Trimmed/winsorized means, extreme-trim sensitivity, direct tail comparison | Divergence is **not** caused by Q4 having fat-tailed outliers — the complement's tails are fatter in every era. Outlier-adjusted OOS deltas are equal to or larger than the raw mean delta. |
| 4. OOS must not be re-touched for band redefinition | Task 3 restricted to Dev + Validation only | **Complied** — no OOS query issued for Task 3. Task 2's OOS numbers reuse the already-opened band-vs-complement comparison only. |

**Net effect on H-001 (revised) evidentiary weight:** the finding is **not strengthened** by this diagnostic — Development is weaker than the base study's uncorrected p-values suggested, and its internal Q1-vs-Q4 contrast does not hold up. Validation remains the strongest leg of the three-era test and is unaffected by any of the four concerns raised. OOS attenuation is now better understood (tail composition, not a vanishing effect) but remains the weakest leg on formal significance. This diagnostic does not change the Section 10 recommendation; it is left to the reviewer/PI to decide whether "Validation-anchored, Development-weak, OOS-attenuated" still merits a Provisional Accept or requires downgrade to Hypothesis-Only pending further replication.

---

# Addendum B — Regime Stratification

**Filed:** 2026-07-03
**Researcher:** Quantitative Analyst
**Reviewer:** Independent Quantitative Reviewer (PI)
**Scope:** Response to the atypical Development/Validation pattern found in the S-001 Diagnostic Addendum (Q4 vs Q1 not significant in Development, p=0.57, but highly significant in Validation, p<0.0001). Tests the alternative hypothesis that the Q4 effect is regime-dependent rather than a stable pivot-distance phenomenon.

**OOS handling: not touched.** All queries in this addendum are restricted to `setup_date` in [2015-01-01, 2019-12-31] (Development) and [2020-01-01, 2022-12-31] (Validation). No OOS row was read. Q4/Q1 quintile boundaries are the same era-specific boundaries already locked in Section 3.2 (Development) and Section 4.1 (Validation) — no threshold was redefined; this is a stratification of already-locked groups by the pre-existing `regime` column (denormalized in `setup_log`, no JOIN required).

---

## B.1 Task 1 — Regime Composition (All BREAKOUT, Q4, Q1)

### Development (2015-01-01 to 2019-12-31)

| Regime | All BREAKOUT (N=17,763) | Q4 (N=3,552) | Q1 (N=3,555) |
|---|---|---|---|
| TRENDING_UP | 10,553 (59.4%) | 2,218 (62.4%) | 1,789 (50.3%) |
| TRENDING_DOWN | 513 (2.9%) | 64 (1.8%) | 141 (4.0%) |
| RANGING | 5,141 (28.9%) | 984 (27.7%) | 1,230 (34.6%) |
| VOLATILE | 1,556 (8.8%) | 286 (8.1%) | 395 (11.1%) |

### Validation (2020-01-01 to 2022-12-31)

| Regime | All BREAKOUT (N=11,604) | Q4 (N=2,320) | Q1 (N=2,324) |
|---|---|---|---|
| TRENDING_UP | 5,717 (49.3%) | 1,223 (52.7%) | 1,006 (43.3%) |
| TRENDING_DOWN | 508 (4.4%) | 84 (3.6%) | 103 (4.4%) |
| RANGING | 4,617 (39.8%) | 867 (37.4%) | 1,038 (44.7%) |
| VOLATILE | 762 (6.6%) | 146 (6.3%) | 177 (7.6%) |

**Observations:**

1. **Within each era**, Q4 consistently skews toward TRENDING_UP relative to Q1, and Q1 consistently skews toward RANGING/VOLATILE relative to Q4. This pattern holds in both eras and is not new information — it simply confirms that more-extended breakouts (Q4) tend to occur more often in established uptrends, and tight breakouts (Q1) occur more often in choppier conditions. This is expected and not diagnostic on its own.

2. **Across eras**, Validation's overall BREAKOUT pool is markedly less TRENDING_UP-heavy (49.3% vs 59.4%) and more RANGING-heavy (39.8% vs 28.9%) than Development's — consistent with 2020-2022 being a choppier, event-driven period (COVID crash, recovery, 2022 drawdown).

3. **The VOLATILE-regime hypothesis is NOT supported by composition.** VOLATILE's share of BREAKOUT setups is actually *lower* in Validation (6.6%) than in Development (8.8%), for both the full pool and for Q4/Q1 specifically. If the Q4 effect's Validation strength were explained by "more VOLATILE-regime days," composition should show the opposite pattern. It does not — the initial regime-mix hypothesis, as stated, is falsified by this table alone.

4. A supplementary check (not requested, included for completeness): within-regime **volatility of `fwd_return_10d`** is materially higher in Validation than in Development for the same regime label — e.g. TRENDING_UP std 10.36 (Dev) vs 12.82 (Val); VOLATILE std 10.31 (Dev) vs 16.39 (Val). This suggests 2020-2022 was a higher-magnitude era *within* every regime bucket, not just a differently-mixed one — the 4-category regime classifier does not fully capture the era's character. This is examined further in B.4.

---

## B.2 Task 2 — Per-Regime Q4 vs Q1, Development Only

| Regime | Q4 N / mean / median / win% | Q1 N / mean / median / win% | Delta mean | MWU p (Q4>Q1) | t-test p (Q4>Q1) |
|---|---|---|---|---|---|
| TRENDING_UP | 2,218 / 1.2697 / 0.1075 / 50.6% | 1,789 / 1.2391 / 0.2647 / 52.0% | +0.03 | 0.908 | 0.458 |
| TRENDING_DOWN | 64 / 2.4940 / 0.0551 / 50.0% | 141 / −0.5868 / −2.0547 / 41.1% | +3.08 | 0.065 | 0.066 |
| RANGING | 984 / 1.4314 / −0.2597 / 48.8% | 1,230 / 0.7821 / −0.2478 / 48.0% | +0.65 | 0.421 | 0.077 |
| VOLATILE | 286 / 0.8459 / −0.2249 / 48.3% | 395 / 0.1563 / −0.0864 / 49.4% | +0.69 | 0.440 | 0.193 |

**No regime clears p<0.05 on the primary (rank-based) MWU test in Development.** TRENDING_DOWN shows the largest raw delta (+3.08) and comes closest to significance on both tests (p≈0.065), but this cell has the smallest N (64 vs 141) of any cell in either era — flagged as the least powered cell, though it clears the ~20-row minimum. Every other regime is clearly non-significant (MWU p ≥ 0.42). This is consistent with Section 13.1 of the Diagnostic Addendum: Development shows no broad, robust Q4-vs-Q1 edge, and stratifying by regime does not reveal a hidden significant sub-effect — if anything, TRENDING_DOWN is the only cell showing a hint of one, and it is underpowered.

---

## B.3 Task 3 — Per-Regime Q4 vs Q1, Validation Only

| Regime | Q4 N / mean / median / win% | Q1 N / mean / median / win% | Delta mean | MWU p (Q4>Q1) | t-test p (Q4>Q1) |
|---|---|---|---|---|---|
| TRENDING_UP | 1,223 / 2.5793 / 0.6772 / 53.5% | 1,006 / 1.3995 / −0.7019 / 45.8% | +1.18 | **0.0006** | **0.0084** |
| TRENDING_DOWN | 84 / 2.2765 / 2.3822 / 54.8% | 103 / −0.7322 / −0.5604 / 42.7% | +3.01 | **0.0102** | **0.0239** |
| RANGING | 867 / 1.5686 / 0.2405 / 51.2% | 1,038 / −0.0841 / −1.5194 / 40.0% | +1.65 | **0.0001** | **0.0020** |
| VOLATILE | 146 / 2.0790 / 1.1977 / 53.4% | 177 / −0.0499 / −0.5428 / 46.9% | +2.13 | **0.0487** | 0.139 |

**All four regimes show a positive Q4-vs-Q1 delta in Validation, and three of four clear p<0.05 on both tests (TRENDING_UP, TRENDING_DOWN, RANGING); VOLATILE clears MWU (p=0.049) but not the t-test (p=0.139), the smallest-N regime here (146 vs 177) and consistent with the outlier-sensitivity pattern already documented in the Diagnostic Addendum.** This is the opposite of a regime-concentrated result — the effect shows up broadly, inside every regime bucket, not inside one specific regime.

---

## B.4 Task 4 — Is the Effect Regime-Concentrated?

**No.** The Q4 advantage is **not concentrated in a specific regime** in either era:

- In **Development**, it is absent (non-significant) in *all four* regimes — there is no regime where Q4 beats Q1 with the rank-based test. The closest thing to a signal (TRENDING_DOWN, p≈0.065) is both underpowered and, at N=64/141, the smallest cell in the entire stratification.
- In **Validation**, it is present in *all four* regimes — RANGING, TRENDING_UP, and TRENDING_DOWN are all significant on both tests; VOLATILE is significant on the rank test only (again the smallest-N cell, N=146/177).

Because Validation shows the effect broadly across every regime bucket rather than in one bucket disproportionately, **this rules out "Validation just contains more of one favorable regime" as the explanation** — that hypothesis would predict the effect concentrating in whichever regime is over-represented in Validation, and it does not (Section B.1 already showed VOLATILE is in fact *less* represented in Validation, the opposite of what a VOLATILE-driven story requires).

**What this does suggest:** the Development/Validation divergence is an **era effect that operates within every regime bucket**, not a regime-mix effect. The supplementary volatility check in B.1.4 is the most likely explanatory thread — within every regime label, Validation-era forward returns are simply more dispersed (std 12-16 vs 10-14 in Development, largest gap in VOLATILE: 16.39 vs 10.31). A more dispersed return distribution mechanically widens the gap a rank-based test can detect between two differently-shaped groups (Q4 vs Q1), even if the *categorical* regime label is identical across eras. In plain terms: 2020-2022 was a higher-amplitude period in absolute terms, in ways the four-category regime classifier (TRENDING_UP / TRENDING_DOWN / RANGING / VOLATILE) does not fully capture, and that amplitude — not a specific regime being more common — is the more plausible driver of why Validation shows a cleaner Q4-vs-Q1 separation than Development.

**Plain-language verdict:** This looks like **neither a pure pivot-distance effect nor a pure regime effect**, but closer to an **era/volatility-regime interaction that the 4-category classifier does not resolve**. The pivot-distance factor itself does not show a stable, regime-independent edge in Development (it fails within every regime there). It shows a strong, broad edge in Validation across every regime there. The most defensible reading is: **this hypothesis has one clean, broad-based supporting era (Validation) and one era where it does not replicate at all, at any regime granularity (Development)** — the regime classifier does not explain the discrepancy, but era-level return dispersion is a plausible unexplained confound that a future study should test directly (e.g. by conditioning on a continuous volatility measure rather than the categorical regime label).

---

## B.5 Summary

| Question | Finding |
|---|---|
| Does Validation's setup pool have a different regime mix than Development's? | Yes — less TRENDING_UP, more RANGING. But VOLATILE share is *lower* in Validation, contradicting the "more volatile regime" hypothesis directly. |
| Is the Q4 vs Q1 effect concentrated in one regime? | No — absent in all 4 regimes in Development, present in all 4 (3 fully, 1 partially) in Validation. |
| Does regime composition explain the Dev/Val divergence? | No — the divergence appears within every regime bucket, so it cannot be a composition artifact. |
| What does explain it? | Unresolved. Era-level return dispersion (higher within-regime std in Validation across the board) is the most plausible candidate but is not formally tested here — flagged as an open question for a future study, not concluded as fact. |

This addendum does not change the Section 10 Evidence Register recommendation. It adds one further consideration for the reviewer/PI: the Development/Validation asymmetry is not a regime-mix artifact, which somewhat strengthens the case that Validation's result is "real" for that era specifically, but it also means Development's failure to replicate cannot be explained away as "wrong regime mix" either — Development's null result stands on its own across every regime tested.

---

# Addendum C — Methodology Change Log and Study Termination

**Filed:** 2026-07-03
**Type:** Paperwork / traceability record — no new analysis in this section.

This section exists per the project guardrail against silent methodology drift: any mid-study change to a hypothesis's operational definition must be logged explicitly (what changed, when, why), not left implicit in narrative text alone.

## C.1 Methodology Change Record

| Field | Value |
|---|---|
| **What changed** | The tested form of `pivot_distance_pct` changed twice within S-001: (1) original registration used a positive-value band [4,8]%, later found sign-inverted and retired before any test was run (zero BREAKOUT rows fall in that range by construction); (2) the sign-corrected replacement band [-8,-4]% was tested in Development and failed (Section 3.3, p=0.783, negative delta) — also retired; (3) the study then pivoted to a **quintile-exploration methodology** on Development data, identifying Q4 [-18.51,-9.53] as the best-performing quintile, which became the band carried into Validation and OOS (Sections 3.4–6), and was later further decomposed into a direct Q4-vs-Q1 quintile contrast (S-001a, Diagnostic Addendum Section 13) in response to reviewer concerns about complement heterogeneity. |
| **When** | All three changes occurred within Development-era analysis, before Validation was examined, and are documented inline in the base study (Sections 1, 3.3, 3.4) and Diagnostic Addendum (Section 13). This addendum consolidates the record explicitly rather than leaving it distributed across narrative sections. |
| **Why** | (1) Sign inversion was a construction error, not a methodology choice — correction was mandatory. (2) The sign-corrected band failed on its own merits in Development, before Validation was touched — retiring it and searching for a better-performing sub-range within the same era is within the IS/OOS discipline (Development-only threshold selection is permitted; see Section 7). (3) The pivot to quintile exploration was the mechanism used to find that better-performing sub-range; the later Q4-vs-Q1 direct contrast was requested by the reviewer specifically to test whether the quintile-vs-pooled-complement result was being driven by complement heterogeneity (Section 12/13) — not a new threshold search, but a decomposition of an already-locked comparison. |
| **Multiple-comparison consequence** | Because quintile exploration is a "test 5, pick the best" procedure, the Development-era Q4 result carries a look-elsewhere penalty. This was quantified after the fact in the Diagnostic Addendum (Section 11, Task 1) and is now codified as a standing rule for all future studies — see [Decision D-001](Decisions.md). |

## C.2 Study Termination Record

| Field | Value |
|---|---|
| **Date terminated** | 2026-07-03 |
| **Terminated by** | Pre-registration gating condition ("effect must hold across all three eras independently") — not a discretionary reviewer/PI call, though reviewed and confirmed by the reviewer before this record was filed. |
| **Failing era** | Development. Both the direct Q4-vs-Q1 quintile contrast (Cliff's delta -0.0023, MWU p=0.568, N=3,552 vs 3,555) and all 4 individual regime-stratified sub-cells (Addendum B, Section B.2) show no relationship. |
| **OOS status** | Not opened for this Q4-vs-Q1 contrast and not required to be — the pre-registered stopping rule triggers on Development failure alone. The original Q4-vs-pooled-complement OOS result from Section 5 remains on record as historical fact (mixed: MWU p=0.033, t-test p=0.145) but is superseded in relevance by the termination. |
| **Disposition** | H-001 marked `Terminated` in [Hypotheses.md](Hypotheses.md). Finding logged as `TRO-001` in the "Tested and Ruled Out" section of [Evidence_Register.md](Evidence_Register.md) — not the confirmed-evidence table. The original Section 10 "Recommended Evidence Register Entry" (Provisional Accept) is preserved above as the historical record of what was proposed before the Q4-vs-Q1 and regime-stratification diagnostics were run; it is superseded by this termination, not deleted. |
| **Open item spun out** | The unexplained Validation-only regime pattern (Addendum B, Section B.4 — dispersion-inflation theory does not cleanly fit VOLATILE or TRENDING_DOWN) is logged as an open question in [Questions.md](Questions.md), explicitly not carried forward under H-001. Any future pursuit requires new pre-registration as H-002 with its own independent Development-era test, per PI decision to proceed — not an automatic follow-on from this termination. |
