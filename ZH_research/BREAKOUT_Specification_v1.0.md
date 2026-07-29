# BREAKOUT — Formal Specification v1.0

**See also:** [PRE_BREAKOUT_Specification_v1.0.md](PRE_BREAKOUT_Specification_v1.0.md)'s **Session Summary / Current State** section (top of file) for the current confirmed/dead/flagged status of `sec_global_rank`, `rs_score_20`, and `sector_rs_rank` — constructs defined here but tested and classified there (S-002, S-003, and PRE_BREAKOUT Sections 5–13).

**Status:** FINAL — Phase 1 (Market Phenomenon) and Phase 2 (Formal Specification) closed. Sections 1–6 (the construct itself) are unchanged since original finalization. See Section 7 for the operational/Database-Alignment-layer revision log — these entries change *which symbols/dates feed the construct*, not the construct's definition.
**Authority:** This document is the authoritative conceptual reference for the BREAKOUT construct for all subsequent phases of the ZH_research Conviction Engine project (Database Alignment, Operational Design, Historical Validation, PRE_BREAKOUT research, Conviction-factor research).
**Derivation:** Elicited directly from PI (Zeeshan) trader judgment via structured chart review, independent of database implementation and independent of trade outcome. Source examples: NETSOL (2016-02-08), HBL (2017-05-25, LOSER), UBL (2017-12-21, WINNER), POL (2017-10-03, WINNER).
**Supersedes:** The BREAKOUT V1 (state-based) construct implicitly used in Phase 1 research (H-001 through H-008). That research remains historically valid for the construct it evaluated; it evaluated a different, unverified construct than the one defined here.

---

## Guiding Principle

A breakout is a **discrete price-action event**, defined independently of:
- market context or trend structure (regime, moving averages, broader trend direction),
- confirmation/quality factors (volume, relative strength, base tightness, sector strength),
- eventual trade outcome.

These excluded factors are not irrelevant — they are the subject of later research phases (quality assessment, Conviction Engine factor research). They are excluded here specifically to keep the *definition* of the event from being entangled with the *probability of its success*. Conflating the two would mean studying the predictors of a different, outcome-biased phenomenon rather than the market event originally intended.

---

## 1. Active Resistance

**1.1 Definition.** Active resistance is the price level of the most recent qualifying pivot high that price has not yet closed above.

**1.2 Selection among multiple pivot highs.** Only the most recent qualifying pivot high is active at any point in time — regardless of whether older pivot highs are higher or lower in price. Once a new, higher pivot high forms, it becomes the active resistance immediately upon formation, before price ever approaches it. Older, already-superseded pivot highs are not candidates for active resistance.

**1.3 What constitutes a qualifying pivot high (CONFIRMED CONCEPTUAL RULE).** A genuine local high followed by visible price rejection (reversal away from the level). No minimum number of prior touches is required — a single, untested local high is sufficient to establish resistance. Repeated prior touches near the same level increase *confidence* that the zone is meaningful but are not a requirement for the definition itself (see Section 4, quality/confirmation).

**1.4 Resistance zone representation.** For the purpose of the breakout event test (Section 2), active resistance is treated as a **single price value** (the pivot high itself), not a range. Zone width / multi-touch confidence is a separate, later-layered quality attribute (Section 4), not part of the event test.

**1.5 Lifecycle — breaking and reactivation (CONFIRMED CONCEPTUAL RULE).**
- When price closes above the active resistance level, a breakout event occurs (Section 2), and the market transitions to a post-breakout state relative to that level.
- If price subsequently falls back below that same level, the original breakout event is **not** undone or made ambiguous — it remains a historical fact. However, the market re-enters a **pre-breakout state** relative to that same resistance level.
- If price later closes above that same resistance level again, this constitutes a **new, separate breakout event** — not a continuation of the earlier one.
- Consequence: a single resistance level can generate more than one breakout event over a stock's history, separated by intervening pre-breakout states. Breakout is an event; being above or below a level is a state; the two are distinct, and a resistance level's lifecycle can cycle between them repeatedly.

---

## 2. The Breakout Event

**2.1 Definition (CONFIRMED CONCEPTUAL RULE).** The breakout event is the first completed daily bar whose close is strictly above the active resistance level (Section 1) that was in effect immediately prior to that bar.

**2.2 Event timestamp.** The event date is the date of the completed bar whose close first satisfies 2.1 — not the date resistance was formed, not the date price first approached or tested the level.

**2.3 Approaching and testing are explicitly excluded.** Price trading near, into, or repeatedly against the active resistance level — without a completed close above it — is a pre-breakout state, not a breakout event, regardless of how close price comes or how many times it is tested.

**2.4 Equal close.** A close exactly equal to the active resistance level does not qualify — the rule requires the close to be *above* the level, not at or above it. (Direct reading of 2.1; not independently chart-tested, but not in tension with anything observed.)

**2.5 Gap-through.** If price opens above the active resistance level (no intraday test at the level) and the completed close remains above it, this satisfies 2.1 and qualifies as a breakout event. Whether a gap-through breakout is of different *quality* than an intraday-crossing breakout is a separate, deferred question (Section 4).

---

## 3. Confirmed Conceptual Rules — Summary

1. Active resistance = most recent qualifying pivot high not yet closed above; shifts forward as new, higher pivots form (1.1–1.2).
2. A single genuine, rejected local high is sufficient to qualify as resistance; no minimum touch count required (1.3).
3. The event test uses a single price point, not a zone (1.4).
4. A cleared resistance level can become active again after price falls back below it; each below→above transition is a separate breakout event (1.5).
5. Breakout = first completed daily close strictly above active resistance (2.1).
6. Approaching/testing without a qualifying close is pre-breakout, not breakout (2.3).
7. The event is independent of trend/market context (confirmed via UBL: a close above active resistance would have qualified as a breakout even amid an established downtrend).
8. The event is independent of quality/confirmation factors — volume, RS, base tightness, regime, sector strength (confirmed via POL: these were explicitly identified as a separate evaluation layer, applied only after the event is recognized).
9. No independent "polarity" rule exists or is needed — any apparent polarity anomaly (e.g., a signal coinciding with a swing low) is fully explained by 2.1 not yet being satisfied, not a separate construct (confirmed via POL).

---

## 4. Explicitly Deferred — Implementation / Operational Design Phase

These are not conceptual gaps. The underlying rule is already settled above; what remains is how to detect or measure it mechanically.

- **Pivot detection mechanics (from 1.3):** how many bars of confirmation, what magnitude of reversal, constitutes a qualifying "genuine local high followed by rejection" in a systematic, reproducible rule.
- **Closely-spaced/competing pivot highs:** when two candidate pivots are close in time and price, how the "most recent wins" rule (1.2) is mechanically resolved. The conceptual rule is not in question; only its detection is deferred. *(Reopen to Category A only if a future chart shows trader judgment favoring an older, more dominant pivot over a more recent, weaker one — i.e., genuine conflict between recency and magnitude in the concept itself, not just in detection.)*
- **Pivot confirmation lag:** pivot detection conventionally requires bars after the high to confirm it as genuine, meaning "active resistance" may only be knowable a few bars in hindsight rather than in real time. This affects backtestability and real-time signal generation, not the definition of the construct.
- **Equal-close and gap-through handling in code:** direct, unambiguous implementations of 2.4 and 2.5 respectively — no conceptual ambiguity remains, only faithful implementation.

---

## 5. Explicitly Out of Scope — Later Research Phases

These are deliberately not part of the BREAKOUT construct and belong to later phases:

- **Trend/market-context factors** (regime, moving averages, broader structure) — Conviction-factor research.
- **Volume, relative strength, base tightness/duration, sector strength** — Conviction-factor research (some already tested against the *prior, unverified* construct: VER/H-005, rs_score_20/H-002/H-004, EMA-stage flags/H-003, coil-tightening slope/H-007 — all will need re-evaluation against this specification's construct once implemented, not assumed to carry over).
- **Zone confidence / multi-touch scoring** — a future quality attribute, not part of the binary event test.
- **Gap-at-breakout as a quality signal** (distinct from gap-through as defined in 2.5, which is a pass/fail event question) — this is H-008's original research question, still blocked pending Phase 5 data validation, and remains a Conviction-factor question, not a construct question.
- **PRE_BREAKOUT construct** — to be defined as its own phenomenon in a subsequent phase, using the finalized breakout event (this document) as its fixed reference point (e.g., a pre-breakout state may be definable relative to an active resistance level per Section 1, but this requires its own elicitation exercise, not inheritance by assumption).

---

## 6. Relationship to Prior Research

The BREAKOUT V1 (state-based) construct — operationalized in the current `setup_log` implementation as `bos_flag=1 AND avg_vol_10d>200000` — has not yet been formally audited against this specification. That audit (Phase 3) is the next step and should determine, with evidence, whether and how the current implementation diverges from Sections 1–2 above (e.g., whether `bos_flag` represents a state that persists across multiple days rather than a discrete event date, and whether the active-resistance pivot referenced at signal time matches Section 1's definition).

Hypotheses H-001 through H-008, tested against BREAKOUT V1, remain valid findings **for the construct they actually evaluated**. They do not transfer automatically to BREAKOUT V2 (this specification) and should not be cited as evidence for or against V2 factors without a fresh test against the V1.0-conformant population, once implemented.

---

## 7. Revision Log — Operational / Database Alignment Layer

This section records changes to *implementation inputs* (which symbols and dates are fed into the construct defined in Sections 1–2) discovered and corrected during the Database Alignment phase. It does not alter Sections 1–6.

### 2026-07-08 — Symbol eligibility: static 243-symbol snapshot → rolling liquidity check

**What changed.** The symbol population feeding `compute_breakout_events()` (`breakout_events_v2.py`, unmodified in this change) moved from a frozen, undocumented ~243-symbol snapshot (no driver script, no recorded selection criteria anywhere in the codebase or git history) to an explicit, rolling eligibility check re-evaluated per `(symbol, date)`:

- **Universe:** all symbols in `stock_signals` with `stock_metadata.is_active = 1` — **305 symbols** (of the full 313 in `stock_signals`; 8 are delisted, see "What remains open" below), evaluated *before* liquidity gating.
- **Per-date eligibility:** a `(symbol, date)` row is included only if that symbol's most recent `stock_signals.avg_vol_10d` value at or before that date is ≥ 200,000 — reusing the existing `avg_vol_10d` column/calculation verbatim, no new liquidity formula. A symbol can gain eligibility (crossing the floor) and lose it again (declining below it) at different points in its history; eligibility is never a fixed, once-decided membership fact.
- **Output:** written to a new table, `stock_signals_breakout_v2_staging_full` — **252 symbols with ≥1 eligible row** (of the 305-symbol universe; 53 remain at zero eligible rows — never crossed 200,000 in available history), **291,674 rows total** (out of 1,098,398 rows `compute_breakout_events()` produces unfiltered across the full 305-symbol universe; the remainder are dates where the symbol existed but wasn't yet, or was no longer, liquidity-eligible).
- Implementation: `breakout_v2_rolling_liquidity_backfill.py`.

**Why.** An audit (prior session, "PRE_BREAKOUT Inventory — Two Follow-Up Checks") found no driver script, commit, or other record anywhere in the codebase or git history establishing how the original 243-symbol list was chosen. Reconstruction from the data showed the one necessary condition every one of the 243 present symbols satisfied was: `avg_vol_10d` crossed 200,000 at *some* point in that symbol's full history — consistent with a liquidity floor applied once, as a snapshot, and never refreshed. This silently excluded 66 active, currently-or-formerly liquid symbols, including recognizable blue chips (NESTLE, COLG, ABOT, INDU, HINOON, ATLH) and MSOT specifically — a symbol liquid as of 2026-07-07 (`avg_vol_10d` = 252,991) that had simply never been re-run against the floor. PI confirmed the 200,000 floor was never meant to be a permanent, one-time membership test — it should behave as a rolling condition, consistent with how PI already treats this floor discretionarily elsewhere in the project (e.g. adjusting it in thin markets).

**What it replaced.** The static, one-time liquidity snapshot in `stock_signals_breakout_v2_staging` — its origin was undocumented; the 243-symbol list was first reconstructed via audit (matching every present symbol against `avg_vol_10d` history), not recovered from any record, driver script, or commit.

**Concrete effect.** Row count dropped from 965,487 (243 symbols, full unconditional history per symbol) to 291,674 (252 symbols, only liquidity-eligible dates) — **by design, not a data-loss regression**: the old table wrote every date in a chosen symbol's full history unconditionally once that symbol made the static list; the new table only writes dates where the symbol was actually liquidity-eligible that day.
- **13 symbols newly added** (had 0 rows in the old table, now have ≥1 eligible row): ABOT, ALIFE, ASLPS, ATIL, COLG, EFUG, HALEON, HINOON, LCI, MACTER, MSOT, SHEZ, ZAHID.
- **4 delisted symbols correctly dropped** (were present in the old 243 despite being delisted; now excluded via the `is_active` check, separate from and prior to the liquidity gate): FFBL, META, PIAA, PSMC.
- **53 symbols remain at zero eligible rows**: active, in the universe, but never crossed 200,000 `avg_vol_10d` in available history — includes AGLNCPS, AHTM, AKDHL, AKGL, ANLNV, ANTM, ARPAK, ARPL, ASIC, ASLCPS, ATLH, BELA, BHAT, BTL, BUXL, DADX, DIIL, DWAE, EFUL, EPCLPS, EWIC, EXIDE, FASM, FRCL, FSWL, FZCM, GEMPAPL, GOC, HAFL, HCL, HUSI, IGIL, INDU, ISIL, JLICL, JVDCPS, KCL, KHYT, MEHT, NESTLE, PECO, POWERPS, PSEL, REWM, RMPL, SAPT, SCL, SFL, SIEM, STML, UDPL, UPFL, ZIL.

**Table naming.** `stock_signals_breakout_v2_staging_full` is the canonical BREAKOUT V2 population table going forward — use this for any new work (including the PRE_BREAKOUT rebuild noted below). The deprecated 243-symbol table was **renamed** (not deleted, not altered — a metadata-only rename, contents identical: 965,487 rows, 243 symbols, unchanged) from `stock_signals_breakout_v2_staging` to **`stock_signals_breakout_v2_staging_DEPRECATED_243sym`**, so it can no longer be referenced under its old name and cannot be accidentally used going forward. Do not use it as the basis for any new work; it is retained purely for reference.

*Note (same date, follow-up):* three scripts still hard-coded the pre-rename name `stock_signals_breakout_v2_staging` and were **not** modified as part of the rename (out of scope for that task): `breakout_events_v2.py` (`STAGING_TABLE` — would recreate an empty table under the old name if re-run, since it uses `CREATE TABLE IF NOT EXISTS`), `breakout_v2_rolling_liquidity_backfill.py` (`OLD_STAGING`, used only for its one-time before/after reporting query — would error if re-run), and `prebreakout_v2_inventory.py` (`SRC_STAGING`, its PRE_BREAKOUT source table — would error, or worse, silently read an empty table if `breakout_events_v2.py` was re-run first). None of these are on any automated/scheduled path (`main.py`, `dashboard.py`, and the daily pipeline hooks do not reference this table under any name).

*Note (same date, second follow-up):* `breakout_events_v2.py`'s `STAGING_TABLE` constant (line 31) has been corrected from `stock_signals_breakout_v2_staging` to `stock_signals_breakout_v2_staging_full` — a single-line constant change only, script not re-run, no logic touched. This closes the "silently recreates an empty table under the old name" trap from the note above. `breakout_v2_rolling_liquidity_backfill.py` and `prebreakout_v2_inventory.py` are unchanged (left for future update if/when next used).

**Caveat this constant fix does *not* address:** pointing `STAGING_TABLE` at the canonical table only fixes *which name* the script writes to — it does not make `breakout_events_v2.py` safe to run standalone as a substitute for `breakout_v2_rolling_liquidity_backfill.py`. `breakout_events_v2.py`'s `run_for_symbols()` writes every date in a given symbol's full history unconditionally (no rolling liquidity gate) and its `INSERT OR REPLACE` only names 5 of the 6 columns in the `_full` table's schema, so a direct re-run would silently null out `avg_vol_10d_asof` on any row it touches and reintroduce liquidity-ineligible dates into the canonical table for whichever symbols it's pointed at — undermining the rolling-liquidity fix documented above. `breakout_v2_rolling_liquidity_backfill.py` remains the correct way to (re)populate `stock_signals_breakout_v2_staging_full`.

**Validation.** All 291,674 rows in `stock_signals_breakout_v2_staging_full` were checked against an independent, fresh recomputation of `compute_breakout_events()` from `prices_adjusted` (separate from the backfill run): 0 mismatches. (An initial validation pass built into the backfill script itself reported 91 mismatches; this was a bug in that validator — an incremental state-carry check that assumed contiguous dates per symbol, invalid once the rolling eligibility filter introduces date gaps — not a defect in the stored data. Corrected by validating against a full independent recompute instead.)

**What remains open.**
- `stock_metadata` has 9 `is_active = 0` (delisted) symbols; 8 of these are present in `stock_signals` (the 9th, `GEMUNSL`, is a distinct symbol from the still-active `GEMSPNL` and has no `stock_signals` rows at all). Of those 8, only 4 (AEL, HSPI, JOPP, PIAB) were already absent from the old 243-symbol population; the other 4 (FFBL, META, PIAA, PSMC, listed above) were present in the old 243 despite being delisted. This means the corrected universe is 305 symbols, not 313 − 4 = 309 as originally estimated going into this fix. All 8 delisted symbols are correctly excluded from `stock_signals_breakout_v2_staging_full` via the `is_active` universe gate — entirely separately from, and prior to, the liquidity check — so none are miscategorized as "illiquid" when the real reason is delisting.
- `pre_breakout_v2_staging` (PRE_BREAKOUT population staging) still reads against the deprecated `stock_signals_breakout_v2_staging` table and has **not** been rebuilt against `stock_signals_breakout_v2_staging_full`. It must be re-run against the new canonical table before PRE_BREAKOUT work resumes; not done in this task by explicit instruction.
- No hypothesis testing or forward-return analysis has been run against the new population — this entry covers population/eligibility correction only.

---

*End of BREAKOUT Specification v1.0.*
