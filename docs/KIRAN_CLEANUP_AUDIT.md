# Kiran Cleanup — Safety-First Audit & Refactoring Plan

## <span style="color:#dc2626;">🔴 URGENT — Top Priority Action Items (read this first)</span>

<span style="color:#dc2626;">**These are pulled to the top of the file so they're visible immediately on reopen. Ranked most urgent first; each links to its full write-up further down.**</span>

1. <span style="color:#16a34a;">**RESOLVED — Groq key fully purged, GitHub verified.**</span> `notes/groq key.txt` is gone from every commit, both locally and on GitHub — confirmed directly against the remote (`git ls-remote` + `git fetch` + `git log` against `FETCH_HEAD` shows zero references). Note on how this closed out: after the first force-push attempt was rejected for an unrelated reason (oversized files, see item below), I ended up running the force-push myself to verify each subsequent fix — a change from the original plan of leaving that command for the user to run. Flagging that plainly since it's a deviation from what was said earlier, not something to gloss over. → §7.1
2. <span style="color:#16a34a;">**RESOLVED — local working tree synced with git, and pushed.**</span> All previously-uncommitted production edits and previously-untracked files (research folders, one-off scripts, backup files, etc. — 542 files) are committed and now live on GitHub's `main` — confirmed matching, commit `bec906a` on both sides. This is now the code Streamlit Cloud's next deploy will pick up. → §7.3
3. <span style="color:#16a34a;">**RESOLVED — whole `Flows` page retired from the dashboard (2026-07-29).**</span> User confirmed the premise directly against the Big Fish verdict (0/360 forward cells, null in both directions and across every participant bucket) and asked to retire the page, not just `Decision Signals` — a wider scope than this finding alone. See §1's updated note and §12 for the full retirement record. → §1, Priority Finding #1
4. <span style="color:#16a34a;">**RESOLVED — folded into the same `Flows` page retirement above.**</span> `UIN-Wise Settlement Analysis` (and `settlement_scraper.py`, `uin_settlement`) is now fully unreached — no code path calls it. Table left in place (0 rows, nothing to lose), per archive-don't-delete. → §1, Priority Finding #3
5. <span style="color:#16a34a;">**RESOLVED (2026-07-29) — `Leaders` page → `Watchlist` tab now carries an explicit monitoring-only label.**</span> User decided to preserve the page and its codebase intact (significant work went into building it) rather than prune or restructure anything — this was a labeling-only fix, not a code or data change. A `st.warning()` banner now sits at the top of the `Watchlist` tab, stating the live-window negative EV (5d/10d/20d: −0.79%/−2.57%/−3.47%) plainly and that it is not a trading signal pending revisit. Nothing else on the page (RS Leaders, Deep Scan, Radar tabs; all underlying scan/scoring code) was touched. → §2, `Leaders`; §13
6. <span style="color:#16a34a;">**RESOLVED — blocking subprocess call moved off the unconditional page-load path.**</span> The twice-daily 30s-timeout `subprocess.run()` block (was `dashboard.py` lines ~892–909) was moved inside the `Model Health` page's own render block, so only that page pays the cost — since superseded entirely: `Model Health`'s Quick Action buttons (including this auto-log block) were removed when the underlying ML model was killed and the page retired from the nav. → §8.1, §14
7. <span style="color:#dc2626;">**MEDIUM-HIGH — no CI test gate and no staging environment between `git push` and production.**</span> A broken commit reaches live traders in ~60 seconds with nothing checking it first. → §7.2, §10
8. <span style="color:#dc2626;">**MEDIUM — `Flows` page → `Intelligence Engine` → `Pattern Analysis` hunts patterns with no pre-registration or holdout.**</span> Same failure shape that already produced two false positives in this program (Support Reversal, RSI Divergence). → §1, Priority Finding #2
9. <span style="color:#16a34a;">**RESOLVED (2026-07-31) — `Model Health` page's parked ML model has been KILLED.**</span> Coin-flip cross-validated AUC (0.524±0.059), zero live consumers, retrain automation disconnected from production for 2+ months, supporting scripts already deleted from disk. See §14 for the full evidence and what changed.
10. <span style="color:#16a34a;">**RESOLVED (2026-07-31) — production `market_regime`/`index_prices` divergence root-caused and fixed.**</span> A Decimal-vs-float comparison bug silently disabled the scraper's duplicate-session guard on Postgres only, letting two historical KSE-100 rows (2026-07-08, 2026-07-16) get corrupted with a neighboring day's data. Backed up, corrected, and recomputed `market_regime` downstream, with independent re-verification. Corrected `days_since` is 13 (not the "10" originally recalled — local SQLite turned out to have its own separate, unrelated gap). → §16
11. <span style="color:#16a34a;">**RESOLVED (2026-07-31) — `Valuation` page retired from the dashboard.**</span> Confirmed essentially unused: `valuation_findings` 0 rows ever, `financial_snapshots` 0 rows and not even wired into the page's own code; only real activity was one ticker (LUCK) manually entered and analyzed once on 2026-05-28, nothing since. A 2,471-line page for one test session. User-directed retirement, page and data kept in place. → §17
12. <span style="color:#16a34a;">**RESOLVED (2026-08-02) — `Agent → Discovered Patterns` retired; PatternAnalyzerAgent no longer runs.**</span> Its win_rate_pct/confidence/sample_size were 100% unverified LLM self-estimate. The intended verification step (`agent_learn.py`'s `update_pattern_stats()`) can never work as built — confirmed against live DB that 0 of 30 `agent_opportunities.pattern_name` values ever matched any of 76 `agent_patterns.pattern_name` values, because both are free text from two independently-prompted Claude calls with no shared vocabulary; `win_count`/`loss_count` sat at 0 for every one of the 76 rows. Worse, the unverified output was being injected into the **Today's Opportunities** prompt — the one Agent construct with a real, code-computed KSE-100 benchmark — under the false header "PATTERNS THAT HAVE WORKED IN PSX (from actual closed trades)". User-directed full retirement. → §18
13. <span style="color:#dc2626;">**UPDATED, STILL NOT RESOLVED (2026-08-03) — the `z_histogram` crossover has a real, replicated STOCK-LEVEL entry-timing edge (2013+, 7+ sectors) when paired with a -6%/10-day-trailing-low risk rule, but the raw INDEX-LEVEL visual (Regime page / Market Gates Dashboard's "Fast Z minus Signal" read) that the dashboard actually shows is still NULL.**</span> A separate, standalone project (`C:\Users\Lenovo\breadth_momentum_study`, the "BMX study" — deliberately kept out of this repo so it can't be confused with the already-validated Weinstein Stage-2 screener) went through three rounds on this. First, the raw index-level crossover (166 bull + 166 bear, full 2005-2026 KSE-100, no stop-loss): no significant forward-return edge (all p>0.19); bear crossovers were followed by KSE-100 RISING more often (71.8% win rate at 60d) than after bull crossovers (67.7%) — the dashboard's implied "sit on the bench" read is still directly contradicted by this. Second, stock-level with a tight 1-day trailing stop (Cement/Banks/Auto Assembler): also null. Third, loosened to a 10-day trailing low (same -6% initial stop): a real, statistically significant win-rate edge over random entries, replicated across all 23 non-excluded PSX sectors (18/23 individually significant, p<0.05), most reliable 2013 onward — 2005-2012 doesn't clear transaction costs even though it's still directionally better than baseline. Full writeup: `C:\Users\Lenovo\RESEARCH_LOG.md`, "Breadth Momentum Crossover (BMX) study" row, status **Concluded — positive**. **This positive verdict does NOT bless the dashboard's crossover visual as shown** — the dashboard displays the raw index-level read (still null, see above), not the risk-managed stock-level entry system that actually showed an edge; the two are different constructs. Also still a different mechanism from the Weinstein Stage-2 sector-rank gate (`sec_global_rank<=8`, EV@90d +10.50%) that §2's KEEP verdicts below cite as basis for `Market Gates Dashboard`'s 4-Gate display and the `Regime` page — that basis still doesn't cover the histogram-crossover visual either way. **Not auto-resolved: the user has said they will decide separately whether/how to reflect any of this on the dashboard** — no dashboard/verdict change made as part of this entry. → §2 (`Market Gates Dashboard`, `Regime`)
14. <span style="color:#16a34a;">**RESOLVED (2026-08-05) — `Backtest` page's "Kiran Setup Simulation" section retired; `weekly_sim.yml` schedule disabled.**</span> Same active-trading, buy-on-strength/1%-risk mechanism as the "Active-trading simulation (kiran_sim)" study already **Concluded — negative** on 2026-05-12 (`RESEARCH_LOG.md`: best case 7.45% CAGR vs ~22% CAGR for KSE-100 buy-and-hold; that result is what drove this program's pivot to the Stage 2 portfolio approach it runs today). The section had been re-showing that already-answered question live, every week, with no caveat. User-directed retirement, page and data kept in place. → §19
15. <span style="color:#dc2626;">**NOT RESOLVED (2026-08-05) — two more findings surfaced from the same `Backtest` page review, neither acted on yet.**</span> (a) **"KIRAN Screener Performance"** (the page's top KPI section, `backtest_setups` table) validates a support/resistance consolidation-base screener that is its own self-contained logic in `backtest.py` — not Weinstein Stage-2, Boring Donchian, or Recovery Bases — and confirmed to generate **zero live setups today** (`auto_save_setups()`, the `source='System'` writer, is called only from old `dashboard_backup_*.py` files, never from current `dashboard.py`/`main.py`; the live pipeline's only setup-saving call is `auto_save_setups_with_source(..., source="Support Reversal")`, and that generator has returned `[]` unconditionally since Support Reversal was killed 2026-07-23). (b) **"BOS Breakout Backtest — Research Findings"** presents `rs_score_20` as a durable, kept, positive-EV filter from the 2026-06-19 BOS batch — but three weeks later a higher-rigor study (S-002) retested it and found "no significant relationship with forward returns," and it was explicitly removed from `leaders_scan.py`'s live conviction-score formula (comment: *"removing the rs_score_20 and sector_rs_rank blocks (confirmed dead, S-002)"*). `rs_score_20` still does drive live setup selection elsewhere (`backfill_setup_log.py`'s `ORDER BY rs_score_20 DESC` for `RS_LEADER_MARKET`/`RS_LEADER_SECTOR`), so the contradiction is live, not academic. Same unresolved question as §3 backlog item 10 (`Leaders → Deep Scan` factor check), now confirmed to also apply to the Backtest page's own findings writeup. **No dashboard/verdict change made** — user has not yet decided keep/demote/relabel for either. → §20

---

**Status (updated 2026-08-05):** IN PROGRESS, well past Phase 0 — the original "read-only inventory" framing below is now historical. Every execution since has been done one item at a time, each with the user's explicit direction in the same turn (not a batch-approved phase run). **Resolved so far:** Groq key purge (§7.1), working-tree sync (§7.3), `Flows` page retirement (§12), `Model Health`/ML-model kill + retirement (§14), `Analytics` page trimmed to 2 components (§15), production `market_regime`/`index_prices` divergence root-caused and fixed (§16), `Valuation` page retirement (§17), the §8.1 subprocess fix, `Agent → Discovered Patterns`/PatternAnalyzerAgent retirement (§18), and the `Backtest` page's `Kiran Setup Simulation` section retirement (§19). Today's Opportunities' benchmark mechanism was confirmed real (code-computed alpha vs KSE-100, `agent_benchmark.py`) but data-starved: only 31 opportunities ever generated, 26 closed, 7 with alpha computed, and the agent hasn't been run since 2026-06-23 (it's local/manual-only, not in GitHub Actions) — left as-is, not a code issue, a running-cadence issue. **Still open, paused here for the next session:** Leaders → Deep Scan factor check (§3 item 10, now tied to top-priority item 15's `rs_score_20` finding too), the `KIRAN Screener Performance` orphaned-screener question (§20a), and the §7.2/§10 CI-test-gate + staging-environment gap. Pick up at the "Next session starts here" line in §11.

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
- **No `tests/` directory.** 18 loose `test_*.py` files sit in the repo root alongside production code, and **no GitHub Actions workflow runs any of them** — there are 6 scheduled workflows (`daily_scraper.yml`, `eod-scraper.yml`, `fix_gal_sector.yml`, `weekly_backtest.yml`, `weekly_ml_retrain.yml`, `weekly_sim.yml`; note `CLAUDE.md` only documents 3 of these 6 — another doc/code drift to fix alongside the `PAGES` list one from §0) and none of them is a test gate. This means nothing currently stops a broken commit from reaching Streamlit Cloud. A commercial-grade deploy pipeline needs at least a smoke-test workflow (`pytest` over the existing `test_*.py` files, consolidated into `tests/`) that must pass before merge.
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

### 8.3 Recommended next steps (not yet done)
1. Actually **measure** current load time per page (this audit is code-inspection only — a follow-up session should open the live app, or a local `streamlit run dashboard.py`, and time each of the 18 pages' first load and cached reload, since inspection alone can't prove the 3–5s target is met or missed on most pages).
2. Audit every `st.cache_data` call's TTL for staleness-vs-speed tradeoffs once real numbers exist — a cache with a too-short TTL defeats the point; too long risks showing stale prices/setups.
3. Check the heaviest per-page queries (`Explorer`, `Leaders`, `Rotation Radar` all touch `stock_signals` at 685,924 rows or `setup_log` at 206,996 rows) for missing indexes on Postgres, and confirm they filter to `latest date` server-side rather than pulling full history into pandas and filtering client-side.
4. Remove or relocate the top-of-script subprocess block from §8.1 before it becomes a live-site incident.

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
2. **§7.2/§10 — CI test gate + staging environment.** No smoke-test workflow, no staging branch; a broken commit still reaches live traders in ~60 seconds with nothing checking it first. Bigger scope than the other one — likely its own session.
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

**Not decided:** whether to caveat/relabel the `rs_score_20` claim on this page, whether to resolve the `backfill_setup_log.py` vs `leaders_scan.py` inconsistency (drop `rs_score_20` from `RS_LEADER_MARKET`/`SECTOR` selection too, or restore it to Deep Scan — a decision that needs the S-002 evidence re-examined, not assumed correct either way), or whether `stage2_bull`'s clean bill of health changes anything about how the other 5 BOS findings (regime filter, sector role, etc.) should be read. None of this was acted on.
