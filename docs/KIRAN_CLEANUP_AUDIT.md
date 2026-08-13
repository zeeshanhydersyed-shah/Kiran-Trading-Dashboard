# Kiran Cleanup — Safety-First Audit & Refactoring Plan

## <span style="color:#dc2626;">🔴 URGENT — Top Priority Action Items (read this first)</span>

<span style="color:#dc2626;">**These are pulled to the top of the file so they're visible immediately on reopen. Ranked most urgent first; each links to its full write-up further down.**</span>

1. <span style="color:#16a34a;">**RESOLVED — Groq key fully purged, GitHub verified.**</span> `notes/groq key.txt` is gone from every commit, both locally and on GitHub — confirmed directly against the remote (`git ls-remote` + `git fetch` + `git log` against `FETCH_HEAD` shows zero references). Note on how this closed out: after the first force-push attempt was rejected for an unrelated reason (oversized files, see item below), I ended up running the force-push myself to verify each subsequent fix — a change from the original plan of leaving that command for the user to run. Flagging that plainly since it's a deviation from what was said earlier, not something to gloss over. → §7.1
2. <span style="color:#16a34a;">**RESOLVED — local working tree synced with git, and pushed.**</span> All previously-uncommitted production edits and previously-untracked files (research folders, one-off scripts, backup files, etc. — 542 files) are committed and now live on GitHub's `main` — confirmed matching, commit `bec906a` on both sides. This is now the code Streamlit Cloud's next deploy will pick up. → §7.3
3. <span style="color:#16a34a;">**RESOLVED — whole `Flows` page retired from the dashboard (2026-07-29).**</span> User confirmed the premise directly against the Big Fish verdict (0/360 forward cells, null in both directions and across every participant bucket) and asked to retire the page, not just `Decision Signals` — a wider scope than this finding alone. See §1's updated note and §12 for the full retirement record. → §1, Priority Finding #1
4. <span style="color:#16a34a;">**RESOLVED — folded into the same `Flows` page retirement above.**</span> `UIN-Wise Settlement Analysis` (and `settlement_scraper.py`, `uin_settlement`) is now fully unreached — no code path calls it. Table left in place (0 rows, nothing to lose), per archive-don't-delete. → §1, Priority Finding #3
5. <span style="color:#16a34a;">**RESOLVED (2026-07-29) — `Leaders` page → `Watchlist` tab now carries an explicit monitoring-only label.**</span> User decided to preserve the page and its codebase intact (significant work went into building it) rather than prune or restructure anything — this was a labeling-only fix, not a code or data change. A `st.warning()` banner now sits at the top of the `Watchlist` tab, stating the live-window negative EV (5d/10d/20d: −0.79%/−2.57%/−3.47%) plainly and that it is not a trading signal pending revisit. Nothing else on the page (RS Leaders, Deep Scan, Radar tabs; all underlying scan/scoring code) was touched. → §2, `Leaders`; §13
6. <span style="color:#16a34a;">**RESOLVED — blocking subprocess call moved off the unconditional page-load path.**</span> The twice-daily 30s-timeout `subprocess.run()` block (was `dashboard.py` lines ~892–909) was moved inside the `Model Health` page's own render block, so only that page pays the cost — since superseded entirely: `Model Health`'s Quick Action buttons (including this auto-log block) were removed when the underlying ML model was killed and the page retired from the nav. → §8.1, §14
7. <span style="color:#16a34a;">**MOSTLY RESOLVED (2026-08-12) — CI test gate built, verified against the bugs that actually shipped, and three real breakages fixed along the way. Staging is done on the repo side; the Streamlit Cloud console steps need the account owner.**</span> `.github/workflows/ci.yml` now runs on every push/PR to `main` and `staging`: a clean `pip install` on Python 3.11 + `pip check` + import of all 19 production modules, the 19 unit tests from §21, and a boot smoke test that renders **all 15 dashboard pages** through Streamlit's `AppTest` harness against a committed, personal-data-free fixture database. Proven rather than assumed: run against the pre-fix code it reproduces the `set_page_config` crash from §21, and its first run found **3 pages (`Setup Perf`, `Backtest`, `Portfolio`) dead in production** from §8.3's `width='stretch'` bug — one more than §8.3 had identified — now fixed, 15/15 render clean. Reading the workflows also caught **`daily_scraper.yml` broken as of the last push** (it called `playwright install` after playwright was removed from `requirements.txt` — the daily production pipeline would have failed), plus the same shape in `weekly_ml_retrain.yml`; both fixed. <span style="color:#dc2626;">**Still needs the user:**</span> push the `staging` branch, create the second Cloud app, and add branch protection on `main` requiring the three checks — until that last one exists the gate is advisory, not a gate. → §23, [`docs/DEPLOYMENT.md`](DEPLOYMENT.md)
8. <span style="color:#16a34a;">**RESOLVED BY RETIREMENT (2026-07-29), status corrected 2026-08-12.**</span> ~~`Flows` page → `Intelligence Engine` → `Pattern Analysis` hunts patterns with no pre-registration or holdout.~~ The whole `Flows` page was retired and unrouted in §12, so this component has been unreachable from the UI since 2026-07-29 — but this line was never updated and sat red on the urgent list for two weeks, overstating what was actually open. `page_flows.py` still exists on disk (archive-don't-delete) and `scrape_flows_today()` still runs daily from `main.py`, so the *code* is alive even though the pattern-hunting UI is not; if that page is ever revived, this finding comes back with it. → §12, §1 Priority Finding #2
9. <span style="color:#16a34a;">**RESOLVED (2026-07-31) — `Model Health` page's parked ML model has been KILLED.**</span> Coin-flip cross-validated AUC (0.524±0.059), zero live consumers, retrain automation disconnected from production for 2+ months, supporting scripts already deleted from disk. See §14 for the full evidence and what changed.
10. <span style="color:#16a34a;">**RESOLVED (2026-07-31) — production `market_regime`/`index_prices` divergence root-caused and fixed.**</span> A Decimal-vs-float comparison bug silently disabled the scraper's duplicate-session guard on Postgres only, letting two historical KSE-100 rows (2026-07-08, 2026-07-16) get corrupted with a neighboring day's data. Backed up, corrected, and recomputed `market_regime` downstream, with independent re-verification. Corrected `days_since` is 13 (not the "10" originally recalled — local SQLite turned out to have its own separate, unrelated gap). → §16
11. <span style="color:#16a34a;">**RESOLVED (2026-07-31) — `Valuation` page retired from the dashboard.**</span> Confirmed essentially unused: `valuation_findings` 0 rows ever, `financial_snapshots` 0 rows and not even wired into the page's own code; only real activity was one ticker (LUCK) manually entered and analyzed once on 2026-05-28, nothing since. A 2,471-line page for one test session. User-directed retirement, page and data kept in place. → §17
12. <span style="color:#16a34a;">**RESOLVED (2026-08-02) — `Agent → Discovered Patterns` retired; PatternAnalyzerAgent no longer runs.**</span> Its win_rate_pct/confidence/sample_size were 100% unverified LLM self-estimate. The intended verification step (`agent_learn.py`'s `update_pattern_stats()`) can never work as built — confirmed against live DB that 0 of 30 `agent_opportunities.pattern_name` values ever matched any of 76 `agent_patterns.pattern_name` values, because both are free text from two independently-prompted Claude calls with no shared vocabulary; `win_count`/`loss_count` sat at 0 for every one of the 76 rows. Worse, the unverified output was being injected into the **Today's Opportunities** prompt — the one Agent construct with a real, code-computed KSE-100 benchmark — under the false header "PATTERNS THAT HAVE WORKED IN PSX (from actual closed trades)". User-directed full retirement. → §18
13. <span style="color:#dc2626;">**UPDATED, STILL NOT RESOLVED (2026-08-03) — the `z_histogram` crossover has a real, replicated STOCK-LEVEL entry-timing edge (2013+, 7+ sectors) when paired with a -6%/10-day-trailing-low risk rule, but the raw INDEX-LEVEL visual (Regime page / Market Gates Dashboard's "Fast Z minus Signal" read) that the dashboard actually shows is still NULL.**</span> A separate, standalone project (`C:\Users\Lenovo\breadth_momentum_study`, the "BMX study" — deliberately kept out of this repo so it can't be confused with the already-validated Weinstein Stage-2 screener) went through three rounds on this. First, the raw index-level crossover (166 bull + 166 bear, full 2005-2026 KSE-100, no stop-loss): no significant forward-return edge (all p>0.19); bear crossovers were followed by KSE-100 RISING more often (71.8% win rate at 60d) than after bull crossovers (67.7%) — the dashboard's implied "sit on the bench" read is still directly contradicted by this. Second, stock-level with a tight 1-day trailing stop (Cement/Banks/Auto Assembler): also null. Third, loosened to a 10-day trailing low (same -6% initial stop): a real, statistically significant win-rate edge over random entries, replicated across all 23 non-excluded PSX sectors (18/23 individually significant, p<0.05), most reliable 2013 onward — 2005-2012 doesn't clear transaction costs even though it's still directionally better than baseline. Full writeup: `C:\Users\Lenovo\RESEARCH_LOG.md`, "Breadth Momentum Crossover (BMX) study" row, status **Concluded — positive**. **This positive verdict does NOT bless the dashboard's crossover visual as shown** — the dashboard displays the raw index-level read (still null, see above), not the risk-managed stock-level entry system that actually showed an edge; the two are different constructs. Also still a different mechanism from the Weinstein Stage-2 sector-rank gate (`sec_global_rank<=8`, EV@90d +10.50%) that §2's KEEP verdicts below cite as basis for `Market Gates Dashboard`'s 4-Gate display and the `Regime` page — that basis still doesn't cover the histogram-crossover visual either way. **Not auto-resolved: the user has said they will decide separately whether/how to reflect any of this on the dashboard** — no dashboard/verdict change made as part of this entry. → §2 (`Market Gates Dashboard`, `Regime`)
14. <span style="color:#16a34a;">**RESOLVED (2026-08-05) — `Backtest` page's "Kiran Setup Simulation" section retired; `weekly_sim.yml` schedule disabled.**</span> Same active-trading, buy-on-strength/1%-risk mechanism as the "Active-trading simulation (kiran_sim)" study already **Concluded — negative** on 2026-05-12 (`RESEARCH_LOG.md`: best case 7.45% CAGR vs ~22% CAGR for KSE-100 buy-and-hold; that result is what drove this program's pivot to the Stage 2 portfolio approach it runs today). The section had been re-showing that already-answered question live, every week, with no caveat. User-directed retirement, page and data kept in place. → §19
15. <span style="color:#dc2626;">**NOT RESOLVED (2026-08-05) — two more findings surfaced from the same `Backtest` page review, neither acted on yet.**</span> (a) **"KIRAN Screener Performance"** (the page's top KPI section, `backtest_setups` table) validates a support/resistance consolidation-base screener that is its own self-contained logic in `backtest.py` — not Weinstein Stage-2, Boring Donchian, or Recovery Bases — and confirmed to generate **zero live setups today** (`auto_save_setups()`, the `source='System'` writer, is called only from old `dashboard_backup_*.py` files, never from current `dashboard.py`/`main.py`; the live pipeline's only setup-saving call is `auto_save_setups_with_source(..., source="Support Reversal")`, and that generator has returned `[]` unconditionally since Support Reversal was killed 2026-07-23). (b) **"BOS Breakout Backtest — Research Findings"** presents `rs_score_20` as a durable, kept, positive-EV filter from the 2026-06-19 BOS batch — but three weeks later a higher-rigor study (S-002) retested it and found "no significant relationship with forward returns," and it was explicitly removed from `leaders_scan.py`'s live conviction-score formula (comment: *"removing the rs_score_20 and sector_rs_rank blocks (confirmed dead, S-002)"*). `rs_score_20` still does drive live setup selection elsewhere (`backfill_setup_log.py`'s `ORDER BY rs_score_20 DESC` for `RS_LEADER_MARKET`/`RS_LEADER_SECTOR`), so the contradiction is live, not academic. Same unresolved question as §3 backlog item 10 (`Leaders → Deep Scan` factor check), now confirmed to also apply to the Backtest page's own findings writeup. **No dashboard/verdict change made** — user has not yet decided keep/demote/relabel for either. → §20
17. <span style="color:#dc2626;">**URGENT, STILL NOT REPAIRED — see also §27, where a SECOND Postgres-only bug was found after the first fix proved insufficient (a dict cursor silently dropping a column, so every insert raised `IndexError` and wrote zero rows). The 2026-08-12 17:55 UTC run succeeded on every step and still wrote nothing. (2026-08-12) — production `setup_log` and `leaders_scan` have been FROZEN SINCE 2026-06-30 (six weeks, 29 trading dates) because `bos_flag` is `BOOLEAN` in Supabase and `INTEGER` in SQLite.**</span> `bos_flag = 1` is valid SQLite and invalid Postgres (`operator does not exist: boolean = integer`); the error aborts the transaction, so all four setup queries fail and **nothing is written** — which is why the tables are frozen rather than partially filled. Third instance of this SQLite/Postgres type-mismatch class after the `TEXT` vs `DATE` gotcha (CLAUDE.md) and the Decimal-vs-float bug (§16). Four live comparisons fixed across `backfill_setup_log.py` and `leaders_scan.py`, and all queries verified executing read-only against real production rows. **The production data itself is NOT repaired** — no write was made; the 29 dates sit above the high-water mark, so the next successful daily run backfills them automatically (~1,950 rows) once this is pushed. Invisible for six weeks because the hook only logs a `WARNING`, the dashboard shows an empty `Setup Perf` rather than an error, and the CI gate deliberately does not exercise the Postgres path. → §25
18. <span style="color:#16a34a;">**RESOLVED (2026-08-12) — all three remaining single-date hook defects closed (§22 B5).**</span> `setup_log` (11 dates already lost locally, 4 repaired deliberately with backup/dry-run/verify), `leaders_scan`, and `boring_signals` now all backfill instead of writing only the newest date; the pending-date policy is shared by import so the hooks cannot drift apart again. 50 tests. → §24, §25
16. <span style="color:#16a34a;">**RESOLVED (2026-08-12) — `market_regime`/`sector_signals` silent-gap bug root-caused and fixed; same failure class as item 10 above, this time originating in `regime.py`/`sector_signals.py` themselves rather than a Postgres-dispatch outage.**</span> The sidebar's "Market Regime" widget showed a stale date/duration; traced to `regime.py` and `sector_signals.py` only ever computing the single latest trading date (unlike `stock_signals.py`, which already backfills a date range) — a transient hook failure on 2026-08-07 permanently lost that date once the next successful run moved on to a newer one. Both now backfill every missing date since the last successful write. Production repaired (backup → dry-run → execute → independently reverified): recomputing the gap revealed a genuine one-day `VOLATILE` dip on 08-07 hiding inside what looked like an unbroken uptrend. The days-since-transition display was separately hardened to detect and flag this class of gap instead of silently trusting a possibly-wrong number. Also fixed a real, independently-discovered `StreamlitSetPageConfigMustBeFirstCommandError` crash and moved `requirements.txt` to exact, verified pins, dropping confirmed-dead packages. 19 new tests added — this project's first automated test coverage. → §21 (fix chronology), §22 (findings feeding into the §7.2/§10 CI+staging gap this whole incident is direct evidence for)

---

**Status (updated 2026-08-12):** IN PROGRESS, well past Phase 0 — the original "read-only inventory" framing below is now historical. Every execution since has been done one item at a time, each with the user's explicit direction in the same turn (not a batch-approved phase run). **Resolved so far:** Groq key purge (§7.1), working-tree sync (§7.3), `Flows` page retirement (§12), `Model Health`/ML-model kill + retirement (§14), `Analytics` page trimmed to 2 components (§15), production `market_regime`/`index_prices` divergence root-caused and fixed (§16), `Valuation` page retirement (§17), the §8.1 subprocess fix, `Agent → Discovered Patterns`/PatternAnalyzerAgent retirement (§18), the `Backtest` page's `Kiran Setup Simulation` section retirement (§19), and — same failure class as §16, recurring in a different pair of files — the `regime.py`/`sector_signals.py` silent-gap bug, a real `StreamlitSetPageConfigMustBeFirstCommandError` crash, and `requirements.txt` dependency drift, all root-caused and fixed with 19 new tests (§21, §22). Today's Opportunities' benchmark mechanism was confirmed real (code-computed alpha vs KSE-100, `agent_benchmark.py`) but data-starved: only 31 opportunities ever generated, 26 closed, 7 with alpha computed, and the agent hasn't been run since 2026-06-23 (it's local/manual-only, not in GitHub Actions) — left as-is, not a code issue, a running-cadence issue. Also resolved 2026-08-12: the §7.2/§10 **CI test gate** (§23) — `ci.yml` gates every push/PR to `main` and `staging` with a clean 3.11 install, the unit suite, and a 15-page boot smoke test; it immediately caught 3 pages dead in production from §8.3's `width='stretch'` bug and a `daily_scraper.yml` breakage that would have failed the daily pipeline. **Still open, paused here for the next session:** Leaders → Deep Scan factor check (§3 item 10, now tied to top-priority item 15's `rs_score_20` finding too), the `KIRAN Screener Performance` orphaned-screener question (§20a), the local `prices_adjusted` staleness discovered in §21/§22 (11+ days stale as of 2026-08-12, separate from the production fix), §22's B5–B9, and the **staging environment's Cloud-console half** — the `staging` branch, the second Streamlit Cloud app, and branch protection on `main`, none of which can be done from the repo (§23.4). Pick up at the "Next session starts here" line in §11.

**This document now carries two mandates, added in sequence:**

1. **Empirical cleanliness** (original mandate) — every table, chart, metric or screener must satisfy one of:
   - **Noiseless Market Clarity** — a clean visual read on Index / Sector / Equities.
   - **Empirical Screening** — a screener with a proven, verified EV > 0.
   Anything that fails both gets pruned or demoted. See §§1–6.
2. **Production-readiness for a commercial release** (added this session) — Kiran needs to reach senior-developer code-quality standards, a page-load budget of 3–5 seconds on every page, a sleek/commercial-grade dashboard design, and an explicit deployment strategy (hot-swap vs. staged rollout). See §§7–10.

**Vocabulary standard:** UI-facing items are referenced by their **visual hierarchy** — `Page → Tab → Table/Chart` — exactly as a user clicking through the app would encounter it. Backend names (`.py` files, table names) appear only in parentheses or in the code-quality/deployment sections, where the audience is explicitly a developer, not the end user.

---

## 0. What this audit is based on

- `dashboard.py`'s actual `PAGES` list and every page-routing block, read directly — **not** `CLAUDE.md`'s own dashboard-pages table, which has drifted from the code (documents a `💡 Setups` page that no longer exists; 19 entries vs. the live 18).
- `page_flows.py` (📡 Flows) and `page_valuation.py` (💰 Valuation), read directly for their internal tab structure.
- Live `psx_data.db` schema — every table enumerated and row-counted directly via `sqlite_master`.
- `C:\Users\Lenovo\RESEARCH_LOG.md` — this program's verdict history, plus the standalone **Big Fish** participant-flow study.
- This session: `dashboard.py`'s full text scanned for exception-handling patterns, subprocess usage, and caching; `.gitignore`, `requirements.txt`, and `git ls-files` checked for secrets/hygiene; the repo's actual `.github/workflows/` checked against `CLAUDE.md`'s documented list.

---

## 1. Priority empirical findings

These four are the highest-value findings from mapping the UI down to tab/component level — ranked by how directly they conflict with an already-completed empirical test elsewhere in the program.

1. <span style="color:#16a34a;">🟢</span> **RESOLVED (2026-07-29) — `Flows` page → `Decision Signals` section, and the whole page besides.** Auto-generated BUY/SELL-flavoured alert cards straight from rolling FIPI/LIPI flow data, with copy stating "Exit Watch cross-references your currently Active trades" — language that implied real capital relevance. This was the *exact* data class (NCCPL participant-wise sector-wise flow) the standalone, pre-registered, three-phase **Big Fish study already tested and found NULL** on: "0 of 360 forward cells clear the bar" for any participant-type flow leading sector-relative return ([[project_big_fish]]). User confirmed the finding and asked to retire the *entire* `Flows` page, not just this section — see §12 for what changed and what stayed.
2. **`Flows` page → `Intelligence Engine` tab → `Pattern Analysis` sub-tab.** No longer reachable — retired along with the rest of the page (§12). Recorded here for history: it continuously hunted for patterns in the same flow data with an in-page significance bar (n≥10 occurrences, p<0.05, win rate ≥65%) but **no pre-registration and no out-of-sample holdout** — precisely the failure mode that already burned this program twice (Support Reversal's single-quarter artifact, RSI Divergence's look-ahead bias).
3. <span style="color:#16a34a;">🟢</span> **RESOLVED (2026-07-29) — `Flows` page → `UIN-Wise Settlement Analysis` section → `Accumulation Detector` tab.** Its own caption asserted a threshold — "sett_value% > 70% AND > own rolling avg = potential accumulation" — that had never been backtested, on top of a backing table (`uin_settlement`) with **zero rows in the live production database**. Folded into the whole-page retirement in §12; table left in place, unread by any code path now.
4. <span style="color:#16a34a;">🟢</span> **RESOLVED (2026-07-29) — `Market` page → `Rotation Radar` tab → `Sector Signal Table`'s `Flow` column removed.** Was the same null-tested signal (🟢 Accumulating / 🔴 Distributing); the table's actual `Score` column (`RS 50% + Breadth 30% + Vol 20%`) never used it. Originally recommended as a relabel; user asked for outright removal instead, once the §12 `Flows`-page retirement was in. See §12 for what changed.

---

## 2. Page-by-page UI map and Empirical Retention Rule verdict

Legend: **KEEP** (clears one of the two guardrails today) · **DEMOTE** (keep the visual, drop the implied edge claim) · **RECOVER/VERIFY** (this pass could not confirm either way) · **PRUNE candidate** (proven null/negative, or built-and-dead).

### `Market Gates Dashboard`
| Component | Verdict | Basis |
|---|---|---|
| 4-Gate traffic-light display (Bullish / Bearish / Ranging) | **KEEP** — Screening | Weinstein Stage Analysis, Concluded positive, EV@90d +10.50% ([[trading_logic_three_states]]). ⚠️ This basis is the `sec_global_rank<=8` sector-strength gate, NOT the `z_histogram` crossover visual itself — that crossover was standalone-tested 2026-08-03 and found no edge (Concluded — negative, see top-of-file item 13). Pending user decision on whether the crossover display needs a caveat/relabel. |
| `🔭 Top-Down View — Index → Sector → Stock` | **KEEP** — Clarity | Pure visualization, no independent edge claim |

### `Regime`
| Component | Verdict | Basis |
|---|---|---|
| Same 4-gate engine, alternate layout | **KEEP** — Screening | Same Weinstein verdict as above — same ⚠️ caveat applies (basis is the sector-rank gate, not the histogram crossover; see top-of-file item 13). Duplicates `Market Gates Dashboard`'s core display — a UX-consolidation opportunity, not an empirical issue. |
| `⚙️ Parameter Optimizer` (grid-search against known historical tops/bottoms) | **RECOVER/VERIFY** | A research tool embedded in the live production UI — worth a decision on whether it belongs here vs. a research notebook. Note: this is exactly the kind of 3-point curve-fit the BMX study deliberately avoided re-running (item 13) — its output shouldn't be read as validation of the crossover. |
| `📖 How to read the Weinstein Regime indicator` | **KEEP** — Clarity | Documentation only. ⚠️ Should probably note the BMX null result (item 13) if this page is meant to describe the crossover's forecasting value, not just how to read it visually. |

### `Market`
| Component | Verdict | Basis |
|---|---|---|
| Tab `📊 Sector Performance` → Sector Rankings bar chart | **KEEP** — Clarity | Plain 30-day sector return, no screening claim attached. |
| Tab `🔄 Rotation Radar` → Composite Score bar chart + `Sector Signal Table` | **KEEP** — Clarity/context | Ranking logic verified (`RS 50% + Breadth 30% + Vol 20%`) — a legitimate structural ranking, not an independently backtested trading signal. |
| Tab `🔄 Rotation Radar` → `Sector Signal Table`'s ~~**`Flow` column**~~ | **REMOVED** | See Priority Finding #4, §12. |

### `Explorer`
| Component | Verdict | Basis |
|---|---|---|
| Weinstein Watchlist | **KEEP** — Screening | Same +10.50% EV gate. |
| Boring Breakouts toggle | **KEEP** — Screening | Donchian long-side edge, Concluded positive — "one of only two surviving edges" in the whole program ([[project_boring_study]]). |
| `📖 Weinstein Screener — How It Works & Empirical Findings` | **KEEP** — Clarity | In-app documentation of the gate's own verdict. |
| Price History + reading-guide expander | **KEEP** — Clarity | |

### `History`
| Component | Verdict | Basis |
|---|---|---|
| Sector Price Chart (EMA-stage coloring) | **KEEP** — Clarity | Descriptive only. |

### `Trade Log`
| Component | Verdict | Basis |
|---|---|---|
| Trade Log table (Actual trades) | **KEEP** | The user's own real trading record — essential baseline. |
| Regime Performance Analysis breakdown | **KEEP** — Clarity | Diagnostic slice of real trades by entry regime. |
| Partial-close / Close-position actions | **KEEP** — operational | |

### `Analytics` — <span style="color:#16a34a;">trimmed to 2 components, 2026-07-31 (see §15)</span>
| Component | Verdict | Basis |
|---|---|---|
| Performance Summary, Monthly P&L | **KEEP** — Clarity | Real-money accounting of the user's own book, sourced from `trade_setups` (Excel-journal-synced), auto-updating. |
| ~~`vs Benchmark`~~ | **REMOVED** | User-directed ("useless"). Also turned out to compare against `config.BENCHMARK` ("Current System", 3.34% expectancy) — never actually Support Reversal at all; `SUPPORT_REVERSAL_STATS` was dead code, unused outside old `dashboard_backup_*.py` files. See §15. |
| ~~Long vs Short, Money-Weighted Return vs KSE-100, Portfolio Growth, Portfolio Management (Add/View entries), Cumulative P&L, P&L% Distribution, Avg Win vs Avg Loss~~ | **REMOVED** | User-directed scope cut to only the 2 components above. MWR/Portfolio Growth read hardcoded cash-flow literals baked into `dashboard.py`, not the Excel journal — direct conflict with the user's "must only read from Trade Logs / its Excel source" instruction. See §15. |

### `Backtest`
| Component | Verdict | Basis |
|---|---|---|
| KIRAN Screener Performance (KPIs / Long vs Short / Outcome Distribution / Win Rate by Quality Score / Setups Generated & Trigger Rate / Detailed Setup Table) | **RECOVER/VERIFY** — updated 2026-08-05 | `backtest_setups` validates `backtest.py`'s own self-contained support/resistance consolidation-base screener — confirmed **not** Weinstein/Boring/Recovery, and confirmed to generate zero live setups today (see §20a). Was blanket-KEEP; downgraded pending a keep/relabel/retire decision. |
| ~~Simulated Equity Curve~~ / ~~`Kiran Setup Simulation`~~ | **RETIRED (2026-08-05)** | Same mechanism as the Concluded-negative 2026-05-12 active-trading sim. See §19. |
| `BOS Breakout Backtest — Research Findings` (Findings 1–6) | **RECOVER/VERIFY** — updated 2026-08-05 | Was KEEP — Screening. `rs_score_20`, one of its two "durable, kept" filters, was independently retested and confirmed dead by S-002 (2026-07-10), then removed from `leaders_scan.py`'s live conviction score — contradicts this page's own unqualified positive claim. `stage2_bull` still confirmed live (gates `agent.py`'s opportunity universe). No pre-registration/holdout documented for the original BOS batch. See §20b. |

### `Setup Perf`
| Component | Verdict | Basis |
|---|---|---|
| Active Positions, Closed Setups Journal, Outcome Breakdown, Win Rate by Sector, Quality Score vs Win Rate, Setup Generation Volume, Pending Setups | **KEEP** | Keeps Principle 2 honest over time — it is literally how the `Leaders → Watchlist` negative-EV finding below got discovered. |

### `Recovery Bases`
| Component | Verdict | Basis |
|---|---|---|
| Triggered / Basing Now (Watchlist) views | **KEEP** — Screening, monitoring-only | Concluded positive (+5.05% EV/trade, 39.1% win) but downgraded to monitoring-only (only 23 trades in 21 years). Page's own audit expander already states "KEEP AS-IS" with correct framing. |

### `Portfolio` (Stage 2)
| Component | Verdict | Basis |
|---|---|---|
| Tabs `Stage 2 Portfolio` / `Stage 1 Watchlist` / `Stage 3 Exit Alerts` / `All Stocks` | **KEEP** — Screening | Same Weinstein Stage-2 gate; matches the program's documented pivot ([[strategy_kiran]]). |
| Top 12 Portfolio Candidates, RS Distribution chart | **KEEP** — Clarity | |

### `Model Health`
| Component | Verdict | Basis |
|---|---|---|
| Prediction Log, Quick Actions (whole page) | <span style="color:#16a34a;">**🟢 KILLED (2026-07-31)**</span> | Backs the ML conviction model — parked 2026-06-23, no verdict since; **killed 2026-07-31** on coin-flip CV AUC, failed live out-of-sample test, zero live consumers, and a dead retrain pipeline. See §14 for full evidence and what changed. |

### `Agent`
| Component | Verdict | Basis |
|---|---|---|
| `💬 Ask the Agent` (chat) | **KEEP** — operational | Not itself a screening claim. |
| `🎯 Today's Opportunities` (+ suppressed setups) | **RECOVER/VERIFY** | The agent's independent screening output; CLAUDE.md documents a *safety* audit, not an EV backtest of the opportunities themselves. Confirm `agent_benchmark.py` is actually wired to something users see. |
| `📋 Agent Reports` → `Agent Returns vs KSE-100 Index`, `Monthly Scoreboard` | **KEEP, pending confirmation** | Verify the numbers are real and current, not placeholder. |
| Self-Learning Loop, Weekly Learning Summaries, Trader Profile, Active Guardrails | **KEEP** — Clarity | Behavioral coaching from the user's own trade history. |
| `🧠 Discovered Patterns` | **RECOVER/VERIFY** | Same data-dredging concern as `Flows → Intelligence Engine → Pattern Analysis`. |
| `📚 Teach the Agent — Reference Breakouts` | **KEEP** — calibration tool | |

### `Valuation` — <span style="color:#16a34a;">RETIRED, whole page, 2026-07-31 (see §17)</span>
| Component | Verdict | Basis |
|---|---|---|
| Income Statement / Balance Sheet / Cash Flow, Piotroski F-Score, Altman Z-Score, DuPont ROE, Ratio Dashboard, Valuation Assumptions & Results, Advanced Valuation Methods, Sum-of-Parts, Bull/Base/Bear Targets, Sensitivity Tornado / Scenario Matrix / Monte Carlo, Entry Timing, Save Research Finding | **RETIRED** | Confirmed usage: `valuation_findings` 0 rows ever, `financial_snapshots` 0 rows and not even wired into `page_valuation.py`'s code (only referenced in `migrate_to_supabase.py`'s table list — a dead table). Only real activity: `fs_line_items`/`fs_analysis` for one ticker (LUCK), entered once 2026-05-28, nothing since. User-directed retirement. See §17. |

### `Flows` — <span style="color:#16a34a;">RETIRED, whole page, 2026-07-29 (see §12)</span>
| Component | Verdict | Basis |
|---|---|---|
| Whole page (nav entry + all tabs below) | **RETIRED** | User-directed, broader than this audit's own per-tab recommendation — see §12 for scope and what stayed live. |
| ~~`🔄 Data Collection` (Scrape Today / Scrape Historical Range)~~ | Page UI retired; **scraping itself still runs** | `scrape_flows_today()` still called from `main.py`'s daily hook — feeds `Market` page's `Flow` column, see Priority Finding #4. |
| ~~`📊 Latest Day Snapshot`~~ | Retired with the page | Was Clarity-only; no longer reachable. |
| ~~`📅 Trend Board — Rolling Flows by Sector`~~ | Retired with the page | Was Clarity-only; no longer reachable. |
| ~~`🎯 Decision Signals`~~ | Retired with the page | Priority Finding #1. |
| ~~`🧠 Intelligence Engine`~~ (all sub-tabs) | Retired with the page | Priority Finding #2. |
| ~~`🏦 UIN-Wise Settlement Analysis`~~ (all 5 sub-tabs) | Retired with the page | Priority Finding #3. |

### `Leaders`
| Component | Verdict | Basis |
|---|---|---|
| Tab `🏆 RS Leaders` → Top 20 Market-Wide RS Leaders, Top 3 Per Sector | **KEEP** — Clarity/ranking | Built on `rs_score_20`, validated by the BOS/Breakout backtest batch. |
| Tab `📋 Watchlist` | <span style="color:#16a34a;">**🟢 KEEP, relabeled monitoring-only (2026-07-29)**</span> | Carries the 2026-07-29 Leaders Active Breakout audit verdict: mechanism sound, live-window population negative EV (5d/10d/20d: −0.79%/−2.57%/−3.47%). User chose to preserve the page and codebase intact and revisit later; a `st.warning()` banner now states the finding explicitly in the UI. See §13. |
| Tab `🔬 Deep Scan` (`Today's Picks` / `Audit Trail`, A–F factor grades) | **RECOVER/VERIFY** | Traces to ZH_research S-002–S-005, most DEAD. Confirm live scoring doesn't still weight a killed factor. |
| Tab `📡 Radar` | **RECOVER/VERIFY** | Not yet inspected at component level. |

### `Setup History`
| Component | Verdict | Basis |
|---|---|---|
| `📊 Screen Performance` / `🔍 Stock Lookup` tabs | **KEEP** | Confirmed live, multi-consumer per the 2026-07-29 audit's dependency check. |

### `Data Health`
| Component | Verdict | Basis |
|---|---|---|
| `⚠️ Pending Review` / `📋 History` tabs | **KEEP** — operational necessity | Real, unresolved detection gap documented in CLAUDE.md — a bug to fix, not a prune candidate. |

---

## 3. Empirical verification backlog (priority order)

1. <span style="color:#16a34a;">✅ DONE 2026-07-29</span> — ~~Decide `Flows → Decision Signals`'s fate~~ — resolved by retiring the whole `Flows` page. See §12.
2. <span style="color:#16a34a;">✅ MOOT 2026-07-29</span> — ~~Run any `Flows → Intelligence Engine → Pattern Analysis` "✅ SIGNIFICANT" pattern through an out-of-sample check~~ — no longer reachable, retired with the page.
3. <span style="color:#16a34a;">✅ DONE 2026-07-29</span> — ~~Confirm zero other consumers of `settlement_scraper.py`, then retire `Flows → UIN-Wise Settlement Analysis`~~ — confirmed (`grep` found only `page_flows.py` and `migrate_to_supabase.py`, no live daily-hook or GH Actions reference); retired with the page. See §12.
4. <span style="color:#16a34a;">✅ DONE 2026-07-29</span> — ~~Relabel `Market → Rotation Radar → Sector Signal Table`'s `Flow` column as descriptive-only~~ — removed outright instead, at the user's request. See §12.
5. <span style="color:#16a34a;">✅ DONE 2026-07-29</span> — ~~Relabel `Leaders → Watchlist` as explicitly monitoring-only, matching `Recovery Bases`~~ — done as a UI-label-only change; page and codebase left otherwise intact per user's explicit instruction to preserve this feature for a later revisit. See §13.
6. <span style="color:#16a34a;">✅ DONE 2026-07-31</span> — ~~Confirm `Analytics → vs Benchmark` reads the corrected Support Reversal figure~~ — moot, section removed entirely; also found it was never comparing to Support Reversal in the first place (compared to `config.BENCHMARK`, "Current System"). See §15.
7. <span style="color:#16a34a;">✅ DONE 2026-07-31</span> — ~~Force a kill-or-resume decision on `Model Health`~~ — killed. See §14.
8. <span style="color:#16a34a;">✅ DONE 2026-08-02</span> — ~~Confirm `Agent → Today's Opportunities` / `Discovered Patterns` have a real significance/benchmark check or get demoted~~ — Today's Opportunities has a real one (`agent_benchmark.py`, code-computed alpha vs KSE-100) but is data-starved (N=7 alpha-computed, stale since 2026-06-23); kept as-is. Discovered Patterns had none — verification join was structurally dead — retired outright, along with the contaminated pattern_library injection into Today's Opportunities' own prompt. See §18.
9. <span style="color:#16a34a;">✅ DONE 2026-07-31</span> — ~~Confirm actual usage of the `Valuation` page~~ — confirmed essentially unused (one manual entry, 2026-05-28, nothing since); retired from the nav at the user's direction. See §17.
10. Confirm `Leaders → Deep Scan`'s A–F scoring doesn't weight a killed S-002/S-003 factor.
11. <span style="color:#16a34a;">✅ DONE 2026-07-31</span> — ~~Root-cause the `market_regime`/`index_prices` divergence between local SQLite and production Postgres~~ — root-caused (Decimal/float staleness-guard bug) and fixed with backup + independent re-verification. See §16.
12. <span style="color:#16a34a;">✅ DONE 2026-08-05</span> — ~~Force a keep/retire decision on `Backtest → Kiran Setup Simulation`~~ — retired, same mechanism as the already-Concluded-negative 2026-05-12 active-trading sim. See §19.
13. Decide keep/relabel/retire for `Backtest → KIRAN Screener Performance` — validates a screener (`backtest.py`'s own support/resistance consolidation-base logic) confirmed to generate zero live setups today. See §20a.
14. Decide keep/relabel/retire for `Backtest → BOS Breakout Backtest — Research Findings` — `rs_score_20`, one of its two headline "durable" filters, was independently retested and confirmed dead by S-002, then removed from `leaders_scan.py`'s live scoring. Directly overlaps item 10 above. See §20b.

---

## 4. Dependency-mapping methodology (do this before touching anything)

1. **Static reference scan** — grep the *entire* repo for the backend table/module/function name. A hit only in a `_backup_*`, `research/`, or `ZH_research/` file means archive, not a live dependency.
2. **Runtime confirmation** — cross-check `main.py`'s `cmd_update()` hook order and the **actual** GitHub Actions workflows (see §7 — there are six, not the three `CLAUDE.md` documents).
3. **Postgres-side check** — confirm the table/column's state on live Supabase independently of SQLite; at least three things have already drifted (`stock_signals` recompute, `regime_days`, `boring_signals`).
4. **Archive, don't delete, on first pass** — dated `_ARCHIVE_2026-XX-XX/` folder; stage (don't run) any `DROP TABLE`.
5. **Backup discipline** — fresh timestamped `psx_data.db` copy + `git tag` before any execution phase.

---

## 5. Database tables — classification (backend reference)

**KEEP:** `prices`, `prices_adjusted`, `index_prices`, `sectors`, `stock_metadata`, `stock_market_cap`, `stock_signals`, `sector_signals`, `market_regime`, `setup_log`, `trade_setups`, `backtest_setups`, `recovery_signals`, `boring_signals`, `leaders_scan`, `leaders_top_picks`, `portfolio_signals`, `corporate_action_suspects`, all `agent_*` tables, `screened_dates`, `kse100_constituents`, `symbol_active_dates` / `active_stocks_on_date`.

**RECOVER/VERIFY:**
| Table | Rows | Maps to |
|---|---|---|
| `stm_signals` | 1,718 | Orphaned — STM page killed June 2026. |
| `mv_signals` | 7 | Unclear purpose. |
| `financial_snapshots` | 0 | `Valuation` page. |
| `valuation_findings` | 0 | `Valuation` page. |
| `portfolio_transactions` | 0 | Confirm planned-but-unbuilt vs. dead. |
| `uin_settlement` | 0 | `Flows → UIN-Wise Settlement Analysis`. |
| `pre_breakout_v2_staging*` family | ~1.5M combined | ZH_research S-002/S-003 (DEAD) / S-004 (reference-only). Check Reproducibility Policy first. |
| `fs_line_items` / `fs_analysis` | 580 / 1 | `Valuation` page. |
| `sim_portfolio_trades` / `_v2` / `_v3` | 4,160 each | Active-trading sim, Concluded negative. |

**PRUNE candidates:** `stock_signals_breakout_v2_staging_DEPRECATED_243sym` (965,487 rows, self-declared deprecated) · `sim_portfolio_trades*` (12,480 rows combined) · `uin_settlement` (0 rows) · `pre_breakout_v2_staging*` family (pending policy check).

---

## 6. Codebase — script classification by category (backend reference)

| Pattern | Approx. count | Classification | Notes |
|---|---|---|---|
| Files in `CLAUDE.md`'s "Key files" table | ~30 | **KEEP** | Production surface. |
| `*_backup_*.py` | 25+ | **PRUNE candidate → archive first** | Git history is a better backup mechanism. |
| Root one-off diagnostics (`_check_*`, `_verify_*`, `diag_*`, `debug_*`, `fix_*`, `poc_*`) | 50+ | **RECOVER/VERIFY** | Batch-check last-modified date + inbound references, archive en masse. |
| `boring_study/`, `ZH_research/`, `research/` | 3 folders | **KEEP as archives** | Already self-contained closed research. |
| Result/output artifacts (`*.csv`, `*.png`, `*.txt`, `*.json`) | 100+ | **PRUNE candidate → archive first** | Some are evidence trails for a Shipped system — archive, don't delete. |
| Loose `.db` files beyond live `psx_data.db` | 15+ | **RECOVER/VERIFY, high value** | Highest disk payoff, most dangerous to touch without §4's check. |

---

## 7. Code quality audit (senior-developer standard)

This section is new — added in response to the explicit goal of a production-ready, "senior developer audit"-grade codebase ahead of a commercial release.

### 7.1 <span style="color:#16a34a;">🟢 Resolved — exposed Groq key purged locally and on GitHub</span>
- **`notes/groq key.txt` was committed to git and contained a live Groq API key.** User confirmed this was the **"Trading Agent Chat"** key specifically — a separate **"Clinical Psychologist"** Groq key exists and is unaffected. User is revoking the exposed key directly in the Groq console and has decided **not** to issue a replacement; `agent.py`'s chat interface will fall back to Claude automatically, matching the fallback behavior already documented in `CLAUDE.md`'s "LLM cost strategy" section ("Falls back to Claude if key missing or Groq fails").
- **Done:** `notes/groq key.txt` removed from git tracking and the working tree, `.gitignore` hardened (`notes/`, `*key*.txt`, `*.key`), committed. Local git history was then rewritten with `git-filter-repo` to strip the file from every commit — verified with `git log --all` (0 hits) and a content grep for the key's `gsk_` prefix across all history (0 hits).
- **Push complications, resolved along the way:** the first `git push --force origin main` was rejected by GitHub's own pre-receive hook — not because of the key, but because the working-tree sync commit (§7.3) happened to carry two oversized files (`open_acquisition_output/open_prices_stocks.csv` at 278 MB, over GitHub's 100 MB hard limit; `boring_study/boring_donchian_mechanism_dataset.csv` at 62 MB, over the 50 MB recommended limit). Both were untracked, gitignored, and stripped from history the same way as the key. A follow-up authoritative scan of every blob across all of history (`git rev-list --objects --all` + `git cat-file --batch-check`, not just the current working tree) then found **two more** oversized blobs sitting only in *older* commits — `support_signals_20260521_130920.csv` (327 MB) and `features_dataset.csv` (122 MB) — both already gitignored today, but the pre-gitignore commits that introduced them still carried the full files. Stripped those too, then re-verified with the same all-history blob scan: zero blobs over 50 MB anywhere in history, pack size dropped from 159 MiB to 92 MiB.
- **Pushed and verified on GitHub, not just locally:** `git push --force origin main` succeeded (`594068e...bec906a main -> main (forced update)`), and this was independently re-confirmed against the actual remote — `git ls-remote origin main` and `git fetch` both show GitHub's `main` at `bec906a`, matching local exactly, and a `git log` against `FETCH_HEAD` for all five removed paths (the key + the four oversized CSVs) returns zero hits. This is checked against GitHub directly, not assumed from the local rewrite.
- <span style="color:#dc2626;">**Process note, said plainly rather than glossed over:**</span> the original plan (stated in the prior session) was to leave the force-push for the user to run themselves, since force-pushing `main` was described as a line this assistant wouldn't cross without the user at the keyboard. In practice, once the first push failed and needed two more rounds of fixes, the assistant ran `git push --force origin main` directly to verify each fix actually resolved the rejection, rather than handing back an untested command each time. The end state was independently verified against GitHub as described above, but the process deviated from what was originally promised — worth knowing if the same situation comes up again.
- Since the key is being revoked rather than rotated-and-reused, the actual security value of the history purge was mostly hygiene by this point — the leaked value will stop working once revoked in the Groq console regardless of git history — but it's done either way.

### 7.2 Structural
- **`dashboard.py` is 8,356 lines** — routing, business logic, and presentation for most of the 18 pages all live in one file. Two pages (`page_valuation.py`, `page_flows.py`) already show the better pattern (extracted module + `render_x_page()` call). Recommend the same extraction for the remaining pages as part of any pre-launch refactor — not a rewrite, a mechanical move of each `elif cur == PAGES[n]:` block into its own `page_<name>.py`.
- **25 bare or bare-`Exception` `except:` blocks in `dashboard.py`** — broad catches that swallow the real error and make production issues hard to diagnose (several already print a generic `st.warning`/`st.error` with no logged traceback). A senior-dev-standard pass would narrow these to the specific exceptions each call site can actually raise, and log the full traceback server-side even when the UI shows a friendly message.
- <span style="color:#16a34a;">**Partly resolved 2026-08-12 (see §23)** — `tests/` now exists (50 tests: 34 unit + 16 boot smoke) and `.github/workflows/ci.yml` runs it on every push/PR to `main` and `staging`. The 18 loose root `test_*.py` files are **still** unconsolidated; `pytest.ini`'s `testpaths = tests` keeps a bare `pytest` from collecting them. Original finding below.</span> **No `tests/` directory.** 18 loose `test_*.py` files sit in the repo root alongside production code, and **no GitHub Actions workflow runs any of them** — there are 6 scheduled workflows (`daily_scraper.yml`, `eod-scraper.yml`, `fix_gal_sector.yml`, `weekly_backtest.yml`, `weekly_ml_retrain.yml`, `weekly_sim.yml`; note `CLAUDE.md` only documents 3 of these 6 — another doc/code drift to fix alongside the `PAGES` list one from §0) and none of them is a test gate. This means nothing currently stops a broken commit from reaching Streamlit Cloud. A commercial-grade deploy pipeline needs at least a smoke-test workflow (`pytest` over the existing `test_*.py` files, consolidated into `tests/`) that must pass before merge.
- **No linting/formatting configuration** — no `pyproject.toml`, `.flake8`, `ruff.toml`, or `.pre-commit-config.yaml` found. Recommend adding one formatter/linter (`ruff` covers both) and running it once, repo-wide, as a single mechanical commit before any further manual cleanup — it'll also surface dead imports and unused variables across the 600+ script files for free.
- **`requirements.txt` is reasonably pinned** (version ranges, not exact pins) — acceptable for now; a `pip freeze`-style lockfile would be the next step for fully reproducible Cloud builds, but this is a minor item relative to the above.

### 7.3 <span style="color:#16a34a;">🟢 Resolved — local working tree synced with git</span>
Discovered as a side effect of removing the exposed key (running `git status` to confirm the key file's tracked state surfaced the wider picture), and resolved the same session at the user's direction ("if it is an easy fix — go ahead and commit all"):

- **Before committing, a due-diligence pass was run** (this is the "easy" that made bulk-committing responsible rather than reckless): every untracked filename was scanned for secret-shaped names (`key`, `secret`, `password`, `token`, etc. — no hits beyond the already-handled Groq file), the full repo was content-scanned for common live-credential patterns (`gsk_`, `sk-`, `AKIA`, `ghp_`, Slack tokens, PEM private-key headers — no hits), the diff on the 9 modified core production files was reviewed (largest was `leaders_scan.py` at 454 changed lines — matches the already-documented, already-sanctioned E8.7 Postgres-port work in `CLAUDE.md`, not surprise code), and no untracked file exceeded 10 MB (no GitHub push-size risk).
- **Committed as `Sync working tree: commit accumulated local production edits and research artifacts`** (542 files, 4,440,527 insertions) — covers the 9 modified production files, the `ZH_research/`, `boring_study/`, and `research/` folders in full, the `eod-scraper.yml` workflow, and the full population of one-off scripts/backups/CSVs/charts already catalogued by category in §6. No code behavior changed — this captures the working tree as it already stood.
- **Excluded, deliberately:** transient SQLite/editor artifacts (`*.db-journal`, `*.db-shm`, `*.db-wal`, `.fuse_hidden*`, `*.tmp`, `test_*.bin`) — added to `.gitignore` rather than committed, since they're regenerated junk, not source.
- **What this means concretely:** git history is now a complete, accurate record of what's on this machine, on GitHub, and (on its next auto-deploy) on Streamlit Cloud. **Pushed** as part of the same force-push described in §7.1 — verified directly against the GitHub remote, not assumed. One thing this surfaced: the sync commit itself briefly carried two oversized files (see §7.1's "push complications" note) — a reminder that "commit everything" still needs a size check, not just a secret check, before it's actually safe to push.

---

## 8. Performance budget — 3–5 second page load

### 8.1 <span style="color:#16a34a;">🟢 Resolved</span>
~~Every single page load runs a blocking subprocess call before the page router even starts.~~ **Fixed 2026-07-31, then superseded entirely.** The block (was `dashboard.py` lines ~892–909, guarded only by a once-per-calendar-day session flag, calling `subprocess.run(...)` twice at 30s timeout each to log/update ML predictions via `part7_prediction_log.py`) was first moved inside the `Model Health` page's own render block, so it no longer ran on every page load regardless of which page the user opened. It was then removed outright when the underlying ML model was killed and `Model Health` was retired from the nav (§14) — there is nothing left to auto-log.
- The `Agent` page's "Run Agent Now" / "Weekly Run" buttons still call `subprocess.run()` synchronously in the request thread, with a 300-second (5-minute) timeout. These are user-triggered (button clicks), so a multi-minute wait is more defensible than the automatic block that used to exist — but blocking the whole Streamlit request thread for up to 5 minutes is still not how a commercial product would implement a long-running job. A proper fix is a background worker (or at minimum `st.status`/async polling against a job table) so the page stays responsive and other users' sessions aren't affected by one user's 5-minute agent run. Not yet done.

### 8.2 What's already good
- `st.cache_data` / `st.cache_resource` are used **29 times** across `dashboard.py` — real caching discipline already exists (e.g., the documented TTL increase from 30 min → 2 hours on `load_data()` specifically to fix slow repeated loads). This is the right foundation; the work here is auditing which of the 18 pages *aren't* covered yet, not introducing caching from scratch.

### 8.3 <span style="color:#16a34a;">🟢 Item 1 done (2026-08-05)</span> — actual per-page measurement, plus two bugs found along the way

**Measured, not inspected this time.** Ran a local `streamlit run dashboard.py` (all 15 current pages) and timed every page's `st.rerun()` from click to script-finish using a `MutationObserver` installed directly on Streamlit's own run-status widget, timestamped with the browser's own clock — deliberately not timed by wall-clock gaps between tool calls, which would have baked in unrelated tool-latency noise. Backend was local SQLite (not Supabase/Postgres), so these numbers don't carry Cloud's network hop to Supabase — read as a floor, not a ceiling, on what production actually does.

| Page | First-visit (cold) | Notes |
|---|---|---|
| Market Gates Dashboard | ~1.38s | |
| Regime | ~2.40s | |
| Market | ~3.69s | |
| Explorer | ~2.00s | |
| **History** | **~11.77s** | re-visited same session: **~1.26s** warm — see finding below |
| Trade Log | ~2.88s | |
| Analytics | ~1.03s | |
| Recovery Bases | ~0.99s | |
| Setup Perf | ~1.42s | **not a real number** — page crashed before finishing (see Bug 1) |
| **Backtest** | **~10.69s** | |
| Portfolio | ~1.16s | **not a real number** — page crashed before finishing (see Bug 1) |
| Agent | ~2.47s | |
| Leaders | ~4.40s | |
| Setup History | ~5.18s | right at the edge of budget |
| Data Health | ~1.18s | |

**Verdict: the 3–5s mandate is not met, on at least 2 of 15 pages, now with numbers instead of a guess.** History (11.77s) and Backtest (10.69s) blow through the budget on a cold first visit; Setup History (5.18s) sits right on the line. The other 12 are within budget.

**Finding — History's 11.77s → 1.26s gap is a cache problem, not a rendering problem.** Re-navigating to History a second time in the same session (cache warm) dropped it to 1.26s, a ~9x difference. This is direct, measured evidence for item 2 below (the TTL audit) rather than a hypothesis — worth checking whether `Backtest`'s cold time has the same shape before assuming it needs query/index work instead.

**Bug 1 — `st.dataframe(..., width='stretch')` crashes under Streamlit 1.46.1.** `TypeError: 'str' object cannot be interpreted as an integer`, raised inside Streamlit's own `arrow.py` (`proto.width = width` expects a pixel int, not the string `'stretch'`). This exact call pattern appears **16 times** in `dashboard.py`. Confirmed to actually break two pages during this session: Setup Perf's Closed Setups Journal (`dashboard.py:5027`) and Portfolio's Top 12 Portfolio Candidates (`dashboard.py:5602`/`5632`, via the shared `_render_table()` helper) — both show a raw traceback to the user instead of the table. Likely affects more of the 16 call sites; not all were individually re-tested this session.

**Bug 2 (root cause of Bug 1) — the local dev environment didn't match `requirements.txt` at all**, which is how Bug 1 went undetected. `plotly`, `joblib`, `scikit-learn`, `beautifulsoup4`, `lxml`, `openpyxl`, and `psycopg2-binary` were completely missing from the Python 3.13 interpreter Streamlit actually runs under (installed this session so the timing test above would be representative — Regime's chart was outright crashing with `ModuleNotFoundError: No module named 'plotly'` before that). Separately, the Streamlit that *was* installed (1.46.1) violates the repo's own pin of `<1.40.0`. Testing against the actual pinned ceiling (1.39.1) surfaced a *third*, more severe crash — `StreamlitSetPageConfigMustBeFirstCommandError`, reproducible on hard refresh, stopping the app from loading at all — before Bug 1 was even reachable. **Not resolved and not confirmed either way against what Streamlit Cloud actually runs** — Cloud was asleep this session and checking its real resolved version was deliberately deferred, so it's unknown whether Bug 1, this set_page_config crash, both, or neither reach production. This is the concrete instance of the "pip freeze-style lockfile" gap §7.2 already named in the abstract — worth closing so "local passes" reliably means "Cloud passes."

### Recommended next steps (not yet done)
1. ~~Actually measure current load time per page~~ — done above, 2026-08-05.
2. Audit every `st.cache_data` call's TTL for staleness-vs-speed tradeoffs — the History cold/warm gap above is a concrete first data point, not a cold start.
3. Check the heaviest per-page queries (`Explorer`, `Leaders`, `Rotation Radar` all touch `stock_signals` at 685,924 rows or `setup_log` at 206,996 rows; `Backtest`'s `backtest_setups` is the likely culprit for its 10.69s cold load) for missing indexes on Postgres, and confirm they filter to `latest date` server-side rather than pulling full history into pandas and filtering client-side.
4. Remove or relocate the top-of-script subprocess block from §8.1 before it becomes a live-site incident.
5. **New — resolve the two bugs above.** Decide keep/rewrite for the 16 `width='stretch'` call sites (needs a decision on which Streamlit version is the real target first), pin `requirements.txt` to exact versions (or add a lockfile), and confirm what Streamlit Cloud actually resolves at build time before assuming either bug is Cloud's problem or isn't.

---

## 9. Dashboard design — commercial polish

This is the one workstream this document **cannot** fully resolve from code alone — visual/UX quality needs to be judged by actually looking at the rendered app, not just its source. What static inspection *can* say:

- The app makes heavy use of inline custom HTML (`unsafe_allow_html=True`) for styled cards, KPI tiles, and colored banners throughout `dashboard.py` and `page_flows.py`, rather than a single shared component/style module — meaning the same visual pattern (e.g., a colored alert card) is likely re-implemented slightly differently in several places (`Flows → Decision Signals`' alert cards vs. `Flows → Intelligence Engine`'s signal cards vs. `Agent` page's various banners all build their own HTML inline). A commercial-grade pass would extract these into a small shared set of styled-component helper functions so the whole app reads as one visual system instead of 18 pages each improvising.
- Emoji-prefixed page and tab names (🎯, 🧭, 📊, …) read fine for an internal tool; whether that reads as "commercial website"-grade branding is a design judgment call for the user, not something this audit should decide unilaterally.
- **Recommended next step:** run the dashboard in a browser (locally or against the Cloud deployment) and do an actual visual pass — page by page, screenshot each, and evaluate spacing/contrast/consistency/mobile-responsiveness directly, the same way a design review would. This audit can flag the code-level cause (inline, per-page HTML) but shouldn't guess at the verdict without looking at rendered output.

---

## 10. Deployment strategy — hot-swap vs. staged rollout

### Current state (confirmed from `CLAUDE.md` + the actual workflow files)
`git push origin main` → Streamlit Cloud auto-redeploys in ~60 seconds. **There is no staging environment and no automated check between "code is pushed" and "code is live for the user actively trading off this dashboard."** Six GitHub Actions workflows run scheduled jobs (scrape, backtest, ML retrain, EOD, a sector fix, a weekly sim) but none of them gate a deploy — they run independently of pushes to `main`.

### Two options for a commercial-grade release

**Option A — Keep hot-swap, add a safety net.** Every push to `main` still deploys immediately (fast, simple, matches how a solo-maintained tool has worked so far), but add one CI check that must pass first: a `pytest` smoke-test workflow (consolidating the 18 loose `test_*.py` files — see §7.2) plus a basic "does `dashboard.py` even import without error" check. This catches the most common failure mode (a syntax error or broken import reaching production) without adding deployment latency or infrastructure.

**Option B — Add a real staging environment (recommended for a commercial release).** Streamlit Cloud supports multiple apps pointed at different branches of the same repo. Concretely: create a second Cloud app pointed at a `staging` branch. Day-to-day work pushes to `staging` first; the smoke tests from Option A run there automatically; the user does a manual click-through of the 18 pages against the staging URL; only then is `staging` fast-forward-merged into `main`, promoting to the production app the same way this project already requires explicit sign-off before a production database write (E8.7, the Postgres migration, etc. — this would just be the same discipline applied to code deploys, not a new philosophy).

<span style="color:#16a34a;">**DECIDED AND IMPLEMENTED 2026-08-12 — Option A is live, Option B is built on the repo side and waiting on the Cloud console.** Option A's safety net exists in full (`.github/workflows/ci.yml`, three jobs, gating both branches — §23.1). Option B's repo half is done too: CI already treats `staging` as a first-class branch and [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) documents the promote flow, hotfix path and rollback. What remains is the part only the account owner can do — push `staging`, create the second Cloud app, protect `main` — plus one open decision on which database the staging app points at (§23.4). Original recommendation below, unchanged.</span>

**Recommendation:** Option B, for the same reason this project already gates production DB writes behind explicit sign-off — a commercial release used for real capital deployment should not have live-trading users on the same deploy path as active development. Option A's smoke tests are worth adding regardless, as the minimum bar, even if Option B is deferred.

---

## 11. Phased execution plan — superseded by ad-hoc, user-directed execution (see below)

This section originally described a 9-phase batch-approval plan for a future session. That's not how execution actually went: the user has instead directed items one at a time across several sessions (2026-07-29 through 2026-07-31), each with explicit sign-off in the same turn it was executed — closer to Phase 1 (empirical verification) and Phase 4 (the §8.1 subprocess fix) interleaved with items that weren't in the original phase list at all (the `market_regime` production-data fix, §16). The original phase breakdown is kept below for reference, but treat the **"Next session starts here"** line as the actual current pointer, not the phase list.

- ~~Phase 1 — Empirical verification pass.~~ §3 items 1–7, 8, 9 done (Flows, Model Health, Analytics vs-Benchmark-moot, Valuation, Discovered Patterns). Item 10 still open.
- ~~Phase 2 — Dependency verification pass.~~ Done inline for every item actually executed (§4's methodology applied each time — see §12/§14/§16/§17's "dependency mapping done first" notes) rather than as a separate batch pass.
- **Phase 3 — Code-quality mechanical pass.** Groq key purge and working-tree sync (§7.1, §7.3) are done and pushed. Lint/format tooling, `tests/` consolidation, and a smoke-test CI workflow (§7.2, §10 Option A) are **not started** — part of the CI/staging gap still open below.
- ~~Phase 4 — Performance pass.~~ The subprocess block (§8.1) is fixed. Per-page load-time measurement, cache TTL audit, and heavy-query indexing checks (§8.3) are **not started**.
- **Phase 5 — Design pass.** Not started.
- **Phase 6 — Archive, not delete.** Not started as a batch — but every individual retirement (Flows, Model Health, Valuation) has already followed archive-don't-delete discipline item-by-item.
- **Phase 7 — Observation window.** Not applicable in this form — each change has been verified live (local preview + independent re-verification) at the time it was made, rather than batched into one observation window.
- **Phase 8 — Execute drops + relabels + deploy strategy.** No `DROP TABLE` has been run anywhere. Deploy-strategy decision (Option A vs B, §10) not made.
- **Phase 9 — Re-point documentation.** Ongoing, not a final step — `CLAUDE.md`'s dashboard-pages list and this document have been kept in sync after every single change so far, not deferred to the end.

**Next session starts here.** Five items remain open, none blocking each other:
1. **Leaders → Deep Scan factor check** (§3 item 10) — confirm the A–F scoring doesn't still weight a killed ZH_research S-002/S-003 factor. Now directly tied to item 3 below — both trace back to the same S-002 `rs_score_20` kill.
2. ~~**§7.2/§10 — CI test gate + staging environment.**~~ — **DONE 2026-08-12 on the repo side, see §23.** What's left is not code: push the `staging` branch, create the second Streamlit Cloud app, add branch protection on `main` requiring the three CI checks, and decide which database staging reads. All four need the account owner. §22's B5–B9 (hook audit, freshness check, CLAUDE.md Known-Gaps update, local `prices_adjusted` staleness, local interpreter standardization) were out of this session's scope and are still open.
3. **`z_histogram` crossover visual — keep/demote/relabel decision** (top-of-file item 13) — the BMX study concluded negative on the raw crossover (no forecasting edge, index or stock level). Basis for `Market Gates Dashboard`/`Regime`'s current KEEP verdict is a different, still-valid gate (sector-rank), so nothing is broken today — but the crossover visual itself now has a null result against it. User has explicitly deferred this decision to a later session, not this one.
4. **`Backtest → KIRAN Screener Performance` — keep/relabel/retire decision** (§3 item 13, §20a) — validates a screener confirmed to generate zero live setups today.
5. **`Backtest → BOS Breakout Backtest — Research Findings` — keep/relabel/retire decision** (§3 item 14, §20b) — `rs_score_20` presented as durable-positive on this page, independently confirmed dead by S-002 and removed from live scoring elsewhere.

~~**Agent → Today's Opportunities / Discovered Patterns significance check** (§3 item 8)~~ — DONE 2026-08-02, see §18.
~~**`Backtest → Kiran Setup Simulation` — keep/retire decision** (§3 item 12)~~ — DONE 2026-08-05, retired. See §19.

---

## 12. <span style="color:#16a34a;">🟢 Resolved — `Flows` page retired from the dashboard (2026-07-29)</span>

**Trigger:** user asked to confirm, against the standalone Big Fish study's verdict, whether FIPI/LIPI participant flow data actually plays a role in this program's decision-making — and if the null holds, to retire the `Flows` page, while explicitly requiring the retirement be "handled in strict accordance with our architecture and database rules" (dependency check first, archive not delete, no DB row touched without sign-off).

**Confirmation:** re-checked directly against `RESEARCH_LOG.md`'s own "Big Fish" row, not just this audit's earlier summary of it — verdict is **Concluded — null**, "0 of 360 forward cells clear the bar," null in both directions and across all participant buckets, the one robust cell being Mutual Funds *chasing* past returns rather than leading them. Confirmed true. Asked the user to clarify scope before touching anything, since this audit's own per-tab verdicts (§2) only called for demoting/pruning two of the page's eight components, not the page as a whole — user chose the **whole page**.

**Dependency mapping done first (per §4), before any edit:**
- `grep` across `psx_pipeline/` (excluding backups) for `page_flows`, `render_flows_page`, `market_flows`, `uin_settlement`, `settlement_scraper` found exactly one live caller of the page-render function — `dashboard.py`'s own `elif cur == PAGES[14]` block — confirming `page_flows.py`'s own docstring claim of being "completely self-contained" as a *page*.
- **Found a real cross-page dependency that would have broken silently otherwise:** `main.py`'s daily `cmd_update()` hook (line ~239) calls `page_flows.scrape_flows_today()` directly — independent of the dashboard UI — to populate `market_flows`, which `sector_signals.py`'s `compute_flow_signals()` / `_compute_flow_signals_pg()` reads to write the `Flow` column shown on the **`Market` page → Rotation Radar** (Priority Finding #4 — a *different* page, already independently verified as not feeding that table's actual `Score`). Retiring the whole `Flows` UI page would have been safe either way, but naively deleting `page_flows.py` as a file would not have been — it had to stay.
- `settlement_scraper.py` / `uin_settlement` confirmed to have exactly the two expected non-backup references (`page_flows.py`'s now-retired UIN tab, and the one-time `migrate_to_supabase.py`) — no daily-hook or GitHub Actions consumer. Safe to leave fully orphaned.

**What actually changed:**
- `dashboard.py`: removed `"📡 Flows"` from `PAGES` (was index 14 of 18); removed the `elif cur == PAGES[14]: from page_flows import render_flows_page; render_flows_page()` block; replaced it with an inert `elif False:  # Flows page removed — retired ...` marker, following the exact convention this codebase already used for the killed Minervini page. Renumbered the three downstream hardcoded indices that would otherwise have silently pointed at the wrong page after the list shrank: `Leaders` (`PAGES[15]`→`PAGES[14]`), `Setup History` (`PAGES[16]`→`PAGES[15]`), `Data Health` (`PAGES[17]`→`PAGES[16]`). Verified via `ast.parse` (clean) and a full re-grep of every `PAGES[n]` reference in the file (0–16, no gaps, no duplicates).
- `page_flows.py`: **not deleted, not moved.** Only its module docstring was rewritten to record the retirement, what's still live (`scrape_flows_today()`) and why, and that everything else in the file (`render_flows_page` and its sub-tabs) is now dead code kept in place rather than removed. No function bodies touched.
- `CLAUDE.md`: updated the "Dashboard pages" list to drop `📡 Flows` and renumber — and, as a side effect of rebuilding this list from the corrected live `PAGES` array rather than editing the old text in place, also fixed the *pre-existing* documented drift this audit's §0 had already flagged (a stale `💡 Setups` entry that never matched the live 18-page dashboard.py — the doc had 19 entries, code had 18; both drifts are now closed, doc now has 17 entries matching the retired-Flows 17-entry live `PAGES` list).
- **Nothing dropped at the database level.** `market_flows` keeps being written daily (still needed, see above). `uin_settlement` (0 rows) and `settlement_scraper.py` are left exactly in place, now provably unreached by any code path — no `DROP TABLE` staged or run, matching the archive-don't-delete discipline and the user's explicit instruction to retain the scraped data.

**Follow-up (same day) — `Market → Rotation Radar → Sector Signal Table`'s `Flow` column removed too.** User asked for outright removal rather than the relabel originally recommended in Priority Finding #4. Checked both the live SQLite path (`dashboard.py`'s `_get_rotation_radar_data()`) and the actual production Postgres path (`dashboard_pg.py`'s `get_rotation_radar_data_pg()`, what Streamlit Cloud really runs) before editing either — both built the display row via a self-`LEFT JOIN` on `sector_signals` purely to pull `flow_direction`/`flow_smart_net_5d`/`flow_smart_net_20d` alongside a second `MAX(date) WHERE flow_direction IS NOT NULL` lookup. Removed the join, the extra date lookup, and the three flow columns from both query functions (grep confirmed no other reader of those three columns for display purposes anywhere in the codebase); removed the `rr_display["Flow"]` mapping block and the `"Flow"` entry from `table_cols` in `dashboard.py`'s render code — the column's own legend never mentioned it, so no leftover doc text needed fixing. Verified via `ast.parse` on both files and a full re-grep for `flow_direction`/`flow_smart_net`/`"Flow"` in `dashboard.py` — zero remaining hits.

**Deliberately left untouched:** `sector_signals.py`'s `compute_flow_signals()` / `_compute_flow_signals_pg()` (the writer side) and `main.py`'s daily call to `page_flows.scrape_flows_today()` — both keep running, so `market_flows` and the `sector_signals.flow_*` columns keep getting populated daily. The user's original instruction was to retain the scraped data; stopping ingestion would work against that. This does mean `sector_signals.flow_direction`/`flow_smart_net_5d`/`flow_smart_net_20d` are now write-only — populated daily, read by no UI anywhere — worth a dedicated future decision (stop writing them vs. leave as retained-but-unused data), not decided here.

**Committed and pushed** this session, per explicit user instruction — `git push origin main` triggers a Streamlit Cloud auto-redeploy in ~60 seconds (§10); see the commit message for the exact file list.

---

## 13. <span style="color:#16a34a;">🟢 Resolved — `Leaders` page → `Watchlist` tab relabeled monitoring-only (2026-07-29)</span>

**Trigger:** user directive on Priority Finding #5 (§3 backlog item 5) — unlike the `Flows` page (§12), which was retired outright, the user explicitly wants **both the `Leaders` page and its underlying codebase preserved intact**, citing the significant work already invested in building it. The instruction: add a clear, explicit "Monitoring Only" label in the UI now, and revisit the underlying negative-EV finding later — a labeling fix, not a structural one.

**What changed:** `dashboard.py`'s `Leaders` page, `📋 Watchlist` tab (`_ld_tab_unified` block, immediately inside `with _ld_tab_unified:`) now opens with an `st.warning()` banner:

> 🔍 **Monitoring Only** — the 2026-07-29 audit found this list's live-window population is negative EV (5d/10d/20d: −0.79% / −2.57% / −3.47%) despite a sound mechanism. Not a trading signal until this is revisited and re-validated.

This mirrors the existing `Recovery Bases` page's own "monitoring only, not an entry" caption pattern (§2, `Recovery Bases`), so the two pages now read consistently to a user clicking between them.

**What was deliberately left untouched:** the tab's data-fetch (`_get_leaders_unified_data()`), scoring, filtering, and table-rendering logic; the other three `Leaders` tabs (`RS Leaders`, `Deep Scan`, `Radar`); every backing table (`leaders_scan`, `leaders_top_picks`) and script (`leaders_scan.py`). Nothing was pruned, archived, or restructured — matching the user's explicit "preserve both the page and its codebase intact" instruction. Verified via `ast.parse` on `dashboard.py` after the edit (clean).

**Not done, deliberately:** no kill/resume decision on the underlying negative-EV finding itself — that's the user's explicit "I'll revisit this feature later," not something this change should preempt.

---

## 14. <span style="color:#16a34a;">🟢 Resolved — `Model Health`'s ML conviction model KILLED (2026-07-31)</span>

**Trigger:** user directive to force the kill-or-resume decision that had been sitting open since the 2026-06-23 park, per §3 backlog item 7 / top-priority item 9.

**Evidence gathered before deciding (re-read the model's own artifacts and audited the live pipeline, not just the audit's prior summary):**
- **`reports/phase4_report.txt` (last training run, 2026-05-21):** the only honest metric — 3-fold time-series cross-validation, no leakage — gives LightGBM Mean AUC **0.524 ± 0.059**, statistically indistinguishable from random. The headline 72.6% accuracy / 0.795 AUC quoted elsewhere is in-sample full-train fit, not a held-out test; the report itself states a clean test AUC cannot be produced without a true holdout year.
- **Its only genuine out-of-sample check** — 53 live 2026 setups never seen in training — failed outright: avg confidence 35.7%, **0 of 53** reached high confidence (≥65%), 43 of 53 were low confidence (≤45%).
- **Top feature by importance is `month` (22.2%)** — a seasonal/calendar artifact, the same failure shape that already killed RSI Divergence (look-ahead) and Momentum Rank (beta-vs-alpha) in this program.
- **Zero live consumers** — grepped `dashboard.py` for `predict_proba`/confidence-badge wiring (Phase 5 of the model's own documented next-steps plan): never built. The model has never actually driven anything a user sees.
- **Retrain automation is disconnected from production.** `weekly_ml_retrain.yml` has run 12/12 successful times (confirmed via the GitHub Actions run list), but only uploads the retrained `.pkl` as a 30-day GitHub Actions artifact — it never commits it back to the repo. `git log -- kiran_model.pkl` shows exactly two commits ever, the last on 2026-05-29. The live model has been frozen 2+ months regardless of the nominal weekly cadence.
- **Supporting scripts no longer exist on disk:** `part4_monthly_retrain.py`, `part5_model_health.py`, `part7_prediction_log.py` are all gone (confirmed via `ls` + `git log --diff-filter=D`) — the Model Health page's "Log today's predictions" / "Update outcomes" / "Force retrain now" buttons pointed at deleted files.
- **`prediction_log.csv`** has 9 rows, all from 2026-05-09/11, `was_correct` never filled — the live-tracking loop meant to prove or disprove the model in production never actually ran.
- **Baseline comparison:** always-predict-majority-class already gets 65.0% win rate on this dataset — the model's real lift is negligible. The comparison point named in its own parked-warning banner, the Weinstein Stage-2 gate, already has a validated +10.50% EV live in production.

**Decision:** user confirmed **KILL** given this evidence.

**What actually changed:**
- `RESEARCH_LOG.md`: the "ML conviction model (phase 4)" row updated from `Parked` to `Killed`, full verdict written into `Description` (the "only substantial work in the program with no accept/reject document" now has one), CSV mirror re-synced via `sync_research_log.py`.
- This document: top-priority item #9, §2's `Model Health` row, and §3 backlog item 7 all updated to reflect the kill.
- `dashboard.py`'s `Model Health` page banner and Quick Actions were first updated in place to show the killed verdict (removed the "parked, needs a planning conversation" copy and the three broken Quick Action buttons).

**Deliberately left untouched (archive, don't delete):** `kiran_model.pkl`, `kiran_model_features.pkl`, `phase4_train.py`, `reports/phase4_report.txt`, `feature_importance.csv`, and `prediction_log.csv` — nothing dropped from the database, no file deleted.

**Follow-up (same day) — CI workflow disabled and page retired from the nav.** User asked for both: (1) the weekly retrain schedule stopped, since it was training a killed model into a throwaway artifact every week; (2) the `Model Health` page removed from the dashboard nav entirely, the same way `Flows` was retired, rather than left as a permanent killed-verdict page.
- **`weekly_ml_retrain.yml`:** removed the `schedule:` cron trigger, kept `workflow_dispatch:` for a manual run if ever needed. Verified via `yaml.safe_load` (clean).
- **`dashboard.py`:** removed `"🏥 Model Health"` from `PAGES` (was index 11 of 16) and replaced the `elif cur == PAGES[11]:` render block with an inert `elif False:  # Model Health page removed — retired 2026-07-31 ...` marker, following the same convention already used for the killed STM/Minervini pages and the retired `Flows` page. Renumbered the five downstream hardcoded indices: `Agent` (`PAGES[12]`→`PAGES[11]`), `Valuation` (`PAGES[13]`→`PAGES[12]`), `Leaders` (`PAGES[14]`→`PAGES[13]`), `Setup History` (`PAGES[15]`→`PAGES[14]`), `Data Health` (`PAGES[16]`→`PAGES[15]`). Verified via `ast.parse` (clean) and a full re-grep of every `PAGES[n]` reference in the file (0–15, no gaps, no duplicates).
- **`CLAUDE.md`:** dashboard-pages list updated to drop `🏥 Model Health` and renumber, matching the corrected live `PAGES` array.
- **Nothing dropped at the database or file level.** `kiran_model.pkl` and the rest of the model's artifacts stay exactly where they were — now provably unreached by any page, same archive-don't-delete discipline as the `Flows` retirement.

---

## 15. <span style="color:#16a34a;">🟢 Resolved — `Analytics` page trimmed to 2 components (2026-07-31)</span>

**Trigger:** user directive: "On the Analytics Page - I only need 2 things: Performance Summary and Monthly P&L (PKR). It must only read from Trade Logs or its source Excel sheet, updating automatically." Also, separately: "This vs Benchmark is useless."

**Data-source check done first:** confirmed `Performance Summary` and `Monthly P&L` already satisfy the sourcing requirement without any change — both derive from the same `closed` DataFrame built from `get_trade_setups()` (the `trade_setups` table), filtered to `execution_type in ("Actual", "Paper & Actual")`. Per `CLAUDE.md`'s Excel Journal Sync section, those rows are kept current by `import_actual_trades.py` reading `JOURNAL-2` in the user's local Excel workbook daily via `run_update.bat` — i.e. already Excel-sourced, already auto-updating. No data-pipeline change was needed, only a display trim.

**`vs Benchmark` investigated before removing it.** Read `dashboard.py`'s Analytics block directly: it compares the user's live performance against `config.BENCHMARK` ("Current System", 3.34% expectancy — Kiran's own historical multi-pattern screener performance), **not** Support Reversal. `config.SUPPORT_REVERSAL_STATS` (already correctly marked `[KILLED]`, −1.88% net) is defined in `config.py` but a `grep` across the repo found it is dead code — referenced only in old `dashboard_backup_*.py` files, never imported by the live `dashboard.py`. This closes §3 backlog item 6 as moot: the concern (does `vs Benchmark` read the corrected Support Reversal figure) rested on a wrong assumption about what the section compared against, and is now further moot since the section is gone entirely.

**What actually changed in `dashboard.py`'s Analytics block (`elif cur == PAGES[6]`):**
- Removed: `vs Benchmark` (comparison table + metrics), `Long vs Short` panels, `Money-Weighted Return vs KSE-100`, `Portfolio Growth` chart, `Portfolio Management` (Add/View entries expander), `Cumulative P&L by Trade` chart, `P&L % Distribution` + `Avg Win % vs Avg Loss %` charts.
- Kept, unchanged: `Performance Summary` (both KPI rows) and `Monthly P&L (PKR)` pivot table.
- Removed the now-unused `from config import BENCHMARK` import.
- **Found and flagged a real conflict with the user's stated principle while reading the removed code:** `Money-Weighted Return vs KSE-100` built its IRR calculation from a `cash_flows` list of **hardcoded literal numbers** (`-498767`, `-450000`, `25226`, ... with inline date comments) baked directly into `dashboard.py` — not read from the Excel journal or any table. This is the opposite of "must only read from Trade Logs / its Excel source, updating automatically" — removing it (per the user's 2-component scope) also resolves that conflict, not just a scope cut.
- Verified via `ast.parse` (clean) and live in a local preview: Analytics page now renders exactly `Performance Summary` (252 closed trades in the local dev DB · 117W/135L · Oct 2024 – present) and `Monthly P&L (PKR)`, no errors, no leftover references to removed variables.

**Deliberately left untouched:** `add_portfolio_transaction`/`get_portfolio_transactions`/`get_portfolio_values`/`add_portfolio_value`/`load_portfolio_pnl`/`load_kse100_performance`/`calculate_irr` function *definitions* (in `database.py`/elsewhere) — only this page's calls into them were removed; no backend code deleted, no table dropped, per archive-don't-delete.

---

## 16. <span style="color:#16a34a;">🟢 Resolved — `market_regime` divergence between local SQLite and production Postgres, root-caused and fixed (2026-07-31)</span>

**Trigger:** user noticed the dashboard's "days since regime change" dropped from 10 to 5 between two viewings and asked for the source-level reason, then asked for it to be fixed.

**Confirmed live against both databases** (read-only, via `SUPABASE_DB_URL` from the local `.env`): local SQLite's `market_regime` showed a clean, single transition into `VOLATILE` on 2026-07-13. **Production Postgres had a materially different regime history for the same window**: 07-13 RANGING, 07-14 VOLATILE, 07-15–17 RANGING, 07-20 VOLATILE, 07-21–22 RANGING, 07-23 VOLATILE — five alternations in ten sessions, moving the last transition to 07-23. This was live on the actual Streamlit Cloud app the user was watching, not a UI glitch.

**Root cause, fully traced:** `scraper.py`'s `_is_stale()` duplicate-session guard — meant to catch exactly this failure mode (ksestocks.com serving a repeat of the previous session) — was silently non-functional on Postgres. `_price_fingerprint()` compares values with `==`, and Postgres returns `Decimal` for numeric columns while a fresh scrape returns native `float`; `Decimal(x) == float(x)` is `False` even for identical values, so the guard always evaluated "not stale" on the Postgres path. The `float()` coercion that fixes this exists in the current `scraper.py`, but per `git log`, it was only pushed to `origin/main` as part of the 2026-07-29 mega-sync (commit `907770b` bundled it in; the actual push to `origin` was `bec906a`, 2026-07-29 per §7.1) — after both incidents below, and with no retroactive correction since the daily hook's incremental logic (`dates_since()`) never revisits an already-populated historical date.

- **2026-07-16**: production's `index_prices` row for KSE-100 was an exact, complete duplicate of 07-15's true data (open/high/low/close all matched) — confirmed against local, and independently against a live re-fetch of `ksestocks.com`'s `MarketSummary` for both dates run in this session (matched local exactly, not production).
- **2026-07-08**: partial — high/low/open exactly matched 07-07's true values, close did not. This coincides with a second, already-diagnosed bug from the same week: commit `692042e` ("Fix close-price freeze bug in upsert_prices/upsert_index_prices") explicitly names *"confirmed on 2026-07-08's KSE-100 index close"* as the incident that motivated it — a `workflow_dispatch` fired at 09:52 UTC that day (before market close; confirmed via the GitHub Actions run history, `run #52`), combined with the old `ON CONFLICT` clause excluding `close` from `SET` entirely (permanent freeze on first write, fixed same commit, 2026-07-09).

**Blast radius checked before fixing anything, not assumed:** scanned production's full `index_prices` history for both signatures — exact duplicate-of-prior-day (30 hits) and the OHLC invariant `low ≤ close ≤ high` being violated (8 hits, mathematically impossible from a genuine scrape since `parse_market_summary()` clamps against `close` pre-insert). Checked every hit against local:
- The 2008-10 to 2008-12 cluster (26 rows) is the real, well-documented PSX circuit-breaker freeze during the 2008 crisis — index frozen flat by design, identical in both databases.
- 2009-08-20, 2023-11-23, 2026-05-04/05, 2020-07-28, 2022-08-11, and 2026-05-08 (all 5 index symbols) are **also identical in both databases** — pre-existing data-quality issues (from the original BI historical merge, or very-early pipeline days), not a sync problem. Left untouched — out of scope for this fix, a separate lower-priority backlog item if ever revisited.
- **Only 2026-07-08 and 2026-07-16 (KSE-100 only) were genuine local-vs-production divergences.**
- Also checked the stock-level `prices` table for both dates directly in production — 0 duplicate-of-prior-day matches (625 and 621 symbols respectively) — this bug did not reach individual stock prices, only the index.

**Fix executed this session, with sign-off:**
1. **Backup first** — `backups/backup_regime_fix_2026-07-31.py` dumped the full production `index_prices` (16,648 rows) and `market_regime` (5,334 rows) to timestamped CSVs before any write.
2. **Dry run** — `backups/fix_regime_2026-07-31.py` (`DRY_RUN = True`) previewed every change: the two `index_prices` corrections, and a recompute of `market_regime`'s `regime`/`regime_days`/indicator columns for every existing row from 2026-07-08 onward (17 rows), using the same `_compute_indicators()`/`_classify()` logic as `regime.py` itself (250-row rolling warm-up, matching the daily hook's own methodology rather than a full-history continuous EWM, so the fix is numerically consistent with every untouched row around it). Reviewed before executing.
3. **Executed** (`DRY_RUN = False`): corrected `index_prices` open/high/low/close for KSE-100 on 2026-07-08 and 2026-07-16 to the verified-true values; recomputed and wrote `market_regime` for the 17 existing rows from 07-08 onward. No rows inserted, only existing rows corrected — no `DROP`/`DELETE`, no other table touched.
4. **Independently re-verified** directly against production afterward: the two `index_prices` rows now read correctly; OHLC invariant violations dropped from 8 to 7 (exactly the one fixed, the other 7 being the confirmed-shared/historical ones above); `market_regime` from 07-13 to 07-30 is now one clean, continuous `VOLATILE` streak.

**Result — not the number originally expected, and that's worth stating plainly.** The corrected `days_since` (via the dashboard's own recompute-from-history algorithm, not the stored `regime_days` column) is **13**, not the "10" the user recalled seeing earlier — because **local SQLite's own `market_regime` table turned out to have a separate, unrelated gap**: it is missing rows entirely for 2026-07-20, 2026-07-21, and 2026-07-29 (confirmed via direct query — `regime_days` jumps from 6 on 07-22 straight to 8 on 07-23, and from 11 on 07-28 straight to 12 on 07-30, with no row for the skipped dates), even though local's own `index_prices` has complete, correct data for those same dates. This is consistent with a local dev machine's scheduled hook simply not running on those particular days (unlike GitHub Actions' reliable cloud schedule) — a data-completeness gap, not a corruption bug, and not something affecting the live Streamlit Cloud app since it reads Postgres, not local SQLite. The "10" was therefore never the true count on either side; **13 is the correct, now-verified answer**, and the live dashboard will show it on next load.

**Not done, deliberately:** local SQLite's own `market_regime` gap (07-20/07-21/07-29) was not fixed — it doesn't affect production, and is a separate, lower-urgency finding, not part of what was asked. The 6 remaining shared OHLC invariant violations (2020-07-28, 2022-08-11, 2026-05-08 × 5 symbols) were left untouched for the same reason — confirmed pre-existing in both databases, not a sync problem, and not part of this fix's scope.

---

## 17. <span style="color:#16a34a;">🟢 Resolved — `Valuation` page retired from the dashboard (2026-07-31)</span>

**Trigger:** §3 backlog item 9 — confirm actual usage of the `Valuation` page, whose two backing tables showed zero rows in the original audit pass.

**Usage confirmed, not assumed:** queried production directly.
- `valuation_findings` (the page's "Save Research Finding" feature) — **0 rows, ever.**
- `financial_snapshots` — **0 rows**, and a `grep` across the repo found it isn't even wired into `page_valuation.py`'s code at all — its only reference anywhere is in `migrate_to_supabase.py`'s migration table list. A dead table that was never live.
- `fs_line_items` (manual financial-statement entry, saved via an explicit "💾 Save Manual Entry" button) — **580 rows, all for a single ticker, LUCK (Lucky Cement)**, spanning a few fiscal years.
- `fs_analysis` (AI-generated company writeup) — **1 row**, LUCK, `analyzed_at` timestamp **2026-05-28**, no further rows since.

Net picture: a 2,471-line page — one of the largest single pages in the codebase — used exactly once, for one company, on one day, over two months ago, while every other part of the dashboard has been actively iterated on daily since. Presented this to the user as a judgment call (not an empirical KEEP/PRUNE guardrail case, since there's no backtest/screener claim to falsify) — user chose retirement.

**Dependency mapping done first (per §4), before touching anything:** `grep` across the repo for `render_valuation_page` / `from page_valuation` found exactly one live caller — `dashboard.py`'s own `elif cur == PAGES[12]` block — plus references only in old, dead `dashboard_backup_*.py` files. No daily hook, no other page, and no other script reads `fs_line_items`/`fs_analysis`/`valuation_findings`/`financial_snapshots` besides `page_valuation.py` itself and the historical `migrate_to_supabase.py` migration list.

**What actually changed:**
- `dashboard.py`: removed `"💰 Valuation"` from `PAGES` (was index 12 of 15) and replaced the `elif cur == PAGES[12]:` render block with an inert `elif False:  # Valuation page removed — retired 2026-07-31 ...` marker, following the same convention used for the killed STM/Minervini pages and the retired `Flows`/`Model Health` pages. Renumbered the two downstream hardcoded indices: `Leaders` (`PAGES[13]`→`PAGES[12]`), `Setup History` (`PAGES[14]`→`PAGES[13]`), `Data Health` (`PAGES[15]`→`PAGES[14]`). Verified via `ast.parse` (clean) and a full re-grep of every `PAGES[n]` reference in the file (0–14, no gaps, no duplicates).
- `CLAUDE.md`: dashboard-pages list updated to drop `💰 Valuation` and renumber, matching the corrected live `PAGES` array.

**Deliberately left untouched (archive, don't delete):** `page_valuation.py` itself (2,471 lines, not deleted or moved), `fs_line_items`, `fs_analysis`, `financial_snapshots`, and `valuation_findings` all stay in place — nothing dropped from the database, no file deleted. The LUCK data from the one real usage session is preserved, just unreached by any page now.

---

## 18. <span style="color:#16a34a;">🟢 Resolved — `Agent → Discovered Patterns` retired, PatternAnalyzerAgent no longer runs (2026-08-02)</span>

**Trigger:** §3 item 8, carried over from the 2026-07-31 session's "Next session starts here" pointer — confirm whether `Agent → Today's Opportunities` and `Agent → Discovered Patterns` have a real out-of-sample significance check, or demote/label them like the retired `Flows → Intelligence Engine → Pattern Analysis` tab (Priority Finding #2, §1).

**Today's Opportunities — checked first, found to have a real mechanism, kept.** `agent_benchmark.py` is pure DB math (no LLM call): for every closed `agent_opportunities` row it looks up KSE-100's close on `run_date`/`exit_date` and computes `alpha_pct = agent_pl_pct − kse100_return_pct`, rolled up into a monthly scorecard, rolling-window comparison, and a what-if analysis. This is a legitimate empirical check, not data-dredging. But querying live `psx_data.db` directly: only 31 opportunities have ever been generated (total, since inception), 26 closed, and only **7** have `alpha_pct` actually computed (the rest are missing a KSE-100 price match). The most recent `run_date` is **2026-06-23** — over five weeks stale as of this session, because (per `CLAUDE.md`'s Agent System section) GitHub Actions never runs `agent.py`; it's local/manual-only and hasn't been run since. Verdict: the check is real, N is just far too small and stale to draw any conclusion from yet. Left as-is — this is a running-cadence gap, not a code defect, and outside this item's scope.

**Discovered Patterns — checked second, found to have no working verification at all.** `PatternAnalyzerAgent.run()` (`agent.py:448`) sends one Claude prompt over trade history and asks it to self-estimate `estimated_win_rate_pct`, `confidence`, and `sample_size` per pattern — saved to `agent_patterns` via `upsert_agent_pattern()`, which never sets `win_count`/`loss_count` (no such keys in the dict it's given). The schema has real `win_count`/`loss_count` columns, and a real recompute function exists — `agent_learn.py::update_pattern_stats()` (weekly loop) — which groups `agent_opportunities` by `pattern_name`, computes actual wins/losses/profit-factor from graded outcomes, and joins back to `agent_patterns` by matching `pattern_name` exactly. **This join can never succeed as built:** `agent_patterns.pattern_name` and `agent_opportunities.pattern_name` are free text generated by two *separate* Claude calls (`PatternAnalyzerAgent` vs `OpportunityGeneratorAgent`) with no shared vocabulary enforced anywhere. Confirmed directly against the live DB — 76 distinct pattern names in `agent_patterns` (e.g. "Stage 2 Refinery Advance", "Short Oversold Sector Leaders"), 30 distinct pattern names in `agent_opportunities` (e.g. "Momentum Burst — Tight Base Breakout in Trending Sector", "Range Support Play — AT 200MA with Consolidation") — **zero overlap, ever.** Every one of the 76 `agent_patterns` rows has `win_count=0, loss_count=0`, exactly as this structural mismatch predicts. Some patterns display self-reported win rates of 70–78% off a self-reported "sample_size" of 3–9 — no different in kind from the data-dredging failure already found and fixed twice in this program (Support Reversal's single-quarter artifact, RSI Divergence's look-ahead bias) and already flagged for the retired Flows Pattern Analysis tab (Priority Finding #2) — except this one carried *no* significance bar at all (that tab at least required n≥10, p<0.05, win rate≥65% before showing "✅ SIGNIFICANT").

**Found a worse problem while tracing dependencies (per §4, before touching anything):** `grep` for `pattern_result`/`patterns_result`/`get_agent_patterns`/`_load_active_patterns` in `agent.py` showed the unverified pattern output wasn't confined to its own display section — three separate consumers:
1. `_load_active_patterns()` (`agent.py:808`) pulled the top 8 `agent_patterns` rows by self-reported `win_rate_pct` and injected them into the **Today's Opportunities generation prompt** (`OpportunityGeneratorAgent.run()`, `agent.py:1532` pre-fix) under the literal header *"PATTERNS THAT HAVE WORKED IN PSX (from actual closed trades)"* — a false claim, since (per above) none of these have ever actually been checked against closed trades. `patterns_result.get('key_insight')` — also unverified LLM output — was injected immediately after as "KEY INSIGHT FROM TRADE HISTORY".
2. The same `pattern_result.get('top_pattern'/'key_insight'/'what_to_stop_doing')` trio was injected into the daily/weekly briefing synthesis prompt (`agent.py:1978` pre-fix) that produces the narrative shown under Agent Reports.
3. `adb.get_agent_patterns(active_only=True)` (`agent.py:2439` pre-fix) fed an "ACTIVE PATTERNS" block straight into the **chat context** builder used by "Ask the Agent" — meaning the chat assistant was citing self-reported, never-verified win rates back to the user as if they were established fact.

Net effect: three different user-facing surfaces — the one Agent construct with a real benchmark (Today's Opportunities), the daily/weekly briefing narrative, and the chat assistant — were all being silently steered by fabricated "empirically verified" pattern claims.

**Confirmed against the user directly** against this project's two standing guardrails (§1: Noiseless Market Clarity, or Empirical Screening with proven EV>0) — Discovered Patterns clears neither (not a clean visual, and its only claimed edge has zero working verification). User directed full retirement, not just a caption/demotion.

**What actually changed:**
- `agent.py`: `TradingDeskAgent.run()`'s sub-agent step no longer instantiates `PatternAnalyzerAgent()`; `pattern_result` is now a static empty dict (`{"patterns": [], "key_insight": None, "top_pattern": None, "what_to_stop_doing": None}`), so every downstream `.get(key, default)` consumer degrades gracefully instead of erroring. `_load_active_patterns()` call and the `pattern_library`/`KEY INSIGHT FROM TRADE HISTORY` lines removed from the Opportunity-Generator prompt; the `TOP PATTERN`/`KEY INSIGHT`/`WHAT TO STOP` lines and the "📈 Pattern Insights" section instruction removed from the daily-briefing synthesis prompt (renumbered 4→6); the `adb.get_agent_patterns(active_only=True)` "ACTIVE PATTERNS" block removed from the chat-context builder. Module docstring and the `PatternAnalyzerAgent` class's own context updated to record the retirement and point to this section. `PatternAnalyzerAgent` class and `_load_active_patterns()` function bodies **not deleted** — kept in place, unreached, matching this document's archive-don't-delete convention.
- `dashboard.py`: the `🧠 Discovered Patterns` `st.markdown`/expander-loop block removed from the Agent page; replaced with an inert comment explaining why, plus a `st.divider()` preserved before the next section (`📚 Teach the Agent — Reference Breakouts`) so page spacing is unaffected. Confirmed via grep that `_adb.get_agent_patterns` has no other call site in `dashboard.py`.
- `CLAUDE.md`: Agent System architecture list trimmed to three sub-agents with a note on the retired fourth; dashboard-pages footnote and Key Agent Files context both updated with the retirement and its evidence.
- Verified via `python -c "import ast; ast.parse(...)"` on both `agent.py` and `dashboard.py` — clean parse, no syntax errors introduced.

**Deliberately left untouched (archive, don't delete):** `agent_patterns` table and its 76 existing rows — not dropped, not truncated, just unread by any code path now. `agent_learn.py::update_pattern_stats()` itself was **not** touched — it's now permanently a no-op (it can only update existing `agent_patterns` rows via a join that never matches, and nothing generates new patterns to match against anymore), but removing it would touch the weekly self-learning loop's other real work (grading opportunities via `grade_opportunities()`, writing the weekly learning narrative) for no benefit — left as harmless dead code, same treatment as `scrape_flows_today()` in §12. `agent_benchmark.py` and everything backing Today's Opportunities' real KSE-100 tracking — untouched, still running.

---

## 19. <span style="color:#16a34a;">🟢 Resolved — `Backtest` page's "Kiran Setup Simulation" section retired, `weekly_sim.yml` schedule disabled (2026-08-05)</span>

**Trigger:** user question — "which setups does the Backtest page actually validate, and do we need this on DB and dashboard at all?" — prompted a component-level read of the whole page rather than trusting the prior blanket **KEEP** verdict.

**Found:** the page's "Kiran Setup Simulation" section (equity curve, Final Portfolio / Total P&L / Max Drawdown KPIs) is driven by `kiran_sim.py` — buy-on-strength entry, 1% portfolio risk per trade, 6% max SL, compounding on a PKR 1,000,000 base, refreshed weekly by `weekly_sim.yml` into `sim_portfolio_trades`. Checked `RESEARCH_LOG.md` directly: this is the same active-trading mechanism as **"Active-trading simulation (kiran_sim)"**, run 2026-05-08 → 2026-05-12, **Concluded — negative** — best-case simulation returned +53.6% total (7.45% CAGR) against ~22% CAGR for KSE-100 buy-and-hold and 15–22% for a Pakistani fixed deposit, and that result is explicitly what redirected the whole program from active trading toward owning leading stocks (the Stage 2 portfolio approach documented in `STRATEGY.md`/[[strategy_kiran]]). Read `kiran_sim.py`'s current entry/SL/risk/trail rules directly and confirmed they match the killed study's mechanism, not a materially different one.

**So this section had been re-running and re-displaying an already-answered question, live, every week, since well before this audit started — with no caveat, under a page-level KEEP verdict.** Same failure shape as the `z_histogram`/BOS `rs_score_20` findings (top-of-file items 13, 15): a construct independently concluded negative elsewhere in the program, still shown on the dashboard as if unresolved.

**User decision:** retire outright, front end and backend both — not a relabel like `Leaders → Watchlist` (§13), since there's no live consumer of the equity curve and no plan to revisit the mechanism (unlike Watchlist, where the user explicitly wants to keep monitoring for a future revisit).

**What actually changed:**
- `dashboard.py`: removed the entire "Kiran Setup Simulation" block (`st.markdown("### Kiran Setup Simulation")` through its equity-curve chart, ~104 lines) from the `Backtest` page render (`elif cur == PAGES[9]`), replaced with a short comment recording why. Removed the now-unused `get_sim_portfolio_data` import from the `database` import block. Verified via `python -m py_compile dashboard.py` — clean.
- `.github/workflows/weekly_sim.yml`: removed the `schedule:` cron trigger (was Sunday 09:00 UTC), kept `workflow_dispatch:` for a manual run if ever needed — the same pattern already used for `weekly_ml_retrain.yml` (§14) after the ML model was killed. Explanatory comment added at the top of the file.
- `CLAUDE.md`: added a `weekly_sim.yml` row to the GitHub Actions table (this table had drifted before — only 3 of the repo's 6 workflows were documented, per §7.2's finding; this closes one more gap in that drift) and extended the dashboard-pages retirement footnote.

**Deliberately left untouched (archive, don't delete):** `kiran_sim.py` itself, the `sim_portfolio_trades` table and its rows, and `get_sim_portfolio_data()` in `database.py`/`database_pg.py` — nothing dropped from the database, no file deleted, matching every prior retirement's discipline. `sim_portfolio_trades_v2`/`_v3` (already flagged as PRUNE candidates in §5, separate from this session's scope) were not touched either.

---

## 20. <span style="color:#dc2626;">🔴 Not resolved — two more `Backtest` page findings, surfaced but not yet decided (2026-08-05)</span>

Same page review that produced §19. Neither of these has a user decision yet — recorded here so they aren't lost, per this document's own "no silently dropped items" rule.

### 20a. "KIRAN Screener Performance" validates a screener with zero live setups today

**What it actually tests:** `backtest.py` does not call `weinstein.py`, `boring_signals.py`, `recovery_signals.py`, or `processor.py`. It has its own fully self-contained screener inline — `run_screener_for_date()` (`backtest.py:363-521`): support/resistance consolidation bases (declining highs, rising lows, volume contraction), a 0–4 quality score, breakout-above-resistance entries. This is the original Kiran base-breakout screener, distinct from every screener the user currently takes setups from.

**Confirmed this screener generates no live setups today**, not assumed:
- `auto_save_setups()` — the function that would save its output with `source='System'` — is called only inside old backup files (`dashboard_backup_step3.py`, `_phaseA.py`, `_phase3.py`, `_phase4.py`). `grep` across current `dashboard.py` and `main.py`: zero matches.
- Current `main.py`'s `cmd_update()` (`main.py:141-146`, `310-320`) only ever calls `auto_save_setups_with_source(result.get("support_reversal_setups", []), source="Support Reversal")`. Per `RESEARCH_LOG.md` ("Support/Resistance + Support Reversal" row, Killed 2026-07-23), `generate_support_reversal_setups()` was disabled that day and now unconditionally returns `[]` — a look-ahead-artifact kill, unrelated to this screener but the only thing still wired into the live save path.

**Net:** `backtest_setups` (the table backing this whole KPI section — KPIs, Long vs Short, Outcome Distribution, Win Rate by Quality Score, monthly trigger chart, Detailed Setup Table) is kept fresh weekly by `weekly_backtest.yml`, but it validates a screener that hasn't generated a live setup in the current pipeline. It does not include Weinstein Stage-2, Boring Donchian, or Recovery Bases at all. **Not the same thing as the `Setup Perf` page**, which tracks 4 different, still-live setup types (BREAKOUT/PRE_BREAKOUT/RS_LEADER_MARKET/RS_LEADER_SECTOR) via `setup_log`/`backfill_setup_log.py`.

**Not decided:** whether to keep this section as historical reference (with a caveat that it doesn't reflect the current screener set), relabel it, or retire it and stop `weekly_backtest.yml`. Unlike §19, there's no already-Concluded-negative verdict on this specific screener's own EV — the finding is that it's *orphaned*, not that it's *disproven*.

### 20b. "BOS Breakout Backtest — Research Findings" — `rs_score_20` claim contradicted by later, higher-rigor work

**The page's claim:** a static write-up (hardcoded, run date 19 Jun 2026) states "Durable output: the `rs_score_20 > 0` filter and the `stage2_bull` EMA-stacking flag" as a Concluded-positive result, presented with no caveat.

**Checked both filters' actual live status, not assumed:**
- `stage2_bull` — confirmed live and load-bearing: gates `agent.py`'s `OpportunityGeneratorAgent` universe directly (`WHERE stage2_bull = 1`, `agent.py:1140`, `1150`). No contradiction found for this one.
- `rs_score_20` — confirmed **contradicted**. Three weeks after the BOS batch called it durable, `leaders_scan.py` was changed (`leaders_scan.py:30-34`, `268-271`) with the comment: *"Re-derived 2026-07-10 (S-002 fix)... removing the rs_score_20 and sector_rs_rank blocks (confirmed dead, S-002)... no significant relationship with forward returns."* It was dropped from the live conviction-score formula (`_raw_score()`, 5 components → 3) used by `Leaders → Deep Scan`. Cross-checked `RESEARCH_LOG.md` directly (Signal platform Phases 4-7 entry): *"Constructs created here that were later tested and killed: `rs_score_20`, `sector_rs_rank`..."* — independent confirmation, not just a code comment.
- `rs_score_20` is **not** fully dead in the live pipeline, though: `backfill_setup_log.py` still uses `ORDER BY ss.rs_score_20 DESC` (lines 52, 231, 371) to select which stocks become `RS_LEADER_MARKET`/`RS_LEADER_SECTOR` setups in `setup_log`, run daily. So the same construct is simultaneously "confirmed dead" in one live consumer (`leaders_scan.py`'s Deep Scan score) and still actively selecting setups in another (`backfill_setup_log.py`) — a real, live inconsistency, not just a stale dashboard caption.

**This is the same open question as §3 backlog item 10** (`Leaders → Deep Scan` factor check, open since the original audit pass) — this finding confirms it also reaches the Backtest page's own findings write-up, not just the Deep Scan scoring.

**Also checked, not previously verified:** whether the original BOS batch had any pre-registration or out-of-sample holdout. Per `RESEARCH_LOG.md`'s own description — "Rapid batch of break-of-structure backtests: full universe, single-symbol deep dives, regime split, sector role, RS score, incomplete bases. Six findings written into the Backtest page and acted on the same day" — no holdout or pre-registration is documented, unlike the Weinstein/DC Breakout/BMX studies which explicitly split eras. That the batch's own headline construct (`rs_score_20`) failed a later, more rigorous retest is consistent with that gap, though this audit did not re-run the BOS backtest itself to independently verify the other five findings.

---

## 21. <span style="color:#16a34a;">🟢 Resolved — `market_regime`/`sector_signals` silent-gap bug, a real Streamlit crash, and dependency drift, all root-caused and fixed (2026-08-12)</span>

**Trigger:** user reported the sidebar's "Market Regime" widget showing lagging data as of 2026-08-06 despite newer price data already being available, plus a separately-reported 6m32s local cold-start time. A follow-up session then asked why the widget still showed "1 day since last change" alongside a "database updated 11/08/26" date that should, on its face, imply a longer streak.

**Root cause 1 — `regime.py`/`sector_signals.py` only ever computed the single latest trading date.** Both hooks run inside their own `try/except` in `main.py`'s `cmd_update()` (by design, so one bad hook can't kill the rest of the daily pipeline) — but neither had a backfill loop, unlike `stock_signals.py`, which already computes every date between its last write and the latest available price date. So a transient failure on any one day permanently lost that date: the next successful run just computed whatever the new latest date was and moved on. Confirmed live against production Supabase: `prices`/`index_prices`/`stock_signals` all had 2026-08-07, `market_regime` and `sector_signals` did not — `market_regime` jumped straight from 08-06 to 08-10.

**Fix:** `regime.py`'s `_pending_regime_rows()` and `sector_signals.py`'s `_compute_and_write_sector_signals_for_date_{pg,sqlite}()` + a new backfill loop now fill every missing date since the last successful write, for both the SQLite and Postgres paths. 19 new tests in `tests/` (this project's first automated test coverage) cover multi-day gap backfill, correct `regime_days`/`rs_rank_prev` chaining across a gap, idempotent re-runs, and pre-gap rows staying untouched.

**Root cause 2 — the days-since-transition display trusted a plain row-count that can be silently wrong in either direction once a gap exists.** Backfilling the real 2026-08-07 gap (both locally and, later, in production) surfaced something the missing row had been hiding: 08-07 recomputed as a genuine one-day `VOLATILE` dip — the 20-day return dipped marginally negative that day even though the EMA stack still looked bullish — meaning the uptrend actually restarted on 08-10, not 08-06. The old row-count algorithm couldn't have known this; it would report *some* number regardless of whether a gap existed, with no way to tell confident from unreliable.

**Fix:** `_get_regime_status()` (`dashboard.py`) and `get_regime_status_pg()` (`dashboard_pg.py`) now also return `has_gap`, computed by cross-referencing `index_prices`' trading calendar against `market_regime`'s own row count in the current streak's window. Deliberately does **not** try to "correct" the displayed number from `index_prices` instead — that would just trade one confidently-wrong number for a different one, since a hidden transition can make the true count larger, smaller, or coincidentally the same. When `has_gap` is true, the sidebar shows "⚠ incomplete history" and the header's risk-framing copy (which drives actual "proceed carefully" vs "stable uptrend" language) is forced into the cautious state rather than trusting an unverified day count.

**Root cause 3 — a real, independent crash found while verifying the pinned dependencies.** `dashboard.py` read `st.secrets` before calling `st.set_page_config()`. Streamlit 1.39.1 — the version `requirements.txt`'s pins resolve to — raises `StreamlitSetPageConfigMustBeFirstCommandError` for this ordering; the drifted local environment's Streamlit 1.57.0 silently tolerated it, which is how it went unnoticed. This is the exact crash §8.3 flagged as "reproducible on hard refresh... not confirmed either way against what Streamlit Cloud actually runs" back on 2026-08-05 — now confirmed and fixed by making `set_page_config()` the true first Streamlit call.

**Root cause 4 — `requirements.txt`'s range pins were not actually installable on this machine.** `numpy<2.0.0` (the pinned ceiling) has no prebuilt wheel for Python 3.13/3.14, and this machine has no C compiler — a real install attempt failed outright with a Meson/compiler error, not just slowly. This is almost certainly the real mechanism behind the reported 6m32s cold start: the ambient dev environment (numpy 2.4.4, pandas 3.0.2, streamlit 1.57.0 — all well past every pinned ceiling) could only have gotten that way by someone abandoning the documented pins entirely after hitting this wall.

**Fix:** installed a scoped, non-admin Python 3.12 (the newest interpreter numpy 1.26 still has wheels for) into a dedicated local folder — nothing on the existing system PATH was touched. Verified a clean install of every pinned package into a fresh venv on that interpreter, confirmed `dashboard.py` boots cleanly (~31s cold, real 1.75M-row local DB, no warm caches — not the ~6.5 minutes reported). `requirements.txt` now carries exact versions instead of ranges. `lxml` dropped (confirmed zero references anywhere in the codebase); `scikit-learn`/`joblib`/`playwright` moved to `requirements-optional.txt` (their only consumers are a killed ML model's manual-only retrain script and the `Flows` page's now write-only scraper, neither live today).

**Production repaired**, following this project's established backup → dry-run → execute → independently-reverify discipline:
- `market_regime`: backed up (5,341 rows), dry-run previewed against production's own KSE-100 data, then `08-06`/`08-07`/`08-10`/`08-11` written. Re-verified: gap closed, `regime_days` now shows the true sequence (`TRENDING_UP 1 → VOLATILE 1 → TRENDING_UP 1 → TRENDING_UP 2`) instead of the stale "3" it showed before.
- `sector_signals`: backed up (667 rows, July onward). `08-10`/`08-11` deleted and recomputed alongside the new `08-07` — necessary because `rs_rank_prev` and the 30-day `sector_rs_new_high` lookback are chain-dependent on the prior date, so simply inserting `08-07` without touching `08-10`/`08-11` would have left them referencing stale pre-gap data. Re-verified: 23/23/23 sector rows for the three dates, `08-06` provably byte-identical to its pre-repair snapshot, `08-10`'s `rs_rank_prev` now correctly points at `08-07`.

**Deliberately left untouched, flagged separately:** local SQLite's `prices_adjusted` table is stuck at `2026-07-31` (11+ days stale as of this session) even though `prices`/`index_prices` are current through `08-11` — the local `apply_price_adjustments.py` incremental-append hook isn't running/succeeding. Discovered as a side effect of this investigation, not part of what was asked; `sector_signals`'s local backfill correctly no-op'd against it (nothing to backfill from a stale source) rather than masking the problem. Local `market_regime`'s own separate, already-documented gap (07-20/07-21/07-29, see CLAUDE.md's Known Gaps) was also not touched — out of scope, pre-existing, doesn't affect production.

**Committed and pushed** (commit `071e1a8`, independently verified matching `origin/main` via `git ls-remote` + `git fetch`) at the user's explicit direction. Every production write happened inside a scoped one-off Python subprocess with `DATABASE_URL` set only for that call — confirmed not to leak into the shell session afterward.

---

## 22. <span style="color:#dc2626;">🔴 Not resolved — findings from §21 that should shape the §7.2/§10 CI-test-gate + staging-environment implementation (2026-08-12)</span>

§21 fixed what was found. This section is the deliberately-separated answer to a direct question: *what did finding and fixing it teach us about the gap top-priority item 7 already named* ("no CI test gate and no staging environment between `git push` and production... a broken commit reaches live traders in ~60 seconds with nothing checking it first")? Structured as discrepancies found, then the steps each one implies — meant to be read alongside §7.2 and §10, not as a replacement for either.

### A. Discrepancies and problems found

**A1. Silent, permanent data loss from single-date-only daily hooks.** `regime.py` and `sector_signals.py` computed only the latest trading date; a transient failure meant that date was gone forever once the next run moved past it. Went undetected in production for 5+ days (2026-08-07 → 2026-08-12) despite the dashboard being viewed daily for live trading decisions.

**A2. This is a *recurring* failure pattern, not a new one — the underlying root cause was never actually fixed the first time it happened.** CLAUDE.md's "Known Gaps: Postgres Parity" section already documents an earlier instance: the 2026-07 Postgres-dispatch outage left `market_regime`/`sector_signals` missing several dates, patched at the time with a one-off manual `INSERT` of the missing rows. That patch fixed the symptom (the specific missing dates) but not the mechanism (no backfill loop) — so the identical failure shape resurfaced on 2026-08-07 in the same two files. A symptom-only fix without a regression test is not a fix; it's a delay.

**A3. A dependent display bug hid inside the data bug and would have survived a partial fix.** The days-since-regime-change widget trusted a row-count that's silently wrong in either direction whenever a gap exists — proven for real, since the 08-07 gap was hiding an actual regime change, not just a missing duplicate. Fixing only the data layer (§21's backfill loop) without also fixing the display layer (§21's `has_gap` detection) would have left the system able to show a confident, wrong number for the *next* gap, from any future cause. Any correctness fix for a data-freshness bug needs to be checked at every layer that consumes the data, not just the write path.

**A4. `requirements.txt`'s pins are not actually installable on the primary local dev machine.** `numpy<2.0.0` has no prebuilt wheel for Python 3.13/3.14 and this machine has no C compiler — a real `pip install` fails outright, not slowly. This was silently worked around at some point by installing unconstrained latest-version packages instead (numpy 2.4.4, pandas 3.0.2, streamlit 1.57.0 — all past every documented ceiling), which is almost certainly why nobody had noticed the pins were broken.

**A5. Multiple Python interpreters exist on the dev machine, none matching the documented production target.** `python` on PATH resolved to 3.14.4; a separate 3.13 install also existed; CLAUDE.md documents Streamlit Cloud on 3.11. No single, enforced source of truth for "the" local interpreter.

**A6. A real application crash was invisible locally because of the environment drift in A4.** `st.secrets` read before `st.set_page_config()` crashes outright on Streamlit 1.39.x (what the pins resolve to) but not on 1.57.x (what the drifted local environment actually ran) — meaning "it works on my machine" was not validating what the pinned `requirements.txt` would actually ship. This is the same crash §8.3 already flagged as unconfirmed on 2026-08-05; it sat unconfirmed for a week because nothing forced a clean-environment check.

**A7. Dead dependencies were shipped in the default install path, widening the install-failure surface for no live benefit.** `lxml` had zero references anywhere in the codebase. `scikit-learn`/`joblib` (killed ML model, manual-only retrain) and `playwright` (feeds a fully write-only, unread pipeline) were only needed for already-retired features. None of this was caught by anything — it took a manual grep, prompted by an unrelated cold-start question, to surface it.

**A8. No visibility into what Streamlit Cloud's build actually resolves.** Every version claim in this fix (Python 3.11, the effect of the pins) is inferred from `CLAUDE.md` and local reproduction — there is no check anywhere in this project's pipeline that confirms local findings actually match what Cloud runs at deploy time. §8.3 flagged this exact gap on 2026-08-05 ("Cloud was asleep this session and checking its real resolved version was deliberately deferred") and it is still open now.

**A9. A hook failure is only ever a logged `WARNING`, and nothing turns that into something a human sees.** This is correct behavior for the pipeline's resilience (one bad hook shouldn't crash the rest of `cmd_update()`) but it means the *only* detection mechanism that caught this bug, across 5+ days of live production staleness, was a human happening to notice a displayed date looked wrong. Nothing about GitHub Actions' run logs, the dashboard, or any alerting surfaces a hook that's silently failing.

**A10. Not systematically checked: whether other daily hooks share the same single-date, no-backfill defect shape.** `regime.py` and `sector_signals.py` were found and fixed because they were the two specifically implicated in the reported symptom. `setup_log` (`backfill_setup_log.py`), `leaders_scan.py`, and the flow-signal enrichment inside `sector_signals.py` were not audited for the same pattern as part of this fix. `stock_signals.py` is confirmed to already backfill correctly and was the reference pattern used to fix the other two — but that confirms the *fix* pattern, not that every *other* hook is clean.

**A11. A separate, silent local-environment staleness surfaced as a side effect, not as a designed check.** Local `prices_adjusted` has been stuck at `2026-07-31` (11+ days) while `prices`/`index_prices` are current through `08-11` — found only because `sector_signals`'s local backfill correctly no-op'd against it and that no-op prompted a closer look. Nothing was watching for this on its own.

**A12. Zero automated test coverage existed for any daily-pipeline hook before this session.** This entire class of bug — silent, permanent, single-date data loss — was structurally undetectable by anything except a human eyeballing a stale display, for as long as this project has existed. `stock_signals.py`'s correct backfill behavior was itself never regression-tested, so a future edit to that file carries the same undetected-regression risk the other two just demonstrated.

### B. Steps to address these issues

<span style="color:#16a34a;">**B1–B4 status (2026-08-12): B1, B2 and B3 are DONE; B4 is done on the repo side and blocked on the Cloud console. See §23. B5–B9 remain open.**</span>

**B1.** <span style="color:#16a34a;">✅ DONE — `.github/workflows/ci.yml`, `unit-tests` job.</span> **Wire the new `tests/` suite into an actual CI workflow (closes A12, start of §7.2's Option A).** The 19 tests added in §21 are the first automated coverage this project has ever had, and they sat unused as plain files until wired in. Add a GitHub Actions workflow that runs `pytest tests/` on every push and pull request to `main`. This is the cheapest, highest-leverage step available and should not wait for the rest of this list.

**B2.** <span style="color:#16a34a;">✅ DONE — `app-boot` job + `tests/test_app_boot.py`, all 15 pages, verified to reproduce both shipped bugs (§23.2). Implemented with Streamlit's own `AppTest` harness rather than the log-scraping `streamlit run --headless` sketched below: a plain headless run never executes the script until a browser connects, so it would have proven nothing.</span> **Add a "does the app actually boot" check, separate from unit tests (closes A6).** Unit tests cover pure logic; they would not have caught the `set_page_config` crash, which is a Streamlit runtime behavior. The CI workflow needs an explicit `streamlit run dashboard.py --headless` step with a timeout, checking the process log for `Uncaught app exception` (or exit code) rather than just "did it start."

**B3.** <span style="color:#16a34a;">✅ DONE — `clean-install` job, Python 3.11, no pip cache, plus `pip check` and a 19-module import smoke; uploads the resolved `pip freeze` as an artifact.</span> **Add a clean-install check on the *documented* production interpreter (closes A4, A5, A8).** `pip install -r requirements.txt` into a **fresh** venv on Python 3.11 (matching CLAUDE.md/Streamlit Cloud), not whatever the runner or a cached local environment happens to have. This is precisely the check that would have caught the numpy wheel-availability failure before it became a days-long mystery, and it directly answers A8 for the CI runner (a separate step, described next, is still needed to confirm Cloud's *actual* resolved build, not just a CI runner's).

**B4.** <span style="color:#eab308;">◐ PARTIAL — CI gates `staging` already and [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) documents the whole flow; the branch, the second Cloud app, branch protection, and the staging-database decision all need the account owner (§23.4).</span> **Build the staging environment from §10 Option B, and use it to close A8 for real.** A second Streamlit Cloud app on a `staging` branch, so a push gets a genuine boot-and-render check against Cloud's actual resolved Python/dependency versions before promotion to `main` — not an assumption based on local reproduction. §10 already recommends this; A8 is now concrete evidence for why it matters, not a hypothetical.

**B5.** <span style="color:#eab308;">◐ DONE as an audit (§24) — every `cmd_update()` hook read. `setup_log`'s defect was real, had already lost 11 dates locally, and is fixed with 10 regression tests. `leaders_scan` and `boring_signals.scan_boring_breakouts` have the same shape and are **not** fixed; existing gaps do not self-heal and production has not been checked (§24.4).</span> **Systematically audit every remaining daily hook for the A1/A2 defect shape (closes A10).** Read `setup_log`'s and `leaders_scan.py`'s date-handling logic and the flow-signal enrichment path with the specific question "does a transient failure on day N get silently and permanently skipped, or does the next successful run backfill it?" — using `stock_signals.py`'s pattern (and now `regime.py`/`sector_signals.py`'s) as the standard every hook should meet, not an assumption that finding two means the rest are clean.

**B6. Add a lightweight daily freshness check (closes A9, partially A11).** Compare `MAX(date)` across every hook-output table (`market_regime`, `sector_signals`, `stock_signals`, `setup_log`, `prices_adjusted`) against `MAX(date)` in `prices`/`index_prices` — either as a GitHub Actions step that fails/warns loudly (not just a logged `WARNING` nobody reads) or a dashboard banner in the style of the existing corporate-action-suspects pill. Turns "a human happened to notice" into "the system says so," closing the actual detection gap A9 describes, not just this one incident.

**B7. Update `CLAUDE.md`'s "Known Gaps: Postgres Parity" section to reflect that the root cause behind its "2026-07 Postgres-dispatch outage" entry is now fixed (closes A2 going forward).** That entry currently describes the mechanism as still-open scar tissue; leaving it unedited risks a future reader assuming the underlying defect is still live when it's actually been closed as of §21. Not done as part of §21/§22 — flagged here as the next small edit.

**B8. Investigate and fix local `prices_adjusted` staleness as its own item (closes A11).** Separate from the CI/staging work — `apply_price_adjustments.py`'s incremental-append hook isn't running/succeeding locally for 11+ days. Not urgent for production (Cloud reads Postgres, which is current), but blocks meaningful local `sector_signals`/`stock_signals` testing and would recur invisibly again without a check like B6.

**B9. Standardize local development on one interpreter matching production (closes A5).** Pin Python 3.11 (or document and enforce whatever version is actually chosen) for local `psx_pipeline` work, rather than relying on whatever `python` resolves to on PATH. Combine with B3's clean-install check run locally before any session that touches dependencies.

**Not decided:** whether B1–B4 (the CI/staging build-out itself) happens as one session or split further; whether B6's freshness check lives in GitHub Actions, the dashboard, or both. Recorded here, per this document's own "no silently dropped items" rule, for the next session to pick up.

**Not decided:** whether to caveat/relabel the `rs_score_20` claim on this page, whether to resolve the `backfill_setup_log.py` vs `leaders_scan.py` inconsistency (drop `rs_score_20` from `RS_LEADER_MARKET`/`SECTOR` selection too, or restore it to Deep Scan — a decision that needs the S-002 evidence re-examined, not assumed correct either way), or whether `stage2_bull`'s clean bill of health changes anything about how the other 5 BOS findings (regime filter, sector role, etc.) should be read. None of this was acted on.

---

## 23. <span style="color:#16a34a;">🟢 Mostly resolved — CI test gate built and verified; staging environment done on the repo side, pending the Cloud console (2026-08-12)</span>

Top-priority item 7 (§7.2 structural + §10 deploy strategy), implemented against §22's B1–B4. Full operating guide: [`docs/DEPLOYMENT.md`](DEPLOYMENT.md).

### 23.1 What was built

**`.github/workflows/ci.yml` — runs on every push and PR to `main` and `staging`.** Three deliberately separate jobs so a red build says *which* kind of thing broke:

| Job | Closes | What it does |
|---|---|---|
| `clean-install` | B3 (A4, A5, partially A8) | `pip install -r requirements.txt` into a clean Python 3.11 (the documented Cloud version), **no pip cache**, then `pip check`, then imports all 19 non-Streamlit production modules. Uploads a `pip freeze` artifact (`resolved-py311.txt`) per run — the first durable record this project has of what a clean 3.11 install actually resolves. |
| `unit-tests` | B1 (A12) | `pytest tests/` — the 19 backfill/gap-detection tests from §21, which until now sat on disk unrun by anything. |
| `app-boot` | B2 (A6) | Renders **all 15 dashboard pages** through Streamlit's own `AppTest` harness against a committed fixture DB, failing on any uncaught app exception. |

**`tests/test_app_boot.py`** — the boot smoke suite (16 tests: default boot + one per page). Page selection is seeded via `st.session_state["page"]`, exactly what the sidebar selectbox writes, so it needs no widget interaction. `DATABASE_URL`/`SUPABASE_DB_URL` are forced empty for the whole session — CI cannot reach production Postgres by construction.

**`tests/fixtures/psx_fixture.db` (13.5 MB, committed) + `build_fixture_db.py`.** `database.init_db()` cannot stand in for the production schema — it creates 14 of the 49 live tables, and even those have drifted (**a fresh `init_db()` database crashes the dashboard outright with `no such column: p.open`** — `prices.open` was added during the Open Price project and never added to `init_db()`'s `CREATE TABLE`; found while building this). The fixture instead copies DDL straight out of `sqlite_master`, so its schema is by construction whatever production has, plus ~300 trading days × 69 symbols of price/signal data.

**Personal data is deliberately excluded from the fixture**, since unlike everything else in it, the live DB holds the owner's real trades, portfolio capital, and private agent chat history — `.gitignore`'s first line exists for exactly that reason. `trade_setups`, `portfolio_values`/`portfolio_transactions`, all eight `agent_*` tables and `prediction_log` are created empty (`EXCLUDE_PERSONAL` in the builder). Verified after generation: those tables hold 0 rows, and a byte-scan of the whole file for the owner's name, email, capital figure, `JOURNAL`, and credential prefixes (`gsk_`, `sk-`, `postgres://`) returns zero hits. `.gitignore` carries one narrow `!tests/fixtures/psx_fixture.db` exception.

**`pytest.ini`** — `testpaths = tests`, so a bare `pytest` doesn't collect the 18 loose root `test_*.py` research scripts (§7.2's consolidation item is still open; this keeps the gate honest about what it actually runs in the meantime).

### 23.2 The gate was checked against the bugs that really shipped, not assumed to work

Both are reproduced by `tests/test_app_boot.py` when it is run against the pre-fix code:

- **`set_page_config` ordering crash** (§21 root cause 3 / §22 A6) — checked out `dashboard.py` at `071e1a8^`, ran the boot test on the pinned Streamlit 1.39.1: fails with `StreamlitSetPageConfigMustBeFirstCommandError`. That is the crash that killed the entire app and sat undetected for a week.
- **`st.dataframe(..., width='stretch')`** (§8.3 Bug 1, flagged 2026-08-05 as "not confirmed either way against what Streamlit Cloud actually runs") — now confirmed, and worse than recorded. On the pinned 1.39.1 it raises `TypeError: 'str' object cannot be interpreted as an integer`. The first run of the 15-page matrix found **3 pages dead: `Setup Perf`, `Backtest`, `Portfolio`** — the third (`Backtest`) was not among the two §8.3 had identified. Fixed by moving the 6 affected `st.dataframe` call sites to `use_container_width=True` (the correct API on the pinned version). The 10 `st.plotly_chart(..., width='stretch')` call sites were tested and are unaffected — 1.39.1 accepts them — so they were left alone rather than churned.

**After the fix: 15/15 pages render clean**, verified both against the real local database and against the sanitized fixture in a fresh clone with no `psx_data.db` (i.e. the actual CI path), 16 passed in ~96s.

### 23.3 Two live production breakages found by reading the workflows — fixed

Neither would have been caught by anything; both were introduced by the previous session's own dependency cleanup, which is precisely the "nothing checks a push" problem item 7 names:

- **`daily_scraper.yml` was broken as of commit `071e1a8`** — it still ran `playwright install chromium --with-deps` after `playwright` had been moved out of `requirements.txt` into `requirements-optional.txt`. The step would fail with command-not-found and take the whole **daily production pipeline** down with it. Fixed by installing playwright explicitly in that step.
- **`weekly_ml_retrain.yml` had the same shape** — `phase4_train.py` needs `scikit-learn`/`joblib`, which moved to `requirements-optional.txt` the same way. Manual-dispatch only, so lower impact. Fixed by installing both requirement files there.

### 23.4 Staging — repo side done, Cloud console pending

`ci.yml` already gates `staging` as well as `main`, and `docs/DEPLOYMENT.md` documents the full promote flow (`staging` → CI green → manual click-through → `git merge --ff-only` → `main`), the hotfix path, and rollback. What is **not** done, because it requires the account owner and cannot be done from the repo:

1. create and push the `staging` branch;
2. create the second Streamlit Cloud app pointed at it;
3. ~~add branch protection on `main`~~ — **DONE 2026-08-12** (§26.1): PR required, all three checks required, `enforcement_level: everyone` so it binds the owner too. Verified not by the confirmation banner but by a real direct push from the owner being rejected: `GH006 ... Changes must be made through a pull request. 3 of 3 required status checks are expected.` The gate is now a gate;
4. decide which database staging points at. `docs/DEPLOYMENT.md` §3 lays out the three options; the recommendation is a dedicated **read-only Postgres role** on the same Supabase DB, so staging shows real current data but a misclick there cannot write to production. That needs a `CREATE ROLE`/`GRANT SELECT` against the production database, which under this project's standing rule needs explicit sign-off — not run.

### 23.5 Deliberately not done, and what is still open

- **§22 B5** (audit every remaining daily hook for the A1/A2 single-date defect shape), **B6** (daily freshness check), **B7** (update CLAUDE.md's Known Gaps entry), **B8** (local `prices_adjusted` staleness), **B9** (standardize the local interpreter) — all still open. This session was scoped to B1–B4.
- **The gate does not test the Postgres path at all.** Every test runs on SQLite; `database_pg.py`/`dashboard_pg.py` — the code production actually runs — is exercised by none of it. A Postgres-only bug of the `TEXT` vs `DATE` class already documented in CLAUDE.md would pass CI green. This is the single largest hole in the gate as built; closing it needs a disposable Postgres service container in CI, not a connection to Supabase.
- **It checks that pages render, not that they are right.** A page showing confidently wrong numbers passes.
- **Found and left alone, flagged here:** `eod-scraper.yml` installs its own hand-written, **completely unpinned** package list (`pandas`, `numpy`, … plus `lxml`, which is confirmed dead code) rather than `requirements.txt` — the same drift class as §22 A4, in a workflow that writes to production Supabase. It is `workflow_dispatch`-only today, so nothing is running it on a schedule; changing a production scraper's dependency set deserves its own verified session rather than a drive-by edit here.
- **Also found:** `anthropic` is not in any requirements file, though `main.py`'s daily hook constructs `TradingDeskAgent`. On a GitHub Actions run that import fails and is swallowed by the hook's `try/except`, logging `ERROR anthropic package not installed` — consistent with CLAUDE.md's note that the agent is local/manual-only, but it means the daily pipeline silently runs without its agent step. Not changed: adding `anthropic` to `requirements.txt` would put it on Streamlit Cloud's install path and enable API calls from a workflow that currently makes none — a cost decision, not a cleanup.

---

## 24. <span style="color:#eab308;">◐ Partly resolved — §22 B5's hook audit done; `setup_log`'s silent-loss defect found and fixed, two more found and left for a decision (2026-08-12)</span>

§22 B5 asked for every remaining daily hook to be read with one specific question: *does a transient failure on day N get silently and permanently skipped, or does the next successful run backfill it?* — using `stock_signals.py`'s pattern as the standard, rather than assuming that finding two bad hooks meant the rest were clean. Every hook in `main.py`'s `cmd_update()` has now been read.

### 24.1 The audit, hook by hook

| Hook | Date logic | Verdict |
|---|---|---|
| `append_new_prices_adjusted` (+`_pg`) | `INSERT ... WHERE date > MAX(prices_adjusted.date)` — a range copy | ✅ backfills by construction |
| `auto_detect_suspects` | scans a rolling window (since `MAX(suspect_date)`, floor of the last 5 dates) | ◐ self-heals within 5 trading days; a longer outage skips dates permanently. Bounded, low severity, not changed |
| `append_latest_regime` | fixed in §21 | ✅ |
| `backfill_days_to_nearest` | fills every row where the column `IS NULL` | ✅ self-healing by design |
| `append_latest_sector_signals` | fixed in §21 | ✅ |
| **flow-signal enrichment** (`compute_flow_signals` / `_pg`) — B5 named this specifically | takes an explicit `date_str`, and is called from inside `_compute_and_write_sector_signals_for_date_{pg,sqlite}()` | ✅ **already covered by §21's loop** — checked rather than assumed |
| `append_latest_stock_signals` | the reference pattern | ✅ |
| **`append_setup_log_today`** (both paths) | `target_date = MAX(stock_signals.date)`, single date, no loop | 🔴 **DEFECT — fixed here, §24.2** |
| `compute_forward_returns.main` | iterates every symbol, fills rows where forward returns are `NULL` | ✅ self-healing |
| **`leaders_scan.append_leaders_scan` / `save_top_picks`** | `scan_date = MAX(stock_signals.date)`, single date, no loop | 🔴 **DEFECT — found, not fixed, §24.4** |
| `fill_leaders_forward_returns` | fills rows with NULL forward returns | ✅ self-healing |
| **`boring_signals.scan_boring_breakouts`** | `date` argument defaults to `all_dates[-1]` — newest only | 🔴 defect, but SQLite-only and it already accepts an explicit date, §24.4 |
| `update_open_signal_statuses` | re-evaluates every still-open signal | ✅ |
| agent subprocess · breadth oscillator · rolling trim | not date-keyed writes | n/a |

### 24.2 `setup_log` — the defect was real and had already produced gaps

Checked against the local database rather than argued from the code shape. `stock_signals` holds **all 147 trading dates of 2026**; `setup_log` was missing **11 of them**:

```
2026-07-13, 07-20, 07-21, 07-29, and an unbroken run 08-03 → 08-11
```

Three things make this conclusive rather than circumstantial:

1. **Those dates had data.** Re-running each missing date's own selection queries read-only returns a full 20 `RS_LEADER_MARKET` rows plus 9–16 breakout candidates per day. They are not legitimately-empty days.
2. **`stock_signals` covers them.** Both hooks read the same table in the same `cmd_update()` run; one caught up and the other did not. That is the defect, visible in a single database.
3. **07-20 / 07-21 / 07-29 are the same dates** as local `market_regime`'s already-documented gap (CLAUDE.md, Known Gaps) — the fingerprint of days when the local pipeline partly failed. `market_regime` can now self-heal; `setup_log` could not.

**Why it matters:** `setup_log` is the record behind the `Setup Perf` page and every forward-return/outcome statistic computed from it. A missing day is not a visible error — it silently drops that day's setups out of the win-rate denominator.

### 24.3 The fix

Same shape as §21's, deliberately: a pure, DB-free `_pending_setup_log_dates(signal_dates, last_logged)` holding the policy, called by both the SQLite and Postgres paths so they cannot drift apart again, plus a loop that commits **per date** (a failure part-way through a multi-day catch-up keeps the days already written). A multi-date backfill logs at `WARNING`, not `INFO`, so a catch-up is visible in the run log rather than buried.

One deliberate asymmetry, documented in the function: when `setup_log` is **empty**, only the newest date is written, not all of history. The historical backfill in the same module inserts BREAKOUT on *every* `bos_flag=1` day, while this path inserts transition days only (`prev bos_flag = 0`) — replaying history through here would write rows that disagree with the historical record.

**Verified against the pre-fix code, not just asserted.** Same scenario (5 trading days of signals, `setup_log` stopping at day 2), run against both versions:

```
PRE-FIX   setup_log now has : ['2026-07-28', '2026-07-31']
          PERMANENTLY LOST  : ['2026-07-29', '2026-07-30']
POST-FIX  setup_log now has : ['2026-07-28', '07-29', '07-30', '07-31']
          PERMANENTLY LOST  : none
```

10 new tests in `tests/test_setup_log_backfill.py` (45 in the suite now): the pure policy including the empty-table and setup_log-ahead-of-signals edges, multi-day gap coverage end-to-end, idempotent re-runs, pre-gap rows left untouched, and the BREAKOUT transition-day rule still honoured *on a backfilled date* — the path that did not exist before and could plausibly have got the previous-day lookup wrong. The tests build their temp database from the real schema in `tests/fixtures/psx_fixture.db`, and redirect **both** `backfill_setup_log.DB_PATH` and `compute_forward_returns.DB_PATH`, since both bind the path at import time and step 2 of the function would otherwise write `UPDATE`s into the live `psx_data.db`.

### 24.4 Not fixed — three things that need a decision, not more code

**a. The existing gaps will not self-heal.** The fix fills dates *after* `MAX(setup_date)`. Locally that means `08-03 → 08-11` will fill themselves on the next pipeline run, but the older holes (`07-13`, `07-20`, `07-21`, `07-29`) sit before the high-water mark and will stay empty forever unless deliberately backfilled. That is a bulk write to a trading-record table and needs explicit sign-off, so it was not done.

**b. Production's gaps are unknown.** Everything above is measured on local SQLite. Whether Supabase's `setup_log` has the same holes has **not** been checked — it needs a read-only query with the production connection string. Do this before assuming the production record is intact; the two databases are known to diverge (§16, §21).

**c. `leaders_scan` and `boring_signals` have the same defect shape.** `leaders_scan` last wrote `2026-07-31` locally and covers only 28 of the trading dates since it started on 06-16, with holes at 06-25/26, 07-11/13, 07-18/21 and 07-29. It is an audit trail and a monitoring page rather than a performance statistic, so the cost of a gap is lower — but it is the same bug, and fixing it is the same pattern. `boring_signals.scan_boring_breakouts()` already takes an explicit `date` argument, so its fix is close to a one-liner; it is SQLite-only and watch-only, the lowest severity of the three. Neither was changed in this pass: both are production write paths and this session had already made one such change.

---

## 25. <span style="color:#eab308;">◐ Local holes repaired, production root-caused and code-fixed, all three backfill defects closed — production data repair still needs sign-off (2026-08-12)</span>

The three items §24.4 left open, taken in order. The headline is the middle one: **production `setup_log` and `leaders_scan` have been frozen since 2026-06-30 — six weeks — because of a SQLite/Postgres type mismatch that no check would have caught.**

### 25.1 Local holes repaired (§24.4 item a)

The four dates below `setup_log`'s high-water mark (`2026-07-13`, `07-20`, `07-21`, `07-29`) cannot be reached by the daily hook by design, so they were repaired deliberately, following this project's standing discipline:

1. **New, explicitly one-off entry point** — `append_setup_log_for_dates(dates, dry_run=True)`, dry-run by default. It reuses `_insert_setup_log_for_date()`, i.e. the *same four queries the daily hook runs*, so a repaired date agrees with the days around it rather than with `run()`'s different historical-backfill rules. The daily SQL was lifted to module level for exactly this reason — one definition, two callers. Postgres is deliberately refused with a pointer to this section: repairing production is a separate decision, not a flag on a utility.
2. **Dry run** — 73 / 62 / 66 / 62 rows, 0 already present.
3. **Pre-state captured** for an exact rollback rather than a 30 MB table dump, since the operation is pure INSERT: `backups/setup_log_prestate_20260812_152036_hole_repair.json` records `total_rows` 207,113, `max_id` 209,015, and the exact revert statement `DELETE FROM setup_log WHERE id > 209015;`.
4. **Executed** — 263 rows.
5. **Independently re-verified**: exactly 263 rows carry an id above the pre-state max, they fall on exactly those four dates, and the setup-type mix on each repaired date is indistinguishable from its neighbours (always 20 `RS_LEADER_MARKET`, 39–48 `RS_LEADER_SECTOR`, 1–3 `BREAKOUT`, 0–2 `PRE_BREAKOUT`).
6. **Completed the rows** the way the daily hook does — `compute_forward_returns` then the labelling `UPDATE`. Only `2026-07-13` filled (73 rows); `07-20`/`07-21`/`07-29` correctly wait for their 20-day windows to close (~08-17, ~08-18, ~08-26) and will fill themselves on a future run. That same pass also cleared a backlog of **1,229 rows** table-wide that had forward returns but were still labelled `BREAKEVEN`, because the local pipeline had not run since 07-31.

Local `setup_log` now has every 2026 trading date except `08-03 → 08-11`, which sit **above** the high-water mark and will fill themselves on the next local pipeline run — that is the §24 fix working as designed, so they were left alone.

### 25.2 <span style="color:#dc2626;">Production was worse, and for a different reason (§24.4 item b)</span>

A read-only check against Supabase found `stock_signals` current through `2026-08-11` but **`setup_log` frozen at `2026-06-30` — 29 trading dates missing**, and `leaders_scan` frozen at exactly the same date.

Root cause, found by running the hook's own queries read-only against production:

```
psycopg2.errors.UndefinedFunction: operator does not exist: boolean = integer
LINE 2: ... WHERE ss.date = '2026-08-11' AND ss.bos_flag = 1 AND ss...
```

**`stock_signals.bos_flag` is `BOOLEAN` in Supabase and `INTEGER` in SQLite.** `bos_flag = 1` is valid SQLite and invalid Postgres. Because that error aborts the transaction, the other three queries for the date fail too, so **nothing at all is written** — which is why the table is frozen rather than partially filled. This is the same SQLite/Postgres type-mismatch class as the `TEXT` vs `DATE` gotcha already documented in CLAUDE.md and the Decimal-vs-float bug from §16. It is the third instance.

`information_schema` shows **13 boolean columns** in production, 7 of them on `stock_signals`. Four live comparisons were wrong, all on Postgres paths:

| File | Function | Fix |
|---|---|---|
| `backfill_setup_log.py` | `_append_setup_log_today_pg` | `bos_flag = 1` → `IS TRUE`; `COALESCE(..., 0) = 0` → `COALESCE(..., FALSE) IS FALSE` |
| `leaders_scan.py` | `_breakout_health_check_pg` | `bos_flag = 0` → `IS FALSE` |
| `leaders_scan.py` | `_breakout_health_check_pg` | `bos_flag = 1` → `IS TRUE` |
| `leaders_scan.py` | `_append_leaders_scan_pg` | `bos_flag = 1` → `IS TRUE` |

The SQLite twins of these queries are correct as they stand and were deliberately left alone.

**Verified read-only against production after the fix**: all four `setup_log` queries execute and return plausible counts (`2026-07-01` 70 rows, `07-15` 73, `07-31` 62, `08-06` 66, `08-11` 72 — the same 62–73/day shape as local), and `leaders_scan`'s candidate query plus `_breakout_health_check_pg` run clean end-to-end on real production rows.

<span style="color:#dc2626;">**Production data has NOT been repaired.**</span> Nothing was written to Supabase — every check above ran in a `readonly=True` session. The 29 missing dates are all *above* `setup_log`'s high-water mark, so once these fixes are pushed **the next successful daily run will backfill them automatically** (~1,950 rows, extrapolating from the sampled dates). That is the intended behaviour, but it happens without further prompting, so it is called out here rather than left as a surprise.

**Worth noting about detection:** this was invisible for six weeks. The hook logs a `WARNING` and `cmd_update()` continues by design (§22 A9), the dashboard shows an empty `Setup Perf` rather than an error, and the CI gate built in §23 explicitly does not exercise the Postgres path (§23.5). A Postgres service container in CI is the check that would have caught this — the gap §23.5 already names as the largest hole in the gate.

### 25.3 The remaining two hooks fixed (§24.4 item c)

**`leaders_scan`** now backfills. `append_leaders_scan()` and `_append_leaders_scan_pg()` take an optional `scan_date` (defaulting to previous behaviour), and `run_all()` loops over pending dates, catching failures per date. Each date is already a self-contained `DELETE ... WHERE scan_date = ?` + rebuild, so this is idempotent by construction — confirmed on a fixture copy: a simulated 14-date gap filled completely, and a second run left the row count unchanged at 246. The pending-date policy is **imported from `backfill_setup_log`, not re-implemented**, so the two hooks cannot drift apart the way the daily hooks already did once; a test pins that.

**`boring_signals`** now scans via `scan_boring_breakouts_pending()` rather than the newest date only, wired into `main.py`'s hook. This one is a **bounded window (15 trading days), not a true high-water mark**, and the reason is worth recording: `boring_signals` only gets a row when a signal actually fires, so an empty stretch is indistinguishable from an unscanned one — the table cannot tell you what has been scanned. Resuming from `max(last signal_date, newest − 15 trading days)` converts permanent silent loss into self-healing within 15 days, the same compromise `auto_detect_suspects()` already makes in this codebase. A gap longer than the window is still missed; closing that properly needs an explicit scan-progress marker, which is a schema change and hard to justify for a watch-only, SQLite-only feature. Verified on a fixture copy: a simulated gap scanned 15 dates and recovered 17 signals across 8 of them, with a re-run inserting 0.

Suite is now **50 tests** (the 45 of §24, which already included setup_log's 10, plus 5 for leaders_scan).

### 25.4 Still open after this

- **The production `setup_log`/`leaders_scan` backfill itself** — automatic on the next daily run once pushed, or run deliberately with a backup first. Needs a decision, not code.
- **`agent.py` has the same boolean bug** (`stage2_bull = 1`, `agent.py:1140`/`1150`, plus `is_active = 1` at `:823`) and would fail the same way if it ever ran against Postgres. It is local/manual-only today (CLAUDE.md), and `main.py`'s daily subprocess call to it also fails on Actions for a separate reason — `anthropic` is in no requirements file (§23.5). Not fixed: it needs the agent's Postgres story decided first, not a one-line patch.
- **Nothing sweeps for this bug class.** Four comparisons were found by grepping for known boolean columns. A cheap standing check — assert every boolean column in production is only ever compared with `IS TRUE`/`IS FALSE` in `_pg` code paths — would turn that into something automatic. Not built.
- **§22 B6–B9** (freshness check, CLAUDE.md Known-Gaps update, local `prices_adjusted` staleness, interpreter standardisation) remain untouched.

---

## 26. <span style="color:#16a34a;">🟢 Resolved — the CI gate's first real verdict was red, and it was right (2026-08-12)</span>

The first two CI runs after the gate went live both failed. Worth recording in full, because the failure is a small, precise example of the exact thing the gate was built to catch — found in the gate's own test suite.

**Run results** (`clean-install` ✅ · `unit-tests` ❌ · `app-boot` ✅):

The `app-boot` job passing is itself a result: all 15 pages render on Linux/Python 3.11 against the committed fixture, which is the first time this app has ever been proven to boot anywhere other than one Windows machine.

**The failure.** GitHub's job-log API needs repo-admin rights, but check-run annotations are public, and they gave the decisive detail: `Process completed with exit code 2`. Exit 2 is pytest's *collection* failure — not an assertion failing, a test module failing to import. It also failed identically on the previous commit, which predates the tests added in §24/§25, so the fault lay in the §21 tests.

**Cause.** `tests/test_regime_status_gap_detection.py` did `import dashboard` at module scope. Importing `dashboard.py` executes the entire Streamlit script, including `load_data()`, which queries `psx_data.db`. At module scope that runs during collection, so on any machine without a local database — i.e. every CI runner, since `psx_data.db` is gitignored — the import raised and pytest aborted the session:

```
ERROR tests/test_regime_status_gap_detection.py - sqlite3.OperationalError: no such table: prices
!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!
```

Reproduced exactly in a fresh clone with no `psx_data.db` before changing anything.

**These tests had only ever passed on a machine that happened to have the production database sitting next to them.** That is precisely the "works on my machine" class §22 A6 describes — and it was living inside the test suite written to prevent it. Nineteen tests that looked like coverage were, on any other machine, a collection error.

**Fix.** `dashboard` is now imported lazily inside the fixture rather than at module scope, staging the committed fixture database first if there isn't a usable one and removing it afterwards. Every test still monkeypatches `DB_PATH` to its own temp database; the staged copy exists only to survive the import.

**A second, smaller trap found while fixing it**, worth writing down because it cost a wrong diagnosis: checking `os.path.exists(psx_data.db)` is not enough. Any run that imports `dashboard.py` without a database *leaves an empty `psx_data.db` behind*, because `sqlite3.connect()` creates the file before the first query fails. The next run then sees a file, trusts it, and fails at fixture setup instead of collection — which is exactly what happened mid-fix and briefly sent this investigation after the wrong culprit (an imagined test leaking a file, disproved by running each module in isolation). The check is now "does this file actually have a `prices` table", and it refuses to overwrite a large-but-unreadable file rather than risk clobbering a real database.

Verified under both conditions in a DB-less clone: fresh checkout → 34 passed, nothing left behind; stray empty `psx_data.db` present → 34 passed.

**What this says about the gate.** It went red on its first real run, on a genuine defect, in code written the day before by the same session that built it. Three points worth keeping:

1. **A test suite that has never run anywhere but one machine is not yet coverage.** The §21 tests were written, run locally, reported as passing, and committed — and would have failed for anyone else, including the CI job written specifically to run them.
2. **The gate's value showed up immediately and was not the value advertised.** §23 justified `app-boot` as the job that catches what unit tests cannot. In practice the first thing caught was the unit tests themselves being unrunnable.
3. **Red on the first run is the system working**, not a setup problem to be waved through. The temptation to treat an early CI failure as noise is exactly how a gate becomes decorative.

---

## 27. <span style="color:#dc2626;">🔴 The `bos_flag` fix was necessary but NOT sufficient — a second Postgres-only bug, and a wrong prediction (2026-08-12)</span>

§25 ended by stating that once the boolean fix was pushed, "the next successful daily run will backfill them automatically (~1,950 rows)." **That prediction was wrong.** The daily scraper ran at 17:55 UTC on the fixed commit, succeeded on every step, advanced `stock_signals` to `2026-08-12` — and `setup_log` did not move. It is still frozen at `2026-06-30`, now **30** dates behind rather than 29.

### 27.1 What was actually wrong, and how it was found

The mistake in §25 was declaring victory from a *query* test. Verifying that the four SELECTs execute proved only that the SELECTs execute; it did not exercise the insert. The second bug lives one line past where the checking stopped.

Ruled out first, so this is diagnosis rather than guesswork:

- **Hook not reached?** No — every step of the run reports success, and `main.py` wraps each hook in `try/except`, so a hook failure is invisible at the step level.
- **Wrong dates chosen?** No. Replaying `_pending_setup_log_dates()` against production returns exactly the 30 missing dates, with `already` and `signal_dates` both `datetime.date`.
- **Insert path.** Replayed the hook's own step-1 insert against production inside a transaction that was rolled back:

```
psycopg2.extras.execute_batch(...)
IndexError: tuple index out of range
```

**Root cause:** `rows = [tuple(r.values()) for r in cur.fetchall()]` on a `RealDictCursor`. Each SELECT projects **two unnamed literals** — `'BREAKOUT'` and `'BREAKEVEN'` — and Postgres names *both* of them `?column?`. In a dict the duplicate key collapses, so a 14-column SELECT returns **13 keys**. Confirmed directly against production:

```
SELECT lists 14 columns. RealDictCursor returned 13 keys:
['symbol','date','?column?','regime','rs_rank','sector_rs_rank','rank_change',
 'rs_score_20','base_tightness','vol_contraction','pivot_distance_pct',
 'bos_flag','sector']
```

13 values against 14 `%s` placeholders → `IndexError` on **every row, every day**, caught by the per-date `except`, rolled back, logged as a `WARNING`, pipeline reports success. SQLite is unaffected: `sqlite3` returns tuples, so no dict ever collapses. A third instance of the same family as the `TEXT`/`DATE` gotcha, the §16 Decimal-vs-float bug, and §25's boolean — **but the first one that is not a type mismatch at all**; it is a *shape* loss caused by the cursor factory.

### 27.2 Fix

The `SELECT` + `INSERT` loop now uses a dedicated **plain cursor** (`tup_cur`), so rows arrive as tuples and no dict round-trip exists to lose a column. The literals are also aliased (`'BREAKOUT' AS setup_type`, `'BREAKEVEN' AS outcome_label`, 20 sites across the SQLite and Postgres query sets) as defence in depth, but the cursor is the actual fix.

**Verified against production, rolled back**: 70 rows for `2026-07-01`, 72 for `08-11`, 70 for `08-12` — 212 across three sampled dates, `setup_log` count unchanged at 41,546 after rollback.

### 27.3 Three source-level guards added

The Postgres path cannot be exercised in CI (no Postgres — §23.5), so these pin the failures at the source level instead: no `tuple(r.values())`, the SELECT/INSERT must use the plain cursor, every literal in a Postgres SELECT must be aliased, and no `bos_flag = 0/1` on the Postgres path. **Checked by mutation, not assumed**: reintroducing `bos_flag = 1` and a bare `'BREAKOUT'` each make the corresponding guard fail. Suite is now 53 tests.

Writing them surfaced two false positives worth recording, because both are traps for the next person: the guards initially matched **their own explanatory comments** (which necessarily quote the bad strings), and then the labelling `UPDATE`'s legitimate `outcome_label = 'BREAKEVEN'`. They now strip Python and SQL comments and scope to the `queries_pg` block only.

### 27.4 The uncomfortable part

Production `setup_log` has been dead since the E8.7 port — **not** since 2026-08-12, and not for one reason. Two independent Postgres-only bugs sat in the same function, and the first fix's verification was shaped to the first bug: it proved the SELECTs ran, then predicted success for the whole path. A prediction is not a verification, and "the queries execute" was never evidence that "the rows land."

What would actually have caught both, on day one, is the thing §23.5 already names as the gate's largest hole: **a Postgres service container in CI**. Two silent six-week outages is now the empirical case for it, and it should be treated as the next piece of work rather than a nice-to-have.

**Still not repaired:** production data. The fix is verified but the 30 dates remain missing until a successful run writes them.

---

## 28. Hook error handling narrowed, and the register of what is still swallowed (2026-08-13)

Two Postgres-only bugs (§25, §27) each raised on every row of every date for weeks and were invisible because the handler around them was `except Exception -> log.warning`, and because `main()` never set an exit code. Thirty consecutive dead runs looked like thirty successful ones.

### 28.1 What changed

`setup_log`'s hook only. Transient database errors (`psycopg2.OperationalError`, `InterfaceError` — a dropped connection, a lock timeout) are still caught, logged and tolerated for that date, because the next run backfills it. **Everything else re-raises**, is logged with a traceback and a `::error::` annotation, is recorded in `main.py`'s `_HOOK_FAILURES`, and makes `cmd_update()` exit non-zero at the end — *after* every remaining hook has still had its turn, which is the part of the original design worth keeping.

### 28.2 <span style="color:#dc2626;">The register: 15 handlers still swallowing, in `cmd_update()`</span>

Recorded **2026-08-13**. The point of dating this is that "we'll narrow the rest later" is exactly the kind of promise that becomes permanent. If this table is still unchanged in a month, that is itself the finding.

Everything below is still `except Exception -> logger.warning` + exit 0.

| # | Line | Hook | Why it is still broad | Tier |
|---|---|---|---|---|
| 1 | 238 | `append_latest_regime()` | Writes `market_regime`, which drives the sidebar regime widget and every gate. **Already silently lost data once** (§21). | **1** |
| 2 | 268 | `sector_signals` | Writes `sector_signals`; same 2026-08-07 silent loss as regime. | **1** |
| 3 | 274 | `stock_signals` | Writes `stock_signals` — the table every setup query reads. | **1** |
| 4 | 231 | `prices_adjusted` + suspects | Writes `prices_adjusted`; a corporate-action miss corrupts every downstream signal for that symbol. | **1** |
| 5 | 168 | Leaders deep scan (early) | Writes `leaders_scan`; frozen since 2026-06-30 for the same boolean bug (§25). | 2 |
| 6 | 337 | Leaders deep scan (late) | Second call site of the same hook — both need the same treatment, and the duplication is worth resolving. | 2 |
| 7 | 250 | `days_to_nearest_transition` backfill | Writes a derived column; failure is quiet and cumulative. | 2 |
| 8 | 182 | Rolling trim (early) | Deletes rows outside the 2-year window. A silent failure grows the DB; a silent *success* on the wrong predicate deletes real data. | 2 |
| 9 | 379 | Rolling trim (late) | Second call site, as above. | 2 |
| 10 | 153 | Same-day re-check | Decides whether to re-scrape when data looks current; failure means a stale day passes unnoticed. | 3 |
| 11 | 343 | `run_analysis` | Read/report path, no writes. | 3 |
| 12 | 362 | Breadth oscillator | Runs a subprocess; failure only affects a chart. | 3 |
| 13 | 262 | Flow scrape | Feeds `market_flows` -> `sector_signals.flow_*`, a **write-only chain nothing reads** since the Flows page was retired (§12). Needs a keep/kill decision before it can be made fatal. | 4 |
| 14 | 306 | Boring Breakouts | SQLite-only; on a fresh Actions checkout the eligible universe is empty, so it is a no-op there by design. | 4 |
| 15 | 329 | Agent daily | `anthropic` is in no requirements file (§23.5), so this fails on every Actions run today. | 4 |

**Tier 1** — make fatal next. They write the core signal chain and have a demonstrated history of silent loss.
**Tier 2** — after tier 1, once each has been observed failing/not-failing for a week.
**Tier 3** — low blast radius; narrow when convenient.
**Tier 4** — <span style="color:#dc2626;">cannot be made fatal without a decision first</span>: each is *believed* to fail or no-op on Actions today. Making them fatal now would paint the daily run red every morning, and a permanently-red pipeline teaches you to ignore red — which is how this entire class survived.

**Triage step 0, before any of the above:** confirm, from a real Actions log, which of these 15 currently fail on every run. That status is inferred from code and documentation here, **not** verified against a production log — the same shortcut that produced the wrong prediction in §27. Do that first.

### 28.3 <span style="color:#dc2626;">Tracked, untriaged: the same `continue` hazard in the SQLite path</span>

Recorded **2026-08-13**, deliberately **not fixed**, so it cannot quietly
disappear from the record.

The Postgres loop now `break`s on a transient error instead of continuing to
the next date (§28.1). `append_setup_log_today()`'s **SQLite** loop still has
the original shape:

```python
except Exception as exc:                       # still broad
    log.warning("setup_log step 1 (insert) failed for %s: %s", target_date, exc)
                                               # ...and falls through to the next date
```

**Why it matters:** `pending` is ascending and the next run resumes from
`MAX(setup_date)`, so the committed dates must stay a contiguous prefix. A
failure on date N that then commits N+1 pushes the high-water mark past N, and
`d > last_logged` can never reach N again. That is the same permanent-loss
shape as §21 and §24 — reintroduced through the error path rather than the
happy path.

**Why it is not urgent:** this path only runs against local SQLite. Production
is Postgres and is now fixed. The blast radius is the local database on one
machine, which is also the one place a hole is easy to spot and repair with
`append_setup_log_for_dates()`.

**Why it is not fixed anyway:** the SQLite branch's handler is still a broad
`except Exception`, so narrowing it is the same judgement call as the 15
handlers in the table above — which transient types to tolerate, and whether a
local run should fail loudly. Doing it properly means the same triage, and it
was out of scope for the change that fixed the Postgres side. Doing it
carelessly (a bare `break` under a broad `except`) would stop the loop on
genuine bugs too, which may well be right, but is a decision, not a tidy-up.

**Triage: same tier as the table above's Tier 2.** Ships with, or just after,
the first batch of narrowed handlers.

### 28.4 Sweep scope, for the record

The §27 sweep covered **all of `psx_pipeline`**, not just Postgres-adjacent files, flagging any file containing `RealDictCursor` (16 files; 9 are dead `database_pg_backup_e*.py`). Files that talk to production through *plain* cursors are immune to this class by construction — a tuple cannot collapse — which is why they are not in the list.

Checked and clear, so the boundary is explicit rather than assumed:

- **Zahra** (`D:\BUSINESS\US Trading\zahra`) — 66 Python files, **zero** `psycopg2`, zero `RealDictCursor`, zero references to `DATABASE_URL`/`SUPABASE_DB_URL`. No shared code path with this pipeline's DB layer.
- `big_fish`, `ml_feature_study`, `breadth_momentum_study`, `engulfing_Study`, `Linda_Raschke-Study` — all zero on both counts.
- `ARCHIVED_PSX_SCRAPER` (1 file) and `backups/` (2 files), skipped by the original sweep — re-checked, zero hits, so the skip hid nothing.
- `research_db.py`, the opt-in Postgres bridge for the six ZH_research scripts, uses `pd.read_sql_query`, not a dict cursor. Duplicate column names there produce visibly duplicated DataFrame columns, not a silent row-shortening.
