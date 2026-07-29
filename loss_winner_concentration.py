"""
loss_winner_concentration.py
--------------------------------
Descriptive diagnostics only, no new modeling. Uses triangle_ev_realistic_r.csv
(the final EV computation's per-candidate output, gap-adjusted realized_R
via lfd_gap_check.py, -3.0R floor applied here identically to the EV
session) joined with triangle_full_universe_symbol_notes.csv (liquidity
tier) and triangle_breakout_dates.csv (breakout calendar dates).
"""

import pandas as pd

FLOOR = -3.0

ev = pd.read_csv("triangle_ev_realistic_r.csv")
notes = pd.read_csv("triangle_full_universe_symbol_notes.csv")[["symbol", "tier"]]
dates = pd.read_csv("triangle_breakout_dates.csv")[["symbol", "start", "end", "breakout_date"]]

ev["R_final"] = ev["realized_R_realistic"].clip(lower=FLOOR)
ev = ev.merge(notes, on="symbol", how="left").merge(dates, on=["symbol", "start", "end"], how="left")
ev["breakout_date"] = pd.to_datetime(ev["breakout_date"])

print(f"Full population: n={len(ev)}")
print(f"Overall: mean R={ev['R_final'].mean():.4f}, win rate={(ev['R_final']>0).mean()*100:.1f}%")

# ═══════════════════════════════════════════════════════════════════════
# 1. SYMBOL-LEVEL LOSS CONCENTRATION
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\n1. SYMBOL-LEVEL CONCENTRATION\n{'='*70}")

by_symbol = ev.groupby("symbol").agg(
    n_candidates=("R_final", "size"),
    win_rate=("R_final", lambda s: (s > 0).mean() * 100),
    mean_R=("R_final", "mean"),
    total_R=("R_final", "sum"),
    sector=("sector", "first"),
).reset_index()

qualifying = by_symbol[by_symbol["n_candidates"] >= 2].sort_values("total_R").reset_index(drop=True)
print(f"\nSymbols with >=2 candidates: {len(qualifying)} of {by_symbol['symbol'].nunique()} total symbols in the 518-set")

print(f"\n--- worst 20 symbols by total_R (ascending) ---")
print(qualifying.head(20)[["symbol", "sector", "n_candidates", "win_rate", "mean_R", "total_R"]].to_string(index=False))

print(f"\n--- best 10 symbols by total_R (descending) ---")
print(qualifying.sort_values("total_R", ascending=False).head(10)[
    ["symbol", "sector", "n_candidates", "win_rate", "mean_R", "total_R"]
].to_string(index=False))

# Concentration: total negative R across ALL 518 individual candidates
total_negative_R = ev.loc[ev["R_final"] < 0, "R_final"].sum()
print(f"\nTotal negative realized_R across all 518 candidates: {total_negative_R:.2f}R")

n_qual = len(qualifying)
for pct in [0.10, 0.20, 0.30]:
    k = max(1, int(round(n_qual * pct)))
    worst_symbols = qualifying.head(k)["symbol"].tolist()
    neg_from_worst = ev[(ev["symbol"].isin(worst_symbols)) & (ev["R_final"] < 0)]["R_final"].sum()
    print(f"  worst {pct*100:.0f}% of qualifying symbols (n={k} symbols): "
          f"contribute {neg_from_worst:.2f}R of total negative R "
          f"({neg_from_worst/total_negative_R*100:.1f}%)")

print(f"\n--- sector-level totals (all symbols, not just >=2-candidate ones) ---")
by_sector = ev.groupby("sector").agg(
    n_candidates=("R_final", "size"), win_rate=("R_final", lambda s: (s > 0).mean() * 100),
    mean_R=("R_final", "mean"), total_R=("R_final", "sum"),
).reset_index().sort_values("total_R")
print(by_sector.to_string(index=False))

# ═══════════════════════════════════════════════════════════════════════
# 2. WINNER CONCENTRATION
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\n2. LARGE-WINNER CONCENTRATION (realized_R > 5.0)\n{'='*70}")

THRESHOLD = 5.0
winners = ev[ev["R_final"] > THRESHOLD].sort_values("R_final", ascending=False)
print(f"\n{len(winners)} candidates exceed {THRESHOLD}R:")
print(winners[["symbol", "start", "end", "sector", "tier", "breakout_date", "R_final"]].to_string(index=False))

print(f"\n--- liquidity tier breakdown of large winners ---")
print(winners["tier"].value_counts().to_string())
print(f"\n--- for comparison, tier breakdown of the FULL 518-candidate population ---")
print(ev["tier"].value_counts().to_string())
print(f"\n--- tier breakdown, % within each tier ---")
for tier in ["liquid", "mid", "thin"]:
    tier_total = (ev["tier"] == tier).sum()
    tier_winners = (winners["tier"] == tier).sum()
    print(f"  {tier}: {tier_winners}/{tier_total} candidates in this tier are large winners "
          f"({tier_winners/tier_total*100:.2f}%)" if tier_total else f"  {tier}: n=0")

print(f"\n--- date range of large winners ---")
print(winners["breakout_date"].describe())
print(f"\nby year:")
print(winners["breakout_date"].dt.year.value_counts().sort_index().to_string())

winner_keys = list(zip(winners["symbol"], winners["start"], winners["end"]))
ev["is_large_winner"] = ev.apply(lambda r: (r["symbol"], r["start"], r["end"]) in winner_keys, axis=1)
ex_winners = ev[~ev["is_large_winner"]]

RISK_FRAC = 0.01
print(f"\n--- EV WITH vs WITHOUT the {len(winners)} large winners ---")
print(f"  WITH  (n={len(ev)}):    mean R={ev['R_final'].mean():.4f} -> {ev['R_final'].mean()*RISK_FRAC*100:+.3f}%/trade, "
      f"win rate={(ev['R_final']>0).mean()*100:.1f}%")
print(f"  WITHOUT (n={len(ex_winners)}): mean R={ex_winners['R_final'].mean():.4f} -> "
      f"{ex_winners['R_final'].mean()*RISK_FRAC*100:+.3f}%/trade, win rate={(ex_winners['R_final']>0).mean()*100:.1f}%")

# ═══════════════════════════════════════════════════════════════════════
# 3. LOSING-STREAK / EQUITY-CURVE DIAGNOSTIC
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\n3. LOSING-STREAK / EQUITY-CURVE DIAGNOSTIC\n{'='*70}")
print("NOTE: chronological single-sequence ordering by breakout date across the WHOLE")
print("universe -- does not model concurrency (multiple symbols breaking out on/near")
print("the same date would be simultaneous positions in reality, not sequential trades).")
print("Simplification, not a portfolio simulation -- flagged, not silently assumed away.\n")

chrono = ev.sort_values("breakout_date").reset_index(drop=True)
chrono["is_loss"] = chrono["R_final"] < 0

# streak lengths
streak_lengths = []
current = 0
for is_loss in chrono["is_loss"]:
    if is_loss:
        current += 1
    else:
        if current > 0:
            streak_lengths.append(current)
        current = 0
if current > 0:
    streak_lengths.append(current)

streak_series = pd.Series(streak_lengths)
print(f"Total losing streaks (runs of consecutive R<0 trades): {len(streak_series)}")
print(f"Longest losing streak: {streak_series.max()} consecutive losses")
print(f"\nStreak length distribution:")
print(streak_series.value_counts().sort_index().to_string())

for thresh in [5, 8, 10, 15]:
    n = (streak_series >= thresh).sum()
    print(f"  streaks of {thresh}+ consecutive losses: {n}")

chrono["cum_R"] = chrono["R_final"].cumsum()
chrono["running_max"] = chrono["cum_R"].cummax()
chrono["drawdown"] = chrono["cum_R"] - chrono["running_max"]
max_dd = chrono["drawdown"].min()
max_dd_row = chrono.loc[chrono["drawdown"].idxmin()]
print(f"\nMax drawdown (peak-to-trough cumulative R): {max_dd:.2f}R, "
      f"reached at {max_dd_row['symbol']} {max_dd_row['start']}-{max_dd_row['end']} "
      f"({max_dd_row['breakout_date'].date()})")
print(f"Final cumulative R (end of full history): {chrono['cum_R'].iloc[-1]:.2f}R")

chrono[["symbol", "start", "end", "breakout_date", "R_final", "cum_R", "drawdown"]].to_csv(
    "C:/Users/Lenovo/psx_pipeline/triangle_equity_curve.csv", index=False)
print(f"\nSaved chronological equity curve to triangle_equity_curve.csv ({len(chrono)} rows)")

by_symbol.to_csv("C:/Users/Lenovo/psx_pipeline/triangle_symbol_concentration.csv", index=False)
winners.to_csv("C:/Users/Lenovo/psx_pipeline/triangle_large_winners.csv", index=False)
print(f"Saved symbol concentration to triangle_symbol_concentration.csv, "
      f"large winners to triangle_large_winners.csv")
