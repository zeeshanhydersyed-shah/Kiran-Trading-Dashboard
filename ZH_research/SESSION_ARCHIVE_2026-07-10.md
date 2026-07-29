# Session Archive — 2026-07-10 (PRE_BREAKOUT / Conviction Engine Research Arc)

**Status:** ARCHIVAL RECORD — standalone historical reference, not itself a hypothesis test. Consolidates S-002 through S-005 and PRE_BREAKOUT_Specification_v1.0.md Sections 5–13 into one chronological narrative. Every number below is pulled verbatim from its source document (cited inline) — none re-derived or approximated for this archive.
**Compiled:** 2026-07-10
**Sources:** `S-002_RS_Rank_Quartile_BREAKOUT_V2.md`, `S-003_Sector_RS_Rank_PreScreen.md`, `S-004_RS_Rank_LiveSystem_Reconciliation.md`, `S-005_Regime_Transition_Age_and_Type.md`, `PRE_BREAKOUT_Specification_v1.0.md` (Sections 5, 9–13, Session Summary), `BREAKOUT_Specification_v1.0.md`, `Market_Structure_Diagnostic_2015-2026.md`, `Hypotheses.md`, `Decisions.md`.

---

## 1. Session Overview

The session's question: **what predicts `fwd_return_10d` among stock-level candidates**, given that BREAKOUT V2's construct (a discrete, database-aligned, rolling-liquidity-corrected event definition) had just been newly validated and the PRE_BREAKOUT construct formally reopened for research on top of it. The session tested a sector-level gate already believed live, five distinct stock-level candidate constructs, one exploratory regime-conditioning idea, and one operational assumption drawn from the PI's personal trading journal.

**Honest final answer:** one confirmed sector-level edge (`sec_global_rank ≤ 8`) held untouched throughout and remains live. Five stock-level constructs — RS-rank as post-breakout quality scoring, `sector_rs_rank` as a pre-screen filter, tightness (standalone and sector-conditioned), velocity/volume (ROC + volume multiplier), and Stealth Relative Strength (unconditional) — were tested to a locked, three-era or locked-confirmatory standard and killed. One exploratory lead (Stealth RS, conditioned on a "non-runaway-bull" market regime) showed a genuinely interesting, mechanistically coherent recovery, but is explicitly not confirmed — it re-uses already-spent data and awaits fresh post-2026-07 data for a single future confirmatory test. One operational assumption — a PI personal-journal observation about regime-transition timing and regime type — was tested against the full database and came back **mixed**, not confirmed and not dead: real in two of three eras, reversed in the third.

---

## 2. Chronological Methodology Log

### (a) RS-rank re-validation — S-002 — 🔴 DEAD
*Filed 2026-07-08.*

**Hypothesis:** a previously-cited finding — RS-rank quartiles within BREAKOUT, Q1 fwd_return_10d ≈ -0.20%, Q4 ≈ +2.07% — replicates on the corrected BREAKOUT V2 population.

**Test design:** population = `stock_signals_breakout_v2_staging_full` WHERE `breakout_event=1` (N=927 rows, 135 symbols, 2015-01-01→2026-07-07). `rs_score_20` and `sector_rs_rank` joined 100% on `(symbol, date)`. `fwd_return_10d` computed fresh via `compute_forward_returns.py`'s formula (valid for 915/927, 98.7%). Equal-count quartiles via `pandas.qcut`. Mann-Whitney U (one-sided, primary), Welch's t-test, Cliff's delta.

**Exact result:** `rs_score_20` quartiles: Q1 (weakest RS) mean **+3.02%**, Q4 (strongest) mean **+4.50%** — non-monotonic (Q1>Q2>Q3, then Q4 highest). Q1 vs Q4: MWU two-sided p=0.7140, one-sided p=0.6432, Welch t=0.860 p=0.3908, Cliff's δ=-0.0198. `sector_rs_rank` (collapsed to 3 groups, cardinality): Q1 (strongest sector) mean +2.55%, Q3 (weakest) mean +1.82% — monotonically decreasing, opposite of hypothesis. Q1 vs Q3: MWU p=0.5810/0.7096, Welch t=-0.740 p=0.4595, Cliff's δ=-0.0265. **The cited baseline (-0.20%/+2.07%) could not be located anywhere in the repository, its documentation, or git history** (`git log --all -S "quartile"`/`-S "qcut"`: zero commits).

**Classification: DEAD.** Two independent, either-sufficient reasons: (1) the cited baseline has no verifiable source; (2) on the corrected population neither variable shows a significant or directionally-matching split (all p≥0.39, all |Cliff's δ|<0.03, low quartile positive not negative in both variables). No era-split replication attempted — per the project's proportional-burden-of-proof principle, a factor this weak on its first clean test doesn't merit the additional cost.

### (b) Live-system audit — A1/A2 discovery
*Surfaced during S-002/S-003 work, consolidated in S-004 (filed 2026-07-09).*

While validating S-002's population, the audit traced where `rs_score_20`/`sector_rs_rank` are actually *used* in the live system, surfacing two findings requiring their own tests before any code change:
- **A1:** `leaders_scan.py::_raw_score()` weights `rs_score_20` and `sector_rs_rank` as 2 of 5 components in a "conviction score" driving Leaders page sort/selection, applied *after* BREAKOUT/PRE_BREAKOUT selection.
- **A2:** Explorer's "Weinstein Watchlist" toggle applies `sector_rs_rank ≤ 5` as one of seven simultaneous AND conditions, independent of any breakout status.

Neither was acted on until each was formally tested (S-002 for A1, S-003 for A2) — no code changed on the strength of the audit trace alone.

### (c) `sector_rs_rank ≤ 5` pre-screen test — S-003 — 🔴 DEAD, REVERSED
*Filed 2026-07-09.*

**Hypothesis:** A2's live filter condition (`sector_rs_rank ≤ 5`) predicts better forward returns as a standalone pre-screen, independent of breakout status.

**Test design:** population = `stock_signals` WHERE `avg_vol_10d > 200000` AND `sector_rs_rank IS NOT NULL` (N=297,640, 257 symbols, 2015-01-01→2026-07-09 — matches the live filter's own liquidity gate exactly). `fwd_return_10d` computed fresh (valid 296,010/297,640, 99.5%). Two groups: `≤5` vs `>5`. Same test battery as S-002, plus per-rank-value breakdown and three-era consistency check (Development 2015-2019, Validation 2020-2022, OOS 2023-2026).

**Exact result:** `≤5` mean **+0.59%** vs `>5` mean **+0.92%** — mean delta **-0.33pp**. MWU two-sided p<0.000001, one-sided (≤5>\>5) p=**1.000000**, Welch t=-7.99 p<0.000001, Cliff's δ=**-0.0334**. Per-rank breakdown (rank 1→+0.59%, rank 5→+0.77%, rank 10+→**+1.05%**): a gentle near-monotonic *rise* from rank 1 to 10+, no cliff at rank 5. Era consistency: Development Cliff's δ=-0.0302, Validation δ=-0.0362, OOS δ=-0.0262 — **direction consistent, `≤5` never outperforms in any era.**

**Classification: DEAD — reversed direction.** Statistically significant at this N (≈296K), practically negligible effect size (Cliff's δ≈-0.03, "negligible" by convention), but never once in the hypothesized direction, in the pooled data or any of three eras.

### (d) Reconciliation — `sec_global_rank` vs `sector_rs_rank` — S-004 — REFERENCE DOCUMENT
*Filed 2026-07-09. No new hypothesis test; consolidates A1/A2 and resolves a field-naming confusion.*

Confirms `sec_global_rank` is a SQL alias — `sec.rs_rank AS sec_global_rank` — identical wherever it appears (`dashboard.py:1716`, `dashboard_pg.py:545`, `weinstein_combined_backtest.py:42`, `screener_audit.py:90`, `backtest_rs_score.py:18`) — resolving to `sector_signals.rs_rank`: **all ~23 sectors ranked against each other, market-wide**, by each sector's market-cap-weighted 20-day return minus KSE-100's. By contrast `stock_signals.sector_rs_rank` ranks individual **stocks against other stocks within their own sector** — a different table, a different entity ranked, a different question.

**Consequence, confirmed:** `sec_global_rank ≤ 8`'s +10.50% EV backtest (`weinstein_combined_backtest.py`, N=1,021 streaks, WR=43.5%, LR=35.7%, 92/yr) is **unaffected by A1/A2's dead verdicts** — different field, separately validated, remains a live, trusted gate. (Open, unresolved item flagged but not fixed here: the dashboard's cited "+1.14% EV" marginal-contribution figure and its 5/8/12/no-gate sweep table exist only as prose in `dashboard.py`'s help expander — not reproducible from any script in the repo. Does not call the +10.50% figure into question.) As of this document's filing, no code had yet been modified — A1/A2 changes held pending PI review.

### (e) PRE_BREAKOUT population rebuild + tightness test — Sections 2–3, 5, 9–10 — 🔴 DEAD, REVERSED
*2026-07-10.*

**Population rebuild:** against `stock_signals_breakout_v2_staging_full` (247 symbols, rolling-liquidity-gated) — up from the deprecated 243-symbol table's 922,056 rows to **280,881 rows** (30.5% of old count; expected, since the new source only holds liquidity-eligible dates). Derivation validated: an initial gap-blind walk produced 91 mismatches (fixed by recomputing `compute_breakout_events()` fresh from full continuous price history); a second issue (602 apparent mismatches, NaN-vs-None artifact) also found and fixed. **Final validation: 0 mismatches out of 291,674 rows.**

**Hypothesis (standalone, Section 5):** tighter `bbw_pct`/`pct_rank_252`/`pct_rank_756`/`zscore_252` (relative to a stock's own history) predicts better `fwd_return_10d`. Tightest quartile (Q1) vs loosest (Q4).

**Exact result (Section 5.1, all eras, N=274,050):** `pct_rank_252` Q1 mean +0.408% vs Q4 mean +1.546% — mean Δ **-1.138pp**, MWU one-sided (tight>loose) p=**1.000000**, Cliff's δ=**-0.0387**. `pct_rank_756` Δ=-1.301pp, δ=-0.0485. `zscore_252` Δ=-1.148pp, δ=-0.0380. **All three measures agree: loose beats tight.** Era-consistent direction (never once tight>loose in Development, Validation, or OOS across all three measures).

**Hypothesis (sector-conditioned, Section 10):** re-tests `pct_rank_252` restricted to `sec_global_rank≤8` (matching PI's actual process — tightness applied only after sector-strength screening). Conditioned population: **103,052/280,881 rows (36.69%)**.

**Exact result (Section 10.2, N=100,680):** Q1 mean +0.579% vs Q4 mean +1.513% — mean Δ **-0.934pp**, Cliff's δ=**-0.0187** (roughly half the unconditioned magnitude). Direction unchanged.

**Classification: REVERSED both times — not confirmed, not simply dead** (Section 5.1's own framing) / **REVERSED, WEAKENED — not rescued by conditioning** (Section 10.5). Sector-strength conditioning does not turn tightness into a positive filter; it survives at reduced magnitude.

### (f) Velocity/volume test — Phase 4c / Section 11 — 🟡 MIXED, no survivor
*2026-07-10.*

**Hypothesis:** ROC-5/ROC-10 (rate of change) and `vol_multiplier` (`avg_vol_10d/avg_vol_20d`) predict `fwd_return_10d`, motivated by BREAKOUT V1's H-005 (Volume Expansion Ratio, this project's strongest individual factor before decaying to null at OOS: Cliff's δ 0.0690→0.0445→-0.0037).

**Structural finding before testing began:** `vol_multiplier` has a hard mathematical ceiling approaching-but-never-reaching 2.0x (nested 10d-within-20d window construction). Observed max **1.999320**. The task's 2.0x threshold candidate is structurally unreachable — shrinks the real test family from 6 to **4**, giving Bonferroni-adjusted α = 0.05/4 = **0.0125**.

**Exact pooled results (N=280,881):** ROC_5 quartile Δ=+0.624pp, one-sided p=0.083692, δ=0.0043 (fails). **ROC_10 quartile Δ=+0.799pp, one-sided p=0.000033, δ=0.0123 (survives Bonferroni)**. `vol_multiplier>1.5x` Δ=+0.597pp, p=0.584362, δ=-0.0007 (fails). Combined ROC10-Q4+vol>1.5x Δ=+0.928pp but p=0.929595, δ=-0.0065 (fails, rank-reversed despite the largest mean delta of the four).

**Era pattern:** ROC_10's pooled "survival" is driven by Development alone (p=0.000043) plus pooled N — Validation n.s. (p=0.181277), OOS rank-reversed (δ=-0.0045). `vol_multiplier>1.5x` reverses with significance in Validation (Δ=**-0.492pp**, p=0.999984, δ=**-0.0292**) — an erratic, non-monotonic pattern, not a graceful decay.

**Classification: MIXED, no confirmed factor.** Nothing survives independently across all three eras; `vol_multiplier`'s Validation reversal and the combined test's pervasive mean-vs-rank divergence are worse-behaved than H-005's own decay.

### (g) Exploratory wildcard: Stealth RS + Volume Regime Shift — Phase 5 / Section 12.1–12.7 — Stealth RS promising in Development
*2026-07-10. Development-era only (2015-01-01→2019-12-31), by deliberate design — no Validation/OOS access confirmed via a runtime `guard_no_future_leakage` assertion.*

**Adverse-day threshold justification:** KSE-100 daily returns (N=3,705 Development-era days): mean +0.059%, std 1.253%. -1.5% threshold sits between the 5th (-2.106%) and 10th (-1.293%) percentile — **303 adverse days**, ~20.6/year.

**Candidate A — Stealth RS** (adverse-day resilience count, trailing 20d window): stealth-count distribution — 0: 93,012 rows; 1: 6,646; 2: 822; 3: 148; 4: 48; 5: 10. Groups: 0 / 1 / **2+ (N=1,028)**.

| Stealth group | N | Hit rate (>+10%) | Mean | Median |
|---|---|---|---|---|
| 0 | 93,012 | 11.47% | +0.242% | -0.559% |
| 2+ | 1,028 | **16.34%** | **+1.536%** | **+0.340%** |

Hit-rate delta **+4.87pp**, MWU one-sided p=**0.000019**, Cliff's δ=**0.0747** — the largest effect size in this session's entire factor work. Decile breakdown: broad shift across 30th–90th percentile, stealth≥2's own max (44.07%) *lower* than baseline's (116.62%) — a genuine broad-based lift, not outlier-driven.

**Candidate B — Volume Regime Shift** (180-day volume high AND tightest local-20d BBW% quartile, compound N=236): hit rate 20.34% vs 11.49%, +8.85pp, but MWU one-sided p=**0.091** — not significant even uncorrected.

**Classification (Section 12.6):** Candidate A recommended as the stronger candidate to carry into a single, locked Validation+OOS confirmation. Candidate B weak, underpowered, directionally interesting only.

### (h) Confirmatory lock-and-test on Stealth RS — Section 12.8–12.13 — 🔴 DEAD on Validation+OOS
*2026-07-10. One-shot, locked run — no parameter adjusted after seeing the result (adverse threshold, window, groups all copied verbatim from (g)).*

**Population:** Validation (2020-2022) + OOS (2023+) combined into one population per explicit PI instruction (180,195 rows, 238 symbols, 2020-01-01→2026-07-07). Adverse days: 406. Stealth-count distribution: 0→162,866; 1→15,298; 2→1,836; 3→162; 4→29; 5→4.

**Exact result:** stealth=0 N=161,843, hit rate 13.52%; stealth≥2 N=2,024, hit rate **17.09%** — hit-rate delta **+3.58pp** (vs Development's +4.87pp). **MWU one-sided p=0.999660** (significant in the *opposite* direction); Cliff's δ=**-0.0439** (sign flipped from Development's +0.0747). Decile breakdown: stealth≥2 is *worse* than baseline from the 10th through 50th percentile (median -0.59% vs -0.22%) — the opposite shape from Development's broad lift.

**Era breakdown (secondary, not the primary verdict):** Validation alone: Cliff's δ=**+0.1007** (larger than Development, confirms). OOS alone: δ=**-0.1450** (reverses completely). The combined figure nets to reversal because OOS's effect outweighs Validation's.

**Classification: DEAD.** Per the task's own instruction not to soften a negative result: the pre-specified secondary/confirmatory tests (Cliff's delta, MWU) — the checks designated to establish whether an effect is real — reverse sign. Not carried forward to any live filter.

### (i) Market Structure Diagnostic — no microstructure break; clear macro regime break
*2026-07-10. Motivated directly by (f) and (h)'s shared OOS-reversal pattern.*

**No cross-sectional microstructure break:** VOLATILE-regime frequency, once the partial 2026 year is handled correctly, is comparable pre/post-2023 (2015-2022: 16.1%; 2023-2025 ex-partial-2026: 14.5% — actually slightly lower). Average pairwise correlation is *lower* in 2023-2025 (0.176) than 2015-2022 (0.224). Liquidity concentration (top-10 volume share) flat throughout (40.7%-46.8% band, 12 years). Sector concentration essentially flat (57.8%→57.4% annually-reranked top-5 share).

**Clear index-level regime break:** KSE-100 +53%/+78%/+49% in 2023/2024/2025 — a historic, sustained bull run vs. a choppy -16% to +44% range in 2015-2022 — externally corroborated (January 2023 PKR devaluation, IMF-program disinflation from 38%→11.8%). Daily volatility rose modestly (1.06%→1.17%); adverse-day frequency actually *fell* (15.6/yr→11.0/yr ex-2026). A separate, dated mechanical change: PSX's circuit breaker was widened to ±10% via a gradual SECP-approved process, May–July 2024.

**Synthesis:** not a case of "everything about PSX changed" — the cross-sectional structure factor tests depend on is stable; what broke is the index-level trend regime, plus a mechanical daily-price-band change. Diagnostic only — does not establish causality with (f)/(h)'s reversals.

### (j) Regime-conditional re-test — Phase 6 / Section 13 — Stealth RS recovers outside "runaway bull," exploratory only
*2026-07-10. No held-out data remains — both Development and Validation+OOS already spent on these constructs this session.*

**RUNAWAY_BULL_THRESHOLD** derived from 2015-2022 only (90th percentile of trailing-252d KSE-100 return): **+36.7447%**. Sanity check: 2015-2022 average runaway-bull-day share 5.8%; 2023-2025 (ex-partial-2026) **51.0%** — ~9x concentration, not built to force this outcome.

**Exact results, all 6 cells (full 2015-2026):**

| Cell | N (hi/lo) | Hit-rate Δ | Cliff's δ | MWU 1-sided p |
|---|---|---|---|---|
| Stealth RS≥2 — runaway bull | 512/63,012 | -3.55pp | **-0.2112** | 1.000000 |
| Stealth RS≥2 — non-runaway-bull | 2,540/191,843 | **+5.83pp** | **+0.0419** | **0.000140** |
| Tightness tight vs loose — runaway bull | 16,993/16,760 | -4.17pp | +0.0743 | 0.000000 |
| Tightness tight vs loose — non-runaway-bull | 52,179/51,395 | -6.80pp | -0.0778 | 1.000000 |
| ROC_10 fast vs slow — runaway bull | 16,936/16,937 | +6.55pp | -0.0119 | 0.971353 |
| ROC_10 fast vs slow — non-runaway-bull | 52,978/52,978 | +0.87pp | +0.0053 | 0.068349 |

**Classification: mixed — regime-conditioning recovers exactly one of three constructs.** Stealth RS shows the clean pattern (original effect intact outside runaway-bull, reversed inside it). Tightness does NOT recover (closed reversal is *stronger* outside runaway-bull, δ=-0.0778 vs the original -0.0387). ROC_10 shows no clear recovery either. **Not a general claim that the bull market explains all OOS reversals** — specific to Stealth RS, exploratory, non-independent (reuses already-spent data).

### (k) A1/A2 live fixes applied
*2026-07-10, following PI approval after (b)/(c)/(d).*

**Fix A1:** `leaders_scan.py::_raw_score()` — `rs_score_20`/`sector_rs_rank` blocks removed entirely (not zeroed), function dropped from 5→3 params, max raw score 15→**9**. `MIN_PICK_SCORE` re-derived proportionally: old 8/15=53.3% → 9×0.533=4.8 → **5**. Before/after on 2026-07-09 (31 candidates): old formula+threshold → **0** qualifying picks; new → **1** (`BREAKOUT, CNERGY`). Recomputed-old-formula sanity check matched the stored `raw_score` column exactly (0 mismatches, 31 rows) before the edit.

**Fix A2:** Explorer's Weinstein Watchlist toggle — `sector_rs_rank ≤ 5` condition removed from the 7-condition filter (now 6) and from its `sort_values()` call. `sec_global_rank ≤ 8` untouched. Before/after on 2026-07-09 (297-row universe): **0 → 0** (screen currently dormant on this date; fix is correct, will matter on a future date).

### (l) Regime-transition-age and regime-type test — S-005 — 🟡 MIXED / PARTIALLY CONFIRMED
*Filed 2026-07-10.*

**Hypothesis (operational, from a PI personal-journal observation — 242 discretionary trades, 20 months, journal figures +5.98% vs -1.08%):** trades taken 6+ days after a TRENDING_UP regime transition show better expectancy than 0-2 days after; VOLATILE regime is meaningfully worse than TRENDING_UP or RANGING.

**Test design:** `stock_signals` joined to `market_regime` (avg_vol_10d>200,000, N=296,010 valid `fwd_return_10d` rows, 99.5% of 297,640). `days_since_transition` recomputed independently from the raw regime label sequence (NOT from the stored `regime_days` column, confirmed ~2x inflated per CLAUDE.md). Transition-age population (TRENDING_UP only): **124,639 rows**. Same three-era boundaries and statistical battery as S-002/S-003.

**Exact result — transition-age, pooled:** 0-2 days N=20,090 mean +1.0726%; 6+ days N=91,018 mean +1.8296% — mean Δ **+0.7570pp**, MWU one-sided p<0.000001, Cliff's δ=**0.0466** (negligible by convention).

**Era breakdown:** Development N=6,024/25,047, mean Δ **-2.2021pp**, one-sided p=**1.000000 (fails)**, δ=**-0.1286 (reversed)** — the *largest*-magnitude effect of the three eras, running opposite to the journal. Validation Δ=+2.5179pp, δ=+0.1687 (confirms). OOS Δ=+1.6612pp, δ=+0.0912 (confirms).

**Classification (transition-age): MIXED.** Not confirmed (reverses in Development, larger magnitude than either confirming era); not dead (Validation and OOS — including the most recent regime — both confirm). Not recommended as a trading rule.

**Exact result — regime-type, pooled (N=296,010):** TRENDING_UP mean +1.7285%; RANGING -0.2472%; VOLATILE +0.2477%; TRENDING_DOWN +0.5425%. TRENDING_UP vs VOLATILE: Δ=+1.4808pp, one-sided p<0.000001, Cliff's δ=**0.0537** — **confirmed**. VOLATILE vs RANGING: mean Δ (RANGING−VOLATILE)=**-0.4949pp**, one-sided (RANGING>VOLATILE) p=**1.000000 (fails)**, δ=**-0.0511** — **reversed** in the pooled test, but era breakdown shows VOLATILE ahead of RANGING in Development (near-tie) and Validation, RANGING ahead in OOS — itself era-inconsistent.

**Classification (regime-type): PARTIALLY CONFIRMED, PARTIALLY MIXED.** "VOLATILE worse than TRENDING_UP" confirmed, all 3 eras. "VOLATILE worse than RANGING" — neither direction is a stable, era-independent effect; do not treat "VOLATILE is the regime to avoid" as validated on the RANGING comparison specifically.

---

## 3. Methodology Principles Demonstrated

- **Three-era design (Development/Validation/OOS) catching pooled-vs-era artifacts.** S-005's transition-age test: pooled Cliff's δ=+0.0466 (apparently confirms the journal) conceals a Development-era reversal (δ=-0.1286, *larger* magnitude than either confirming era) — the pooled figure is Validation+OOS's combined N outweighing Development's opposite sign, not a stable effect. Same mechanism in today's regime test's VOLATILE-vs-RANGING comparison (§2l): pooled reversal (δ=-0.0511) itself dissolves into era disagreement once broken out.
- **Bonferroni correction for multi-test families.** Phase 4c (§2f): a structural finding (vol_multiplier's 2.0x ceiling is mathematically unreachable) shrank the real test family from a naively-counted 6 to 4, changing the correction from α=0.05/6 to the correct α=0.05/4=0.0125 — applied *before* reporting which tests "survive," not retrofitted.
- **Right-tail hit-rate vs mean/Cliff's-delta divergence as an overfitting detector.** Phase 4c's combined ROC10+volume test (§2f): the *largest* raw mean delta in the whole study (+0.928pp/+1.180pp OOS) coexists with a negative Cliff's delta and p≈0.93–0.999 rank test — flagging outlier-driven mean inflation, not genuine central-tendency effect. Section 12.8's confirmatory Stealth RS result (§2h): hit-rate lift remains nominally significant (proportion z-test p=0.000002) while Cliff's delta reverses (-0.0439) — because the confirmatory data's *median/bulk* is worse than baseline even as tail-crossing is more frequent, the opposite distributional shape from Development.
- **Locked, one-shot confirmatory testing preventing post-hoc threshold adjustment.** Section 12.8–12.13 (§2h): adverse threshold, window, and comparison groups copied verbatim from the exploratory pass; the result (DEAD) was reported as-is per explicit instruction not to soften a negative outcome, rather than re-cut the threshold after seeing an unfavorable result.
- **Construct-revision discipline preventing premature construct testing.** `BREAKOUT_Specification_v1.0.md`'s own status conventions (Supersedes/Status fields, Section 6: "H-001 through H-008... do not transfer automatically to BREAKOUT V2... and should not be cited as evidence for or against V2 factors without a fresh test against the V1.0-conformant population") — the reason S-002 re-ran RS-rank against the corrected BREAKOUT V2 population from scratch rather than reusing any BREAKOUT V1-era figure, and the reason the cited -0.20%/+2.07% baseline, once found unverifiable, was not simply assumed true.
- **Self-caught validator bugs before reporting findings.** PRE_BREAKOUT population rebuild (§2e): an initial gap-blind `already_broken` derivation produced 91 mismatches; found, diagnosed (gap-blind incremental walk misattributing state), and fixed by recomputing from full continuous price history before any hypothesis was tested. A second issue (602 apparent mismatches, a NaN-vs-None comparison artifact) was also found and corrected in the same pass. Final validation (0/291,674 mismatches) preceded, not followed, the tightness test.
- **Distinguishing genuinely different constructs sharing similar names.** S-004 (§2d): `sec_global_rank` (sector-vs-market, `sector_signals.rs_rank`) and `sector_rs_rank` (stock-vs-sector-peers, `stock_signals.sector_rs_rank`) are traced to their exact SQL definitions and confirmed as different fields, ranking different entities, against different comparison sets — preventing A1/A2's dead verdicts from being incorrectly applied to the separately-validated `sec_global_rank ≤ 8` gate.

---

## 4. Final State Table

| Construct/Field | Status | Evidence doc reference | Live system status |
|---|---|---|---|
| `sec_global_rank ≤ 8` (sector-vs-market gate) | CONFIRMED-LIVE | S-004 §4; `weinstein_combined_backtest.py` | Deployed — Weinstein Watchlist toggle, combined backtest base gate |
| `rs_score_20`/`sector_rs_rank` as post-breakout quality scoring | DEAD | S-002 | Removed — `leaders_scan.py::_raw_score()` (Fix A1) |
| `sector_rs_rank ≤ 5` as standalone pre-screen | DEAD (reversed) | S-003 | Removed — Weinstein Watchlist filter (Fix A2) |
| Tightness (`pct_rank_252`/`756`, `zscore_252`), standalone | DEAD (reversed) | PRE_BREAKOUT §5 | Not applicable — never live |
| Tightness, sector-conditioned (`sec_global_rank≤8`) | DEAD (reversed, weakened) | PRE_BREAKOUT §10 | Not applicable — never live |
| ROC-5/ROC-10 velocity + `vol_multiplier` | MIXED, no survivor | PRE_BREAKOUT §11 | Not applicable — never live |
| Stealth RS ≥2, unconditional | DEAD (confirmatory) | PRE_BREAKOUT §12.8–12.13 | Watch-only dashboard toggle (not a validated screener) |
| Stealth RS ≥2, conditioned on non-"runaway bull" | EXPLORATORY | PRE_BREAKOUT §13 | Not applicable — awaiting fresh-data re-test |
| Regime-transition-age (0-2 vs 6+ days, TRENDING_UP) | MIXED, era-inconsistent | S-005 §3–5 | Not applicable — not a trading rule |
| Regime-type: TRENDING_UP > VOLATILE | CONFIRMED | S-005 §6–7 | Not applicable — descriptive only, not a filter |
| Regime-type: VOLATILE vs RANGING | MIXED, era-inconsistent | S-005 §6–7 | Not applicable |
| PSX cross-sectional microstructure (correlation/dispersion/liquidity/sector concentration) | STABLE, no break | Market_Structure_Diagnostic_2015-2026.md | Diagnostic context only |
| KSE-100 index-level trend regime | CONFIRMED BREAK (2023-2025 bull market) | Market_Structure_Diagnostic_2015-2026.md | Diagnostic context only |

---

## 5. Open Items for Future Sessions

- **Stealth RS re-confirmation** once genuinely new post-2026-07 data accrues (PI target: **year-end**) — tested once, not iteratively, per PRE_BREAKOUT Section 13.4/Session Summary.
- **H-006 (Sector Breadth Participation)** — still **Parked** (Development result confounded/concentrated in 2 of 5 sectors — Commercial Banks δ=0.2162, Textile Composite δ=0.2589 — not advanced to Validation; may be revisited as a narrower, sector-specific hypothesis if PI chooses).
- **H-008 (Gap-at-Breakout)** — still **BLOCKED**, pending both: (a) Phase 5 corporate-action adjustment of `prices_adjusted.open` (currently NULL, not yet re-run through `apply_price_adjustments.py`), and (b) a reconstruction/look-ahead audit of `prices_adjusted.open` comparable in rigor to EXP-0002's standard.
- **Sector BBW%** — still idea-stage, not yet formally scoped or registered.
- **Index-level active-resistance thesis** — still parked, not yet formally scoped or registered.
- **S-004's open gap** — the dashboard's cited "+1.14% EV" marginal-contribution figure and its 5/8/12/no-gate sweep table remain unreproduced from any script in the repo; does not call the confirmed +10.50% figure into question, but the sweep table itself is unverified prose.
- **PRE_BREAKOUT Section 10.8 (Path B)** — trend/EMA-stack conditioning of tightness, PI-deferred, not yet run; if ever executed, requires an explicit multiple-comparison disclosure covering all three tightness-conditioning passes together (standalone, sector-conditioned, trend-conditioned), not a fresh isolated test.
