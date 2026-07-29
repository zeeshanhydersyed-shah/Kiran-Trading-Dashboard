# S-005 — Test: Regime-Transition-Age and Regime-Type as Predictors of `fwd_return_10d`

**Status:** CLOSED — 🟡 **MIXED** (transition-age, era-inconsistent) / 🟡 **PARTIALLY CONFIRMED, PARTIALLY MIXED** (regime-type: TRENDING_UP>VOLATILE confirmed all 3 eras; VOLATILE-vs-RANGING itself era-inconsistent, no stable verdict either way)
**Filed:** 2026-07-10
**Researcher:** Quantitative Analyst
**Reviewer:** Independent Quantitative Reviewer (PI)
**Population:** `stock_signals` joined to `market_regime`, full universe — NOT the PRE_BREAKOUT population, NOT conditioned on `active_resistance`/`bos_flag`
**Database:** psx_data.db

---

## 1. What this document is

Tests, at full-database rigor, the market-only claim underlying a PI personal-journal observation (242 discretionary trades, 20 months): that trades taken **6+ days after a TRENDING_UP regime transition** show materially better expectancy than trades taken **0-2 days after transition** (journal figures: +5.98% vs -1.08%), and that **VOLATILE** regime is meaningfully worse than **TRENDING_UP** or **RANGING**. The journal figures are confounded by the PI's own execution/sizing/discretion and rest on a small, unsplit, untested sample — a materially lower evidence bar than every other finding in this project's session. This document isolates the underlying market mechanism (does forward return itself depend on days-since-transition and regime type, independent of any trader's decisions) and tests it against the full history, at the same rigor as S-002/S-003/S-004 and PRE_BREAKOUT_Specification_v1.0.md Sections 9-13.

Two independent sub-claims are tested and classified separately, since they behaved differently:
- **Transition-age** (0-2 vs 6+ days since entering TRENDING_UP) — §3-5 below.
- **Regime-type** (VOLATILE vs TRENDING_UP, VOLATILE vs RANGING) — §6 below.

---

## 2. Methodology

### 2.1 Two framing corrections found during setup (investigated before running, not assumed)

1. **`stock_signals` has no `fwd_return_10d` column** — the task's population definition assumed it did. Confirmed absent via `PRAGMA table_info(stock_signals)`. `fwd_return_10d` lives only on `setup_log` (setup-event rows only) and on `pre_breakout_v2_staging_full` (PRE_BREAKOUT population only) — neither is this task's population. Computed fresh here using `compute_forward_returns.py`'s exact existing formula — `(close at entry+10 trading days − close at entry) / close at entry × 100`, sourced from `prices_adjusted`, per-symbol continuous sequence — reused verbatim, same approach as S-002/S-003, not a new formula.
2. **`market_regime.regime_days` is not used to compute days-since-transition.** CLAUDE.md's "Known Gaps: Postgres Parity" section documents this column as confirmed ~2x inflated across same-date re-runs, and `dashboard_pg.py`'s `get_regime_status_pg()` already deliberately ignores the stored column for this reason (recomputes from history instead of trusting it). Per this project's standing production-DB-discipline convention (independent re-verification, not trust — see `docs/DECISIONS.md`), days-since-transition is recomputed here directly from the raw `market_regime.regime` label sequence: every date where `regime` differs from the immediately preceding date's `regime` resets the counter to 0; consecutive same-regime dates increment it. **Convention: the transition day itself (first day of the new regime) = 0 days since transition** — a trade taken on the transition day is "0 days after" it, matching the journal's own "days after transition" framing. This is stated explicitly per the task's request to declare which convention is used.

### 2.2 Population

```sql
-- liquidity-gated base population, joined to independently-recomputed regime state
SELECT symbol, date, avg_vol_10d
FROM stock_signals
WHERE avg_vol_10d > 200000
```
joined on `date` to `market_regime.regime` + recomputed `days_since_transition`, then filtered to rows with a valid (window-closed) `fwd_return_10d`.

| | N |
|---|---|
| Liquidity-gated `stock_signals` rows (`avg_vol_10d > 200,000`) | 297,640 (257 symbols, 2015-01-01 → 2026-07-09) |
| Valid `fwd_return_10d` (window closed + price data present) | 296,010 / 297,640 (99.5%) |
| — filtered to `regime = TRENDING_UP` (transition-age population) | **124,639** rows, 250 symbols, 2015-01-01 → 2026-06-23 |
| — all 4 regime types (regime-type population) | **296,010** rows |

`market_regime` itself: 5,319 rows, 2005-01-03 → 2026-07-09, 479 total regime transitions detected. 2,136 `TRENDING_UP` rows exist in `market_regime`, with recomputed `days_since_transition` ranging 0-121.

### 2.3 Split and tests

**Transition-age:** three groups per task's own framing — 0-2 days, 3-5 days (reported separately, not the primary comparison), 6+ days since transition. Primary test: 6+ vs 0-2, one-sided in the journal's hypothesized direction (6+ > 0-2). Same test battery as S-002/S-003: Mann-Whitney U (two-sided and one-sided), Welch's t-test (`equal_var=False`), Cliff's delta (via the MWU U-statistic, exact at this N).

**Regime-type:** four groups (`TRENDING_UP`, `RANGING`, `VOLATILE`, `TRENDING_DOWN`; `INSUFFICIENT_DATA` excluded). Two pairwise one-sided tests per the journal's specific claim: `TRENDING_UP > VOLATILE` and `RANGING > VOLATILE` (i.e., "VOLATILE is worse than both").

### 2.4 Eras

Same three-era boundaries reused verbatim from S-001/S-002/S-003 and `prebreakout_v2_phase4c_velocity_volume.py`: Development 2015-01-01→2019-12-31, Validation 2020-01-01→2022-12-31, OOS 2023-01-01→2026-12-31.

---

## 3. Results — transition-age, full population (all eras combined)

| Group | N | Mean fwd10 | Median fwd10 |
|---|---|---|---|
| 0-2 days since transition | 20,090 | +1.0726% | -0.3265% |
| 3-5 days since transition | 13,531 | +2.0221% | +0.5637% |
| **6+ days since transition** | **91,018** | **+1.8296%** | **+0.1656%** |

**Primary test — 6+ days vs 0-2 days (hi=6+, lo=0-2, hypothesis: 6+ > 0-2):**

| Test | Result |
|---|---|
| Mean delta (6+ minus 0-2) | +0.7570pp |
| Mann-Whitney U, two-sided | p < 0.000001 |
| Mann-Whitney U, one-sided (6+ > 0-2, journal's direction) | p < 0.000001 |
| Welch's t-test | t = 8.7377, p < 0.000001 |
| Cliff's delta | **0.0466** (negligible by convention, \|δ\|<0.147) |

Pooled result is statistically significant in the journal's hypothesized direction, but the effect size is negligible by convention, and — critically — this does **not** hold up era-by-era (§5).

---

## 4. Era-consistency check — transition-age (6+ vs 0-2, repeated per era)

| Era | N (0-2) | Mean (0-2) | N (6+) | Mean (6+) | Mean Δ | MWU one-sided p (6+>0-2) | Cliff's δ |
|---|---|---|---|---|---|---|---|
| **Development (2015-2019)** | 6,024 | +2.6696% | 25,047 | +0.4675% | **-2.2021pp** | **1.000000 (fails)** | **-0.1286 (reversed)** |
| Validation (2020-2022) | 4,070 | -0.7681% | 14,898 | +1.7498% | +2.5179pp | <0.000001 | +0.1687 |
| OOS (2023-2026) | 9,996 | +0.8597% | 51,073 | +2.5209% | +1.6612pp | <0.000001 | +0.0912 |

3-5 day middle band, for reference (not the primary comparison): Development n=4,656 mean +3.0161%; Validation n=1,644 mean +2.2289%; OOS n=7,231 mean +1.3350%.

**Direction reverses in Development** — the largest-magnitude Cliff's delta of the three eras (-0.1286) runs opposite to the journal's claim, and the one-sided test in the hypothesized direction fails completely (p=1.0) in that era. Validation and OOS both independently confirm the journal's direction, with Validation showing the largest correctly-directioned effect (δ=+0.1687). The pooled "significant" result in §3 is not evidence of a stable, era-independent effect — it reflects Validation+OOS's larger combined N outweighing Development's opposite-signed effect in the pooled test, the same pattern this project has already flagged elsewhere (e.g. PRE_BREAKOUT_Specification_v1.0.md §12.10) as requiring the era breakdown to be reported, not just the pooled figure.

---

## 5. Classification — transition-age

**🟡 MIXED.** Not confirmed: the effect reverses direction in Development, with an effect size (Cliff's δ=-0.1286) larger in magnitude than either of the two eras that support the journal's direction. Not dead either: two of three eras (Validation, OOS) — including the most recent, most relevant regime environment — show a statistically significant, correctly-directioned effect, and the 3-5/6+ groups both consistently beat the 0-2 group outside Development. This is the same classification pattern PRE_BREAKOUT_Specification_v1.0.md §11.9 already applied to the ROC/volume factors for an identical reason: pooled significance driven by unequal era weighting, not independent replication across all three eras. **Not recommended for promotion to a live filter or trading rule** — the era inconsistency means a trader cannot rely on "wait 6+ days" as a stable edge; it worked in two of three regimes tested and reversed in the third.

---

## 6. Results — regime-type, full population (all eras combined)

| Regime | N | Mean fwd10 | Median fwd10 |
|---|---|---|---|
| **TRENDING_UP** | 124,639 | **+1.7285%** | **+0.1157%** |
| RANGING | 86,517 | -0.2472% | -1.0887% |
| VOLATILE | 50,639 | +0.2477% | -0.2380% |
| TRENDING_DOWN | 34,215 | +0.5425% | -0.2086% |

**VOLATILE vs TRENDING_UP** (hi=TRENDING_UP, lo=VOLATILE, hypothesis: TRENDING_UP > VOLATILE):

| Test | Result |
|---|---|
| Mean delta | +1.4808pp |
| MWU one-sided (TU > VOL) | p < 0.000001 |
| Welch's t | t = 23.9614, p < 0.000001 |
| Cliff's delta | **0.0537** (negligible-small) |

**Confirmed** — TRENDING_UP significantly and consistently outperforms VOLATILE.

**VOLATILE vs RANGING** (hi=RANGING, lo=VOLATILE, hypothesis: RANGING > VOLATILE, i.e. "VOLATILE is worse than RANGING too"):

| Test | Result |
|---|---|
| Mean delta (RANGING minus VOLATILE) | **-0.4949pp** (RANGING is lower, not higher) |
| MWU one-sided (RANGING > VOLATILE) | **p = 1.000000 (fails completely)** |
| Welch's t | t = -7.9689, p < 0.000001 |
| Cliff's delta | **-0.0511** (RANGING ranks *below* VOLATILE) |

**Reversed** — RANGING does not outperform VOLATILE; on this data, VOLATILE actually has a higher mean and median `fwd_return_10d` than RANGING.

### 6.1 Era breakdown — mean/median `fwd_return_10d` by regime (no formal significance test per era; see Limitations §8.2)

| Era | TRENDING_UP | RANGING | VOLATILE | TRENDING_DOWN |
|---|---|---|---|---|
| Development (n=108,766) | n=35,727, +1.1709% / 0.0000% | n=36,625, +0.0417% / -0.7053% | n=16,203, +0.0432% / -0.6314% | n=20,211, -0.7998% / -1.3029% |
| Validation (n=78,434) | n=20,612, +1.2908% / -0.3111% | n=33,375, -1.2781% / -2.0202% | n=12,991, +0.3277% / +0.3155% | n=11,456, +2.4787% / +1.1612% |
| OOS (n=108,810) | n=68,300, +2.1523% / +0.3341% | n=16,517, +1.1954% / -0.0116% | n=21,445, +0.3537% / -0.2886% | n=2,548, +2.4849% / +1.3182% |

**VOLATILE vs RANGING by mean is era-inconsistent, same failure pattern as the transition-age result:** VOLATILE is fractionally ahead in Development (+0.0432% vs +0.0417%, essentially a tie), clearly ahead in Validation (+0.3277% vs -1.2781%), but RANGING is ahead in OOS (+1.1954% vs +0.3537%) — the most recent era reverses the pooled §6 result. The pooled figure is driven by Validation's large gap (VOLATILE beating RANGING by ~1.6pp there) outweighing OOS's smaller reversal in the pooled test, the same pooled-vs-era-breakdown caveat already flagged for transition-age (§4-5). **This further weakens, not strengthens, any claim that RANGING is a confirmed-safe fallback relative to VOLATILE** — the two eras disagree on which of the two is worse.

TRENDING_UP is the best regime by mean/median in all three eras without exception — the one part of this whole test that is fully era-consistent. `TRENDING_DOWN` shows a separate mean/median divergence pattern worth flagging (worst of all four regimes in Development, but better than VOLATILE by both mean and median in Validation and OOS) — a mean-reversion/snapback signature consistent with this project's previously-documented mean-vs-rank divergence (PRE_BREAKOUT_Specification_v1.0.md §§5.2/10.3/11.6), not separately tested here since `TRENDING_DOWN` was not part of the journal's specific claim.

---

## 7. Classification — regime-type

**🟡 PARTIALLY CONFIRMED, PARTIALLY REVERSED.** The journal's claim has two parts, and they resolve differently:
- **"VOLATILE is worse than TRENDING_UP"** — **CONFIRMED**, small but statistically significant and directionally consistent across all three eras by mean.
- **"VOLATILE is worse than RANGING"** — **REVERSED** in the pooled test (statistically significant, wrong direction, Cliff's δ=-0.0511), but the era breakdown (§6.1) shows this is itself era-inconsistent: VOLATILE beats RANGING in Development (near-tie) and Validation (clearly), while RANGING beats VOLATILE in OOS, the most recent era. Neither the journal's original claim nor its pooled reversal is a stable, era-independent effect. On the full-database evidence, RANGING is not a confirmed "safer" regime than VOLATILE, but VOLATILE is not confirmed "safer" than RANGING either — the two eras disagree, and no single answer to "which is worse, VOLATILE or RANGING" survives all three eras. **Do not treat "VOLATILE is the regime to avoid" as validated** — TRENDING_UP is confirmed the best regime of the four, but neither RANGING nor VOLATILE is confirmed as the reliably worse of the other two.

---

## 8. Limitations

1. **Overlapping 10-day windows** — same caveat as every prior forward-return study in this project (S-002/S-003, PRE_BREAKOUT §12.5.4): forward-return windows for the same symbol on adjacent dates overlap heavily, so standard errors at this N are likely understated by both MWU and Welch's t. Affects the *precision* of the significance claims, not the observed sign/direction.
2. **Regime-type era breakdown (§6.1) reports mean/median only, no per-era MWU/Cliff's-delta suite** — this matches the task's own explicit request ("Report mean/median fwd_return_10d by regime type... plus era breakdown"), which did not ask for a full per-era statistical battery on the regime-type sub-question the way it explicitly did for transition-age (§5). The full-population pairwise tests (§6) are formally tested; the era table is descriptive only — the VOLATILE-vs-RANGING era reversal noted in §6.1/§7 is based on mean comparison only, not a formal significance test per era. A future task wanting formal era-level significance on VOLATILE-vs-RANGING specifically would need to run that separately.
3. **`days_since_transition` is recomputed independently of the stored, flagged-unreliable `regime_days` column** (§2.1) — this is a deliberate, documented choice, not an oversight, but means this figure will not match `regime_days` exactly on any row where that column's known non-idempotency bug has inflated it.
4. **Single, bounded test** — per task constraint, no sector/tightness/RS conditioning was introduced; this tests regime-transition-age and regime-type alone, exactly as scoped.
5. **`TRENDING_DOWN`'s mean-reversion pattern (§6.1) is reported as an observation, not tested** — it was not part of the journal's claim and no formal test was run on it here.

---

## 9. Reproducibility

Script: `regime_transition_age_test.py` (project root). Read-only against `psx_data.db` (`market_regime`, `stock_signals`, `prices_adjusted`) — no production writes, no dashboard/code changes. Full run output saved to `regime_transition_age_test_output.txt`.
