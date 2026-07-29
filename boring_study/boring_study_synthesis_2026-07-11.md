# Synthesis — Post-Crowding Logical Analysis

**Date:** 2026-07-11
**Status:** Pure causal reasoning, no computation performed. Scoped strictly to the empirical facts established through the Momentum Crowding falsification test — does not incorporate the later Structure/Flow test results (see `boring_study_mechanism_prereg_2026-07-11.md` addendum), by deliberate request.

---

## 1. What new empirical constraints have these results imposed?

Stylized facts any future mechanism must explain **simultaneously**, not one at a time:

1. **Breakout edge (hit-rate: TP before stop) rises monotonically with Stock RS.** No saturation, no reversal at the extreme decile — the relationship keeps climbing to the top of the RS distribution.
2. **Among winning breakouts, the speed advantage over control shrinks monotonically as RS rises**, replicated in sign and rough shape across both 20d and 60d panels. Important precision: the advantage does not reverse sign — breakouts are still faster than control at every RS level — it just compresses toward zero at high RS. High-RS breakouts are the *relatively* slowest winners, not literally slow in absolute terms.
3. **Volume acceleration into the breakout shows no RS-dependent, breakout-specific pattern.** Null in both panels. This is a genuine null, not a directional finding — per the pre-reg's own stated asymmetry, it fails to confirm any volume-based story but does not positively refute one either (proxy is inherently weak, as pre-registered).
4. **Downside-excursion behavior (Protection / race-horizon MAE) does not replicate in sign across panels** (protective in 20d, borderline-adverse in 60d) — so its *direction* cannot be used to discriminate anything. But its **explained variance (ΔR²) exceeds Speed's in both panels**, consistently. This is a second-order fact, weaker than 1–3, but it is real: whatever is happening on the downside-excursion dimension carries more of the outcome's variance than the speed dimension does, even though we can't yet read which way it points.
5. *(Carried forward from earlier, still-standing phases of this study, not re-derived here but still binding):* the RS-heterogeneity is a genuine stock-level effect — not an artifact of sector aggregation (closed dead via leave-one-out correction) or market-environment aggregates (closed dead, R²≈0). Any future mechanism must operate at the individual-stock level, not through a market- or sector-wide channel.
6. *(Also carried forward)* part of the overall Donchian edge is attributable to breakout **rarity/information content** (longer lookbacks = rarer signal = bigger edge) independently of regime. This constrains how much of the *total* edge any RS-linked mechanism needs to explain — some of it is a lookback/rarity effect orthogonal to RS entirely.

**The single load-bearing derived fact, stated explicitly because it reshapes the rest of this document:** since (2) shows the *speed* channel works *against* high-RS breakouts (relatively slower), yet (1) shows they still win more often, the win-rate advantage cannot be arithmetically explained by upside velocity. It must be arithmetically located on the downside-avoidance side of the race — reduced probability or depth of touching the stop before the target, regardless of pace. This reframes the entire causal question: the mechanism is not "why do high-RS breakouts move faster," it is **"why do high-RS breakouts have a higher signal-to-noise ratio in their post-breakout path — steadier upward persistence relative to downside volatility — without moving faster in absolute terms."**

---

## 2. Which causal stories are now impossible?

Ruled out by logic, at the level of broad classes, not just the named "Momentum Crowding" hypothesis:

- **Any acceleration-based story** — mechanisms whose defining causal signature is *faster* realization of gains as RS rises: momentum-chasing/herding/FOMO buying, short-covering cascades, "momentum ignition," reflexive self-fulfilling buying spirals. These all predict a *growing* speed advantage with RS. Fact (2) rules out the entire class, not just the specific "Momentum Crowding" operationalization — Crowding was simply this class's flagship member.
- **Any story requiring a visible, RS-scaling volume surge as its mechanism** — "distribution into strength," volume-confirmed breakout climaxes, institutional-chasing-with-visible-footprint stories. Fact (3) doesn't strictly falsify these (the proxy is weak), but it removes the one piece of positive evidence such stories would need, and none currently have any support.
- **Any exhaustion/mean-reversion story at high RS** — "extended stocks are due for a pullback, so the edge should shrink or invert in the top decile." Fact (1)'s absence of saturation or reversal rules this out cleanly.
- **Sudden-information/re-rating shock stories specifically** — a discrete, fast repricing on new information would predict a *speed* advantage (the market jumps quickly to a new equilibrium). This is ruled out by (2). Note the distinction: *gradual* information diffusion (already folded into Class 1 per the existing taxonomy) is not ruled out by this — only the fast/discontinuous variant is.
- **Pure market- or sector-level explanations** remain excluded, reaffirmed rather than newly rejected — already closed via the leave-one-out and market-environment work, and structurally incompatible with RS being an individual-stock, relative measure.

Net: the surviving space of explanations is now restricted to mechanisms whose causal signature is **gradual, non-accelerating, and located on the downside/protection side of the race** — which is exactly the shared prediction of both remaining classes.

---

## 3. Remaining taxonomy, revisited

### Class 1 — Persistent Directional Flow (Order-Flow Imbalance / Information Diffusion, merged)

- **Unique predictions:** (a) protection/downside-suppression without a speed advantage; (b) steady, non-accelerating volume; (c) no tail reversal/saturation; (d) the RS-edge relationship should hold **regardless of technical structure quality** — the channel is behavioral/actor-driven, not geometric, so it shouldn't require a clean chart to operate.
- **Consistent with established findings:** the no-speed-advantage finding is not merely compatible with Class 1, it is *required* by it — this is the one class whose central prediction was directly confirmed by fact (2), not just left unfalsified. Volume-acceleration-null is consistent (though a weak, asymmetric confirmation per the pre-reg's own caveat — null evidence, not positive evidence, of steadiness). No tail reversal is consistent.
- **Tension:** none of the established facts directly contradict Class 1. Its consistency so far is mostly *by elimination* (its main rival, Crowding, was falsified) rather than by direct positive confirmation of a flow signature. The one soft tension: the Protection sign instability across panels sits slightly awkwardly with a story whose entire causal content is "downside gets absorbed by steady buying" — if that were true, cross-panel sign stability would be the more natural expectation, though the pre-reg explicitly pre-registered this specific ambiguity as inconclusive, not disconfirming.
- **Untested:** whether the edge survives specifically in low-volume subsets (the "requires no active buying" prediction); whether a genuine steadiness signature (not just non-acceleration) distinguishes high- from low-RS breakouts; whether the flow-consistent signature holds independent of technical structure.

### Class 2 — Technical Market Structure

- **Unique predictions:** (a) the edge should track distance-from-prior-highs / consolidation-density directly, and this should survive controlling for volume pattern; (b) effect present even in thin/low-volume breakouts, since the mechanism requires no active buying — just the absence of overhead resistance; (c) no speed advantage, no tail reversal (shared with Class 1).
- **Consistent with established findings:** same as Class 1 on the two shared predictions.
- **Tension — worth surfacing explicitly, not previously flagged in the pre-reg:** clean structure (no overhead supply) has an arguably more natural link to a *speed* benefit than to a *protection* benefit — nothing above the price to slow its ascent should, if anything, make it reach target faster, not just safer. That high-RS breakouts show the opposite (slower relative speed, whatever is driving the win-rate gain) sits less comfortably with Class 2's own internal logic than with Class 1's, where "someone keeps absorbing dips" maps directly onto reduced downside excursion without any implied speed change. This is a logical soft spot for Class 2 to answer, not a rejection — Class 2 hasn't yet articulated *why* structure would suppress downside specifically rather than accelerate upside.
- **Untested:** essentially everything — no structural proxy has been measured within the fact set this document is scoped to. The pre-registered discriminating test (does RS's effect shrink more from structure controls than from an equivalent volume control) is the one specifically designed to give Class 2 a fair, falsifiable hearing.

---

## 4. Identification — what would uniquely distinguish the two remaining classes (OHLCV-only, no variables proposed)

Since Class 1 and Class 2 share every prediction confirmed so far (no speed advantage, no volume acceleration, no tail reversal), discrimination cannot come from any of the dimensions already tested — by construction, more data on those three dimensions cannot separate them further. Identification requires a dimension, or a design, where the two classes' predictions **diverge**.

The general identification strategy, independent of any specific feature choice:

- **Dissociation, not marginal testing.** A geometric/structural axis and a trading-activity/flow axis must each be measured in a way that lets them vary *independently* of one another in the data (to whatever extent they naturally do). The discriminating evidence is not "does structure correlate with the edge" or "does flow correlate with the edge" in isolation — both will likely show *some* correlation, precisely because they are entangled with each other and with RS. The informative comparison is what happens in the cases where the two axes **disagree**: geometrically clean setups with unremarkable trading activity, versus geometrically poor setups with a persistent trading-activity signature. Whichever axis the edge follows in the disagreement cases is the one doing the causal work.
- **Static pre-existing condition vs. an unfolding in-trade pattern.** Structure (distance from a prior high) is a condition that exists in full at the moment of entry and needs no confirmation afterward. A genuine flow/persistence signature, by contrast, is a pattern that would need to continue being expressed *through* the holding period to plausibly be doing the protective work claimed for it. Whether the discriminating signal is fully present at entry versus something that must be observed unfolding afterward is itself identifying information — though anything measured after entry immediately re-raises the exact mediator/post-treatment risk this thread has already caught twice, and must be handled with the same discipline.
- **Distributional shape, not just central tendency.** Because the established finding is about *protection* (avoiding the downside path) rather than *speed* (reaching the upside path faster), the informative signal is more likely to live in the shape of the downside-excursion distribution (how often, how deep, in what pattern the price approaches the stop) than in any single average statistic — a geometric/structural story and a flow/persistence story plausibly produce different *shapes* of near-miss behavior even if their mean excursion looks similar.

---

## 5. Recommended next experiment

**Do not run a marginal test of either class in isolation** — both would likely show a positive correlation with the edge, and neither result would be interpretable given how each is confounded with RS and with the other. The single most informative experiment is a **dissociation design**: a test explicitly built around the subpopulation where structural cleanliness and flow-persistence point in different directions, rather than another test of either dimension averaged across the whole panel.

**Causal hypothesis under test:** the RS-conditioned protection edge is caused by the passive absence of overhead resistance (Class 2), rather than by active, sustained buying pressure (Class 1) — versus the reverse, versus neither being separable.

**Required pre-treatment observables (described, not specified as features):** a geometric axis capturing how much price history sits above the entry level, computed without reference to trading activity; a trading-activity axis capturing the persistence/pattern of activity in the pre-entry window, computed without reference to price levels. Both must be computed on strictly pre-entry windows, symmetric across breakout and control rows, exactly as every proxy in this study has been built so far.

**Expected signatures:**
- If Class 2 is the true driver: the protection benefit appears in the clean-structure/unremarkable-activity cell and is absent (or much reduced) in the poor-structure/persistent-activity cell — structure wins even when working against the flow signal.
- If Class 1 is the true driver: the mirror image — the benefit tracks the activity axis and is present even where structure is poor, absent even where structure is clean.
- If the edge appears roughly proportionally across all combinations, or the disagreement cells are too sparse to read, the classes remain entangled — an outcome the original pre-registration already flagged as an acceptable, honest stopping point, not a failed experiment.

**Likely identification challenges:**
- The two axes may simply not vary independently enough in this market — clean-structure names may disproportionately *be* the ones with persistent trading activity (the same entanglement problem already flagged in the pre-reg's §5), leaving too few disagreement observations for either sign to be read confidently.
- Splitting on two axes simultaneously divides an already-finite sample further; combined with this study's recurring illiquid/junk-price contamination problem, statistical power in exactly the cells that matter most (the disagreement cells) is the most likely failure mode.
- RS itself must be conditioned on throughout, or any apparent structure/flow effect risks simply re-deriving the already-established RS effect rather than isolating what's distinct about either axis.

**Collider / mediator risks:**
- If the trading-activity axis is measured using any window overlapping with or following the entry point, it becomes a mediator of the outcome being explained — the exact trap already caught twice in this thread (the post-treatment "immediate failure" discriminator, and the day-to-target-conditioned MAE regression). It must be measured strictly pre-entry.
- A subtler risk specific to this design: if the geometric/structural condition is itself partly a *downstream consequence* of earlier trading activity (a stock sits near its highs precisely because of sustained past buying), then structure isn't an independent cause at all — it's a mediator of an earlier flow process. In that case a clean "horse race" between the two classes is conceptually the wrong frame; the right frame would be a mediation question (does structure merely transmit flow's effect, or carry independent information beyond it) rather than a dissociation between two competing, independent causes. This possibility should be reasoned through explicitly before the design is finalized, not discovered as a surprise afterward.

**What result would conclusively reject each class:**
- **Class 2 rejected** if, holding RS fixed, the protection benefit tracks the activity axis and is flat or absent across the structural axis specifically — poor-structure-but-persistent-activity breakouts still get the full benefit, clean-structure-but-unremarkable-activity breakouts do not — replicated across both 20d and 60d panels, per this study's standing consistency bar.
- **Class 1 rejected** under the mirror-image result: benefit tracks structure regardless of activity pattern.
- **Neither rejected** if the disagreement cells are too sparse, the two axes turn out too collinear to separate with adequate power, or the pattern is genuinely mixed — which would need to be reported as a real, honest non-result, not reframed as a partial win for either side.
