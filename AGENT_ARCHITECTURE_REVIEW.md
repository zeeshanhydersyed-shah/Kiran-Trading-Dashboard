# Kiran Trading Desk Agent — Architecture Review
**Date:** 2026-06-04  
**Files reviewed:** `agent.py`, `agent_db.py`, `agent_benchmark.py`, `agent_learn.py`  
**Scope:** Contradictions, logic gaps, intentionality, evolutionary design, recommendations

---

## 1. Contradictions

### 1.1 Two grading functions with different win criteria (Unintentional)

There are two separate functions that evaluate whether an agent opportunity was a Win or a Loss, and they use different rules.

`grade_opportunities()` in `agent_learn.py` (the weekly learning loop) checks whether the **daily HIGH crossed Target 1R** for a Win. `evaluate_skipped_opportunities()` in `agent_db.py` (called during every daily run) checks whether the **daily CLOSE crossed Target 2R** for a Win. The first function uses intraday high/low for realistic touch detection; the second uses closing prices only. The first targets T1; the second targets T2.

This means the same opportunity evaluated on a Tuesday by the daily run will reach a different Win/Loss verdict than the one written by the weekly grading loop on Sunday. Whichever runs second silently overwrites the first. Pattern statistics — which drive future screening — are poisoned by whichever verdict happened to win the race.

**Why it appears unintentional:** The two functions were clearly built at different times. `evaluate_skipped_opportunities()` was the earlier, simpler version. `grade_opportunities()` is the more sophisticated replacement, but neither was retired.

---

### 1.2 Performance summary query uses Outcome values as Status values (Unintentional bug)

`get_agent_performance_summary()` in `agent_db.py` filters with:

```
WHERE status IN ('Win','Loss','Breakeven','Pending','Taken')
```

But the valid status values are `Pending`, `Taken`, `Skipped`, and `Expired`. The values `'Win'`, `'Loss'`, and `'Breakeven'` are **outcome** column values, not status values. No row will ever have `status = 'Win'`.

The practical effect is that every opportunity graded to `status = 'Expired'` (the most common final state, set by the learning loop) is excluded from this summary entirely. The "pending" count is the only number this query can correctly return. Every other metric on the agent performance widget is likely zero or misleading.

---

### 1.3 Regime decay and the learning loop both consume the same Pending pool (Unintentional)

`apply_regime_decay()` converts hostile-regime Pending opportunities to `status='Closed', outcome='Regime Decay'`. `grade_opportunities()` looks for `status='Pending'` opportunities older than 5 days and grades them to Win/Loss/Expired.

Both run on overlapping records. If regime decay fires first (it runs at the start of every daily run), the weekly grader never sees those records — they are already Closed. The result is that stocks which were blocked by a bad regime but would have hit their targets anyway are permanently logged as `Regime Decay` rather than `Win`, making the regime gate look better than it actually is and suppressing the pattern win rate of setups flagged in ranging markets.

Conversely, if the grader runs first (on Sundays, before the Monday regime decay run), a stock gets a real Win/Loss outcome, and regime decay later never touches it. The outcome of each opportunity depends entirely on which day of the week it was old enough to process.

---

### 1.4 What-if return is identical to average agent return (Unintentional)

`get_inception_summary()` in `agent_benchmark.py` returns two fields intended to mean different things:

- `avg_agent_return` — average actual P&L across all closed opportunities  
- `what_if_return` — "average return if ALL suggestions had been taken"

Both are computed with the same line: `_avg(closed, "actual_pl_pct")`. They will always be equal. The `what_if` scenario is supposed to model hypothetical full participation, but it can only deliver meaningful insight if it reads `actual_pl_pct` from the `Skipped` pool as well, using the paper-graded outcomes. As written, it measures the same population twice.

---

### 1.5 Pattern confidence assignment happens twice with different thresholds (Partly intentional, partly problematic)

When `PatternAnalyzerAgent` runs, it asks Claude to assign a confidence of `High | Medium | Low` based on qualitative reasoning, and saves that directly to `agent_patterns`. When `update_pattern_stats()` runs weekly, it recomputes confidence from hard numeric thresholds: High requires ≥15 closed trades with ≥55% win rate; Medium requires ≥8 trades.

Claude might assign High confidence to a pattern with 4 samples on day one. The weekly recompute will downgrade it. But between those two events — potentially 7 days — the daily opportunity picker uses the inflated High confidence to prioritize that pattern. This is a bootstrapping compromise that is probably intentional but has no explicit acknowledgement in the code that the initial confidence is a soft placeholder.

---

## 2. Intentionality Assessment

**Clearly intentional design choices:**

The two-phase regime gate (Phase 1 blocks on bias/sizing; Phase 2 blocks on breadth exhaustion and rate-of-change) is a deliberate layered defense. The `prev_stage3_pct` lookup gracefully returns `None` if there are fewer than 7 days of history, and the gate silently skips the RoC check in that case. This is thoughtful degradation for a new system.

The use of Groq for chat and Claude only for agent runs is a deliberate cost control measure, explicitly documented. It is a reasonable trade-off.

The Hard Stage 3 exclusion from the long pool (code enforces, Claude cannot reason around it) is an intentional hard risk rule. The agent is designed so Claude cannot accidentally include a Stage 3 stock as a long no matter how compelling the reasoning sounds.

Reference breakout calibration — the concept of letting the user hand-label good setups and injecting those as structural examples — is a sophisticated intentional design to compensate for Claude's tendency to match statistics without understanding chart structure.

**Ambiguous choices:**

The learning loop's decision to set `status = 'Expired'` for all auto-graded opportunities regardless of outcome (line 172 in `agent_learn.py`) may be intentional to preserve the distinction between "agent suggested and user took" (Taken) vs "agent suggested but user didn't act" (Expired). The outcome column still records Win/Loss correctly. But this collapses an important distinction — was the Expired record a winning suggestion the user missed, or a paper loss? The performance summary query bug (§1.2) then compounds this by excluding all Expired records.

---

## 3. Logic Gaps and Deficiencies

### 3.1 No automated path to close Active agent opportunities

The agent creates opportunities with `status = 'Pending'`. The user can mark one as `Taken` via the dashboard. But once Taken (Active in the context of a live trade), there is no mechanism — automated or manual — that transitions it to `Closed` with a real exit price and P&L. The benchmark backfill (`backfill_all_benchmarks()`) only runs on records where `exit_date IS NOT NULL`, which a Taken opportunity will never have unless someone manually updates it via `update_opportunity_status()`. In practice, this means Taken trades likely sit in the DB permanently without real outcome data, making the benchmark comparisons and alpha calculations work only on the auto-graded Expired pool.

### 3.2 Chat emotion detection is wired up but never populated

`agent_chat_log` has an `emotions` field and `agent_trader_profile` has an `emotion_counts` field. The behavioral profile prompt explicitly describes "emotional signals detected" as part of its analysis. But `log_chat_message()` accepts an `emotions` parameter that callers must populate themselves — no NLP or sentiment detection runs anywhere in the codebase. Unless the dashboard or chat handler is running emotion classification on each message before calling `log_chat_message()`, this field will always be `[]` and the behavioral profile's emotion section will be based on nothing.

### 3.3 Phase 2 gate uses the filtered (after sector/volume exclusion) universe, not the full universe

The `universe_stage3_pct` is computed on `all_df` after it has already been filtered for volume (≥50,000 shares) and excluded sectors. This means the breadth exhaustion check is measuring "what percentage of tradeable liquid stocks are in Stage 3" — not "what percentage of the total PSX universe is in Stage 3." These are different numbers. The filtered universe skews toward larger, more liquid stocks, which tend to peak before the broader market. This likely makes the Phase 2 gate trigger earlier than it would on the full universe, which may be conservative (good) but is inconsistent with how regime breadth is calculated elsewhere (which uses the full dataset).

### 3.4 The RS calculation uses calendar days, consolidation streak uses trading bars

`kse_30d` (used for RS computation) is fetched as a 30-calendar-day lookback. The `consol_days` streak and 5-day range are computed on actual trading bars. On a week with two public holidays, these windows are measuring different durations of market activity, which will make RS appear slightly weaker than it is for stocks that moved on high-volume days near those holidays.

### 3.5 Pattern learning is weekly but opportunity scanning is daily

The daily run calls `_load_active_patterns()` to feed Claude's opportunity generation. But `update_pattern_stats()` only runs on Sundays via `agent_learn.py`. This means for the first 7 days of any new pattern the daily scanner is operating with either no pattern data (first run) or Claude's unvalidated initial assessment (see §1.5). The lag between pattern identification and pattern validation is one full week, which is long relative to the daily scanning cadence.

### 3.6 No conflict resolution when both regime gates fire on the same run

If Phase 1 blocks the run (cash bias), the function returns immediately. If Phase 1 passes but Phase 2 blocks (breadth exhaustion), the function returns a different blocked result. This is correct. However, neither blocked result writes to `agent_reports` with the block reason. The daily run saves a full JSON report to `agent_reports` via the orchestrator only when opportunities are returned. When the gate fires, `TradingDeskAgent.run()` calls `OpportunityGenerator.run()` which returns `regime_blocked=True` — but the orchestrator still proceeds to synthesis and saves the report. What gets saved is a narrative that says "no opportunities" without the full gate reasoning being prominent in the stored raw JSON. The `regime_warning` field captures the reason, but it is one field in a larger JSON blob and is not surfaced in the daily narrative unless the synthesis prompt happens to include it (it does include `opp_text`, but `regime_warning` is not explicitly in `synth_prompt`).

---

## 4. Evolutionary Design Assessment

The system is clearly a foundation designed to improve with time, not a static specification. Several mechanics are explicitly calibrated around data accumulation milestones:

The Phase 2 RoC gate silently degrades to "no check" for the first 7 days — by design. The behavioral profile requires 5+ chat messages before it runs. Pattern confidence uses sample size thresholds (8, 15 trades). Reference breakouts improve screening quality with each new example the user provides. `universe_stage3_pct` is stored daily for exactly the purpose of enabling trend analysis once the dataset is deep enough.

However, there is no explicit activation schedule and no in-system notification when these thresholds are crossed. The system just quietly becomes more powerful. A user who has been running the agent for 3 months has a substantially different (better) system than one who started last week, but nothing in the interface signals this progression.

The memory files confirm three deliberate hold decisions:

- **Step 3 (Adaptive Range Pivot):** frozen until ~2026-06-25 (30 days of regime telemetry)
- **Stage 2 Recovering validation:** deferred to ~2026-06-25
- **STM + Weinstein sync redesign:** deferred to ~2026-06-26 once agent telemetry is available

This confirms the design philosophy: build the data collection layer first, then activate the logic that depends on it. This is sound. The risk is that these deferred activations are tracked only in memory files external to the code — if the notes are lost, the trigger dates are lost too.

---

## 5. Recommendations

**Priority 1 — Fix the performance summary query (§1.2)**

Change the WHERE clause in `get_agent_performance_summary()` from filtering on status='Win'/'Loss'/'Breakeven' to:

```sql
WHERE status IN ('Expired', 'Taken', 'Skipped')
  AND outcome IS NOT NULL
```

This is a one-line fix with outsized impact: every agent performance metric on the dashboard is currently wrong because of this.

**Priority 2 — Retire `evaluate_skipped_opportunities()` in favor of the learning loop (§1.1, §1.3)**

`evaluate_skipped_opportunities()` is a weaker version of `grade_opportunities()` (uses close prices only, targets T2, runs daily). The learning loop's grader is more accurate (uses intraday H/L, targets T1). Remove `evaluate_skipped_opportunities()` or convert it to a thin wrapper that simply calls `grade_opportunities()` logic. Until then, the two functions will continue to compete for the same records and produce inconsistent outcomes.

**Priority 3 — Fix the what-if return calculation (§1.4)**

The `what_if_return` in `get_inception_summary()` should average only the Expired/Skipped pool — opportunities the user did not take — rather than the full closed set. This would make it a genuine "missed opportunity" metric: "if you had taken every suggestion, including the ones you skipped, your average return would have been X."

**Priority 4 — Add a status gate on regime decay vs grading (§1.3)**

Add an `outcome IS NULL` filter to `apply_regime_decay()` (it already has one) and add a complementary check: if an opportunity was already closed by regime decay, `grade_opportunities()` should skip it. A simple `AND outcome IS NULL` added to the grading query already ensures this — verify it is present on both paths.

**Priority 5 — Clarify emotion detection or remove the field from behavioral profiling (§3.2)**

Either: (a) add a simple keyword-based emotion detector in the chat handler that flags words like "tempted", "scared", "FOMO", "regret" before calling `log_chat_message()`, or (b) remove the emotion claims from the behavioral profile prompt until detection is implemented. A behavioral profile that cites "0 emotional signals" when signals were never collected is misleading.

**Priority 6 — Surface regime gate blocks in the saved report narrative (§3.6)**

In `TradingDeskAgent.run()`, when `_opp_result.get("regime_blocked")` is True, the synthesis prompt should lead with the gate reason prominently rather than burying it in `regime_warning`. Consider a short-circuit: if regime blocked, skip the full synthesis and save a minimal "gate fired — no report today" entry with the block reason. This keeps the report archive interpretable without spending Claude tokens on a full synthesis when nothing was generated.

**Priority 7 — Add a bootstrap notice to the dashboard's agent panel**

When `agent_patterns` has fewer than 3 active patterns with real signal counts, show a banner: "Agent is still calibrating — pattern confidence scores are provisional until ~N more weekly grading cycles complete." This manages expectations and prevents the user from acting on High-confidence labels that were assigned by Claude without statistical backing.

---

## Summary Table

| Issue | Severity | Type | Recommended Action |
|-------|----------|------|-------------------|
| Performance summary query excludes all graded records | High | Unintentional bug | Fix WHERE clause (1-line change) |
| Dual grading functions with different criteria | High | Unintentional overlap | Retire `evaluate_skipped_opportunities` |
| Regime decay and grader compete for same pool | Medium | Unintentional race | Verify outcome IS NULL filter on both |
| What-if return = avg return (identical) | Medium | Incomplete implementation | Fix to use skipped pool only |
| Pattern confidence inflated on first Claude assign | Low-Medium | Intentional but undocumented | Add "provisional" label until N≥8 |
| No path to close Taken opportunities with real exit | Medium | Logic gap | Add manual update UI or webhook |
| Emotion detection wired up but never populated | Low | Logic gap | Add keyword detector or remove from prompt |
| Phase 2 gate measures filtered universe only | Low | Design ambiguity | Document intentionality or switch to full universe |
| Regime gate blocks not surfaced in narrative | Low | UX gap | Short-circuit synthesis when gate fires |
