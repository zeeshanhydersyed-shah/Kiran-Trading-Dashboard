# Pre-Registration — Mechanism Discrimination Phase

**Study:** Boring Study — Donchian Breakout Edge, Mechanism Investigation
**Status:** PRE-REGISTERED, PENDING EXECUTION
**Date filed:** 2026-07-11
**Prior phases this document builds on (all closed, not reopened here):** Donchian breakout definition and TP-before-stop baseline edge; lookback sweep (10-120d); regime-conditioning; predictor-only mechanism discovery (market-environment branch closed dead; sector-leadership branch closed dead via leave-one-out correction; Stock RS and Directional Volatility Ratio survived as predictor-only constructs); heterogeneity phase (Stock RS confirmed as a real, consistent moderator of the TP-before-stop edge once the correct outcome — TP-race, not stop-managed return — was used; Directional Volatility Ratio rejected as independent of RS); mechanism taxonomy and causal-structure synthesis (six candidate mechanisms reduced to four via merging and renaming, then reduced again to three empirically distinguishable groups after confronting OHLCV observational-equivalence limits).

---

## 1. Research question

Does the heterogeneity in TP-before-stop breakout edge across Stock Relative Strength arise primarily from (a) persistent directional order flow, (b) technical market structure, or (c) momentum crowding — and which of these, if any, can be distinguished from one another using OHLCV data alone, versus remaining observationally equivalent?

This is explicitly a discrimination question, not a prediction question. The edge itself is already established. This phase asks *why* it varies with RS, to the extent the available data can answer that at all.

---

## 2. Competing hypotheses, grouped by observational equivalence class

**Class 1 — Persistent Directional Flow (cause unspecified).** Contains Persistent Order-Flow Imbalance and Information Diffusion. **These two are explicitly stated not to be separately testable with OHLCV data and will not be treated as separate empirical competitors in this phase.** Both predict identical observable footprints (gradual build, reduced downside excursion, no speed advantage, no tail reversal); the only thing that would ever separate them — patient capital-allocation flow versus informed reaction to real fundamental news — requires ownership/news data this project does not have and is not acquiring. Information Diffusion is not rejected by this decision; it is set aside as untestable here, and folding it into Class 1 is an empirical convenience, not a conceptual claim that the two are the same thing.

**Class 2 — Technical Market Structure.** Stands alone. Merged from the earlier Overhead Supply and Trend Maturity candidates, which were judged to be two views of the same geometric construct.

**Class 3 — Momentum Crowding.** Stands alone. The only mechanism with multiple sharp, mutually exclusive predictions relative to the other two classes.

---

## 3. Primary observable dimensions

| Dimension | Definition |
|---|---|
| **Speed** | Time-to-target among winning breakouts — does the target get reached quickly or slowly |
| **Protection** | Downside excursion behavior — depth and frequency of drawdown toward the stop before resolution |
| **Technical structure** | Relationship between the breakout's price level and prior price-history geometry (distance from highs, consolidation, moving-average proximity) |
| **Persistent directional flow** | Volume pattern shape over the trailing window and through the breakout — used only as an imperfect proxy, since no buy/sell-directional classification exists in this dataset |

---

## 4. Predictions — differentiating only, shared predictions not repeated

**Class 1 (Persistent Directional Flow):**
- Volume pattern should be steady, not accelerating.
- The RS-edge relationship should hold even for breakouts with poor technical structure (far from prior highs, little consolidation below), since this class's channel is flow-based, not geometry-based — this is what would separate it from Class 2.
- No speed advantage specifically — the channel is downside protection, not upside acceleration — this is what would separate it from Class 3.
- No reversal or saturation of the edge at the most extreme RS values.

**Class 2 (Technical Market Structure):**
- Effect should track distance-from-prior-high and consolidation density directly, and this relationship should hold (or strengthen) independent of volume pattern — this is what would separate it from Class 1.
- Effect should be present even among thin, low-volume breakouts specifically, since the mechanism requires no active buying flow, only the absence of resistance or presence of structural support.
- No speed advantage, no tail reversal — same as Class 1 on these two dimensions, differing only on the structure and flow-independence predictions above.

**Class 3 (Momentum Crowding):**
- Faster time-to-target for higher-RS breakouts — a speed claim none of the others make.
- Accelerating (not steady) volume into and through the breakout — direct opposite of Class 1's prediction.
- Saturating or reversing edge at the most extreme RS deciles — a tail prediction none of the others make, and one already in mild tension with what's been observed so far (edge rose, not fell, at the most extreme decile in the heterogeneity phase — noted here as a prior consideration, not as a result of this phase).

---

## 5. Potential identification failures — stated explicitly in advance

- **Order-Flow / Structure entanglement.** Professional or patient buying may concentrate disproportionately in stocks that also happen to have clean technical structure. Even though the two classes are conceptually separable, the "low-volume, clean-structure" and "high-volume, clean-structure" subsamples needed to test them independently may not both exist in sufficient number, producing an underpowered or collinear test rather than a clean answer.
- **Within-trade mechanism switching.** A single breakout could plausibly start with a crowding-style fast initial move and later settle into what looks like steady accumulation-style support. A single trade's path is not guaranteed to carry one clean signature throughout its holding period, which complicates any test that assumes a fixed mechanism per trade.
- **Volume is only an imperfect, non-directional proxy.** This project has no buy-initiated vs. sell-initiated volume classification. Elevated volume is consistent with accumulation, distribution, or crowding alike — a null or ambiguous volume-pattern finding should be read as evidence about the proxy's limits, not as evidence against Class 1 or Class 3 specifically. This asymmetry is intentional: a *positive*, sharply-patterned volume finding is informative; a *null* one is not strong evidence of absence.
- **Structure proxies are mechanically correlated with RS.** Climbing to clear overhead or approach a prior high necessarily raises trailing RS too, for the same reason sector RS turned out to be almost entirely a self-inclusion artifact. A finding that "RS's effect shrinks once structure is controlled for" needs to be compared against how much it shrinks when controlling for volume-steadiness instead — shrinkage alone, without that comparison, does not uniquely implicate Class 2.
- **Known data contamination.** The recurring illiquid/junk-price outlier issue (documented repeatedly across this study) could produce erratic, spiky volume patterns in thin names for reasons unrelated to any of these mechanisms, risking misclassification as a crowding signature that is really just microstructure noise.
- **Cell sparsity.** Some combinations relevant to disentangling the classes (e.g., high RS, low volume, strong technical structure) may simply be rare, limiting how confidently any single comparison can be read.

---

## 6. Decision rules — specified before any result is seen

**Speed:**
- *Strengthens Class 3, weakens 1 and 2:* high-RS breakouts show meaningfully faster time-to-target than low-RS breakouts.
- *Weakens Class 3, is neutral-to-supportive for 1 and 2:* time-to-target shows no relationship with RS, or high-RS breakouts are if anything slower — consistent with a patience/defense story rather than a speed story.
- *Fails to discriminate:* the relationship is unstable in sign or magnitude across the two already-established breakout-lookback definitions (20d, 60d), the same instability pattern that invalidated the stop-managed-return outcome earlier in this study. If this happens, the finding should be treated the way that one was — not confirmed, not denied, flagged as unreliable.

**Protection:**
- *Strengthens Class 1 and 2 jointly (does not separate them):* downside excursion is measurably lower for high-RS breakouts, beyond what the higher hit-rate alone would mechanically produce.
- *Weakens Class 1 and 2 jointly:* no relationship between RS and downside excursion, or the apparent protection is fully explained by faster resolution (Speed) rather than genuine drawdown suppression.
- *Note:* this dimension alone cannot separate Class 1 from Class 2 — both predict the same signature here. Separating them requires the Technical Structure and Persistent Directional Flow dimensions specifically.

**Technical structure:**
- *Strengthens Class 2:* distance-from-prior-high or consolidation density predicts the edge independent of RS, and RS's own effect shrinks substantially once these are accounted for — while the equivalent shrinkage does *not* occur when controlling for volume-steadiness instead (the comparison that distinguishes this from simple entanglement, per the identification-failure note above).
- *Weakens Class 2:* RS's effect is essentially unchanged after accounting for structural proxies.
- *Fails to discriminate:* structural proxies and RS are too collinear to separate which one is carrying the shared variance.

**Persistent directional flow:**
- *Strengthens Class 1:* volume pattern is steady (not accelerating), and the RS-edge relationship holds even in low-volume subsets specifically.
- *Strengthens Class 3:* volume pattern accelerates into the breakout and this co-occurs with the Speed finding above.
- *Weakens both simultaneously:* no systematic volume-pattern difference across RS levels at all — shifts relative weight toward Class 2, which is the only class that requires no volume signature to be true.
- *Given the proxy's known weakness (§5):* treat a clear, patterned finding as meaningful; treat a null or noisy finding as inconclusive about the proxy, not as a rejection of either flow-based class.

**On the possible outcome of this phase:** it is an anticipated, acceptable result that Class 1 and Class 2 remain entangled and unresolved against each other — genuinely correlated in practice even where conceptually distinct — while only Class 3 (Momentum Crowding) is cleanly confirmed or rejected, given it is the only class with predictions sharp enough to survive the identification failures listed above. A study that closes with "Crowding resolved, Class 1 vs. Class 2 still indistinguishable" is a complete, honest result under this pre-registration, not a failure to reach one.

---

*Original document ends here — no computation had been performed as of this filing. Results of the first executed test are appended below, dated separately, per standard pre-registration practice (hypotheses/decision rules above are frozen and were not altered after seeing these results).*

---

## RESULTS ADDENDUM — Momentum Crowding test (executed 2026-07-11)

**Design finalized after three rounds of causal-DAG scrutiny** (see conversation record): Speed and Protection run as fully parallel, uncontrolled regressions on the same winners-only population (`hit_tp_10=1`), not one conditioned on the other — conditioning MAE on day-to-target was considered and rejected, since the outcome is mechanically entangled with the mediator via the measurement rule itself (a fast win definitionally has less time to show drawdown), making any controlled-direct-effect estimate uninterpretable. A conditioned version was still run as a non-decisive exploratory appendix only. Volume acceleration redefined from an arbitrary 10d/10d split to the theory-anchored second-half-vs-first-half of the same 60d RS-measurement window. Tail saturation used a pre-specified rule (`edge(decile9) ≤ mean(edge(decile7,8))`), not visual inspection.

**Verdict: Momentum Crowding is not supported, and its central claim is directly contradicted, not merely unconfirmed.**

- **Speed** (`day_to_target ~ Breakout + z(RS) + Breakout×z(RS)`, winners only): interaction consistently **positive** in both panels (20d: +0.727, p=2.9e-7; 60d: +1.719, p=2.7e-13) — meaning the breakout's speed advantage over control *shrinks*, not grows, as RS increases. Decile table confirms: speed edge peaks around decile 1-4 (~4.7-5.0 days faster) and declines to the lowest value at decile 9 (1.65d at 20d, 1.73d at 60d). Spearman rank correlation of decile vs. speed edge: ρ=-0.745 (p=0.013) at 20d, ρ=-0.855 (p=0.0016) at 60d — both negative and significant. This is the opposite direction from what Crowding's core prediction requires, consistently across both breakout definitions.
- **Volume acceleration** (`vol_accel ~ Breakout + z(RS) + Breakout×z(RS)`, full panel): null in both panels (20d p=0.337, 60d p=0.890) — no evidence acceleration is specifically tied to high-RS breakouts vs. high-RS control days.
- **Protection** (`race_mae ~ Breakout + z(RS) + Breakout×z(RS)`, winners only): sign-inconsistent across panels (20d +0.365 p=2.7e-5, positive/protective; 60d -0.228 p=0.059, negative/borderline) — per the pre-registered rule, this specific result is inconclusive, not read either way. But **ΔR² for Protection exceeds ΔR² for Speed in both panels** (20d: 0.0052 vs 0.0029; 60d: 0.0118 vs 0.0043) — Protection is not the smaller channel by explanatory power, regardless of its sign instability, which itself undercuts "primarily speed, not protection."
- **Tail saturation:** pre-specified rule fires true in both panels, but this is a continuation of a decline already underway from decile 1-2 onward, not an exhaustion effect specific to the extreme tail — reported as confirmed per the mechanical rule, with this context attached.
- **Exploratory appendix** (MAE controlling for day-to-target, non-decisive): also sign-inconsistent across panels (20d +0.479 p=1.2e-8; 60d +0.044 p=0.71) — doesn't resolve the Protection ambiguity, as expected, not used as evidence.

**What remains open:** Technical Market Structure and Persistent Directional Flow (the latter merging Order-Flow Imbalance and Information Diffusion, per §2's observational-equivalence finding) have not been tested. Given Protection's ΔR² dominance over Speed's in this test, and Crowding's clean rejection on its own defining prediction, weight shifts toward the two untested, protection-predicting mechanism classes as more promising candidates for the next test — not confirmed, just next in line.

Scripts: `boring_crowding_test.py` (project root). Full run output: `boring_crowding_test_output.txt`. Underlying matched panels: `boring_heterogeneity_panel_20d.csv` / `_60d.csv` (seed=42, reused unchanged from the heterogeneity phase).

---

## RESULTS ADDENDUM — Technical Market Structure + Persistent Directional Flow test (executed 2026-07-11)

**Design:** structure/volume proxies computed strictly pre-entry (indices `[t-252,t-1]` for distance-from-high, `[t-60,t-1]` for consolidation range and volume CV/level), identical computation for `breakout=1` and `breakout=0` (control) rows — no post-treatment or look-ahead contamination, since none of the three proxies use anything at or after the entry index. **Distance-from-high** = `(252d trailing high − close[t-1]) / 252d trailing high × 100` (an independently-defined Overhead Supply construct for this study, not imported from `breakout_signal.py`'s production version). **Consolidation** = 60d trailing `(high−low)` range as % of `close[t-1]`. **Volume CV** = 60d trailing `volume.std()/volume.mean()` (steadiness proxy, distinct from the acceleration ratio already tested in the Crowding run); **volume level** = 60d trailing mean volume (used only for the tercile split). Reused the exact matched panels (seed=42) with `hit_tp_10` already computed: `boring_heterogeneity_panel_20d_race.csv` / `_60d_race.csv` — no new random draw.

**Technical Structure — the decisive, pre-registered test (§6):** Class 2 requires RS's own `breakout×z(RS)` interaction to shrink substantially once structure proxies are added, *and* that shrinkage to exceed what an equivalent volume-steadiness control produces — otherwise it's simple entanglement, not Class-2-specific evidence.

**Result: no meaningful shrinkage in either panel, and no gap between the structure and volume-control arms.** 20d: baseline interaction +0.0353 → structure-controlled +0.0350 (0.9% shrink) vs. volume-controlled +0.0355 (−0.6%, i.e. grew slightly). 60d: baseline +0.0289 → structure-controlled +0.0311 (interaction *grew* 7.7%) vs. volume-controlled +0.0289 (flat). Neither panel shows structure absorbing any of RS's explanatory power, and the volume-control arm behaves identically to the structure arm — the decisive comparison this decision rule specifies never materializes. Per §6 ("RS's effect is essentially unchanged after accounting for structural proxies") → **weakens Class 2** as the explanation for *why* the edge varies with RS.

**Independent effect of the structure proxies (a separate question from the shrinkage test above):** Distance-from-prior-high does carry a real, independently significant association with outcome in the 20d panel — `bo_x_dist` = −0.0154 (p=8.8e-7) — and the breakout-rows-only decile check shows a strong monotonic decline in hit rate moving away from the prior high (56.5% at decile 0 down to 41–46% at deciles 5–9; Spearman ρ=−0.83, p=0.003), exactly the overhead-supply signature Class 2 predicts. **It does not replicate in the 60d panel** (`bo_x_dist` = −0.0005, p=0.89; decile Spearman ρ=−0.43, p=0.24, non-monotonic). Applying this study's own standing convention for cross-panel instability (§6's Speed rule: unstable sign/magnitude across the 20d/60d pair → flagged unreliable, not confirmed — the same treatment given the abandoned stop-managed-return outcome) — **this finding is flagged as unreplicated, not confirmed.**

Consolidation range shows the opposite of the naive "tight base is good structure" intuition, where it is significant: `bo_x_consol` is *positive* in both panels (20d +0.0133, p=0.0007; 60d +0.0698, p=0.0001) — wider, not tighter, prior ranges associate with a larger breakout edge. This replicates in direction across both panels and is a genuine, if unexpected and unexplained, structural signature — but it is not the signature Class 2 as pre-registered actually predicted, so it neither confirms nor rejects Class 2's specific claim; it is a separate, unanticipated finding worth flagging, not folding into the Class 2 verdict.

Entanglement check (breakout rows only): corr(RS, dist_from_high) = −0.15 / −0.09 (20d/60d); corr(RS, consolidation) = +0.12 / +0.37. Real but modest — not severe enough to preclude separating the two effects in regression (standard errors on both `z_rs` and the structure terms stayed tight throughout both models). Collinearity is not why the shrinkage test came back null.

**Persistent Directional Flow:**
- **(a) Volume steadiness by RS:** `bo_x_rs` on `vol_cv` is +0.0269 (p=2.3e-5) in the 20d panel — significant, but *positive*, meaning higher-RS breakouts have LESS steady (higher-CV) volume, the opposite sign from Class 1's steadiness prediction. Null in the 60d panel (+0.0111, p=0.28). Combined with the already-established null on volume acceleration (Crowding test), there is no cross-panel-consistent evidence of a steady-volume signature tied to RS — if anything, the one significant result runs against Class 1's specific prediction.
- **(b) RS-edge interaction restricted to the lowest volume-level tercile:** survives cleanly and replicates. Low-volume tercile `bo_x_rs` = +0.0325 (p=6.5e-7, 20d) and +0.0373 (p=0.0004, 60d) — both significant, both comparable to or larger than the full-panel baseline. All three volume terciles (low/mid/high) show significant positive interactions in both panels; the edge is not concentrated in high-volume names. This supports the joint Class 1/Class 2 prediction that the mechanism requires no active buying volume — it rules out a pure volume/crowding-driven alternative, though per §6 it does not by itself separate Class 1 from Class 2, since both predict this same signature.

**Verdict:** Technical Market Structure's decisive, pre-registered test (RS-interaction shrinkage vs. the volume-control comparison arm) comes back null in both panels — structure does not explain the RS heterogeneity, weakening Class 2 as specifically formulated. A real but non-replicating overhead-supply signal and a real but unanticipated wide-consolidation signal both showed up as independent correlates of outcome, neither confirmed against the cross-panel consistency bar this study applies everywhere else. Persistent Directional Flow's steadiness prediction is not supported (null-to-backwards), but its low-volume-robustness prediction is confirmed and replicates cleanly across both panels. Net: **Class 1 and Class 2 remain entangled and unresolved against each other** — exactly the outcome the pre-registration flagged in advance (§6, closing note) as an acceptable, complete result — with the additional finding that structure-as-mediator-of-RS is now specifically ruled out, even though structure-as-independent-correlate (unreplicated) and wide-consolidation (replicated but unanticipated) are not.

Scripts: `boring_structure_flow_test.py` (project root). Full run output: `boring_structure_flow_test_output.txt`. Same matched panels as the Crowding test (seed=42, unchanged).
