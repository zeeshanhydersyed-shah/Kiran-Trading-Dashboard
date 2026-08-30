# Boring Study — Status Checkpoint

**Last updated:** 2026-07-11
**Read this file first** if picking up "boring study" in a new session. It indexes everything below; don't re-derive what's already settled.

**Headline result:** the mechanism-discrimination phase is **complete**. Momentum Crowding is rejected (falsifiable, and falsified). Persistent Directional Flow and Technical Market Structure are **not** rejected, but have been proven — by DAG projection into OHLCV-observable space, not left as an open gap — to be indistinguishable with this data source. See `boring_study_identification_limits_2026-07-11.md` for that result.

**Terminal program review:** `boring_study_final_assessment_2026-07-11.md` — the full research-program assessment (established facts vs. causal interpretations vs. speculation; every falsified claim with its evidence; the identification frontier adversarially re-checked; remaining uncertainty classified by what it would take to resolve; a publication-quality conclusion; and the final recommendation). **Read this file, in full, before doing anything else with this thread.** Bottom line: the mechanism-discrimination question is closed; one single well-defined replication experiment (distance-from-prior-high) remains before the broader program itself is fully exhausted.

**EXECUTION-VIABILITY FOLLOW-UP (2026-08-30) — CONCLUDED NEGATIVE.** A separate thread tested whether the system survives *real execution* (the `Close(t)` entry the backtest assumes is not achievable — signals fire EOD and the stock gaps up next open). Full archive: [`overnight_gap_execution_2026-08/`](overnight_gap_execution_2026-08/FINDINGS.md). Result: 65-70 % of signals gap up (81 % for Strategy Confirmed); entering at the real open drops net EV from +0.5-1.8 % to ≈0/negative; a working limit at the signal price wins only ~19 %; the one positive sub-rule is indistinguishable from a matched random-day control; and the Strategy-Confirmed edge fails an era split even at the ideal entry. **As an executable mechanical rule the system has no demonstrable edge.** This does not overturn the raw breakout-vs-control finding at `Close(t)` entry (never claimed executable) and is not a verdict on discretionary use.

---

## What "boring study" is

An informal, deliberately-simple research thread inside the Kiran PSX project (`C:\Users\Lenovo\psx_pipeline\`), run separately from that project's more formal S-00X research track and not bound by its conventions (no default liquidity gates, no forced era-splits, no reused classifications — see `project_boring_study.md` in memory for the origin story). It has organically grown into a rigorous, pre-registration-driven mechanism-discovery program on its own terms. Two sub-threads exist; the second is now dominant:

1. **Weekly Dow-theory swing structure** — dormant since 2026-07-10, not abandoned. Script: `dow_weekly_explore.py`. Only tested on 6 blue chips, never taken further.
2. **Donchian breakout mechanism research** — the active thread, extensively developed. Everything below is this thread.

---

## Locked definitions (do not re-derive)

- **Breakout:** `close[t] > MAX(high[t-N..t-1]) × 1.01`, N ∈ {10,20,40,60,120}, on `prices_adjusted`. No liquidity gate.
- **Matched control:** same stock, same regime, random non-breakout day, `seed=42` — reused identically in every stage that needs a control group.
- **Primary outcome measure:** TP-before-(-6%)-stop race, target +10% primary (other thresholds +5/20/30/50% also validated). A "stop-managed continuous return" alternative was tried and abandoned — see estimand-mismatch note below.
- **Stock RS:** trailing 60-trading-day stock return minus trailing 60-day KSE-100 return.
- **Eras/windows:** 20d and 60d lookbacks are the standing "primary + cross-definition-consistency" pair used everywhere in the later phases.

---

## Full research arc, in order

| Stage | Result |
|---|---|
| Occurrence counts + control methodology | Established, seed=42 locked |
| Lookback sweep (10-120d) | Edge over control rises monotonically with lookback length |
| Regime-conditioning | Rarity explains most of the lookback effect at cell level; regime adds independent power |
| **Market-environment predictor search** (breadth, dispersion, correlation, etc.) | **CLOSED DEAD** — R²~0.0007, negative out-of-sample |
| **Sector-leadership branch** | **CLOSED DEAD** — leave-one-out correction showed ~89% of the sector-stock RS correlation was self-inclusion artifact |
| Directional Volatility Ratio | Real, clean, monotonic signature of leadership — but downstream of Stock RS, not independent (partial corr ≈0 once RS controlled) |
| **Stock RS heterogeneity of the TP-race edge** | **CONFIRMED** — real, consistent in sign/magnitude across 20d and 60d, survives decile robustness. (First attempt using stop-managed-return as outcome gave an inconsistent, sign-flipping null result — diagnosed as an *estimand mismatch*, not a failed hypothesis; rerunning with the correct TP-race outcome on the identical matched pairs resolved it cleanly.) |
| Mechanism theory-building | Causal-DAG framework (mechanism / state variable / consequence / selection variable / mediator). 6 candidates generated, reduced via merging: Overhead Supply + Trend Maturity → **Technical Market Structure**; Institutional Accumulation renamed **Persistent Order-Flow Imbalance**. Observational-equivalence analysis: **Persistent Order-Flow Imbalance and Information Diffusion cannot be distinguished with OHLCV data** — folded into one empirical class, not conceptually equated. |
| Pre-registration filed | `boring_study_mechanism_prereg_2026-07-11.md` — 3 empirically distinguishable classes, 4 observable dimensions (Speed/Protection/Structure/Flow), decision rules fixed before any data touched |
| **Momentum Crowding test** — designed across 3 rounds of causal scrutiny (post-treatment-conditioning trap caught and avoided twice), executed 2026-07-11 | **REJECTED.** Speed advantage *shrinks* with RS in both panels (opposite of the core prediction, ρ=-0.745/-0.855, both significant). Volume acceleration null in both panels. Protection's ΔR² exceeds Speed's ΔR² in both panels (though Protection's own sign is unstable across panels — inconclusive on its own, but rules out Protection being the *smaller* channel). Full results appended to the pre-reg doc. |
| **Technical Market Structure + Persistent Directional Flow test**, executed 2026-07-11 | Null shrinkage result in both panels. **Superseded interpretation below** — this was originally read as weakening Class 2 specifically; DAG analysis (next row) showed the comparison arm (volume steadiness) was never a valid Flow proxy, so the correct reading is a joint null about price-path/volume-level features, not a selective result. Overhead-supply signal (distance-from-high) real in 20d (ρ=-0.83, p=0.003), unreplicated in 60d (p=0.24). Wide-consolidation replicates as an unanticipated correlate in both panels. Low-volume-tercile robustness confirmed and replicates cleanly. Full results appended to the pre-reg doc. |
| **Separability analysis (DAG projection into OHLCV space)** + **Identification-limits capstone**, both 2026-07-11 | **Technical Market Structure and Persistent Directional Flow proven observationally equivalent under OHLCV** — not confounded-but-separable, structurally non-identifiable. Every candidate discriminating proxy (level, range, volume magnitude, path-topology/multi-touch, setup duration/tempo) either is mechanically shared by both mechanisms' DAGs or collapses once Flow is allowed to vary in tempo. Momentum Crowding was falsifiable (three predictions unique to it, all tested against it); Flow vs. Structure share every prediction OHLCV can test, so no dissociation experiment can separate them. **Recommendation: merge into one empirical class, do not build the dissociation experiment.** Full result: `boring_study_identification_limits_2026-07-11.md`. |

---

## Current state — what's proven, what's open

**Proven / locked in:**
- The TP-before-stop breakout edge is real (vs. matched random control).
- It's larger for longer lookbacks.
- It's heterogeneous across Stock RS (bigger edge at higher RS) — confirmed on the correct outcome measure, replicated across two lookback definitions.
- Market-environment variables and sector-leadership do not explain any of this.
- Momentum Crowding, as a specific causal story for *why* RS predicts a bigger edge, is rejected — its defining prediction (speed advantage grows with RS) runs backwards in the data.
- The RS-edge heterogeneity survives cleanly in the lowest volume-level tercile, replicated in both panels — rules out a pure volume/crowding-driven alternative.
- **Technical Market Structure and Persistent Directional Flow are observationally equivalent under OHLCV — a proven identification limit, not an open gap.** DAG projection shows both hypothesized latent causes (net order imbalance; residual overhead supply) manifest through the identical manifest variables (price-path level and range statistics). No OHLCV-computable proxy — including path-topology/multi-touch and setup-duration candidates, both explicitly tested by reasoning and both collapsing — carries independent, class-specific information. **Recommended disposition: merge the two classes; do not attempt a dissociation experiment with this data.**

**Superseded interpretation (flagged, not yet edited into the original file):** the Structure/Flow test's shrinkage comparison was previously read as "weakens Class 2 specifically." Per the separability analysis, volume steadiness was never a valid Flow proxy (magnitude, not direction), so structure would have absorbed a genuine Flow effect too — the correct reading is a **joint** null about price-path/volume-level features, not a selective one. Correction is documented in `boring_study_identification_limits_2026-07-11.md`; the original pre-reg addendum has not been altered pending sign-off.

**Genuinely open (real findings, not mechanism-classified):**
1. **Distance-from-prior-high (overhead supply)** — real, strong signal in the 20d panel (ρ=-0.83, p=0.003) that does not replicate in 60d (p=0.24). Flagged unreplicated, not confirmed, not rejected.
2. **Wide-consolidation** (not tight-consolidation) — an unanticipated, replicated (both panels) independent correlate of the edge, outside anything the pre-registration predicted. Not yet explained by any mechanism.

**Not being pursued:** Information Diffusion, and now Structure-vs-Flow discrimination generally, as independently testable questions with this data — both require signed order-flow, ownership/holder, or microstructure data this project doesn't have and isn't acquiring.

---

## Key files (all in `psx_pipeline` project root)

- **This file** (`BORING_STUDY_STATUS.md`) — read first.
- `boring_study_mechanism_prereg_2026-07-11.md` — the pre-registration + Crowding results addendum. Read second if continuing mechanism work.
- `boring_donchian_*.py` / `_output.txt` / `.csv` — early-phase scripts (occurrence finding, control generation, lookback sweep, regime sweep).
- `boring_leadership_*.py` / `_output.txt` / `.csv` — predictor-only mechanism search (PCA, leave-one-out correction, lag/persistence analysis).
- `boring_heterogeneity_*.py` / `_output.txt` / `.csv` — the RS-heterogeneity phase (both the failed stop-managed-return attempt and the successful TP-race rerun), including the matched panels (`boring_heterogeneity_panel_20d.csv` / `_60d.csv`) reused by every later test.
- `boring_crowding_test.py` / `_output.txt` — the Crowding falsification test.
- `boring_structure_flow_test.py` / `_output.txt` — the Technical Market Structure + Persistent Directional Flow test (interpretation superseded, see above).
- `boring_study_synthesis_2026-07-11.md` — post-Crowding logical synthesis (stylized facts, ruled-out causal classes, taxonomy revisit) — pure reasoning, no computation.
- `boring_study_separability_analysis_2026-07-11.md` — the DAG projection proving Structure/Flow observational equivalence.
- `boring_study_identification_limits_2026-07-11.md` — **capstone result of the mechanism-discrimination phase.** Read this one first if you only read one.
- `dow_weekly_explore.py` — dormant Dow-theory sub-thread.
- `overnight_gap_execution_2026-08/` — the execution-viability follow-up (2026-08-30). Its own `README.md` + `FINDINGS.md`; `scripts/s0..s6`; `data/`; `reports/00..03`. Read-only; reuses this thread's panels, does not regenerate signals.

All read-only against `psx_data.db` / the cloud Postgres. No production writes anywhere in this entire thread.

---

## Short-Side Thread Closure (2026-07-17)

**Status:** CLOSED — Strategy not deployable.

Three comprehensive phases conducted (Phase 1a: SL optimization, Phase 1b: TP optimization, Phase 1c: regime/sector analysis) plus stress-test battery. **Finding:** The apparent 9.89% edge in TRENDING_DOWN regime was entirely driven by the 2008-2009 global financial crisis. In normal market conditions (2011-2026), edge collapses to ~1% and is not statistically significant.

Focused reality check on post-2011 data with sector-downtrend filter: 197 trades, 1.02% edge, p=0.156 (not significant). **Verdict:** No tradeable edge.

See `SHORT_SIDE_DONCHIAN_FINAL_REPORT_2026-07-17.md` for complete documentation of all phases, findings, and stress tests.

---

## How to resume (Long-Side Thread)

**The mechanism-discrimination phase is closed, not paused.** Momentum Crowding is rejected on falsifiable grounds. Technical Market Structure and Persistent Directional Flow are proven observationally equivalent under OHLCV — an identification-impossibility result, not an unresolved comparison awaiting a better experiment. Do not design a dissociation experiment between them; the separability analysis shows why no OHLCV-only design can succeed (every candidate proxy considered, including two higher-order escape hatches, collapses under DAG scrutiny). If this distinction matters enough to revisit, it requires data this project doesn't have and isn't acquiring (signed order flow, ownership/holder data, or microstructure/tick data) — that's a data-acquisition decision, not an analysis one.

Two open threads worth picking up next, neither obligatory, both real findings independent of the mechanism taxonomy:
1. **Replicate the distance-from-prior-high (overhead supply) signal** on a design built to test replication specifically (e.g. a third lookback definition, or an out-of-sample date split) before treating the 20d-only result as anything more than a lead.
2. **Investigate the wide-consolidation finding** — it's real and replicates, but wasn't predicted by any of the three mechanism classes and has no explanation yet. Worth a DAG pass before building any test around it, same as every other stage in this thread.

The weekly-Dow-swing sub-thread also remains available to pick back up. Do not skip the DAG-scrutiny step on either new thread; it caught real, non-obvious errors on four separate occasions now (the "immediate failure" post-treatment trap, the day-to-target mediator-vs-mechanical-confound issue in the Crowding test, the pre-entry-only proxy-window discipline in the Structure/Flow test, and the mechanism-level observational-equivalence proof itself).

**Execution viability is CLOSED (2026-08-30, negative)** — see `overnight_gap_execution_2026-08/`. Do not re-open "can we trade the raw breakout on the RS-conditioned rule" without a genuinely new idea; the mechanical rule was tested at every reachable entry (close / open / working-limit / gap-capped) across 2005-2026 and a matched-control test on clean 2020-2026 data. The one lead the salvage tests surfaced was killed by that control. Any revisit needs either verified pre-2020 `open` data (currently unverified backfill) or a discretionary-execution framing the backtest can't represent.
