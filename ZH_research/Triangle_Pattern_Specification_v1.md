# Triangle Pattern Study — Final Specification & Closure Report

**Status:** **CLOSED.** This is the terminal, standalone reference for the triangle-pattern study. It supersedes every prior version of this document. Read this file alone — no other chat history or session context is needed to understand what was built, what was found, or what to reuse.
**Filed:** 2026-07-16
**Researcher:** Claude Code (implementation), under direction of the Independent Quantitative Reviewer
**Reviewer:** Independent Quantitative Reviewer (Zeeshan) — every design decision and every bug documented below was found via direct review of real-data output, not proposed by the implementer
**Full build history:** `Change_Log.md` (this workspace) has a dated entry for every stage summarized here. This document is the synthesis; the log is the audit trail.

---

## 1. Overview

A **triangle** is a classical chart pattern: two converging trendlines (an upper boundary and a lower boundary) drawn across a series of confirmed swing highs and lows, narrowing toward a projected apex. Three shapes are recognized — **symmetrical** (both lines converge toward each other), **ascending** (flat/rising lower boundary, flat/declining upper boundary meeting a rising floor), **descending** (the mirror image). The pattern is a statement about *supply and demand compressing*, and chartists treat a decisive close through either boundary as a breakout signal.

**Why PSX:** the Pakistan Stock Exchange is a useful, demanding testbed for this kind of pattern-detection work specifically because its data is messy in ways that force real engineering discipline — long frozen-close plateaus from thin trading, a pervasive `prices_adjusted` placeholder-zero artifact, corporate-action adjustment bugs that pin some symbols' prices near zero for years, and wide liquidity variance across the universe. A pipeline that survives PSX's data honestly is a pipeline worth reusing.

**The working discipline, held throughout:** definitions locked in plain language → formal spec/math written down → code built against the spec → synthetic hand-verified test cases → only then a real-data run. No stage skipped ahead of the one before it. Every bug in this study (Section 2) was caught by direct review of real chart output or adversarial fuzzing, not assumed away — and every fix got a permanent regression test before the pipeline moved on. This discipline is the main reason the negative result in Section 4 is trustworthy: nothing here is a first-draft finding.

The study's actual arc: pivot/boundary/triangle detection built and validated on 5 hand-picked tickers → widened to 18 tickers (same sectors, spanning liquidity tiers) → run across the full 305-symbol (302 after exclusions) active PSX universe → raw breakout-occurrence counting → Type 1-4 post-breakout classification (Kibar/TechCharts framework) → stop-loss/R-multiple comparison (LFD vs. rolling-low vs. opposite-boundary) → full EV validation, which is where the profitability claim broke down under scrutiny (Section 4).

---

## 2. Reusable Infrastructure

These six project-root modules (`C:\Users\Lenovo\psx_pipeline\`, not `ZH_research/` — they are library code, not analysis scripts) are the actual deliverable of this study and should be the starting point for rectangles and any future classical-pattern work.

### `pivots.py` — fractal pivot detection + frozen-close collapsing
`find_pivots(highs, lows, left=3, right=3)` does fractal swing-high/low detection (strict local extremum in a `[i-left, i+right]` window; every pivot carries `confirmed_at = index + right` so nothing downstream can reference a pivot before it was actually knowable). `collapse_frozen_closes()` / `find_pivots_collapsed()` sit in front of it as a preprocessing step: any run of ≥2 consecutive identical closes is collapsed into one synthetic bar before pivot detection runs, so a frozen-close plateau (thin trading, not a real price move) occupies one slot in the fractal window instead of scattering spurious pivots across it. **Key design decision:** this is a deliberately different tuning (`left=3, right=3`) from `breakout_signal.py`'s existing pivot logic (`left=10, right=10`) — the two were kept separate rather than merged, because they serve different granularities (triangle boundary fitting vs. breakout-level detection). **Known limitation:** the frozen-close collapse only catches literal repeated-close runs; it does not catch the separate placeholder-zero artifact (that's `research_filters.py`'s job), so the two guards must both be applied — one alone is not sufficient on this dataset.

### `boundaries.py` — robust tolerance-band trendline fit
`fit_boundary(pivots, tolerance_pct=0.015, max_iterations=10)` is a RANSAC-lite fit: Theil-Sen median-slope seed → classify inliers within a percentage-of-price tolerance band → OLS refit on inliers → repeat to convergence. Returns `None` rather than fabricating a fit if a genuine ≥2-inlier fit is never reached. `check_violation()` is a deliberately separate function from touch/inlier logic — a pivot that sits inside the pattern without touching the line is not a failure, only a non-touch; a `close` crossing the boundary by more than tolerance is a real violation. **Key design decision:** tolerance is a single percentage-of-price constant, which is what makes it work across PSX's huge price-level range (Rs 0.14 penny stocks to Rs 1,000+ blue chips) without per-symbol tuning — confirmed directly when a log-scale alternative was tested and found unnecessary (Section 7.4.3 of the build history). **Known limitation:** that one global tolerance value was never re-derived per volatility regime — it is uniform across calm and turbulent periods alike, untested as a source of bias.

### `triangle.py` — classification, apex, and the forced-line gate
`compute_apex()` solves the two boundaries' intersection (`None` if parallel — a channel, not a triangle). `classify_triangle()` does the 3-way shape classification using a **window-based cumulative-move** flatness definition — the third of three design iterations, the first two (per-bar rate, touch-span cumulative move) both failed on real KEL data before this one was reached. `is_forced_line()` rejects boundaries whose touches don't span enough of the window or sit too close together (`min_touch_span_fraction=0.5`, `min_pairwise_gap_bars=5`) — a line that technically fits the tolerance band but is built from crammed/duplicate touches is not a validated trendline. **Key design decision:** `assemble_triangle()`'s checks run in a fixed layered order (touch count → spacing/forced-line → shape → apex/convergence → duration), each independently tested, so a candidate is never accepted on a partial pass. **Known limitation, load-bearing:** `is_forced_line()` turned out to be the dominant rejection filter at every scale tested (71% of converging candidates at 5 tickers, 74% at 18 tickers, 74.3% at the full 305-symbol universe) — its two thresholds were flagged as worth revisiting but never retuned. Whether they are correctly calibrated for triangles specifically, and whether the same thresholds would even make sense for rectangles (which have a different touch geometry by construction), is unresolved.

### `research_filters.py` — data-quality guards (research-pipeline-only, not production)
Two independent guards, deliberately kept separate rather than merged because they have different signatures and scope: `drop_placeholder_zero_bars()` is a **row-level** filter for a pervasive `prices_adjusted` artifact (`open=high=low=0.00, close≠0, volume=0` — confirmed on 1,596 rows across 205 symbols in the original 5-ticker check, and on 122 of 305 symbols at full-universe scale). `exclude_known_artifact_symbols()` is a **symbol-level**, upfront exclusion of `SGPL`/`DWAE`/`FRCL` — three symbols whose `prices_adjusted` corporate-action adjustment factor is broken, pinning their price near zero (0.0001) for hundreds of bars despite real trading volume. Neither guard touches `stock_signals.py`, the live dashboard, or writes to `psx_data.db`. **Known limitation:** both guards encode artifacts *actually observed in this dataset* — reusable as-is for rectangles (same underlying prices), but a new artifact type discovered on rectangles needs a new guard, not an extension of these two.

### `breakout_classification.py` — Type 1-4 breakout classification (**GENERAL, not triangle-specific**)
Implements Aksel Kibar / TechCharts' Type 1 (momentum) / Type 2 (controlled retest) / Type 3 (hard retest) / Type 4 (failed) framework plus Peter Brandt's Last-Full-Day (LFD) stop-reference concept. **This module only needs a boundary/breakout event and a negation (LFD) level — it has no triangle-assembly logic inside it at all**, which is exactly what makes it reusable for rectangles or any other pattern with a defined breakout and a natural invalidation level. **Key design decision:** three `lfd_variant` supersession windows were tested (`full` = LFD live for the whole horizon, `fixed` = live for N bars, `trigger` = live until price closes at the pattern's own measured-move target) — `trigger` was locked as the default because its cutoff derives from the pattern's own geometry, consistent with every other threshold in this study. **Known limitation, carried forward unresolved:** even under `trigger`, 46.6% of clean `up` breakouts and 52.1% of clean `down` breakouts still touch their own LFD level before the trigger fires. This may be a property of PSX's intrabar noise, or specific to how tight a triangle's LFD reference typically is (the last full day sits right at a converging apex) — not established as a general property of the classification scheme itself.

### `stop_loss_definitions.py` — N-stop walk-forward comparison framework (**GENERAL, not triangle-specific**)
`raw_lfd_level()`, `rolling_low_stop()` (a truncated, no-lookahead reuse/mirror of `backtest.py`'s consolidation-window search), and `walk_forward()` (bar-by-bar, with an extensible `opposite_stop` third arm) together form a framework that takes only entry price, direction, and OHLC arrays — nothing about triangle assembly is referenced anywhere in this module. The **anchor-bar rule** (whichever stop fires first sets the comparison point; every other stop is marked-to-market in its own risk units at that same bar) is the key mechanism that makes an apples-to-apples multi-stop comparison possible at all. **Key design decision:** the rolling-low stop is deliberately *not* imported from `breakout_classification.py`'s LFD machinery — it's a self-contained reimplementation so a future refactor can't accidentally collapse two conceptually different stop definitions into one. **Known limitation, triangle-specific and explicitly flagged as maybe-not-general:** the rolling-low ("kiran-style") stop had only **~25% coverage on triangle candidates** (58/230 "ok", 143/230 skipped for risk > 6%, 29/230 no valid consolidation window found at all). This low coverage is plausibly a property of triangles' pre-breakout structure interacting badly with `kiran_sim.py`'s fixed 5/7/10-bar window search and 6% risk cap — it is not established whether rectangles, with a naturally different (and more explicitly bounded) pre-breakout range, would show the same poor coverage or something better.

---

## 3. Validated, Robust Finding — the One Thing to Trust

**Type-conditional stop selection is real.** On the n=230 primary walk-forward set (the 544 classified triangles narrowed to 518 with a computable realized-R outcome, then to 230 after excluding Type-4-under-`trigger` candidates), the Last-Full-Day stop's win rate against the opposite (un-broken) boundary stop falls **monotonically** with retest severity:

| Type | Description | LFD win rate |
|---|---|---|
| 1 | Momentum breakout | 56.2% |
| 2 | Controlled retest | 41.5% |
| 3 | Hard retest | 20.0% |

This is not a pooled artifact of one strong era. Split across the two independent temporal eras (pre/post 2017-02-07), the **same monotonic ordering held in both, separately**:

| Type | Era A | Era B |
|---|---|---|
| 1 | 60.7% | 50.0% |
| 2 | 39.3% | 43.2% |
| 3 | 14.3% | 25.0% |

It also held when restricted to *eventually-successful* Type 3 trades only — not just the ones that failed outright — confirming this is a genuine property of hard-retest structure (a wider stop surviving a deep pullback), not merely a proxy for "this trade was going to lose anyway."

**How to use this finding:** it is an **ex-ante judgment aid** — a discretionary read of setup quality made *at trade entry* (how clean the retest structure looks: Type 1/2 → favor the tighter LFD stop; Type 3 → favor the wider opposite-boundary stop). **It is explicitly NOT a mid-trade rule.** An adaptive implementation — start on LFD, switch to the opposite-boundary stop the moment the pattern boundary is breached before LFD touches — was built and tested as the obvious real-time version of this finding, and it failed (Section 4.5): by the time a boundary breach is observable, the adverse move causing it has usually already consumed the room a wider stop would have offered. Being wide from entry and going wide after the fact are different trades against the same price path, even though a static comparison treats them as interchangeable.

---

## 4. Everything Tested and Rejected, With the Actual Reason

This section is as load-bearing as Section 3 — it exists specifically to stop the same dead ends from being re-walked on rectangles.

### 4.1 Full-sample EV claim — failed temporal holdout and failed concentration check

On the n=518 primary EV population, the **pooled, full-sample** number looks like a real edge: gross mean R = +1.277 (+1.28%/trade), net of friction and CGT on wins = **+0.853%/trade**, win rate 18.1%. This is the number that would get reported if the study stopped here.

**It does not survive a temporal holdout.** Split at the same 2017-02-07 boundary used throughout this project:

| Era | n | Gross mean R | Net of friction+CGT |
|---|---|---|---|
| A (pre-2017-02-07) | 261 | +2.362%/trade | **+1.762%/trade** |
| B (post-2017-02-07) | 257 | +0.176%/trade | **−0.070%/trade** |

Era A is strongly positive. Era B is net-negative after realistic costs. The pooled full-sample number is an average of a real edge and a dead (or negative) edge, not a stable signal.

**It also does not survive a concentration check.** 47 of the 518 candidates (9.1%) are "large winners" (realized R > 5.0). Removing exactly these 47 flips the entire result:

| | n | Mean R | %/trade |
|---|---|---|---|
| With the 47 large winners | 518 | +1.277 | +1.28% |
| Without them | 471 | **−0.730** | **−0.73%** |

The reported edge is not a broad-based statistical property of triangle breakouts — it is a handful of large individual trades (`CYAN` alone contributes 405R from a single 2009 trade). A result this concentration-dependent is not a tradeable edge; it's a description of a few outlier trades.

### 4.2 Kind asymmetry (descending vs. ascending) — reversed entirely between eras

Using percent-of-measured-move achieved at the 90-day horizon (a different, raw-move metric from the R-multiple EV work above — kept separate deliberately, see Section 6):

| | Era A | Era B |
|---|---|---|
| Ascending | mean +29.9%, median +36.6% | mean **+287.8%**, median +47.0% |
| Descending | mean **+312.4%**, median +117.0% | mean **−2010.9%**, median −37.5% |

In Era A, descending triangles dramatically outperform ascending. In Era B, that flips completely — ascending strongly outperforms, and descending goes catastrophically negative. Any single-era "descending triangles are better" (or vice versa) finding would have been a genuine, statistically clean-looking result and also completely wrong going forward. This is the clearest single illustration in the whole study of why the temporal-holdout discipline exists.

### 4.3 Kibar's 200-day trend filter — worsens EV when tested properly, not just neutral

The naive check (filtering candidates to those aligned with their 200-day SMA/EMA trend, then comparing **raw percent-move-among-survivors** across horizons) looked roughly neutral — a mix of "improves," "mixed," and "worsens" depending on horizon and direction, nothing alarming.

**The proper check — realized R-multiple EV, not raw gain% — tells a different story.** The SMA filter passes 343 of 503 SMA-eligible candidates (68.2%):

| | n | Gross mean R | Net of friction+CGT |
|---|---|---|---|
| Unfiltered baseline | 518 | +1.277 | +0.853%/trade |
| SMA-filtered | 343 | +0.709 | **+0.387%/trade** |

The filter removes 175 candidates and roughly **halves** the net edge. It does not fix the underlying instability either — filtered Era A mean R is 1.19 vs. filtered Era B mean R 0.24, essentially the same order-of-magnitude gap as the unfiltered eras. And it makes concentration *worse*, not better: among the 343 filtered survivors, the top 5 trades contribute 94.4% of the filtered population's total summed R (229.41 of 243.12R) — a narrower population leaning even harder on the same handful of outliers. The filter removes noise-level trades along with everything else and concentrates what's left.

### 4.4 Fixed 1:2 stop/target scheme — solves concentration structurally, edge too thin for costs

A fixed 2%-stop / 4%-target scheme (vs. the LFD dynamic stop used everywhere else) genuinely fixes the outlier-concentration problem: top-5 concentration drops from ~94-99% (LFD-based schemes) to **32.3%** unfiltered / 38.5% with the Kibar filter, and win rate rises to 35.3% / 35.9% (vs. 18.1% / 18.7% for LFD). This is a real structural improvement — proof that the concentration problem is a property of the stop scheme, not an unfixable property of the underlying pattern.

But the resulting edge is too thin to matter: mean R = **+0.06%/trade** unfiltered, +0.076%/trade filtered. For comparison, moving from gross to net-of-friction-and-CGT cost the LFD scheme about 0.4 percentage points off a base of +1.28%/trade. An edge of 0.06-0.08%/trade would not be expected to survive the same order of cost drag — it was not separately walked through cost adjustment because the gross number alone is already inside the noise band of realistic transaction costs.

### 4.5 Adaptive stop-switching — underperforms static LFD on the exact trades it targets

Tested as the real-time implementation of the Section 3 finding: start every trade on the LFD stop, switch to the opposite-boundary stop the moment the pattern's own boundary is breached before LFD touches. On the 26 trades (11.3% of the n=230 primary set) where a switch actually triggered — concentrated almost entirely in Type 3, exactly where the static finding says a wider stop should help — switching **underperformed** simply staying on LFD: mean realized R 0.076 (switching) vs. 0.207 (static LFD), 8 wins / 12 losses / 6 ties head-to-head. Mechanism: by the time a boundary breach is observable, the adverse move causing it has typically already consumed the room a wider stop would have offered. Reported as a closed, negative sub-finding — not a gap needing further iteration.

### 4.6 Re-entry after stop-out — median outcome worse than walking away

Tested whether re-entering after an LFD stop-out (chained trades, capped at 3 re-entries) recovers value the single-trade LFD stop leaves on the table. Half of all chains (115/230, 50.0%) re-entered at least once. Restricted to those 115 re-entered chains — where, by construction, the original single trade was already a loser (median realized R = −1.0):

- Chain (all legs summed) median realized R: **−2.0 to −2.71** (worse than the original single loss)
- Chain beat the original single-trade outcome: 39/115 (34%)
- Chain was worse: **76/115 (66%)**
- Ties: 0

Re-entering after a stop-out more often compounds the loss than recovers it. The median trader following this rule would have been better off simply walking away after the first stop.

---

## 5. Final Verdict

**Triangles, as specified and tested in this study, are NOT a demonstrated tradeable edge on PSX.** The full-sample EV claim that would have looked publishable in isolation does not survive temporal holdout (one era net-negative) or concentration analysis (the result depends on 9.1% of trades). Every attempted fix — trend filtering, a bounded stop/target scheme, adaptive stop-switching, re-entry after stop-out — either failed outright or solved one problem (concentration) while remaining too thin to trade.

**The pattern-detection and stop-selection infrastructure is real and should be reused** (Section 2) — it is honestly built, adversarially tested, and the one positive finding it produced (Section 3, Type-conditional stop selection) is temporally robust. **The profitability claim is not real and should not be revived** on triangles without a genuinely new angle that has not already been tried here — trend filters, alternative stop/target schemes, adaptive rules, and re-entry logic are all now closed avenues, not open ones.

---

## 6. Meta-Lessons for Rectangles

1. **Run temporal-holdout and top-decile-removal concentration checks early — not as a final gate.** In this study both checks were the *last* thing done, after the full breakout-classification and stop-loss machinery was already built on the strength of a full-sample EV number that turned out not to survive either check. Running both checks on the first descriptive EV pass would have surfaced the instability months of build-work earlier.

2. **Watch for mean/median divergence from the very first descriptive pass — it is the early warning sign of outlier domination.** Every dataset in this study that later turned out to be concentration-dependent (Section 4.1, 4.3) showed a median realized R of exactly −1.0 next to a wildly larger mean. That gap was visible from the first summary table; it should be treated as a standing red flag, not just background statistical texture.

3. **Distinguish raw gain%-among-winners from real EV/R-multiple from the start.** Section 4.3's Kibar-filter check is the clearest lesson here: the raw-percent-move check looked neutral-to-positive; the same filter, judged on realized R-multiple EV, clearly worsened the result. If only the raw-move check had been run, the wrong conclusion would have shipped.

4. **Test a bounded stop/target scheme early**, given how cleanly it solved the outlier-concentration problem here (Section 4.4) even though the resulting edge was too thin to trade. For rectangles, a fixed-R scheme should be one of the first things tried, not a late-stage patch attempt.

5. **Before reporting any sector- or kind-level "edge," check whether it survives removing that subgroup's single best trade.** The kind-asymmetry reversal (Section 4.2) would have looked like a clean, real finding in either era alone. A same-era check — does "descending beats ascending" survive dropping descending's own best trade — would have been a cheap early warning that the effect was concentration-driven before the second-era data even existed to falsify it directly.

6. **Decide upfront whether to use Kibar's preferred horizontal-boundary-with-3-touches convention.** Triangles have inherently diagonal boundaries, which created real tension throughout this study between Kibar's stated preference and the diagonal `fit_boundary()`/`is_forced_line()` machinery actually built. Rectangles are naturally horizontal — this specific tension may simply not apply, which could mean either a simpler boundary-fitting problem, or a different set of validity questions (e.g., the 3-touch convention may bind harder when the boundary literally is a fixed horizontal level). Make this call explicitly before building, rather than discovering the tension mid-study as happened here.
