# Boring Breakouts — Overnight Gap / Execution-Slippage Study

**Date:** 2026-08-28
**Scope:** Every signal in the cloud (Supabase) `boring_signals` table — the Explorer page
"Boring Breakouts" tab — from screener inception (2026-07-10) through 2026-08-27.
**Type:** Read-only event study. No code or database changes.

---

## The question

Boring signals fire on the **close** of day *t* (the `trigger_price` on the dashboard **is**
that close — verified: it matches `prices_adjusted` close to the paisa on all 393 rows). A
manual trader can't act until the **open** of day *t+1*. How often, and by how much, does the
stock gap away from you overnight?

```
gap %  =  (Open(t+1) − Close(t)) / Close(t) × 100
```

Open(t+1) is the open of the next trading date that exists for that symbol in
`prices_adjusted`. Adjusted and raw prices give identical gaps over this window (no corporate
actions), so the number is clean.

---

## Headline result

Counting **one event per (symbol, signal_date)** — 232 distinct signals, 232 with a usable
next-day open:

| Metric | Value |
|---|---|
| **Gapped UP at the open** | **76.3 %** (177 / 232) |
| Opened flat (± 0) | 4.3 % |
| Gapped DOWN (in your favour) | 19.4 % |
| **Mean gap (signed)** | **+3.31 %** |
| Median gap (signed) | +1.55 % |
| **Mean gap magnitude ( \|gap\| )** | **4.07 %** |
| Median gap magnitude | 2.29 % |
| Mean magnitude of the *up-gaps only* | **+4.83 %** (median +3.29 %) |

Counting **all 400 rows** (the 20-day and 60-day Donchian variants listed separately, as the
dashboard shows them) barely moves it: 75.8 % gap up, mean **+3.34 %**, mean magnitude 4.12 %.

### How big are the up-gaps?

Of the 232 distinct signals:

| Overnight move | Share of all signals |
|---|---|
| Gap up ≥ 3 % | **39.7 %** |
| Gap up ≥ 8 % | **25.0 %** |
| Gap up the full daily limit (~10 %) | **20.7 %** |

One signal in four opens essentially **limit-up** the next morning. One in five is pinned at
the +10 % circuit cap, so the true unconstrained gap on those is even larger than measured.

---

## Confirmed vs. "Not Fit"

The gap problem is **real in both states, and slightly worse for the "Not Fit" signals**:

| Cut | N | Gap-up rate | Mean gap | Median gap | Mean \|gap\| | Gap up ≥ 8 % |
|---|---|---|---|---|---|---|
| **Strategy Confirmed** (RS decile 9 + liquidity) | 55 | 74.5 % | **+2.39 %** | +1.39 % | 3.43 % | 16.4 % |
| **Not Fit** (everything else) | 177 | 76.8 % | **+3.59 %** | +2.16 % | 4.27 % | 27.7 % |

The actionable set (Strategy Confirmed) still gaps up ~3 times in 4, but the *typical* gap is
about half as large — median +1.4 % vs +2.2 %, and only 1-in-6 blows out past 8 % vs better
than 1-in-4 for the unfiltered feed.

Month-over-month the picture is stable (Jul: 70 % up / +3.4 % mean; Aug: 81 % up / +3.3 %
mean) — this is not a one-week artifact.

---

## The one piece of good news for execution

Among the 177 up-gap events, **111 (63 %) printed a next-day LOW at or below the signal
close.** In other words, on roughly two-thirds of the up-gaps the stock came back down
intraday to the trigger price at some point during day *t+1*.

**Implication:** a *limit order at (or just above) the signal close*, left working through
day t+1, would have filled on ~63 % of the up-gaps — turning the average realised entry
slippage from ~+4.8 % (market-on-open) toward roughly 0. The cost is the ~37 % of up-gap
days (and the very strongest runners specifically) where price never comes back and you
simply don't get filled — i.e. you miss the trade rather than chase it.

---

## What this means for the trade rule

1. **Market-on-open is expensive.** Expected entry slippage ≈ **+3.3 %** vs the signal price,
   ≈ +4.8 % conditional on the (majority) up-gap case. The validated Boring edge
   (TARGET +10 % / STOP −6 %) does not survive paying that on entry — a +3.3 % worse entry
   turns the +10 % target into ~+6.5 % and the −6 % stop into ~−9 %.

2. **A working limit at the signal close is the natural fix** — fills ~63 % of up-gaps near
   the intended price, at the cost of missing the ~25 % of signals that open limit-up and
   never look back.

3. **Prefer the Strategy-Confirmed subset** for execution: same gap-up frequency but roughly
   half the gap magnitude and far fewer limit-up opens.

4. **A hard "don't chase" cap is worth pre-committing to** — e.g. skip any signal whose
   t+1 open is already > X % above the trigger (25 % of signals are ≥ 8 % gapped; those are
   exactly the ones where a stop-based entry is incoherent).

---

## Caveats

- **N is small** — 232 distinct events, 7 weeks of live history. Directionally strong
  (76 % is not a coin-flip) but the magnitude tails will move.
- The cloud `boring_signals` table's own integrity is still **AMBER / DO NOT TRADE** per the
  Production Integrity Program (missing 2026-07-07 calendar day, 87 dedup-conflict pairs,
  no SQLite/PG parity test). This gap study is descriptive of what's *in* the table; it does
  not certify the table.
- "Next trading day" was Fri→Mon or across a holiday for ~34 % of events. Those are still
  genuine single-session overnight gaps, just with a weekend in them.
- 12 of the 232 events are still `Pending` (unresolved); the other 220 are `Stopped`. Gap
  measurement doesn't depend on the outcome, so all 232 are included.

---

# Part 2 — Do the fillable gap-ups actually make money?

Follow-up: join each event to its realised outcome. Outcome uses the **dashboard's own
convention** — collapse N20/N60 to one trade, a trade is *resolved* once `status = 'Stopped'`,
`ret% = (current_stop − trigger_price) / trigger_price × 100`, **win = ret > 0** (there is no
take-profit; the exit is the HYBRID trailing-stop level, −8 % floor from entry). Entry is
assumed exactly at the signal close for both the fill test and the return — internally
consistent with how `boring_signals` resolves every row.

Population = same as Part 1 (all fired signals, one event per symbol/date, includes the
`dedup_conflict` rows so the 177 / 111 tie out). Numbers **excluding** `dedup_conflict` (the
dashboard's valid-outcome set) are given alongside.

### Q1 — Fill-to-Loss Rate

Of the **111** up-gap events where a limit at the signal close would have filled
(`Low(t+1) ≤ Close(t)`): 108 have resolved, 3 still open.

| | incl. dedup_conflict | excl. dedup_conflict |
|---|---|---|
| Resolved filled trades | 108 | 75 |
| **Exited at a LOSS** | **86 → 79.6 %** | **60 → 80.0 %** |
| Exited at a win | 22 → 20.4 % | 15 → 20.0 % |
| Mean exit return | +2.46 % | +1.31 % |
| Median exit return | **−1.97 %** | −1.98 % |
| (mean win +25.8 %, mean loss −3.5 %) | | |

**≈ 4 out of 5 of the trades you can actually get filled on at the signal price lose.**
The mean is still marginally positive only because a handful of the 22 winners are huge
(+25 % average) — names that dipped to the trigger on day t+1 and *then* ran.

### Q2 — Gap-Up Win Probability

Of the **177** gap-up events (`Open(t+1) > Close(t)`): 170 resolved, 7 open.

| | incl. dedup_conflict | excl. dedup_conflict |
|---|---|---|
| Resolved | 170 | 101 |
| **Closed positive (win)** | **84 → 49.4 %** | **41 → 40.6 %** |
| Closed negative | 86 → 50.6 % | 60 → 59.4 % |
| Mean exit return | +9.84 % | +5.08 % |
| Median exit return | 0.0 % | −0.67 % |

A gap-up entry is **roughly a coin flip** on the inclusive set, **~41 %** on the clean set —
about the same as the strategy's unconditional resolved win rate (40.2 % incl / 32.1 % excl),
i.e. gapping up by itself tells you almost nothing about whether the trade wins.

### The interaction that matters

| Sub-group (resolved, incl. dedup) | N | Win rate | Mean return |
|---|---|---|---|
| Gap DOWN at open | 45 | 8.9 % | −0.2 % |
| Gap up 0–3 % | 82 | **24.4 %** | −0.2 % |
| Gap up 3–8 % | 32 | 56.2 % | +7.0 % |
| Gap up > 8 % | 56 | **82.1 %** | +25.6 % |
| — Gap up **AND** retraced to close (fillable) | 108 | **20.4 %** | +2.5 % |
| — Gap up **AND never came back** (un-fillable) | 62 | **100 %** | +22.7 % |

**Every winner in this window that gapped up and never traded back to its signal close.**
The trades that oblige you by dipping back to the trigger are overwhelmingly the ones that
were already failing. This is partly mechanical — an entry-anchored trailing stop plus a
fill test that selects for immediate reversal — but it is also a real signal: a breakout
that immediately fills back to its breakout close is a weak breakout.

### Revised execution implication

The "leave a limit at the signal close" idea from Part 1 **does not rescue the entry** — it
just systematically fills you into the worst cohort (20 % win rate) and leaves you flat on
the +25 % runners. The usable reading is closer to:

- A working limit at the close is only worth it as a *cheap option* — most fills are losers
  that the −8 % floor caps quickly, and you keep the rare dip-then-rip.
- The bigger lever is a **momentum filter on the open itself**: the ≥ 8 % gap-ups (82 % win
  rate) are the opposite of "don't chase" — historically they were the trades to take at the
  open despite the gap. The 0–3 % gap-ups (24 % win rate) are the trap.
- N is small (56 in the > 8 % bucket, 15 filled Strategy-Confirmed trades) and exits are
  modelled optimistically — treat the bucket win rates as directional, not settled.

---

## Caveats (Part 2)

- **Modelled exits** — a resolved trade books out at the trailing-stop *level*, not the
  printed low; real fills on circuit-lock days are worse, so every win rate here is an
  optimistic bound.
- **Entry assumed at the signal close** for both the fill test and the return. Real fills
  differ; that's the whole point of Part 1.
- **Mechanical / selection coupling** — `fillable_at_close_t` and an entry-anchored stop are
  not independent, so Q1's 80 % is not a pure "these setups are bad" statement.
- Small N, still AMBER / DO NOT TRADE on the underlying table.

## Files

- `scripts/s1_cloud_gap_event_study.py` → `data/cloud_gap_detail.csv` — Part 1 (overnight gap).
- `scripts/s2_cloud_gap_outcomes.py` → `data/cloud_gap_outcomes.csv` — Part 2 (gap × outcome join).
- All read-only; connect via `_paths.cloud_conn()` (SUPABASE_DB_URL from `psx_pipeline/.env`).

> **Snapshot note:** the `data/cloud_*.csv` here are a **2026-08-28** snapshot of the cloud
> `boring_signals` table (400 rows, including the 87 `dedup_conflict` pairs). OI-7
> (2026-08-30) removed those pairs — the live table is now ~237 rows, so re-running s1/s2
> today produces smaller counts. The numbers in this report are the 2026-08-28 state.
