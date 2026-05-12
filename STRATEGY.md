# Kiran Trading — Strategic Direction

*Recorded: 2026-05-12. Preserve this file. Reference it before rebuilding anything.*

---

## The Decision (after 7 years)

Active trading — waiting for breakout triggers, managing SL ticks daily — does not
justify the time and psychological cost. Simulation confirms this:

- Best active sim (v6, 2020–2026): +53.6% total = **7.45% CAGR**
- KSE-100 same period: ~22% CAGR
- Pakistan fixed deposit (recent years): 15–22%

The learning phase is over. The new objective:

> **Beat the KSE-100 index by owning only the leading stocks. No active trading.**

---

## The Philosophy

**Singles and doubles make the score. Sixes get you out.**

- The 1% risk rule stays. It is not a position-sizing timidity — it is what keeps
  you in the game through bad periods. A 10-stock portfolio with 1% risk each
  means a complete wipeout of all positions still only costs 10% of capital.
- You can only win when you are in the game. Preservation of capital > maximising
  any single trade.
- The index is forced to own everything — Stage 1, 2, 3, and 4 stocks. You are not.
  Owning only Stage 2 leaders is the edge.

---

## The Strategy: Concentrated Stage 2 Portfolio

### Core rules

| Rule | Detail |
|------|--------|
| Universe | PSX stocks, Kiran-filtered sectors only |
| Entry condition | Stage 2 confirmed + RS vs KSE-100 > 0 + sector in Stage 2 |
| Portfolio size | 8–12 stocks at any time |
| Position sizing | 1% capital risk per position (SL = recent support / 30w MA) |
| Hold condition | Do nothing while stock remains in Stage 2 with positive RS |
| Exit condition | Weekly close below 30-week MA (Stage 2 → Stage 3 break) |
| Review cadence | Weekly only. Not daily. Not intraday. |
| Activity level | ~15–20 decisions per year total |

### Why this beats the index over time

The index cannot exit Stage 3/4 stocks — it must hold them by definition.
A portfolio that only holds Stage 2 leaders, and exits when stage breaks,
structurally avoids the index's biggest drag positions.

### What is NOT changing

- 1% risk rule for all position sizing (keeps you in the game)
- Kiran sector filters (no textiles, modarabas, sugar, etc.)
- Weinstein stage analysis as the primary framework
- RS vs KSE-100 as the quality filter within stages

---

## What was built (active trading phase)

All of this remains usable as a monitoring and signal layer:

- **Backtest engine** (`backtest.py`) — labels historical outcomes
- **Portfolio sim** (`kiran_sim.py`) — buy-on-strength execution sim
- **Weinstein analysis** (`weinstein.py`) — stage detection
- **STM screener** — short-term momentum setups (still valid as *watchlist* input)
- **Kiran model** (`kiran_model.pkl`) — predicts Win_Trail probability (still useful
  as a quality filter for portfolio candidates)
- **Dashboard** (`dashboard.py`) — all pages remain; new Portfolio page added

---

## The New Dashboard Page: Portfolio

See dashboard.py PAGES list — "Portfolio" page added.

Shows at any point in time:
1. **Current portfolio candidates** — Stage 2 stocks, ranked by composite score
   (RS rank + sector strength + stage clarity + Kiran model score)
2. **Hold list** — stocks currently in portfolio with stage/RS status
3. **Exit alerts** — any portfolio stock showing Stage 3 warning signs
4. **Watchlist** — Stage 1→2 transitions approaching (early entry candidates)

---

## Simulation findings (for reference)

| Variant | Return (2020–2026) | CAGR | Notes |
|---------|-------------------|------|-------|
| v1 baseline (SL=6%, T1=1R) | +36.9% | 5.4% | Original |
| v6 (SL=6%, full trail) | +53.6% | 7.4% | Best active variant |
| KSE-100 index | ~220% | ~22% | Benchmark |

Active sim cannot beat index because:
- Only 4.2% of signals ever trigger (capital sits idle in cash earning 0%)
- Small position sizes (1% risk = ~16% capital per trade) limit upside
- Idle cash in sim earns nothing; real fixed deposit earns 15–22%

---

*Next step: build the Portfolio screener page in dashboard.py*
