# Production Trading Rulebook v1 — RS-Conditioned Donchian Breakout

**Date:** 2026-07-11
**Built from:** established facts only (`boring_study_final_assessment_2026-07-11.md` §1). Does not use the distance-from-prior-high or wide-consolidation findings (unreplicated / unexplained — excluded from v1 by design). Does not depend on resolving Structure vs. Flow (correctly — the rulebook only needs *that RS predicts the edge*, not *why*).

---

## 0. Correction to the operating premise (read before implementing)

Top-decile RS winners resolve to target **faster in absolute terms** than bottom-decile winners (~2.4–2.6 trading days vs. ~3.8–5.0 days, both panels — see chat). What shrinks with RS is breakout's *speed advantage over a matched control day*, not the winner's own time-to-target. The capital-planning implication is about the **non-winning tail's duration** (up to the full 90-day measured horizon), not slow winners. Exit logic below reflects this.

---

## 1. Environment (The Filter)

**Base universe hygiene (reuse existing infra, don't reinvent):**
- Exclude `INDEX_SYMBOLS`, `DFC_SYMBOLS`, futures/derivatives (existing `-JAN/-FEB/...` regex), and `EXCLUDED_SECTORS` — all already defined in `config.py`, already the standing filter for every other setup type in this project. Apply identically here for consistency.
- **Liquidity gate — added for production, not part of the tested research.** The boring study ran with no liquidity gate by design (deliberately informal, per its charter). This project's own documentation flags a recurring illiquid/junk-price contamination problem (e.g. SGPL, PIAB-style near-zero-price symbols). Deploying capital against an edge measured on a population that includes untradeable junk is not something I'd sign off on without a gate. Recommend reusing the existing convention already applied to every other setup type: `avg_vol_10d > 200,000`. **This gate was not backtested as part of this specific edge** — flagging honestly rather than implying it was.

**The RS filter — the one validated effect modifier:**
- Compute `RS_60(s, t-1) = [Close(s,t-1)/Close(s,t-61) − 1] − [KSE100(t-1)/KSE100(t-61) − 1]` — the exact 60-trading-day definition this program locked and tested. **Do not substitute the existing `rs_score_20` / `rs_rank` columns in `stock_signals.py`** — those are a 20-day-window construct computed for a different purpose (setup ranking) and were never the object this research validated. Using them would be exactly the kind of "looks similar, isn't the same" substitution this project has caught itself on before. Compute `RS_60` fresh.
- Rank `RS_60` **cross-sectionally, daily**, among the post-exclusion, post-liquidity-gate eligible universe as of `t-1`. Require **top decile** (≥ 90th percentile of that day's eligible universe).
- **Why top decile, concretely (CORRECTED 2026-07-11 — see Addendum B below for the full replication):** the 55.1%/57.0% hit rates originally quoted here were computed without a liquidity gate and were inflated by illiquid/junk-price names (median RS in the most extreme sub-bucket ran 400–580%, an implausible 60-day return not seen in genuinely tradeable names). **The corrected, liquidity-gated top-decile hit rate is ~49.0% (20d) / ~48.5% (60d).** The RS effect modifier itself survives the liquidity gate intact (regression interaction retains 110% of its original magnitude in 20d, 81% in 60d, both still highly significant, p<0.003 in both panels) — only the absolute headline win-rate needed revising down, not the underlying logic for using RS_60 as a filter. Decile 9 (top decile) remains the best-or-tied-best decile by edge in both panels even after gating (+14.89pp 20d, +10.74pp 60d) — decile 8 is a solid second but does not overtake it.
- **Flagged extrapolation, not a hidden assumption:** the historical decile analysis ranked `RS_60` by pooling all dates and symbols together (`pd.qcut` on the full panel), not by a live daily cross-sectional rank against that day's specific universe. Ranking daily against the live universe (as specified above) is the more robust, standard, regime-adaptive choice — an absolute historical RS cutoff would drift as market-wide return levels shift over time — but it is a translation of the tested design, not literally the design that was backtested. Worth a quick validation pass (recompute the historical decile table using a daily cross-sectional rank instead of pooled `qcut`) before sizing real capital on it — that's an implementation-validation step, not new mechanism research.

**What we explicitly throw away, and why:**
- **Sector RS / `sector_rs_rank`** — CLOSED DEAD. Leave-one-out correction showed ~89% of the sector-stock RS correlation was a self-inclusion statistical artifact (r: 0.59→0.07). Not used anywhere in this system.
- **Directional Volatility Ratio / `vol_ratio`** — real pattern, but partial correlation ≈0 once RS is controlled. Fully redundant with `RS_60`; adds no independent signal, adds a second knob to tune for zero benefit. Dropped to keep the system to one validated state variable.
- **Market-environment aggregates** (breadth, dispersion, correlation, trend persistence, sector concentration) — CLOSED DEAD, R²≈0.0007, negative OOS. No regime gate on entries.
- **Distance-from-prior-high, consolidation width** — real in places, but unreplicated (structure signal, 60d panel null) or unexplained (wide-consolidation). Excluded from v1; would be deploying capital against findings this program itself flagged as not yet established.

---

## 2. Entry

**Signal definition (pick one as primary — both were independently validated, this is a real choice, not a default):**

`Close(s,t) > MAX(High(s,t−N), …, High(s,t−1)) × 1.01`, on `prices_adjusted`.

- **N=60 recommended as primary**: stronger, more monotonic RS interaction (Spearman ρ=0.927 vs. 0.733 for N=20 on the decile-edge relationship), larger top-decile edge (22.57pp vs. 20.73pp). Fewer signals, since a 60-day high is a rarer event.
- **N=20 as a higher-frequency companion**, if signal count matters more than per-signal edge — validated independently, not as an OR-combination with N=60 (the two were never tested combined; run them as two separate systems if you want both, not merged logic).

**Zero-lookahead data plumbing — the sequencing that actually matters:**

1. **At the close of `t−1`:** freeze the day's eligible watchlist. Compute `RS_60(s,t−1)` using only `Close(t−1)` and `Close(t−61)` (stock) and the equivalent KSE-100 levels — never anything from day `t`. Rank cross-sectionally, keep the top decile, post liquidity/sector filters. This list is locked before day `t`'s price action exists.
2. **During/at the close of `t`:** for watchlist symbols only, evaluate the breakout condition using `Close(t)` against `MAX(High(t−N..t−1))` — the rolling max already excludes `t` itself by construction, so this leg was lookahead-safe in the original definition; confirming it explicitly here since it's the second half of the same discipline.
3. **The specific bug this guards against:** computing `RS_60` with a window that includes day `t`'s own return would make "RS is high" partly a *consequence* of "today was a big up-day," creating a tautological breakout↔RS relationship — the same class of endogeneity trap (a variable contaminated by the very event it's supposed to predict) this project's DAG-scrutiny step has caught twice before at the mechanism level. Locking the RS window to `t−1` and earlier is the entry-level version of that same discipline.
4. **Entry price = `Close(t)`** — this is what the backtest actually measured (the race begins at `t+1`'s high/low against this entry). If same-day at-the-close execution isn't reliably achievable on PSX, using `Open(t+1)` instead is a small, *untested* deviation from what was validated — worth tracking separately (slippage vs. the backtested entry) rather than assuming it's equivalent.

> **UPDATE (2026-08-30) — this deviation was tested and it is not a small one.** Full study:
> [`overnight_gap_execution_2026-08/`](overnight_gap_execution_2026-08/FINDINGS.md). Across
> 2005-2026, both lookbacks: **65-70 % of signals gap up** at `Open(t+1)` (81 % for
> Strategy Confirmed), mean +0.9-3.2 %. Entering at the real open instead of `Close(t)`
> drops net-of-cost EV from +0.5-1.8 % to **≈0 or negative** — the friction is roughly the
> size of the whole edge. A working limit at `Close(t)` fills ~74 % of the time but those
> fills win only ~19 % (net EV −1.3 to −2.1 %). The one positive-looking sub-rule (take
> only signals that open ≤ prior close, enter at the discounted open) is **not
> distinguishable from a matched random-day control** on clean 2020-2026 data. Separately,
> the Strategy-Confirmed filter's edge fails an era split even at the ideal `Close(t)`
> entry (negative pre-2010, concentrated in 2020-2026). **Verdict: as an executable
> mechanical rule this system has no demonstrable edge; the backtested edge lived in the
> `Close(t)` fill assumption.** Not a verdict on discretionary intraday execution.

---

## 3. Exit & Capital Allocation

**Fixed race, exactly as validated — do not deviate:**
- Target: `Entry × 1.10`. Stop: `Entry × 0.94`. Monitored via `High`/`Low` from `t+1` onward.
- **Horizon cap: 90 trading days.** This is not an arbitrary risk-management add-on — it's the exact ceiling the backtest itself used. A trade unresolved at day 90 was scored as a non-win in every result quoted above. **Close the position at day 90 regardless of P&L.** Trading past day 90 means trading a population that was never measured at all — that's the unvalidated side of the line, not the conservative side.

**No time-stop shorter than 90 days — CORRECTED reason, per Addendum A below:** the original justification here (guarding against a population of slow-draining, undecided positions occupying capital for months) turned out not to describe this population at all. Directly measured (top-decile RS, non-winners, both panels): **98.7–99.0% resolve via the stop, median 2 trading days, 90th percentile 5–6 days, essentially all resolved within 30 days.** Zero rows in either panel represent a genuine full-90-day non-resolution — the tiny "unresolved" remainder (~1%) is just trades too recent (relative to today's date) to have had 90 days pass yet, not stuck positions. The 90-day cap is kept as a backstop for a tail this historical sample doesn't show, not because it's load-bearing. Still don't add a shorter time-stop or trailing-stop rule — not because one would cut into "necessary patience" (it wouldn't — see below), but because none has ever been tested, and this data gives no reason to think one is needed.

**Capital allocation — the corrected opportunity-cost picture (Addendum A supersedes the original text here):**
- **Both winners and losers resolve fast.** Winners hit target in ~2.4–2.6 days (median, top decile). Losers hit the stop in ~2 days (median, top decile, both panels). This system turns capital over quickly either way — the "slow grind" framing from earlier in this document was wrong on the winning side, and the "long-drifting zombie" framing was wrong on the losing side. Neither exists in this data.
- **The real, still-open capital risk is correlated/simultaneous entry clustering** (e.g. a whole sector firing top-decile-RS breakouts on the same day), not individual-position duration. Checked separately (Addendum C): clustering does **not** predict a worse per-trade hit rate, so it's a portfolio-concentration question, not a signal-quality one — don't build a per-stock penalty for it, but do be aware `kiran_sim.py`'s `MAX_INVEST_FRAC=0.99` cap silently skips new signals with no prioritization logic when capital is full, and fast turnover reduces but does not eliminate the chance of that happening during a genuine cluster.
- Position sizing: standard 1% account-risk rule applies unchanged — size = (1% of account) / 6% stop distance. The RS filter changes *which* trades you take and *how often you win*; it does not change the stop distance or the sizing formula.

---

## What this rulebook deliberately does not attempt

No mechanism claim is embedded anywhere above — the system runs entirely on the *fact* that `RS_60` modulates the edge, not on any theory of *why*. That's the correct use of an identification-frontier result: you don't need to resolve Persistent Directional Flow vs. Technical Market Structure to deploy capital, because neither would change a single number in this rulebook if resolved.

---

## Addendum A (2026-07-11) — Capital-lockup / duration analysis

Directly measured day-to-stop and day-to-expiry for non-winning top-decile-RS breakouts (`boring_capital_lockup_analysis.py`, both panels): 98.98%/98.71% resolve via the stop (median 2 days, 90th percentile 6/5 days, max 38/30 days); 0 genuine full-90-day non-resolutions in either panel; the ~1% "unresolved" rows are right-censored (too recent to have had 90 days pass, median available history ~5.5–6 days, unrealized return clustered near 0%). **This falsifies the "long-drifting zombie" concern that motivated considering a trailing stop or decay filter.** No decay filter has been added; none is justified by this data. Full output: `boring_capital_lockup_analysis_output.txt`.

## Addendum B (2026-07-11) — Liquidity-gated replication of the core RS-heterogeneity result

A star-rating design exercise for the manual-execution UI surfaced that the most "elite" RS sub-bucket was dominated by implausible RS values (illiquid/junk-price contamination). This triggered a full, dedicated, pre-registered-style recheck of the core finding with the liquidity gate (`avg_vol_10d > 200,000`) applied **from the start** (`boring_liquidity_gated_replication.py`), not just at the extreme tail. Result: **the RS effect modifier survives.** Regression interaction term retains 110% of its original magnitude in the 20d panel (p=1.3e-12) and 81% in the 60d panel (p=0.003), both still highly significant despite the sample dropping to 28% of its original size. Decile 9 remains the best-or-tied-best decile by edge in both panels. **What does not survive:** the absolute headline hit-rate figures, which were inflated by the same contamination (corrected from 55.1%/57.0% to ~49.0%/48.5% — reflected in §1 above). A first-pass check that compared raw breakout hit-rate instead of edge-over-matched-control briefly and incorrectly suggested the whole relationship might be an artifact — corrected once the proper matched-control methodology was applied; noted here as a live example of why this program insists on that specific comparison. Full output: `boring_liquidity_gated_replication_output.txt`.

## Addendum C (2026-07-11) — Star-rating design investigation → scrapped in favor of a binary badge

Two checks were run to evaluate a proposed 1–5 star rating for the manual-execution chart view (`boring_star_rating_checks.py`):
- **Granular RS percentile depth within the top decile:** initially looked real (hit rate rising monotonically from ~52% to ~61–63% across sub-quintiles, ρ=0.900) — but this was the same contamination Addendum B addresses. Once liquidity-gated, the pattern flattens to noise (ρ=−0.500/+0.300, both non-significant). **Not supported. Do not build a granular star system on RS percentile depth.**
- **Same-day, same-sector entry clustering:** no evidence it predicts a worse per-trade hit rate in either panel (ρ≈−0.02, both non-significant; isolated breakouts actually show the *highest* hit rate). **Do not build a clustering penalty into a per-stock rating** — if clustering matters at all, it's a portfolio-concentration question (Addendum A), not a signal-quality one.

**Decision: the star system is scrapped.** Replaced with a binary **Pass/Fail "Strategy Confirmed" badge**: green (✅ Confirmed) if `rs_60_decile == 9` (top decile, liquidity-gated ranking) **AND** `avg_vol_10d > 200,000`; red (❌ No Fit) otherwise. This is the only claim the data actually supports — a clean gate, not a graded score. Shown as a column in the signals table itself ("Strategy Fit"), with a "Strategy Confirmed only" filter defaulting to on so unconfirmed breakouts don't clutter the actionable list by default. A separate per-symbol chart lookup was built, then removed at the user's request as redundant with the table. See `boring_signals.py` / the Streamlit Explorer toggle for the implementation.

---

**Version lock:** this document, as of 2026-07-11 with Addenda A–C applied, is the locked v1 specification for the `boring_signals` database table and the "Boring Breakouts" Explorer toggle.

**Patch (2026-07-11):** added a `breakout_level` column (1.01× prior N-day high — the threshold that had to be cleared) alongside the existing entry price, since displaying only the entry price under the label "Trigger Price" made it look like it should equal the threshold, when it's actually the close and is often well above it. Table renamed accordingly: "Trigger Price" → "Entry Price", with "Breakout Level" shown next to it. Existing rows backfilled from real price history, not approximated from the entry price.
