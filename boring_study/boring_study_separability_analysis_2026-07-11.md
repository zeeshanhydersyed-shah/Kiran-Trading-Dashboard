# Separability Analysis — Technical Market Structure vs. Persistent Directional Flow

**Date:** 2026-07-11
**Status:** Pure causal-DAG reasoning. No computation performed. This document exists to answer one question before any dissociation experiment is designed: *can these two mechanism classes be told apart with OHLCV data at all?*

**Bottom line up front: no.** Not as ordinary confounding that a clever design could untangle — full observational equivalence. Both hypothesized latent causes funnel through the identical manifest variables, and this document's own attempt to find an escape hatch (a higher-order signal that might survive) collapses under the same DAG scrutiny this project applies everywhere else. Recommendation at the end: merge the two classes, don't build the dissociation experiment, and flag a retroactive interpretive correction to the already-filed Structure/Flow test.

---

## 1. DAG — Persistent Directional Flow (Class 1)

```
NetOrderImbalance_t  (LATENT, unobserved — no trade-direction data exists in OHLCV)
  |  sustained, positive, low-variance over the pre-entry window
  |
  ├──> Cumulative price drift (price rises as net buying accumulates)
  |        └──> "Distance from prior high"        [DERIVED — monotonic transform of cumulative drift]
  |        └──> "Stock RS" (trailing return)       [DERIVED — same family of object, different window]
  |        └──> Donchian breakout condition fires  [MECHANICAL — close > N-day-high×1.01 is a direct
  |                                                  consequence of enough cumulative drift]
  |
  ├──> Reduced realized volatility (steady absorption of opportunistic selling dampens swings)
  |        └──> "Consolidation tightness"           [DERIVED — transform of realized range/volatility]
  |
  ├──> Post-entry continuation of the same imbalance
  |        └──> Suppressed downside excursion → Protection → higher hit_tp_10
  |        └──> NOT necessarily fast time-to-target, if imbalance is steady not accelerating → no
  |             Speed advantage (this is the one place Flow's prediction was directly tested and held)
  |
  └──> Weak, non-directional trace: volume level / steadiness
           (imperfect — magnitude of volume reveals nothing about its direction)
```

**Key observation:** every OHLCV-computable node in this DAG — distance-from-high, consolidation tightness, RS, the breakout flag itself — is a *downstream, deterministic transform* of the same single latent cause. Nothing here is an independent channel; they are all different windowings/moments of the one price path that `NetOrderImbalance` is hypothesized to generate.

---

## 2. DAG — Technical Market Structure (Class 2)

```
OverheadSupplyResidual_t  (LATENT, unobserved — no holder/ownership or order-book data exists)
  |  stock of prior buyers sitting underwater at higher prices / reflexive "traders watch this level"
  |
  ├──> Less resistance to further advance (fewer stale sellers to absorb before continuing up)
  |        └──> "Distance from prior high"        [DERIVED — the SAME summary statistic as Class 1's]
  |        └──> "Consolidation tightness"           [DERIVED — the SAME summary statistic as Class 1's]
  |
  └──> Predicted effect on outcome: faster upside progress (nothing to slow it) AND/OR
       reduced downside vulnerability (fewer stale sellers to panic-dump) — Class 2 has never
       specified cleanly which of these two it predicts, which is itself a problem (see §7 of the
       prior synthesis memo — clean structure maps more naturally onto a speed benefit than a
       protection benefit, and the established evidence is a protection-shaped result).
```

**Key observation:** Class 2's own true causal object — a *stock* concept (how many underwater holders remain) — has **no independent OHLCV measurement** either. The standard proxy for it, in this project's own production code (`breakout_signal.py`'s `high_200d` overhead-supply check) and in the technical-analysis literature generally, is the identical price-level construct used above.

---

## 3. Combined view — where the two DAGs actually differ

```
                    NetOrderImbalance_t  (Class 1, latent)
                              \
                               \--> [Distance from prior high] <--/
                               \--> [Consolidation tightness]  <--/
                               /                                  \
                    OverheadSupplyResidual_t  (Class 2, latent)  --/
```

Restricted to the variables OHLCV can actually produce, **the two DAGs are the same graph.** There is no manifest node reachable from `NetOrderImbalance` that isn't equally reachable from `OverheadSupplyResidual`, and vice versa. This is not the ordinary confounding case (two causes sharing a mediator but each also having some separate, class-specific footprint) — it's a case where the entire observable layer is shared and exhaustive. Neither class has a private observable consequence left over.

---

## 4. Cause / consequence / merely-correlated

| Observable | Role w.r.t. Class 1 (Flow) | Role w.r.t. Class 2 (Structure) | Verdict |
|---|---|---|---|
| Distance from prior high | Consequence (transform of cumulative drift) | Consequence (transform of "resistance removed") | **Consequence of both — cannot serve as an independent cause for either** |
| Consolidation tightness | Consequence (transform of realized volatility) | Consequence (transform of "clean base") | **Consequence of both** |
| Stock RS | Consequence (same family as distance-from-high, different window) | Not directly claimed by Class 2, but mechanically related to the same price path | Consequence of Flow; incidentally correlated with Structure through the shared price path |
| Volume level / steadiness | Weak, non-directional proxy — magnitude only, no direction | Not predicted by Class 2 at all (structure requires no active buying) | Weakly informative for Flow at best; **merely correlated**, not a clean cause-consequence link for either, since OHLCV volume carries no directional information |
| Breakout flag (Donchian condition) | Mechanical consequence of enough cumulative drift | Mechanical consequence of price clearing the resistance level | **Consequence of both, identically** |
| hit_tp_10 (outcome) | Consequence, mediated entirely through the above | Consequence, mediated entirely through the above | Consequence of both, indistinguishably |

No row in this table gives either class a variable it can call its own.

---

## 5. Is any proposed Structure proxy a downstream consequence of Flow?

**Yes, and not just probabilistically — mechanically.** Distance-from-prior-high is a monotonic transform of cumulative return; under the Flow hypothesis, cumulative return *is* the channel through which sustained buying manifests. Consolidation tightness is a transform of realized volatility; sustained, low-variance buying pressure mechanically compresses realized volatility relative to two-sided or choppy flow. There is no version of "clean structure" measurable from OHLCV that a sufficiently steady Flow process wouldn't also produce as a mathematical necessity, not a coincidence.

## 6. Does any proposed Flow proxy mechanically create cleaner Structure?

**Yes, for the same reason in reverse.** If net order imbalance is positive and low-variance over the window, the resulting price path is, by the basic mechanics of a drift-plus-noise process, both closer to a new high (reduced distance-from-high) and lower-range (tighter consolidation) than an equal-magnitude but two-sided/choppy imbalance would produce. "Steady flow" *mechanically generates* the exact OHLCV signature that gets labeled "clean technical structure" — this is a mathematical implication of the DAG, not an empirical association that a bigger sample could break apart.

## 7. Nesting — stated explicitly

**Neither class is a one-directional subset of the other; both collapse into the same observational-equivalence class.** The precise statement: given OHLCV data alone, the manifest signatures Technical Market Structure predicts and the manifest signatures Persistent Directional Flow predicts are **identical sets**. This is stronger than confounding (which a well-designed comparison can sometimes still resolve with enough independent variation) — it is structural non-identifiability. No amount of subsetting, interacting, or controlling within {distance-from-high, consolidation-tightness, volume level/steadiness, RS, breakout flag, hit_tp_10} can discriminate them, because the two hypotheses do not differ in what they predict about the *joint distribution* of these variables — only in the unobservable causal story behind identical predictions.

**Retroactive consequence for the already-completed Structure/Flow test:** the "shrinkage" comparison run previously (does RS's interaction shrink more from structure controls than from a volume-steadiness control) needs a correction to its interpretation. Volume steadiness is not a valid stand-in for genuine Flow — it's a magnitude-based, non-directional statistic, not a measure of net order imbalance (which OHLCV cannot observe at all). The comparison that was actually run was **Structure (which mechanically subsumes any real Flow effect operating through price) vs. an unrelated, weak, non-directional activity-level statistic** — not Structure vs. Flow. A null shrinkage result there does not selectively weaken Class 2, as the addendum previously concluded; **structure would have absorbed a genuine Flow effect too, since Flow has no channel to affect the outcome except through the very price-path features structure measures.** The correct reading of that earlier null result is: *neither the level/range price-path features nor volume-level pattern explain the RS-edge relationship* — a joint null, not a selective one. I'd recommend appending this correction to `boring_study_mechanism_prereg_2026-07-11.md`'s addendum; I haven't made that edit yet, since it changes a filed conclusion and should get your sign-off first.

---

## 8. Looking for an escape hatch — and why it doesn't survive scrutiny

Before concluding non-separability outright, two candidate higher-order signals were considered, since first/second-moment (level, range) statistics are the ones shown above to collapse. Both fail under the same DAG discipline this project has applied throughout:

- **Path-shape / multi-touch patterns** (a stock that tests a level repeatedly before breaking through, vs. one that drifts smoothly through it) initially looks like it might separate "trader psychology at a recognized level" (Structure) from "sustained accumulation" (Flow). It does not survive scrutiny: Wyckoff-style accumulation theory — itself a Flow-family story — explicitly predicts multi-touch, range-bound basing as the *signature of patient accumulation*, not its absence. Both classes can produce either a smooth-drift or a choppy-multi-touch path depending on unobservable details of how the underlying process unfolds. This candidate collapses.
- **Duration/age of the setup** (a stock quietly near its highs for years with no recent drift, vs. one on a fresh multi-month ramp) initially looks like it might separate "supply exhaustion via the passage of time" (a genuinely passive, Structure-specific story) from "recent active buying" (Flow). It also does not survive scrutiny: a sufficiently patient, slow-tempo accumulator operating over years would produce an observably identical flat-then-breakout pattern. Flow does not need to be recent to be Flow — allowing it to vary in tempo/duration lets it mimic this signature too.

**This matters beyond just closing off two candidate designs.** A hypothesis flexible enough to reproduce whatever pattern is put in front of it — smooth or choppy, recent or aged — is, in the Popperian sense, at risk of being unfalsifiable with this data source. That is an epistemic weakness of "Persistent Directional Flow" as currently scoped, not a strength, and should be named as such rather than treated as Flow quietly "winning" by process of elimination.

---

## 9. Conclusion and recommendation

Technical Market Structure and Persistent Directional Flow are **not empirically separable using OHLCV data.** Every candidate proxy examined — first-moment (level), second-moment (range/volatility), path-topology (touch count), and duration/tempo — either is mechanically shared by both DAGs or collapses into being shared once Flow is allowed to vary in tempo. This is full observational equivalence, not ordinary confounding.

**Do not design the dissociation experiment as conceived.** It would be built to detect a distinction that does not exist in what this data can, in principle, reveal — the same category of mistake this project has been careful to avoid at every prior stage (the post-treatment collider trap, the mediator-vs-mechanical-confound trap), just one level up, at the level of comparing mechanisms rather than comparing variables.

**Recommended resolution:** merge Technical Market Structure and Persistent Directional Flow into a single empirical class — call it, for now, **Persistent Price-Path Quality** — exactly analogous to how Order-Flow Imbalance and Information Diffusion were already merged for the identical reason (observational equivalence under OHLCV) earlier in this project. The honest, complete statement of where the mechanism-discrimination phase now stands: Momentum Crowding is rejected on its own defining prediction; the remaining two classes are not rejected, but are also not — and cannot be, with this data — told apart from one another. Further separation would require data this project does not have and, per its own standing practice on Information Diffusion, is not acquiring: trade-direction/tick data, or ownership/holder-level data. Absent that, the mechanism-discrimination question is complete, not stalled.
