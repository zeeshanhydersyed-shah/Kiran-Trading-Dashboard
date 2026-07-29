"""
test_fixed_pct_stop_target.py
---------------------------------
Synthetic, hand-verified tests for fixed_pct_stop_target.py, before any
real-data run. Same discipline as every other module in this study.
"""

from fixed_pct_stop_target import walk_forward_fixed_pct

results = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    results.append(ok)


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


# entry=100, up: stop=98.0 (2% below), target=104.0 (4% above)

# ─────────────────────────────────────────────────────────────────────
# (a) stop hit before target
# ─────────────────────────────────────────────────────────────────────
closes = [100.0] * 21
highs = [100.0] * 20 + [100.0]
lows = [100.0] * 20 + [100.0]
closes[20] = 100.0
# bar 21: low touches stop (98.0), high doesn't reach target (104.0)
closes += [97.5]
highs += [99.0]
lows += [97.8]
r = walk_forward_fixed_pct(closes, highs, lows, breakout_idx=20, direction="up")
check("Test a: stop hit at bar 21, realized_R=-1.0",
      r.exit_bar == 21 and r.exit_type == "stop" and approx(r.realized_R, -1.0),
      f"got exit_bar={r.exit_bar}, exit_type={r.exit_type}, R={r.realized_R}")

# ─────────────────────────────────────────────────────────────────────
# (b) target hit before stop
# ─────────────────────────────────────────────────────────────────────
closes = [100.0] * 21
highs = [100.0] * 21
lows = [100.0] * 21
closes += [104.5]
highs += [105.0]
lows += [101.0]
r = walk_forward_fixed_pct(closes, highs, lows, breakout_idx=20, direction="up")
check("Test b: target hit at bar 21, realized_R=+2.0",
      r.exit_bar == 21 and r.exit_type == "target" and approx(r.realized_R, 2.0),
      f"got exit_bar={r.exit_bar}, exit_type={r.exit_type}, R={r.realized_R}")

# ─────────────────────────────────────────────────────────────────────
# (c) neither hit within horizon -- mark-to-market at horizon close.
# entry=100, horizon ends at bar 20+90=110 (array must reach index 110).
# price drifts to 101.0 by horizon close, never touching stop(98) or target(104).
# realized_R = (101-100)/100 / 0.02 = 0.01/0.02 = 0.5
# ─────────────────────────────────────────────────────────────────────
closes = [100.0] * 21 + [101.0] * 90
highs = [100.0] * 21 + [102.0] * 90
lows = [100.0] * 21 + [99.0] * 90
r = walk_forward_fixed_pct(closes, highs, lows, breakout_idx=20, direction="up")
check("Test c: neither hit, horizon-close at bar 110, realized_R=+0.5",
      r.exit_bar == 110 and r.exit_type == "horizon" and approx(r.realized_R, 0.5),
      f"got exit_bar={r.exit_bar}, exit_type={r.exit_type}, R={r.realized_R}")

# ─────────────────────────────────────────────────────────────────────
# (d) both hit same bar (gap-through) -- conservative tie-break: stop wins.
# entry=100, bar 21's low=97.0 (below stop 98.0) AND high=105.0 (above target 104.0).
# ─────────────────────────────────────────────────────────────────────
closes = [100.0] * 21
highs = [100.0] * 21
lows = [100.0] * 21
closes += [101.0]
highs += [105.0]
lows += [97.0]
r = walk_forward_fixed_pct(closes, highs, lows, breakout_idx=20, direction="up")
check("Test d: gap-through both same bar, tie-break to STOP, realized_R=-1.0",
      r.exit_bar == 21 and r.exit_type == "stop" and approx(r.realized_R, -1.0),
      f"got exit_bar={r.exit_bar}, exit_type={r.exit_type}, R={r.realized_R}")

# ─────────────────────────────────────────────────────────────────────
# (e) down-direction mirror sanity check: stop hit
# entry=100, down: stop=102.0 (2% above), target=96.0 (4% below)
# bar 21: high touches stop (102.0)
# ─────────────────────────────────────────────────────────────────────
closes = [100.0] * 21
highs = [100.0] * 21
lows = [100.0] * 21
closes += [102.5]
highs += [102.2]
lows += [100.5]
r = walk_forward_fixed_pct(closes, highs, lows, breakout_idx=20, direction="down")
check("Test e: down-direction stop hit at bar 21, stop=102.0, realized_R=-1.0",
      approx(r.stop_price, 102.0) and approx(r.target_price, 96.0)
      and r.exit_bar == 21 and r.exit_type == "stop" and approx(r.realized_R, -1.0),
      f"got stop={r.stop_price}, target={r.target_price}, exit_type={r.exit_type}, R={r.realized_R}")

# ─────────────────────────────────────────────────────────────────────
# (f) entry bar itself carries an extreme low/high -- confirm the walk
# starts at breakout_idx+1, not breakout_idx (poisoned bar 20).
# ─────────────────────────────────────────────────────────────────────
closes = [100.0] * 20 + [100.0]
highs = [100.0] * 20 + [200.0]  # would trigger target if scanned
lows = [100.0] * 20 + [1.0]     # would trigger stop if scanned
closes += [100.5]
highs += [101.0]
lows += [100.0]
r = walk_forward_fixed_pct(closes, highs, lows, breakout_idx=20, direction="up")
check("Test f: breakout bar's own extreme high/low excluded from the scan",
      r.exit_type != "stop" and r.exit_type != "target",
      f"got exit_type={r.exit_type} (should be 'horizon' since bar 20 is excluded and bar 21 is safe)")

# ═══════════════════════════════════════════════════════════════════════
n_pass = sum(results)
n_total = len(results)
print(f"\n{'='*60}\n{n_pass}/{n_total} PASSED\n{'='*60}")
if n_pass != n_total:
    raise SystemExit(1)
