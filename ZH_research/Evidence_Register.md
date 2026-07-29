# Evidence Register — PSX Breakout Research

> **Purpose:** Permanent record of findings that have been validated by completed empirical studies.  
> **Rule:** This document contains confirmed evidence only. Assumptions, opinions, and untested ideas are never recorded here.  
> **Naming convention:** `E-001`, `E-002`, … in order of confirmation.

---

## Traceability Chain

```
RQ-001  Research Question
  └── H-001  Hypothesis
        └── S-001  Study (Research_Log.md)
              └── E-001  Evidence (this file)
                    └── D-001  Decision (Decisions.md)
```

---

## Confidence Definitions

| Confidence | Criteria |
|---|---|
| `Strong` | N ≥ 200 per group · Result consistent across regimes · Replicated in out-of-sample period |
| `Moderate` | N ≥ 50 per group · Result directionally consistent · Not yet out-of-sample validated |
| `Weak` | N < 50 per group · Or result only present in one regime or one time period |

---

## Status Definitions

| Status | Meaning |
|---|---|
| `Active` | Finding stands; no contradicting evidence |
| `Under Review` | A new study is re-examining this finding |
| `Superseded` | A later study produced a more precise or contradicting finding; see notes |

---

## Evidence Register

| Evidence ID | Finding | Supporting Study | Confidence | Date Confirmed | Status |
|---|---|---|---|---|---|
| | | | | | |

---

## Rules for Adding Evidence

1. **Every entry must reference a completed study.** An `S-xxx` entry in Research_Log.md must be marked Complete before evidence is recorded here.

2. **State the finding precisely.** Not "RS matters" — but "BREAKOUT setups with rs_rank ≤ 20 produced a 20d win rate of X% vs Y% for rs_rank 21–100 (N=A vs N=B, S-001)."

3. **Include the sample size.** N must be stated. Findings with N < 30 per group are recorded at `Weak` confidence regardless of the result.

4. **Findings must be reproducible.** The supporting study must contain enough methodological detail that the analysis could be re-run independently and produce the same result.

5. **Opinions are never evidence.** Domain knowledge, intuition, and practitioner wisdom may appear in Hypotheses.md as motivation — they do not appear here.

6. **Evidence may be revised.** If a later study contradicts an earlier finding, the original entry is marked `Superseded` with a reference to the new evidence ID. Earlier entries are never deleted.

7. **Confidence is not static.** A `Moderate` finding may be upgraded to `Strong` once out-of-sample validation is complete. Update the entry and note the supporting study.

---

## Superseded Evidence

_Entries moved here when a newer finding replaces them. Original text preserved for the record._

| Evidence ID | Original Finding | Superseded By | Date |
|---|---|---|---|
| | | | |

---

## Tested and Ruled Out

> **Purpose:** Factors/hypotheses that completed a study and were found to have **no** predictive relationship, or failed a pre-registered gating condition. These are not "confirmed evidence" (this register's main table is reserved for validated positive findings) but are recorded here so the same ground is not retested without new-evidence justification. Uses a separate `TRO-xxx` ID sequence, distinct from `E-xxx` (confirmed findings).
>
> **Note on prior entries:** Project history references two earlier ruled-out factors — BBW% / coiling-under-resistance (dead on both BREAKOUT and PRE_BREAKOUT) and RS_LEADER_MARKET / RS_LEADER_SECTOR (dead via two independent tests). Those findings are not yet formally logged in this table with study citations; this is flagged as an outstanding backfill item, not fabricated here without the source study record in hand.

| ID | Factor / Hypothesis | Supporting Study | Era(s) Tested | Result | Date | Status |
|---|---|---|---|---|---|---|
| TRO-001 | `pivot_distance_pct` — both the original fixed band [-8,-4]% and the Q4/Q1 quintile-derived follow-through form (H-001) | S-001 (base study + Diagnostic Addendum + Addendum B) | Development (fixed band, and Q4-vs-Q1 quintile, non-stratified and stratified by all 4 regimes) | No Development-era relationship to BREAKOUT `fwd_return_10d`. Fixed band [-8,-4] failed first (p=0.783). Q4-vs-Q1 quintile follow-up: well-powered null, Cliff's delta = -0.0023 (N=3,552 vs 3,555, MWU p=0.568), null holds in all 4 market regimes individually. Validation showed a real effect (Cliff's delta +0.1022) but pre-registration required independent-era consistency, which Development did not meet — **hypothesis Terminated, not carried to OOS.** | 2026-07-03 | Ruled Out (H-001 Terminated) |
| TRO-002 | `stage2_bull` (H-003, one of a six-flag family) | S-003 | Development only | N=10,632 (flag=1) vs N=6,850 (flag=0). MWU p (two-sided) = 0.507474 — fails Bonferroni-corrected α=0.0083 by a wide margin. Cliff's delta = -0.0059 (near-zero). No Development-era relationship to BREAKOUT `fwd_return_10d`. **Terminated at Development gate, not carried to Validation.** | 2026-07-03 | Ruled Out (H-003 per-flag Terminated) |
| TRO-003 | `close_above_ema150` (H-003, one of a six-flag family) | S-003 | Development only | N=15,985 (flag=1) vs N=1,554 (flag=0). MWU p (two-sided) = 0.039826 — clears the uncorrected α=0.05 but fails the pre-registered Bonferroni-corrected α=0.0083 for this 6-flag family (per D-001). Cliff's delta = 0.0315. **Terminated at Development gate under the pre-registered correction, not carried to Validation.** | 2026-07-03 | Ruled Out (H-003 per-flag Terminated) |
| TRO-004 | `close_above_ema50` (H-003, one of a six-flag family) | S-003 | Development only | N=17,683 (flag=1) vs N=66 (flag=0). MWU p (two-sided) = 0.284703 — fails Bonferroni-corrected α=0.0083. Cliff's delta = 0.0762. Flag=0 minority class is extremely thin (66 of 17,749, 0.37%) — see standing candidate-selection note in Decisions.md (D-002). **Terminated at Development gate, not carried to Validation.** | 2026-07-03 | Ruled Out (H-003 per-flag Terminated) |
| TRO-005 | `ema150_slope_pos` (H-003, one of a six-flag family) | S-003 | Development only | N=15,518 (flag=1) vs N=2,015 (flag=0). MWU p (two-sided) = 0.046805 — clears the uncorrected α=0.05 but fails the pre-registered Bonferroni-corrected α=0.0083 for this 6-flag family (per D-001). Cliff's delta = 0.0272. **Terminated at Development gate under the pre-registered correction, not carried to Validation.** | 2026-07-03 | Ruled Out (H-003 per-flag Terminated) |
| TRO-006 | `ema50_slope_pos` (H-003, one of a six-flag family) | S-003 | Development only | N=17,555 (flag=1) vs N=189 (flag=0). MWU p (two-sided) = 0.673120 — fails Bonferroni-corrected α=0.0083. Cliff's delta = 0.0178. Flag=0 minority class is extremely thin (189 of 17,744, 1.07%) — see standing candidate-selection note in Decisions.md (D-002). **Terminated at Development gate, not carried to Validation.** | 2026-07-03 | Ruled Out (H-003 per-flag Terminated) |
| TRO-007 | `rs_score_20` Q4-vs-Q1 quintile, pooled across all regimes (H-002) | S-002 | Development only | N=3,552 vs 3,552. MWU p (two-sided) = 0.000294 (significant), but MWU p (one-sided, pre-registered direction Q4>Q1) = 0.999853 — **decisively rejected in the pre-registered direction**. Cliff's delta = -0.0496 (Q1 outperforms Q4: win% 52.87% vs 47.94%). Pre-registered one-sided test failed at Development gate. **Terminated, not carried to Validation or OOS.** A new, distinct, regime-scoped hypothesis (H-004, TRENDING_UP only) has been separately pre-registered to test the same directional claim in a narrower population — H-004 is not a re-test of this finding. | 2026-07-03 | Ruled Out (H-002 Terminated) |
| TRO-008 | Coil-Tightening Slope — linear-regression slope of `base_tightness` over trailing 20 trading days (H-007) | S-007 | Development only | N=3,433 (Q1, steepest-negative slope) vs N=3,433 (Q5, least-negative/positive slope). MWU p (two-sided) = 0.334954, one-sided (pre-registered direction, Q1>Q5) = 0.832526 — near-zero, wrong-direction null. Cliff's delta = **-0.0134**. **Explicit lineage disclosure:** this factor is mathematically derived from `base_tightness` (F-07), the same underlying series referenced in project history as the dead "BBW%/coiling-under-resistance" factor (that finding still has no formal TRO ID of its own — see this register's header note). H-007 tested the *slope/trajectory* of that series (distinct in principle from the *level* the BBW% finding tested) and found no relationship either — both the level form and the trajectory form of this underlying series are now null on BREAKOUT forward returns. **Terminated at Development gate, not carried to Validation or OOS.** | 2026-07-03 | Ruled Out (H-007 Terminated) |
| TRO-009 | Volume Expansion Ratio — `VER = volume[setup_date] / mean(volume[setup_date-20..setup_date-1])`, N=20 fixed (H-005) | S-005 | Development, Validation, and OOS — full three-era sequence completed | **Closure basis is the three-era decay trajectory, not an isolated null — documented here explicitly as the more informative pattern.** Cliff's delta: **0.0690 (Development, N=3,552 vs 3,552, one-sided p<0.000001) → 0.0445 (Validation, N=2,320 vs 2,320, one-sided p=0.004360) → -0.0037 (OOS, N=3,881 vs 3,881, one-sided p=0.611131)**. The effect was statistically significant and correctly directioned in both Development and Validation, then decayed monotonically to a negligible, sign-flipped null in the final OOS test. This is recorded as a **monotonic three-era decay pattern** distinct from a single-era null (as with TRO-001, TRO-007, TRO-008) — future studies referencing this factor should note that VER passed two full gating stages before failing only at the final, no-recalibration OOS check, which is a materially different (and more cautionary) failure mode than failing at Development. **Terminated at OOS gate per protocol — OOS is final, no recalibration performed.** | 2026-07-04 | Ruled Out (H-005 Terminated) |
| TRO-010 | `overhead_clear` (H-003, one of a six-flag family; the one flag that passed the Development gate) | S-003 | Development and Validation | Development: N=6,082 vs 11,400, one-sided p=0.000758, Cliff's δ=+0.0309 — clears Bonferroni-corrected α=0.0083. Validation: N=3,078 vs 8,409, MWU p (two-sided)=4.40×10⁻⁸, Cliff's δ=**-0.0666** — direction reversed from Development; one-sided p in the pre-registered direction (flag=1 > flag=0), recomputed from the already-reported U statistic, ≈0.99999998 — decisive rejection in the predicted direction. **Terminated at Validation gate, not carried to OOS.** This closure was delayed in the paper record — the Validation result was collected and reported before this entry was filed but not immediately written into Hypotheses.md; corrected 2026-07-04, no new query was run to produce this entry. | 2026-07-04 | Ruled Out (H-003 Terminated, all 6 flags) |

---

## BREAKOUT — Research Status Summary (2026-07-04)

> **Correction to the closure framing as initially proposed:** the closure request described "six terminated hypotheses" (`pivot_distance_pct`, the six-flag EMA/stage family, `rs_score_20` pooled, `rs_score_20`/TRENDING_UP, coil-tightening slope, VER). Verification against the actual paper trail before writing this summary found two problems with that framing, both corrected in this same pass rather than carried forward silently:
>
> 1. **The six-flag EMA/stage family (H-003) was not actually fully closed** — `overhead_clear`'s Validation result (collected and reported as raw output in an earlier round) had never been written back into Hypotheses.md, leaving H-003 showing "In Progress." This has now been closed (see TRO-010, above) — `overhead_clear` reversed direction in Validation (Cliff's δ +0.0309 → -0.0666) and is terminated there, so H-003 is now genuinely fully closed, all 6 flags terminated.
> 2. **`rs_score_20`/TRENDING_UP (H-004) was never executed at all.** It was registered but no Development query was ever run against it — there is no TRO entry, no result, nothing to close. It is **not** part of this closure and is **not** counted among the terminated hypotheses below. It remains open/untested, separate from the five hypotheses that were actually run to completion.
>
> With that correction, the accurate count for BREAKOUT is: **five hypotheses independently reasoned, tested, and terminated**, spanning five distinct variable categories (price-structure, relative-strength/momentum, trend-structure, volatility-trajectory, volume-confirmation), none surviving the full three-era protocol:
>
> | Hypothesis | Variable Category | TRO Citation(s) | Terminated At |
> |---|---|---|---|
> | H-001 — `pivot_distance_pct` | Price-structure (pivot extension) | TRO-001 | Development (fixed band + Q4/Q1 quintile + regime-stratified) |
> | H-002 — `rs_score_20` (pooled, all regimes) | Relative strength / momentum | TRO-007 | Development (wrong direction) |
> | H-003 — six-flag EMA/Stage family | Trend-structure | TRO-002, TRO-003, TRO-004, TRO-005, TRO-006 (Development), TRO-010 (Validation) | 5 flags at Development; `overhead_clear` at Validation |
> | H-005 — Volume Expansion Ratio (VER) | Volume-confirmation | TRO-009 | OOS (monotonic three-era decay to null — see TRO-009 for why this is a materially different, more informative closure pattern than a single-era null) |
> | H-007 — Coil-Tightening Slope | Volatility-trajectory | TRO-008 | Development (wrong direction) |
>
> **Separately, not part of this closure:**
> - **H-004** (`rs_score_20`, TRENDING_UP regime only) — registered, **never executed**. Open/untested, not terminated.
> - **H-006** (Sector Breadth Participation) — Development result confounded by sector concentration (concentrated in 2 of 5 top sectors); **Parked** by PI decision, not terminated — may be revisited as a narrower, sector-specific hypothesis.
> - **H-008** (Gap-at-Breakout) — registered but **Blocked** pending Phase 5 corporate-action adjustment of `prices_adjusted.open` and a reconstruction/look-ahead audit; not affected by this pivot to PRE_BREAKOUT, remains BREAKOUT-specific and independently gated.
>
> **This is a standing finding, not a closed door.** BREAKOUT is deprioritized, not abandoned. Five independently-reasoned, single-variable hypotheses across five distinct theoretical categories were tested to completion and none survived the full three-era protocol — a reasonably thorough single-variable search of the readily available factor space came up empty. This does not rule out: sector-specific mechanisms (per H-006's per-sector result), factor interactions/combinations (untested — all five closed hypotheses were single-variable), or H-008 once its data-quality gates clear. Research focus is shifting to PRE_BREAKOUT; BREAKOUT may be revisited if new evidence, a new theoretical angle, or resolution of H-006/H-008's open threads warrants it.

---

*This register begins empty for confirmed findings (main table above). The first confirmed entry will be added upon a study producing evidence that survives full cross-era testing.*
