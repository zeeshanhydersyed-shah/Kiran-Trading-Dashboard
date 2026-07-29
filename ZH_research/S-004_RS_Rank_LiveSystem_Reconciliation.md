# S-004 — RS-Rank Live-System Reconciliation (A1/A2 Closure + `sec_global_rank` vs `sector_rs_rank`)

**Status:** REFERENCE DOCUMENT — not a new hypothesis test, no verdict of its own
**Filed:** 2026-07-09
**Researcher:** Quantitative Analyst
**Reviewer:** Independent Quantitative Reviewer (PI)
**Scope:** Consolidates the A1/A2 live-system audit findings, reconciles the `sec_global_rank` vs `sector_rs_rank` field confusion surfaced during that work, and records current implementation status. No new analysis performed here.

---

## 1. A1 — post-breakout quality scoring (dead)

Audit finding A1: `rs_score_20` and `sector_rs_rank` are used as weighted components inside `leaders_scan.py::_raw_score()`, a 5-factor "conviction score" applied to candidates *after* BREAKOUT/PRE_BREAKOUT selection, feeding `final_score` which drives sort order and pick selection across the Leaders page (Watchlist, Deep Scan, Radar tabs). Tested in **S-002**: on the corrected BREAKOUT V2 population (`stock_signals_breakout_v2_staging_full` WHERE `breakout_event=1`), neither `rs_score_20` nor `sector_rs_rank` showed a statistically significant relationship with `fwd_return_10d` (Mann-Whitney U p=0.58–0.71, negligible Cliff's delta in both variables). Classified **DEAD**. Full detail: [S-002_RS_Rank_Quartile_BREAKOUT_V2.md](S-002_RS_Rank_Quartile_BREAKOUT_V2.md).

## 2. A2 — pre-screen filter (dead, reversed)

Audit finding A2: the Explorer page's "Weinstein Watchlist" toggle applies `sector_rs_rank ≤ 5` as one of seven simultaneous AND conditions, narrowing the full stock universe independent of any breakout/pre-breakout status. Tested in **S-003**: on a population of 296,010 rows (liquid `stock_signals` rows, not conditioned on `bos_flag`/`active_resistance`/`breakout_event`), `sector_rs_rank ≤ 5` showed a small but statistically significant *negative* mean-return delta (-0.33pp) versus `sector_rs_rank > 5`, consistent in direction across the full population and all three eras (Development, Validation, OOS), with no threshold effect visible in the per-rank breakdown. Classified **DEAD — reversed direction** (effect size negligible, Cliff's δ ≈ -0.03, but never once in the hypothesized direction). Full detail: [S-003_Sector_RS_Rank_PreScreen.md](S-003_Sector_RS_Rank_PreScreen.md).

---

## 3. Field reconciliation — `sec_global_rank` is NOT `sector_rs_rank`

Both A1 and A2's dead verdicts apply specifically to `stock_signals.rs_score_20` and `stock_signals.sector_rs_rank`. A separate field, `sec_global_rank`, shares a superficial naming resemblance and appears in the same live filters (Explorer's Weinstein Watchlist uses `sec_global_rank ≤ 8` alongside `sector_rs_rank ≤ 5`) — a follow-up trace confirmed these are genuinely different constructs, not the same field under two names.

**`sec_global_rank` is a SQL alias, not an independently computed field:**

```sql
sec.rs_rank AS sec_global_rank
```

— identical wherever it appears (`dashboard.py:1716`, `dashboard_pg.py:545`, `weinstein_combined_backtest.py:42`, `screener_audit.py:90`, `backtest_rs_score.py:18`). It resolves to `sector_signals.rs_rank`.

**Computation** (`sector_signals.py:341-343`):

```python
valid_sectors = {s: v for s, v in sector_rs_scores.items() if not np.isnan(v["rs_score_20"])}
ranked = sorted(valid_sectors, key=lambda s: valid_sectors[s]["rs_score_20"], reverse=True)
ranks  = {s: i + 1 for i, s in enumerate(ranked)}
```

This ranks all ~23 sectors **against each other, market-wide**, by each sector's own market-cap-weighted 20-day return minus KSE-100's 20-day return (`sector_signals.py:305-311`). Rank 1 = strongest sector vs. the index.

**By contrast, `stock_signals.sector_rs_rank`** ranks individual **stocks against other stocks within their own single sector** — a different table, a different entity being ranked, a different question ("which sector is winning market-wide" vs. "which stock is winning within its sector").

| | `sec_global_rank` (= `sector_signals.rs_rank`) | `sector_rs_rank` (`stock_signals`) |
|---|---|---|
| Entity ranked | Sector | Stock |
| Ranked against | All other sectors, market-wide | Other stocks in the same sector only |
| Basis | Sector's own `rs_score_20` vs. KSE-100 | (computed in `stock_signals.py`, not re-derived here — out of scope for this reconciliation) |
| Tested by A1/A2? | **No** | Yes — both A1 (S-002) and A2 (S-003) |

---

## 4. `sec_global_rank ≤ 8` and its +10.50% EV backtest — CONFIRMED UNAFFECTED

`weinstein_combined_backtest.py` uses `sec_global_rank ≤ 8` (line 182: `ss['sec_global_rank'].fillna(999) <= 8`) as the base sector condition in its combined-gate backtest, producing the dashboard-cited result (N=1,021 streaks, WR=43.5%, LR=35.7%, EV@90d=+10.50%, 92/yr — `dashboard.py` lines 3207-3210).

Because `sec_global_rank` is confirmed (Section 3) to be a different field from both `sector_rs_rank` and `rs_score_20` — the two fields A1/A2 tested and found dead — **this gate and its backtest result are unaffected by the A1/A2 dead verdicts.** Different field, different question (sector-vs-market strength, not stock-vs-sector-peers or post-breakout quality scoring), separately validated by its own backtest. It remains, as of this document, a live, trusted gate — no action follows from A1/A2 regarding `sec_global_rank ≤ 8`.

---

## 5. Open gap — the +1.14% EV sweep is not reproducible from any script in the repo

Flagged during the trace, **not resolved here**: the dashboard's cited "+1.14% EV" marginal contribution of the `sec_rank ≤ 8` gate, and its accompanying cutoff-sweep table (`sec_rank ≤ 5` → +7.89%, `≤8` → +8.41%, `≤12` → +7.31%, no gate → +7.27%; `dashboard.py` lines ~3166, 3185-3212), exist **only as prose** in `dashboard.py`'s help-text expander. A full-repo search for the exact figures (`8.41`, `7.89`, `7.27`, `1.14`) found no other `.py` or `.md` file containing them. `weinstein_combined_backtest.py` tests only the fixed `≤8` cutoff — it does not sweep 5/8/12/none, so it is not the source of this specific table.

This is an open item for future reference. It does not block or call into question the `+10.50%` combined-EV figure (Section 4), which *is* independently reproducible from `weinstein_combined_backtest.py` as it exists today.

---

## 6. Current implementation status — NOT YET IMPLEMENTED

Per PI instruction, all live-system changes stemming from A1/A2 are **held pending further review**. As of this document's filing date:
- `leaders_scan.py::_raw_score()` — unchanged, live, still weights `rs_score_20`/`sector_rs_rank` as described in S-002.
- Explorer page's Weinstein Watchlist toggle — unchanged, live, still applies `sector_rs_rank ≤ 5` as described in S-003.
- `sec_global_rank ≤ 8` (Weinstein Watchlist condition, and `weinstein_combined_backtest.py`'s base gate) — unchanged, live, unaffected per Section 4.

No code was modified in the production of S-002, S-003, or this document.
