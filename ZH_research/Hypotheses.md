# Hypotheses — PSX Breakout Research

> **Purpose:** Every research idea is recorded here before it is tested.  
> **Rule:** A hypothesis must exist in this file before a study (S-xxx) is opened in Research_Log.md.  
> **Naming convention:** `H-001`, `H-002`, … in order of creation. Each hypothesis links to one or more Research Questions (`RQ-xxx`) and zero or more Studies (`S-xxx`).

---

## Traceability Chain

```
RQ-001  Research Question
  └── H-001  Hypothesis
        └── S-001  Study (Research_Log.md)
              └── E-001  Evidence (Evidence_Register.md)
                    └── D-001  Decision (Decisions.md)
```

---

## Status Definitions

| Status | Meaning |
|---|---|
| `Untested` | Hypothesis exists; no study has been started |
| `In Progress` | A study (S-xxx) is currently open |
| `Confirmed` | Study complete; evidence supports the hypothesis |
| `Rejected` | Study complete; evidence does not support the hypothesis |
| `Inconclusive` | Study complete; result was ambiguous or sample too small |
| `Terminated` | Study closed because a pre-registered gating condition failed (e.g., "must hold independently across all eras") at an early era, before later eras were tested. Distinct from `Rejected`: the hypothesis did not complete its full intended test sequence — it failed its own pre-registered stopping rule. |

---

## Priority Definitions

| Priority | Meaning |
|---|---|
| `High` | Expected to have a material impact on the conviction engine |
| `Medium` | Worth testing; impact uncertain |
| `Low` | Interesting but unlikely to change decisions |

---

## Template

Copy this block for each new hypothesis.

```markdown
---

## H-XXX — [Short Title]

| Field | Value |
|---|---|
| **Related RQ** | RQ-XXX |
| **Priority** | High / Medium / Low |
| **Status** | Untested |
| **Related Study** | — |
| **Evidence** | — |

### Hypothesis

> _State the specific, testable prediction. One sentence. Avoid vague language._

### Motivation

> _Why might this be true? Reference theory, prior observation, or domain knowledge._

### Related Factors

- Factor 1 (`column_name`, source table)
- Factor 2 (`column_name`, source table)

### Expected Outcome

> _What result would confirm this hypothesis? What would reject it?_
>
> - **Confirmed if:** ...
> - **Rejected if:** ...

### Notes

> _Any caveats, data concerns, or related hypotheses to consider._

---
```

---

## Hypotheses

---

## H-001 — Pivot-Distance-Pct Band for BREAKOUT

| Field | Value |
|---|---|
| **Related RQ** | RQ-001 |
| **Priority** | Medium |
| **Status** | **Terminated** |
| **Related Study** | S-001 (base study + Diagnostic Addendum + Addendum B, S-001a Q4-vs-Q1 sub-test) |
| **Evidence** | TRO-001 (Evidence_Register.md, "Tested and Ruled Out" section) |

### Hypothesis

> Among BREAKOUT setups, `pivot_distance_pct` (the percentage distance of the close from the breakout pivot) identifies a sub-population with higher forward returns than the rest of the BREAKOUT population, within either a fixed band or a quintile-derived range.

### Motivation

> Extension magnitude above a breakout pivot may proxy setup quality — moderate extension could reflect a clean, well-formed breakout with follow-through, while very tight or very extended breakouts could reflect either premature entries or exhausted moves. Originally registered as a fixed band [4,8]% (later found sign-inverted; corrected to [-8,-4]).

### Related Factors

- Pivot Distance % (`pivot_distance_pct`, F-11, `stock_signals` / denormalized into `setup_log`)

### Expected Outcome

> - **Confirmed if:** the identified band/quintile shows a statistically significant, directionally consistent forward-return advantage **independently in all three eras** (Development, Validation, OOS) — per this study's pre-registration rule that cross-era consistency is required, not majority-of-eras.
> - **Rejected/Terminated if:** any era fails to show the effect on its own, before later eras are opened.

### Notes — Termination Reasoning (2026-07-03)

> **Terminated, not merely Rejected.** Per pre-registration ("must hold across all three eras independently"), the hypothesis fails at the Development era and does not proceed to a full evidentiary rejection test — OOS was never opened for this specific Q4-vs-Q1 contrast, and does not need to be; Development alone is sufficient to close it under the pre-registered rule.
>
> **Headline numbers:** Development shows a well-powered null — Cliff's delta = **-0.0023** (N=3,552 Q4 vs N=3,555 Q1; MWU p=0.568, one-sided). This is not a small-sample inconclusive result; at N≈3,550 per group it clears the `Strong`-confidence sample-size bar (N≥200/group) for detecting an effect, and still shows essentially zero separation. Validation, by contrast, shows Cliff's delta = **+0.1022** (N=2,320 vs 2,324; MWU p<0.0001) — a real, well-powered effect in that era alone. The two eras do not agree, and the pre-registration rule treats independent-era failure as disqualifying regardless of how strong any other single era looks.
>
> Confirmed further by regime stratification (Addendum B): the Development-era null holds in **all four** market regimes individually (TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE) — there is no regime-conditional pocket of significance hiding inside the Development-era aggregate null.
>
> The original fixed-band form of this hypothesis ([-8,-4]%) failed even earlier, in Development, before quintile exploration began (S-001 Section 3.3, p=0.783) — see Addendum C in S-001 for the explicit methodology-change record of the pivot from fixed-band to quintile-based testing within this same study.
>
> The unexplained Validation-only regime pattern (dispersion-inflation theory does not cleanly fit — see S-001 Addendum B, Section B.4) is logged as an **open question**, not carried forward under H-001. See Questions.md (Q-001). Any future pursuit of that pattern requires new pre-registration with its own independent Development-era test — it is not an automatic continuation of this hypothesis. **Correction (2026-07-03):** this note previously referenced "H-002" as the placeholder ID for that future pursuit; the PI has since assigned H-002 and H-003 to two different, unrelated candidate hypotheses (rs_score_20 and the binary flag family, below). The Q-001 open question, if pursued, will take the next available H-ID at that time — see Questions.md for the corrected cross-reference.

---

## H-002 — RS Score 20d Quintile (Q4 vs Q1) for BREAKOUT

| Field | Value |
|---|---|
| **Related RQ** | RQ-001 |
| **Priority** | Medium |
| **Status** | **Terminated** (2026-07-03) |
| **Related Study** | S-002 — Development only; Validation/OOS never opened |
| **Evidence** | TRO-007 (Evidence_Register.md, "Tested and Ruled Out") |

### Development Gate Result and Termination (2026-07-03)

Development Q4 vs Q1: N=3,552 vs 3,552; MWU p (two-sided) = 0.000294 (a significant result); MWU p (one-sided, Q4>Q1 as pre-registered) = **0.999853 — rejected**; Cliff's δ = −0.0496. The pre-registered one-sided test (Q4 > Q1, momentum-continuation direction) is decisively rejected — the effect, where real, runs opposite to the pre-registered direction (Q1 win% 52.87% vs Q4 win% 47.94%). Per the gating rule in Expected Outcome below, failure of the pre-registered one-sided test at Development terminates the hypothesis before Validation is opened. **Terminated, not carried to Validation or OOS.** PI has separately authorized a new, distinct, regime-scoped hypothesis (H-004) testing the same directional claim restricted to TRENDING_UP only — H-004 is a new pre-registration, not a re-test of H-002.

### Hypothesis

> Among BREAKOUT setups, stocks in the fourth quintile of `rs_score_20` (Q4 — strong but not extreme relative strength) produce a different `fwd_return_10d` than stocks in the first quintile (Q1 — weakest relative strength).

### Motivation

> `rs_score_20` (stock's 20-day return % minus KSE-100's 20-day return %) is a core relative-strength/momentum construct in the Weinstein/Minervini tradition. Stocks already outperforming the index before a breakout may behave differently afterward than stocks that were lagging the index going into the breakout. Q4 (not Q5, the most extreme top quintile) is used as the pre-registered comparison group to avoid re-creating H-001's "extreme tail may reverse" pattern without first checking the moderate range — this is a direct design choice, not a post-hoc selection: **no quintile exploration or best-of-5 selection is performed for this hypothesis; Q4 vs Q1 is the single pre-registered comparison**, so no multiple-comparison correction is required for this test in the way D-001 requires for exploratory quintile-selection studies.

### Related Factors

- RS Score 20d (`rs_score_20`, F-01, `setup_log` — **Group A**, no JOIN required)

### Expected Outcome

> - **Confirmed if:** Q4 vs Q1 shows a statistically significant `fwd_return_10d` advantage (direction consistent with Q4 > Q1), **independently in all three eras**, tested strictly sequentially — Development first, then Validation only if Development passes, then OOS only if both Development and Validation pass.
> - **Rejected/Terminated if:** any era, tested in that sequence, fails to show the effect independently. Per the H-001 precedent, failure at Development terminates the hypothesis before Validation or OOS is opened — there is no "average across eras" or "2 of 3" pass condition.

### Notes

> Pre-registered 2026-07-03, before any Development-era query was run (see Change_Log.md for the registration timestamp, preceding the execution timestamp). `sector` and `regime` are declared as **stratifiers/controls only** for this study — not standalone hypotheses — to be used only if a Development-era effect is found and is worth checking for sector/regime concentration, mirroring the role `regime` played in H-001 Addendum B. This round (this document turn) covers Development only; Validation and OOS are explicitly out of scope until Development's result is reviewed.

---

## H-003 — Binary EMA/Stage-Structure Flag Family for BREAKOUT

| Field | Value |
|---|---|
| **Related RQ** | RQ-001 |
| **Priority** | Medium |
| **Status** | **Terminated** (2026-07-04, all 6 flags) |
| **Related Study** | S-003 — Development complete for all 6 flags; Validation opened and closed for `overhead_clear` only; no flag reached OOS |
| **Evidence** | TRO-002 through TRO-006 (5 flags terminated at Development), TRO-010 (`overhead_clear`, terminated at Validation) — all in Evidence_Register.md "Tested and Ruled Out" |

### Paperwork correction (2026-07-04) — closing a gap, not a new query

> `overhead_clear`'s Validation result (N=3,078 flag=1 vs 8,409 flag=0; MWU p two-sided=4.40×10⁻⁸; Cliff's δ=**-0.0666**) was executed and reported as raw output in an earlier round but never written back into this hypothesis's status field, leaving H-003 incorrectly showing "In Progress" with `overhead_clear` still "proceeding." The direction reversed from Development (δ=+0.0309, flag=1 better) to Validation (δ=-0.0666, flag=0 better) — recomputing the one-sided test in the pre-registered direction (flag=1 > flag=0) from the already-reported U statistic (no new query) gives p≈0.99999998, a decisive rejection in the predicted direction, the same pattern as H-002's termination. Per the pre-registered gating rule, this **terminates `overhead_clear` at the Validation gate** — it does not reach OOS. This closes H-003 in full: all 6 flags are now terminated, none reached OOS.

### Development Gate Result (2026-07-03) — Per-Flag Disposition

| Flag | Development N(1) / N(0) | MWU p (two-sided) | Cliff's δ | vs. α=0.0083 | Disposition |
|---|---|---|---|---|---|
| `overhead_clear` | 6,082 / 11,400 | 0.000758 | 0.0309 | Clears | **Provisional Accept — proceeding to Validation** |
| `stage2_bull` | 10,632 / 6,850 | 0.507474 | −0.0059 | Fails | Terminated at Development gate |
| `close_above_ema150` | 15,985 / 1,554 | 0.039826 | 0.0315 | Fails (would clear uncorrected α=0.05) | Terminated at Development gate |
| `close_above_ema50` | 17,683 / 66 | 0.284703 | 0.0762 | Fails | Terminated at Development gate |
| `ema150_slope_pos` | 15,518 / 2,015 | 0.046805 | 0.0272 | Fails (would clear uncorrected α=0.05) | Terminated at Development gate |
| `ema50_slope_pos` | 17,555 / 189 | 0.673120 | 0.0178 | Fails | Terminated at Development gate |

Per the pre-registered gating rule (Expected Outcome, below), any flag failing Development is terminated before Validation is opened for that flag — no partial credit for clearing the uncorrected α=0.05 without clearing the Bonferroni-corrected α=0.0083. Only `overhead_clear` proceeds.

### Hypothesis

> Among BREAKOUT setups, at least one of six binary trend/structure flags — `stage2_bull`, `overhead_clear`, `close_above_ema150`, `close_above_ema50`, `ema150_slope_pos`, `ema50_slope_pos` (all **Group B**, require JOIN to `stock_signals`) — shows a `fwd_return_10d` / win-rate difference between flag=1 and flag=0 that survives a Bonferroni correction for testing all six simultaneously (adjusted α = 0.05 / 6 = **0.0083**, applied from the start per [Decision D-001](Decisions.md), not retrofitted after the fact).

### Motivation

> All six flags encode variants of "is the stock in a confirmed uptrend / low-overhead structure," drawn from Weinstein Stage Analysis and Minervini trend-template conventions. Because a BREAKOUT setup already requires `bos_flag=1` (constant in this population — see the Candidate Factor Inventory), these six flags test whether *additional* trend-confirmation context adds further separation in forward returns beyond the breakout signal itself.

### Related Factors

- Stage 2 Bull (`stage2_bull`, F-13, `stock_signals` — Group B)
- Overhead Clear (`overhead_clear`, F-19, Group B)
- Close Above EMA150 (`close_above_ema150`, F-16, Group B)
- Close Above EMA50 (`close_above_ema50`, F-14, Group B)
- EMA150 Slope Positive (`ema150_slope_pos`, F-17, Group B)
- EMA50 Slope Positive (`ema50_slope_pos`, F-15, Group B)

### Expected Outcome

> - **Confirmed (per flag) if:** that flag's flag=1 vs flag=0 comparison clears the Bonferroni-corrected α = 0.0083, **independently in all three eras**, tested strictly sequentially (Development → Validation → OOS, same gating rule as H-002).
> - **Rejected/Terminated (per flag) if:** any era, tested in sequence, fails to clear 0.0083 for that flag.
> - **Reporting rule (explicit, per PI instruction):** this is a 6-way family test. All six flags are reported together in every round, regardless of individual outcome. Selective reporting of only the flags that clear the threshold is not permitted.

### Notes

> Pre-registered 2026-07-03, before any Development-era query was run. Because all six flags are constructed from overlapping EMA/price-structure logic (e.g. `close_above_ema50` and `ema50_slope_pos` both derive from the same EMA(50) series; `stage2_bull` is itself a compound condition that includes an EMA-stack check), high co-occurrence among them is expected. A correlation matrix among the six flags will be computed in Development **before** any individual flag's result is interpreted, to surface this co-occurrence issue directly rather than treating the six as independent tests in substance (only in the Bonferroni arithmetic). `sector` and `regime` are stratifiers/controls only, not standalone hypotheses, applied only if a Development-era effect is found worth checking for concentration. This round covers Development only.

---

## H-004 — RS Score 20d Quintile (Q4 vs Q1), TRENDING_UP Regime Only, for BREAKOUT

| Field | Value |
|---|---|
| **Related RQ** | RQ-001 |
| **Priority** | Medium |
| **Status** | Untested |
| **Related Study** | S-004 (to be opened) |
| **Evidence** | — |

### Hypothesis

> Within BREAKOUT setups classified as `regime = TRENDING_UP` only, stocks in the fourth quintile of `rs_score_20` (Q4 — strongest momentum within this regime, excluding the extreme Q5 tail) produce a **higher** `fwd_return_10d` than stocks in the first quintile (Q1 — weakest momentum), tested one-sided in the momentum-continuation direction — same directional convention and same Q4-vs-Q1 quintile construction as H-002.

### Motivation

> H-002 tested this same directional claim (Q4 > Q1 on `rs_score_20`) pooled across all four regimes and was Terminated at Development — the pre-registered one-sided test was decisively rejected (p=0.999853), with the significant effect running in the opposite direction (see TRO-007). One plausible explanation is that momentum continuation is a regime-conditional phenomenon: relative strength may predict continuation specifically in trending conditions, while in RANGING/VOLATILE/TRENDING_DOWN regimes a pooled test could dilute or invert the relationship. This is a **new, distinct, PI-authorized hypothesis** scoped to TRENDING_UP only — it is explicitly **not** a re-test of H-002, and H-002 remains Terminated regardless of this hypothesis's outcome.

### Related Factors

- RS Score 20d (`rs_score_20`, F-01, `setup_log` — **Group A**, no JOIN required)
- `regime` (`setup_log.regime` — used here as a **population-defining scope filter**, not a post-hoc stratifier. This is a methodological distinction from H-001/H-002/H-003, where `regime` was declared a stratifier/control applied only after an aggregate effect was found. Here, TRENDING_UP is the entire population under test from the outset.)

### Expected Outcome

> - **Confirmed if:** Q4 vs Q1, within TRENDING_UP only, shows a statistically significant one-sided (Q4 > Q1) `fwd_return_10d` advantage, **independently in all three eras**, tested strictly sequentially — Development first, then Validation only if Development passes, then OOS only if both Development and Validation pass.
> - **Rejected/Terminated if:** any era, tested in that sequence, fails to show the one-sided effect independently. Development failure terminates the hypothesis before Validation is opened, per the H-001/H-002 precedent.
> - **Scope discipline (explicit, per PI instruction):** this hypothesis's scope is TRENDING_UP exclusively. A null or reversed result in TRENDING_UP does **not** automatically trigger testing of the other three regimes (RANGING, VOLATILE, TRENDING_DOWN) — extending to those regimes would require separate new pre-registration and reviewer/PI sign-off, per [Decision D-001](Decisions.md)'s multiple-comparison discipline (testing 4 regimes as an undisclosed family would recreate the exact problem D-001 exists to prevent).

### Notes

> Pre-registered 2026-07-03, before any Development-era query was run (see Change_Log.md for the registration timestamp preceding the execution timestamp). This round covers Development only, TRENDING_UP rows only. `sector` remains a stratifier/control only, not a standalone hypothesis, to be used only if a Development-era effect is found and is worth checking for sector concentration within TRENDING_UP.

---

## H-005 — Volume Expansion Ratio (VER) for BREAKOUT

| Field | Value |
|---|---|
| **Related RQ** | RQ-001 |
| **Priority** | Medium |
| **Status** | **Terminated at OOS gate** (2026-07-04) |
| **Related Study** | S-005 — Development, Validation, and OOS all executed; OOS is final per protocol, no recalibration |
| **Evidence** | TRO-009 (Evidence_Register.md, "Tested and Ruled Out") |

### Closure Rationale — Three-Era Decay Trajectory (headline finding)

> **Cliff's delta: 0.0690 (Development) → 0.0445 (Validation) → -0.0037 (OOS).** The effect did not fail outright in any single era on its own — Development and Validation both showed a statistically significant, correctly-directioned advantage (Development one-sided p<0.000001; Validation one-sided p=0.004360). What closes this hypothesis is the **monotonic decay across all three eras to a negligible, sign-flipped OOS result** (one-sided p=0.611131) — a smoothly eroding effect that fully evaporates by the final, no-recalibration OOS test. This is the headline finding, not the isolated OOS number: a single-era OOS null could reflect noise around a real effect, but a *monotonic three-era decay to zero* is a different, more informative pattern — consistent with a Development-era artifact (or a genuinely time-decaying effect) rather than a robust, stable factor. Per protocol, OOS is final — no recalibration, no re-test.

### Development Gate Result (2026-07-03)

> Q4 vs Q1: N=3,552 vs 3,552; MWU p (two-sided) < 0.000001; MWU p (one-sided, Q4 > Q1, pre-registered direction) < 0.000001; Cliff's delta = **0.0690**.

### Validation Gate Result (2026-07-03)

> Q4 vs Q1: N=2,320 vs 2,320; MWU p (two-sided)=0.008720; MWU p (one-sided, Q4 > Q1, pre-registered direction)=0.004360; Cliff's delta = **0.0445**.

### OOS Result (2026-07-04) — final, single OOS query per protocol; no recalibration, no parameter changes from Development/Validation

> Q4 vs Q1: N=3,881 vs 3,881; MWU p (two-sided)=0.777747; MWU p (one-sided, Q4 > Q1, pre-registered direction)=0.611131; Cliff's delta = **-0.0037**. Reviewed 2026-07-04 — see Closure Rationale above for the full three-era decay pattern this result completes. **Terminated per protocol; OOS was final, no recalibration performed.**

### Hypothesis

> Among BREAKOUT setups, a higher Volume Expansion Ratio — `VER = volume[setup_date] / mean(volume[setup_date−20 .. setup_date−1])`, with the trailing window fixed at **N=20 trading days** — predicts a **higher** `fwd_return_10d` (one-sided). N=20 is fixed at registration and will not be tuned after seeing any result.

### Motivation

> Wyckoff's "effort vs. result" principle and the classical CANSLIM/O'Neil breakout convention hold that a genuine breakout should be accompanied by volume expansion — the pivot level represents supply, and only a demand shock can clear it convincingly. A breakout on unremarkable volume is theorized to be more prone to failing back below the pivot.

### Related Factors

- Volume Expansion Ratio (new derived variable — not in `setup_log` or `stock_signals`; computed at research time from `prices_adjusted.volume`, symbol + date joined to `setup_log.setup_date`)

### Standing Limitation (registered explicitly, per PI instruction — not just a caveat appendix)

> **It is unconfirmed whether `prices_adjusted.volume` is split/bonus-adjusted for share-count changes.** Price fields in `prices_adjusted` are corrected for confirmed corporate actions (`rebuild_symbol_adjusted()`), but there is no established confirmation that volume undergoes the same adjustment. If a stock underwent a split or bonus issue inside or near a VER measurement window and volume was not adjusted accordingly, the ratio could show a spurious level shift unrelated to genuine demand. This is a standing, uninvestigated limitation carried into every result reported under H-005, at every era, until resolved.

### Expected Outcome

> - **Confirmed if:** Q4 vs Q1 of VER (quintiled the same way as `rs_score_20` — ascending sort, Q1=lowest, Q5=highest, Q4=second-highest to avoid the extreme tail) shows a statistically significant one-sided (Q4 > Q1) `fwd_return_10d` advantage, **independently in all three eras**, tested strictly sequentially (Development → Validation only if Development passes → OOS only if both pass).
> - **Rejected/Terminated if:** any era, tested in sequence, fails to show the one-sided effect independently.

### Notes

> Pre-registered 2026-07-03, before any Development-era query was run. N=20 is a fixed, non-tunable parameter for this registration — a different window would constitute a new hypothesis requiring its own pre-registration, not a parameter sweep under H-005. This round covers Development only. `sector` and `regime` are stratifiers/controls only, not standalone hypotheses.

---

## H-006 — Sector Breadth Participation at Breakout for BREAKOUT

| Field | Value |
|---|---|
| **Related RQ** | RQ-001 |
| **Priority** | Medium |
| **Status** | **Parked** — Development result confounded/concentrated in 2 of 5 sectors (Commercial Banks, Textile Composite); not advanced to Validation; may be revisited as a narrower, freshly pre-registered hypothesis specific to those sectors if PI chooses. |
| **Related Study** | S-006 — Development complete; sector-controlled re-test complete; parked by PI decision, no further action pending |
| **Evidence** | — |

### Sector-Controlled Re-Test Result (2026-07-03) — basis for parking

> Per-sector Q4-vs-Q1 (within-sector quintiling): significant in 2 of 5 top sectors — COMMERCIAL BANKS (Cliff's δ=0.2162, one-sided p<0.000001) and TEXTILE COMPOSITE (Cliff's δ=0.2589, one-sided p<0.000001) — and not significant in the other 3 (CEMENT p=0.136965, CHEMICAL p=0.330341, TECHNOLOGY & COMMUNICATION p=0.381647). The sector-adjusted (sector-demeaned) pooled comparison remained directionally positive and significant (Cliff's δ=0.0457, one-sided p=0.000437) but at a materially smaller effect size than the raw pooled result (δ=0.0570). PI has elected to park this hypothesis rather than advance the pooled, confound-affected result to Validation.

### Development Gate Result (2026-07-03) — Confounded, Not Yet a Pass/Fail Verdict

> Q4 vs Q1 (pooled): N=3,536 vs 3,536; MWU p (two-sided)=0.000033, one-sided (Q4>Q1)=0.000016; Cliff's delta=0.0570 — nominally clears the pre-registered directional test. However, the **pre-registered, required** sector-concentration check (Required Development Report Contents, below) found top-5-sector share rising monotonically from Q1 (43.95%) to Q5 (61.28%), with materially different sector composition per quintile (e.g., Q1 top sector is POWER GENERATION & DISTRIBUTION; Q5 top sector is CEMENT, with FERTILIZER and OIL & GAS EXPLORATION appearing only in Q5's top-5). Per this hypothesis's own pre-registered disqualification rule, this is treated as an open confound requiring a sector-controlled re-test before any Accept/Terminate verdict is issued — the pooled result above is not read as either a pass or a fail on its own.

### Hypothesis

> Among BREAKOUT setups, a higher sector `breadth_score` (from `sector_signals` — % of the stock's sector trading above its 20d EMA) at the setup date predicts a **higher** `fwd_return_10d` for the individual stock (one-sided).

### Motivation

> Breadth-thrust and sector-rotation logic holds that a breakout occurring while its sector is broadly participating (many peers also strong) is more likely to reflect genuine institutional rotation into the group, with follow-through support from capital flowing into the sector as a whole — versus an idiosyncratic breakout in a stock whose sector is weak, more consistent with a one-off event lacking real sponsorship.

### Related Factors

- Sector Breadth Score (`breadth_score`, F-23, `sector_signals` — requires `LEFT JOIN sector_signals ON date=setup_date AND sector=setup_log.sector`)

### Required Development Report Contents (pre-registered, not optional, not added after the fact)

> 1. **L-03 exclusion accounting:** rows with no matching `sector_signals` row (NULL `breadth_score` after `LEFT JOIN`) must be explicitly excluded and the excluded N reported — never silently dropped via an INNER JOIN.
> 2. **Sector-concentration check:** top-5-sector share of the tested population must be reported for the overall Development population **and for each quintile**, matching the discipline already applied to regime-checks in H-001 Addendum B. If the Q4-vs-Q1 result is concentrated in a small number of sectors, this must be flagged in the same report, not as a follow-up.

### Expected Outcome

> - **Confirmed if:** Q4 vs Q1 of `breadth_score` (quintiled the same way as `rs_score_20` — ascending, Q1=lowest, Q5=highest, Q4=second-highest) shows a statistically significant one-sided (Q4 > Q1) `fwd_return_10d` advantage, **independently in all three eras**, tested strictly sequentially.
> - **Rejected/Terminated if:** any era, tested in sequence, fails to show the one-sided effect independently, **or** the effect is shown to be a sector-concentration artifact rather than a broad-based relationship (per the required check above) — the latter is a data-quality disqualification, not merely a caveat.

### Notes

> Pre-registered 2026-07-03, before any Development-era query was run. This round covers Development only. `regime` remains a stratifier/control only, not a standalone hypothesis for this study. Inherits B-02 (Known_Limitations.md) — `sector`/breadth-adjacent constructs are computed by the same pipeline/timeframe as signal generation, not fully independent of it.

---

## H-007 — Coil-Tightening Slope (Volatility Contraction Trajectory) for BREAKOUT

| Field | Value |
|---|---|
| **Related RQ** | RQ-001 |
| **Priority** | Medium |
| **Status** | **Terminated** (2026-07-03) |
| **Related Study** | S-007 — Development only; Validation/OOS never opened |
| **Evidence** | TRO-008 (Evidence_Register.md, "Tested and Ruled Out") |

### Development Gate Result (2026-07-03)

> Q1 (steepest-negative slope) vs Q5 (least-negative/positive slope): N=3,433 vs 3,433; MWU p (two-sided)=0.334954, one-sided (Q1>Q5, pre-registered direction)=0.832526; Cliff's delta = **-0.0134** — a near-zero, wrong-direction null relative to the pre-registered claim. Terminated at Development gate per the pre-registered sequential gating rule; not carried to Validation or OOS.

### Hypothesis

> Among BREAKOUT setups, the linear-regression slope of daily `base_tightness` over the **trailing 20 trading days ending at and including setup_date** (N=20, fixed) — computed per symbol from `stock_signals` — predicts `fwd_return_10d`: a **more negative** slope (steeper tightening trajectory) predicts a **higher** `fwd_return_10d` than a less-negative or positive (loosening) slope (one-sided).

### Motivation

> Classical base-and-breakout theory (Darvas boxes, Minervini's VCP — "volatility contraction pattern," Bollinger Band squeeze logic) holds that the *trajectory* of a base's volatility contraction carries information independent of its instantaneous tightness level — a base that is actively, progressively tightening reflects diminishing supply and increasingly confident holders, theorized to produce cleaner breakouts than a base that is merely tight-and-static or has recently begun loosening again.

### Required Lineage Disclosure (registered explicitly, per PI instruction — must appear here, not only in working notes)

> **This hypothesis is mathematically derived from `base_tightness` (F-07), the same underlying BBW%-style series as the "BBW% / coiling-under-resistance" factor referenced in project history as dead on both BREAKOUT and PRE_BREAKOUT.** The PI's instruction to this registration cited "TRO-001" as that finding's ID — **this has been verified against Evidence_Register.md and is incorrect: `TRO-001` is `pivot_distance_pct` (H-001), a different factor.** The BBW%/`base_tightness` dead finding does **not** currently have a formal `TRO-xxx` entry — it exists only as a project-history reference, flagged in Evidence_Register.md's "Tested and Ruled Out" section header as an outstanding backfill item ("not yet formally logged in this table with study citations... not fabricated here without the source study record in hand"). This registration does not fabricate that citation now either — no TRO ID is assigned to BBW% here, since the original study's N/p-values are not in hand. What is disclosed, per PI's explicit instruction, is the **shared mathematical lineage**: `base_tightness` (terminated, undocumented ID) is a **level/magnitude** measure — "how tight is the coil right now" — while this hypothesis is a **slope/trajectory** measure — "is the coil actively tightening, and how fast." These are different dimensions of the same underlying series, per the PI's explicit judgment that the level-vs-trajectory distinction is theoretically meaningful and worth testing independently. H-007's Development result stands on its own regardless of the BBW% backfill's eventual resolution.

### Related Factors

- Coil-Tightening Slope (new derived variable — not in `setup_log` or `stock_signals`; computed at research time as `linregress(base_tightness[t-19..t])` per symbol from `stock_signals`)

### Quintile Convention (differs from H-005/H-006 — explicit, not "Q4 vs Q1")

> Ascending sort by slope value: Q1 = most negative (steepest tightening), Q5 = least-negative/most positive (loosening or flattening). Per the PI's specification, this hypothesis compares the **two extreme quintiles directly — Q1 ("steepest-negative") vs Q5 ("least-negative/positive")** — not the moderate Q4-vs-Q1 comparison used for H-005/H-006. This is a deliberate, explicit deviation from the other two hypotheses' quintile convention, not an inconsistency.

### Expected Outcome

> - **Confirmed if:** Q1 (steepest-negative slope) vs Q5 (least-negative/positive slope) shows a statistically significant one-sided (Q1 > Q5 on `fwd_return_10d`) advantage, **independently in all three eras**, tested strictly sequentially.
> - **Rejected/Terminated if:** any era, tested in sequence, fails to show the one-sided effect independently.

### Notes

> Pre-registered 2026-07-03, before any Development-era query was run. N=20 is fixed and non-tunable for this registration. Rows without a full 20-point non-NULL `base_tightness` window (e.g., near a symbol's listing date or near the start of the `stock_signals` history, per L-01) are excluded and the excluded N must be reported, not silently dropped. This round covers Development only. `sector` and `regime` are stratifiers/controls only, not standalone hypotheses.

---

## H-008 — Gap-at-Breakout for BREAKOUT

| Field | Value |
|---|---|
| **Related RQ** | RQ-001 |
| **Priority** | Medium |
| **Status** | **BLOCKED — registered but not runnable.** No query, exploratory or otherwise, is permitted against `prices.open` or `prices_adjusted.open` under this hypothesis until both unblock conditions below are satisfied and confirmed by the PI. |
| **Related Study** | S-008 (not yet opened — blocked pre-Development) |
| **Evidence** | — |

### Hypothesis

> Among BREAKOUT setups, a binary flag — 1 if `open[setup_date] > pivot_high` (the breakout occurred via an overnight gap through the pivot), 0 if `open[setup_date] <= pivot_high < close[setup_date]` (the breakout occurred via an intraday crossing) — predicts a **higher** `fwd_return_10d` for gap-at-breakout (flag=1) setups than non-gap (flag=0) setups (one-sided). Must hold across all three eras independently, Development first, per standard protocol.

### Motivation

> Gap theory and overnight order-imbalance logic hold that a gap reflects information/demand that accumulated while the market was closed, clearing resistance before any intraday trading could test it — theorized as a stronger conviction signal than a level being ground through during the session. (See the original Candidate 4 proposal write-up for full rationale and its explicit disclosure that this is not a re-derivation of any terminated construct.)

### Related Factors

- Gap-at-Breakout flag (new derived variable — not in `setup_log` or `stock_signals`; requires `open` from `prices_adjusted`, joined by symbol + `setup_date`, compared against `pivot_high`)

### Unblock Conditions (explicit — both required before any Development query)

> **(a) Phase 5 corporate-action adjustment of `open`, completed by the PI outside this workflow.** As of this registration, `prices.open` has been backfilled (non-NULL count 462,377 → 1,572,584, gap-fill only, per CLAUDE.md 2026-07-04 entry) but **`prices_adjusted.open` is still NULL** — `apply_price_adjustments.py` already contains the logic to adjust `open` alongside high/low/close, but has not yet been re-run against the new raw values. This hypothesis cannot run against unadjusted `open` — a stock that split or issued a bonus inside a lookback window would show a spurious pre/post-event discontinuity unrelated to genuine gap behavior, the same L-09/B-03 risk class already documented for `close`.
>
> **(b) A reconstruction/look-ahead audit of `prices_adjusted.open` comparable in rigor to EXP-0002's standard**, completed before any Development query is permitted. Per CLAUDE.md's 2026-07-03/07-04 entries, this audit needs to cover more than a generic look-ahead check: (i) **2020–2023 values** were spot-verified for accuracy against BI PostgreSQL (40/40 sample match) prior to the `prices.open` import, but the *pipeline provenance* is still undocumented — `load_bi_history.py`/`upsert_prices()` do not currently write `open`, so this data is not reproducible from current code, a standing concern under this project's reproducibility standard (Research Law #4) independent of its spot-checked accuracy; (ii) **2005–2019 values** are explicitly logged as "best available, unverified" — no independent source exists to check them (BI PostgreSQL only covers 2020 onward) — meaning the entire Development era (2015–2019) this hypothesis must test first would run against unverified Open data unless this is resolved or explicitly caveated as a Development-era limitation before the query runs; (iii) the standard EXP-0002-style reconstruction check (open ≥ low, open ≤ high, no forward-looking contamination) still needs to be run and passed for the new column.

### Expected Outcome

> - **Confirmed if:** flag=1 vs flag=0 shows a statistically significant one-sided `fwd_return_10d` advantage, **independently in all three eras**, tested strictly sequentially (Development → Validation only if Development passes → OOS only if both pass) — once unblocked.
> - **Rejected/Terminated if:** any era, tested in sequence, fails to show the one-sided effect independently.

### Notes

> Pre-registered 2026-07-04, in a BLOCKED state — this registration exists so that, once unblocked, no retroactive "test first, register after" gap of the kind flagged for H-001 recurs for this hypothesis. `sector` and `regime` remain stratifiers/controls only, not standalone hypotheses, for this study. See [Decision D-003](Decisions.md) for the prior shelving decision this hypothesis supersedes now that backfill has partially progressed — D-003's shelving reasoning (0% Development-era coverage) is resolved by the `prices.open` backfill, but the two unblock conditions above are new, separate gates that did not exist at the time D-003 was written.
