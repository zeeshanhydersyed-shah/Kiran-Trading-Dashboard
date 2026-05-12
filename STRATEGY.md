# Kiran Trading — Strategic Direction

*Created: 2026-05-12. Last updated: 2026-05-12. Preserve this file.*
*Reference it before rebuilding anything in this project.*

---

## The Decision (after 7 years)

Active trading — waiting for breakout triggers, managing SL ticks daily — does not
justify the time and psychological cost. Simulation confirms this:

- Best active sim (v6, 2020–2026): +53.6% total = **7.45% CAGR**
- KSE-100 same period: ~22% CAGR
- Pakistan fixed deposit (recent years): 15–22%

The learning phase is over. The new objective:

> **Beat the KSE-100 index by owning only the leading stocks.**

---

## The Philosophy

**Singles and doubles make the score. Sixes get you out.**

- The **1% risk rule stays permanently.** It is not timidity — it is what keeps you
  in the game through bad periods. Lose 10 trades in a row and you are still only
  down 10% of capital. You can only win when you are in the game.
- Preservation of capital > maximising any single trade.
- The index is forced to own everything — Stage 1, 2, 3, and 4 stocks. You are not.
  Owning only Stage 2 leaders, and being short Stage 4 laggards in bear markets,
  is the structural edge.
- **System + discretion is the edge.** The screener finds the candidates.
  Experience and judgment decide which ones to act on.

---

## The Complete Trading System

### Step 1 — Regime Filter (top-down, non-negotiable)

| Signal | Bias | Action |
|--------|------|--------|
| KSE-100 > 50d MA **AND** Z-histogram > 0 **AND** breadth ≥ 70 | Bull | Look for LONG setups only |
| KSE-100 < 50d MA **AND** Z-histogram < 0 **AND** breadth ≤ 30 | Bear | Look for SHORT setups only |
| Mixed signals | Neutral | Reduce size or sit out |

The Regime page Z-score histogram is the primary confirmation tool.
When KSE-100 is below the 30-week MA and bouncing back up to it from underneath —
that is a distribution/resistance signal, not a recovery. Do not be fooled by
dead-cat bounces back to a broken MA. (Observed: KSE-100 broke 30w MA ~27 Feb 2026.)

### Step 2 — STM Screener (candidate list)

The STM page provides candidates automatically based on regime:

**LONG conditions (bull regime):**
- Sector in top 35% by 30d performance
- Close > 21 MA > 50 MA (uptrend, MAs aligned)
- Stock outperforming KSE-100 on 30d basis
- 5-day range ≤ 10% (tight consolidation)
- Avg volume ≥ 500k (liquid)
- SL = 1% below day low

**SHORT conditions (bear regime — exact mirror):**
- Sector in bottom 35% by 30d performance
- Close < 21 MA < 50 MA (downtrend, MAs aligned down)
- Stock underperforming KSE-100 on 30d basis
- 5-day range ≤ 10% (tight consolidation — avoid chaotic names)
- Avg volume ≥ 500k
- SL = 1% above day high

Quality score 0–4 shown for each stock. Score ≥ 3 is best.

### Step 3 — Entry

- Enter on strength (buy above resistance / sell below support)
- 1% of capital risk per trade
- SL at structural support (LONG) or resistance (SHORT)
- Discretion applied: not every screener name is worth taking

### Step 4 — Exit (trail the 20-day MA)

- **Hold as long as the stock is above its 20-day MA (LONG)**
- **Cover when stock closes above its 20-day MA (SHORT)**
- No fixed T1 or partial exits — let the MA do all the work
- Review weekly. No intraday management needed.

### Why 20-day MA (not 10-day, not 30-week)

- 10-day MA exits too quickly — cuts winners short (v1/v6 simulations)
- 30-week MA exits too slowly — gives back too much at the end
- 20-day MA holds through normal pullbacks in a trending stock while
  getting you out promptly when the trend genuinely breaks

---

## Portfolio Screener (Stage 2 long-term holds)

Separate from the STM day-to-day system. For longer-term position building.

The **Portfolio page** in the dashboard shows:
- **Stage 2 tab** — top candidates ranked by composite score (RS + stage clarity +
  sector strength + RS trend). These are stocks to hold for months.
- **Stage 1 tab** — basing stocks near 30w MA. Early watchlist.
- **Stage 3 tab** — exit alerts for any current holdings.

Entry: buy Stage 2 stocks using 1% risk rule (SL = 30-week MA).
Exit: weekly close below 30-week MA only. Review weekly.

---

## What NOT to do

- Do not trade when regime is mixed or neutral — sit out
- Do not override the 1% risk rule for "high conviction" trades
- Do not exit winning trades early — let the 20-day MA decide
- Do not trade STM signals when KSE-100 is in Stage 4 (below declining 30w MA)
- Do not add complexity. The system is complete.

---

## Dashboard pages reference

| Page | Purpose |
|------|---------|
| 📊 Market | Breadth, sector rankings, top candidates — daily overview |
| 🧭 Regime | Z-score, Weinstein breadth — **check this first every session** |
| 🔎 STM | LONG and SHORT candidates (tabs) — auto-filtered by regime gates |
| 🗂️ Portfolio | Stage 2 screener for longer-term holds |
| 📋 Trade Log | Track all open and closed trades |
| 🎯 Setup Perf | Historical setup performance stats |
| 🤖 Backtest | Historical backtest engine results |

---

## Simulation findings (reference only)

| Variant | Return 2020–2026 | CAGR | Notes |
|---------|-----------------|------|-------|
| v1 — SL=6%, T1=1R split | +36.9% | 5.4% | Original |
| v6 — SL=6%, full 10d MA trail | +53.6% | 7.4% | Best parameter variant |
| **v3 — regime filter + 20d MA trail** | **+22.8%** | **3.3%** | Complete system sim |
| KSE-100 index | ~220% | ~22% | Benchmark |

**Why simulations understate real performance:**
- Simulations take every screener signal blindly — no discretion applied
- Idle capital earns 0% in sim (real money earns 15–22% in T-bills)
- System + discretion = the actual edge; simulation = the floor, not the ceiling
- The structural advantage (only Stage 2, exit on MA break) compounds over time
  in ways the backtest cannot fully capture

---

## Files in this project

| File | Role |
|------|------|
| `dashboard.py` | Main app — all pages |
| `processor.py` | Run analysis — sector rankings, candidates |
| `weinstein.py` | Weinstein stage / regime / Z-score |
| `portfolio.py` | Stage 2 portfolio screener computation |
| `kiran_sim.py` | Simulation v1 (baseline) |
| `kiran_sim_v3.py` | Simulation v3 (complete system) |
| `backtest.py` | Historical backtest engine |
| `phase4_train.py` | ML model retrain (weekly via GitHub Actions) |
| `kiran_model.pkl` | LightGBM — win probability score |
| `database.py` / `database_pg.py` | SQLite (local) / Supabase (cloud) |
| `STRATEGY.md` | **This file** |
