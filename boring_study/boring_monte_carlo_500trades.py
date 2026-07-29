"""
boring_monte_carlo_500trades.py -- portfolio-level Monte Carlo projection for
the locked RS_60 / Donchian-60 / liquidity-gated system
(boring_study_trading_rulebook_v1_2026-07-11.md, Addenda A-C).

This is a FORWARD-LOOKING CAPITAL SIMULATION using the validated per-trade
parameters as INPUTS. It is not a new backtest and does not touch
psx_data.db -- everything below this line is either a locked, validated
parameter (win rate, target, stop, median durations) or an EXPLICITLY
FLAGGED MODELING ASSUMPTION this project has not validated. Read the
assumptions section before trusting the output as more than a structural
illustration.

============================= MODELING ASSUMPTIONS =============================
(none of these are backed by this project's research -- flagged exactly as
that discipline requires)

1. TRADE INDEPENDENCE. Outcomes are drawn i.i.d. Bernoulli per trade. Real
   trades are NOT independent -- sector-wide breakouts and market regime
   shifts correlate outcomes. This almost certainly UNDERSTATES true
   drawdown risk, especially during a clustering event where many positions
   could lose together instead of independently.

2. SIGNAL ARRIVAL RATE. How many qualifying (Donchian-60, top-decile RS_60,
   liquid) signals appear per trading day, for the CURRENT live universe,
   has never been measured with this project's rigor. Modeled as a mixture:
   a low steady rate on typical days, plus occasional cluster days (matching
   the sector-clustering scenario raised earlier), calibrated to a plausible
   range -- not fitted to data. This directly determines how often the
   cash constraint actually binds; treat BASE_DAILY_RATE / CLUSTER_PROB /
   CLUSTER_MEAN below as free parameters to sensitivity-test, not facts.

3. DURATION DISTRIBUTION. Modeled as Geometric, mean-matched to the given
   2.5d (win) / 2.0d (loss) figures. Losers' median/tail (2d median, ~30-38d
   max) is grounded in boring_capital_lockup_analysis.py; winners' full
   distribution was never measured (only decile-level means, ~2.4-2.6d) --
   the winner duration shape is an extrapolation from that mean, not a
   validated distribution.

4. MARK-TO-MARKET. Equity updates only when a trade CLOSES (win or loss
   realized) -- no interim mark-to-market while a position is open. Given
   ~2-day median holds this is a minor simplification, not a material one.

======================= POSITION-SIZING, CORRECTED =======================
Position size is the actual risk-based formula, confirmed against the
worked example (Price 100, SL 94, capital 2,000,000): risk = 1% of capital
= 20,000; units = 20,000 / (100-94) = 3,333; position value = 3,333 x 100
= 333,300 = 16.67% of equity = RISK_PCT / STOP_PCT exactly. There is no
separate "10% of equity" cap -- that was a misreading of the earlier "10
slots" comment, corrected here.

This account is cash-only (no margin). 10 positions at 16.67% each would
need 167% of capital, which is impossible without borrowing. So the actual
concurrency constraint is CASH, not a slot count: at most floor(1/0.16667)
= 6 positions can be open at once, regardless of how large equity grows,
since the 16.67% sizing ratio is scale-invariant. MAX_SLOTS=10 is kept as
a nominal admin ceiling in the code below but will not bind -- cash binds
first, at 6. New signals that arrive with no cash available are skipped
(not queued -- a stale entry price can't be retroactively taken once a
slot frees up later), exactly as originally described.
"""

import numpy as np

RNG_SEED = 42
N_ITER = 1000
N_TRADES = 500

INITIAL_CAPITAL = 2_000_000.0
RISK_PCT = 0.01
STOP_PCT = 0.06
TARGET_PCT = 0.10
POSITION_FRACTION = RISK_PCT / STOP_PCT   # 0.16667 of equity, matches the worked example exactly
WIN_PROB = 0.485
MAX_SLOTS = 10               # nominal ceiling only -- cash binds first, at ~6
FRICTION_SCENARIOS = [0.0015, 0.0020, 0.0025]   # 0.15% / 0.20% / 0.25% round-trip

WIN_MEAN_DURATION = 2.5
LOSS_MEAN_DURATION = 2.0
MAX_DURATION_CAP = 40        # soft ceiling, consistent with the observed ~30-38d max

BASE_DAILY_RATE = 0.35       # ASSUMPTION -- typical-day signal count (Poisson mean)
CLUSTER_PROB = 0.04          # ASSUMPTION -- ~1-in-25 trading days is a cluster day
CLUSTER_MEAN = 8             # ASSUMPTION -- simultaneous signals on a cluster day

DD_THRESHOLDS = [0.10, 0.15, 0.20]


def simulate_one_run(rng, friction_pct):
    equity = INITIAL_CAPITAL
    cash = INITIAL_CAPITAL       # uncommitted capital -- the real constraint, cash-only account
    equity_curve = [equity]
    resolved_sequence = []        # bools, in the order trades CLOSE
    open_positions = []           # dicts: exit_day, position_value, net_pct, is_win
    trades_taken = 0
    skipped_no_cash = 0
    max_concurrent = 0
    day = 0

    while trades_taken < N_TRADES or open_positions:
        day += 1

        still_open, closing = [], []
        for pos in open_positions:
            (closing if pos["exit_day"] == day else still_open).append(pos)
        open_positions = still_open
        for pos in closing:
            pnl = pos["position_value"] * pos["net_pct"]
            equity += pnl
            cash += pos["position_value"] + pnl   # committed capital returns, plus realized P&L
            equity_curve.append(equity)
            resolved_sequence.append(pos["is_win"])

        if trades_taken >= N_TRADES:
            continue

        n_new = (rng.poisson(CLUSTER_MEAN) if rng.random() < CLUSTER_PROB
                  else rng.poisson(BASE_DAILY_RATE))
        n_new = min(n_new, N_TRADES - trades_taken, MAX_SLOTS - len(open_positions))

        for _ in range(n_new):
            position_value = equity * POSITION_FRACTION
            if position_value > cash + 1e-6:
                skipped_no_cash += 1
                continue   # cash-only constraint -- signal missed, not queued
            is_win = rng.random() < WIN_PROB
            raw_pct = TARGET_PCT if is_win else -STOP_PCT
            net_pct = raw_pct - friction_pct
            mean_dur = WIN_MEAN_DURATION if is_win else LOSS_MEAN_DURATION
            duration = int(np.clip(rng.geometric(1.0 / mean_dur), 1, MAX_DURATION_CAP))
            open_positions.append({
                "exit_day": day + duration, "position_value": position_value,
                "net_pct": net_pct, "is_win": is_win,
            })
            cash -= position_value
            trades_taken += 1
            max_concurrent = max(max_concurrent, len(open_positions))

    return equity, np.array(equity_curve), resolved_sequence, day, skipped_no_cash, max_concurrent


def max_drawdown(curve):
    peak = np.maximum.accumulate(curve)
    dd = (curve - peak) / peak
    return -dd.min()


def longest_streak(seq, target):
    best = cur = 0
    for v in seq:
        cur = cur + 1 if v == target else 0
        best = max(best, cur)
    return best


def run_scenario(friction_pct, seed=RNG_SEED):
    rng = np.random.default_rng(seed)
    finals, maxdds, win_streaks, loss_streaks = [], [], [], []
    calendar_days, skips, max_concs = [], [], []
    for _ in range(N_ITER):
        final_eq, curve, seq, days, skipped, max_conc = simulate_one_run(rng, friction_pct)
        finals.append(final_eq)
        maxdds.append(max_drawdown(curve))
        win_streaks.append(longest_streak(seq, True))
        loss_streaks.append(longest_streak(seq, False))
        calendar_days.append(days)
        skips.append(skipped)
        max_concs.append(max_conc)
    return {
        "finals": np.array(finals), "maxdds": np.array(maxdds),
        "win_streaks": np.array(win_streaks), "loss_streaks": np.array(loss_streaks),
        "calendar_days": np.array(calendar_days), "skips": np.array(skips),
        "max_concs": np.array(max_concs),
    }


def report(results, friction_pct, label):
    f = results["finals"]
    dd = results["maxdds"]
    print(f"\n{'='*90}\n{label}  (friction={friction_pct*100:.2f}% round-trip)\n{'='*90}")
    print(f"Median ending equity:      PKR {np.median(f):,.0f}  "
          f"({np.median(f)/INITIAL_CAPITAL:.2f}x)")
    print(f"5th pct (worst-case):      PKR {np.percentile(f,5):,.0f}  "
          f"({np.percentile(f,5)/INITIAL_CAPITAL:.2f}x)")
    print(f"95th pct (best-case):      PKR {np.percentile(f,95):,.0f}  "
          f"({np.percentile(f,95)/INITIAL_CAPITAL:.2f}x)")
    print(f"Fraction of runs ending BELOW initial capital: {(f < INITIAL_CAPITAL).mean()*100:.1f}%")
    print(f"\nMax drawdown distribution (peak-to-trough, any point in the 500 trades):")
    print(f"  median max DD: {np.median(dd)*100:.1f}%   90th pct max DD: {np.percentile(dd,90)*100:.1f}%")
    for thr in DD_THRESHOLDS:
        print(f"  P(max drawdown >= {thr*100:.0f}%): {(dd >= thr).mean()*100:.1f}%")
    print(f"\nStreak lengths (consecutive, in trade-close order):")
    print(f"  Win streak  -- median: {np.median(results['win_streaks']):.0f}   "
          f"90th pct: {np.percentile(results['win_streaks'],90):.0f}   "
          f"max observed: {results['win_streaks'].max()}")
    print(f"  Loss streak -- median: {np.median(results['loss_streaks']):.0f}   "
          f"90th pct: {np.percentile(results['loss_streaks'],90):.0f}   "
          f"max observed: {results['loss_streaks'].max()}")
    print(f"\nCapital-constraint diagnostics:")
    print(f"  Max concurrent positions actually reached -- median: {np.median(results['max_concs']):.0f}   "
          f"max observed across all runs: {results['max_concs'].max()}  (nominal ceiling was {MAX_SLOTS})")
    print(f"  Signals skipped for lack of cash -- median per run: {np.median(results['skips']):.0f}")
    print(f"\nCalendar time to complete 500 trades -- median: {np.median(results['calendar_days']):.0f} "
          f"trading days (~{np.median(results['calendar_days'])/21:.1f} months)")


print(f"Fixed inputs: capital=PKR{INITIAL_CAPITAL:,.0f}  risk_pct={RISK_PCT*100:.0f}%  "
      f"stop={STOP_PCT*100:.0f}%  position_fraction={POSITION_FRACTION*100:.2f}% of equity  "
      f"win_prob={WIN_PROB}  target=+{TARGET_PCT*100:.0f}%  iterations={N_ITER}  trades/run={N_TRADES}")
print(f"NOTE: cash-only account -- 1/{POSITION_FRACTION:.4f} = {1/POSITION_FRACTION:.1f} positions "
      f"is the real concurrency ceiling, not the nominal {MAX_SLOTS} slots.")

all_results = {}
for friction in FRICTION_SCENARIOS:
    res = run_scenario(friction)
    all_results[friction] = res
    report(res, friction, "PRIMARY RESULT" if friction == 0.0020 else "SENSITIVITY")

print(f"\n\n{'='*90}\nFRICTION SENSITIVITY SUMMARY\n{'='*90}")
for friction, res in all_results.items():
    print(f"friction={friction*100:.2f}%: median ending equity = PKR {np.median(res['finals']):,.0f} "
          f"({np.median(res['finals'])/INITIAL_CAPITAL:.2f}x)   "
          f"5th pct = PKR {np.percentile(res['finals'],5):,.0f}   "
          f"median max DD = {np.median(res['maxdds'])*100:.1f}%")

print("\nDone.")
