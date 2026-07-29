# Questions — PSX Breakout Research

> **Purpose:** Living catalogue of research questions.  
> **Rule:** Move a question from Open → Under Investigation when a study begins. Move to Answered when a Research_Log entry is complete.  
> **Format:** Each question should be specific and measurable — not "is RS important?" but "does rs_rank ≤ 20 produce a higher 20d win rate than rs_rank 21–50 for BREAKOUT setups?"

---

## Open Questions

_Questions identified but not yet assigned to a study._

### Q-001 — Does the Validation-only Q4/Q1 pivot-distance effect track a specific regime, and if so, why doesn't dispersion explain it?

**Origin:** Surfaced during S-001 / H-001 (Terminated 2026-07-03 — see [Hypotheses.md](Hypotheses.md) and [S-001 Addendum B](S-001_Pivot_Distance_BREAKOUT.md)). Not itself a hypothesis and not pre-registered — flagged as an observation for potential future investigation only.

**The pattern:** In Validation, the Q4-vs-Q1 quintile effect for BREAKOUT `pivot_distance_pct` was significant in 3 of 4 regimes (TRENDING_UP, TRENDING_DOWN, RANGING) and only failed Bonferroni-corrected significance in VOLATILE — the regime with the *largest* increase in within-regime return dispersion between Development and Validation (std 10.31 → 16.39). Meanwhile TRENDING_DOWN cleared significance despite its within-regime dispersion *decreasing* from Development to Validation (std 13.79 → 9.81, N=84 vs 103 — small sample). The "era-level dispersion inflation" explanation floated in Addendum B Section B.4 does not cleanly account for either of these two cells.

**Why this is not yet a registered hypothesis:** This is a post-hoc observation on already-examined Validation data, surfaced while diagnosing a terminated hypothesis (H-001). It has no independent Development-era pre-registration and no OOS discipline established. Per project rule, it cannot be investigated further under H-001, and does not become a hypothesis worth its own study until the PI explicitly decides to pursue it — at which point it would be registered with its own from-scratch Development-era test, under the next available H-ID.

**ID correction (2026-07-03):** this entry previously stated the future ID would be "H-002." The PI has since registered H-002 (rs_score_20 quintile) and H-003 (binary EMA/stage flag family) for two unrelated candidate factors — see [Hypotheses.md](Hypotheses.md). If this open question is pursued, it will take the next available H-ID at that time (currently H-004), not H-002.

**Status:** Open — awaiting PI decision on whether to pursue.

---

## Questions Under Investigation

_Questions with an active or planned entry in Research_Log.md._

| # | Question | Study # | Started |
|---|---|---|---|
| | | | |

---

## Answered Questions

_Questions with a completed Research_Log entry. Include the key finding in one line._

| # | Question | Study # | Finding |
|---|---|---|---|
| | | | |

---

*Add questions to the Open section as they arise. Move them through the pipeline as research progresses.*
