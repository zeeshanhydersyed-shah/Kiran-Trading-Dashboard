# Identification Limits of OHLCV-Based Mechanism Testing

**Date:** 2026-07-11
**Status:** Capstone result of the mechanism-discrimination phase of the Boring Study (Donchian breakout, RS heterogeneity). Supersedes the interpretive framing in the Structure/Flow addendum to `boring_study_mechanism_prereg_2026-07-11.md` on the specific point noted in §4 below; that file is left as-filed, with this document serving as the corrected, authoritative statement.

---

## Central result

**Using only daily OHLCV data, Momentum Crowding can be falsified because it makes unique observable predictions. Persistent Directional Flow and Technical Market Structure, in contrast, are observationally equivalent after projection into OHLCV space and cannot be distinguished without richer data (e.g., signed order flow, ownership, or microstructure information).**

---

## 1. Why Crowding was falsifiable

Momentum Crowding made three sharp, *exclusive* predictions — claims none of the other candidate mechanisms made, and in one case a claim directly contradicted by a rival mechanism's prediction:

- **Speed advantage grows with RS.** No other class predicted this; Flow and Structure both explicitly predict *no* speed advantage. This is what made the test decisive rather than merely suggestive: a result either confirmed a claim unique to Crowding, or it didn't.
- **Volume accelerates into the breakout**, as opposed to holding steady — again a claim the other classes explicitly do not make (they predict steady, non-accelerating volume, or are silent on volume entirely).
- **The edge saturates or reverses at extreme RS** — a tail-specific prediction unique to Crowding; the other classes predict a persistent, non-exhausting channel.

All three were tested and came back against Crowding — the speed interaction ran backwards (opposite-signed, replicated across both panels), volume acceleration was null, and no tail-specific reversal appeared beyond a decline already underway from low deciles. **Because Crowding's predictions were unique to it, the evidence could unambiguously reject it.** This is falsifiability doing its job: a hypothesis earns rejection precisely because it staked out ground no rival occupied.

---

## 2. Why Flow and Structure are not falsifiable against each other with this data

Persistent Directional Flow and Technical Market Structure make **no differentiating predictions** once restricted to what OHLCV can observe. The DAG analysis (`boring_study_separability_analysis_2026-07-11.md`) establishes this is not a matter of the current proxies being poorly chosen — it is structural:

- Both hypothesized latent causes (sustained net buying imbalance; residual overhead supply) manifest through the identical manifest variables — price-path *level* (distance from highs, RS) and price-path *range/volatility* (consolidation tightness) — because both causal stories operate by shaping the same price path, and OHLCV cannot see anything about that path except its level and range statistics.
- Two higher-order candidate signals that might have offered a way out — path-shape/multi-touch patterns, and setup duration/age — were examined and both collapse: a sufficiently flexible version of Flow (patient, slow-tempo, capable of producing either a smooth ramp or a choppy multi-touch base, over any duration from months to years) reproduces whatever signature Structure would claim as distinctively its own.
- Volume level/steadiness, the one OHLCV field that isn't purely a price-path statistic, carries no *directional* information (buy vs. sell) at all, and so cannot serve as a genuine Flow-specific proxy either — it's magnitude-only, and magnitude is silent on the question that actually separates the two hypotheses (whether price advanced because of active buying or because resistance was merely absent).

**This means the null result from the previously-run Structure/Flow test (RS's interaction did not shrink more from structure controls than from a volume-steadiness control) should be read as a joint null about price-path and volume-level features generally — not as evidence selectively weakening Technical Market Structure.** Structure, if real, and Flow, if real, would have produced the identical shrinkage pattern in that test; the test could not have told them apart even in principle. This is the correction referenced in the header.

---

## 3. The general principle

A mechanism is identifiable from a given dataset only if it makes at least one prediction that a rival mechanism, operating through the same observable channels, does not also make. Crowding cleared this bar (three exclusive predictions, all tested, all against it). Flow and Structure do not clear it with OHLCV alone — every observable consequence either predicts identically or can be reproduced by the other hypothesis under a sufficiently flexible parameterization. **The absence of a discriminating test is not a failure of imagination or effort here — it was proven, via DAG projection, to be a property of the data source itself.** No amount of additional OHLCV-only computation, subsetting, or clever interaction design changes this; the two hypotheses collapse to the same predicted joint distribution over every variable this dataset can produce.

---

## 4. What data would resolve it, and what happens absent it

Separating Flow from Structure would require an observable that depends on *why* the price path looks clean, not just on the fact that it does:

- **Signed order flow / Level 2 data** — direct measurement of buy- vs. sell-initiated volume, the one thing OHLCV structurally cannot provide, would let "steady net buying" be measured on its own terms rather than inferred from its price-path residue.
- **Ownership/holder-level data** (e.g., 13F-style filings, if a PSX equivalent existed) — would let "overhead supply" be measured directly as a stock of underwater holders, rather than inferred from distance-from-high.
- **Tick/microstructure data** — trade-by-trade sequencing could distinguish a steady accumulation pattern from a resistance-clearing pattern by looking at execution behavior around the level itself, not just the resulting daily bars.

This project has none of these and, consistent with the standing decision already made for Information Diffusion (folded into Class 1 for the identical reason — observational equivalence under OHLCV, not acquiring the data that would separate it), is not acquiring them for this purpose.

**Recommended disposition:** merge Persistent Directional Flow and Technical Market Structure into a single empirical class for the remainder of this study — their shared, un-separable observable signature is what matters going forward, not an arbitrary assignment of credit between two indistinguishable causal stories.

---

## 5. Status of the mechanism-discrimination phase

**Complete, not stalled.** The phase set out to discriminate among three candidate explanations for the RS-conditioned Donchian breakout edge. One (Momentum Crowding) is rejected on falsifiable, replicated grounds. The other two are not merely unresolved — it has been affirmatively demonstrated, by DAG projection into OHLCV-observable space, that they *cannot* be resolved with this data, which is itself a complete and citable result: an identification-impossibility proof, not an open question awaiting a better experiment. Further work on *why* the RS-edge exists, beyond "some persistent, non-accelerating quality of the price path," requires data this project has deliberately chosen not to pursue.
