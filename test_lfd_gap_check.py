"""
test_lfd_gap_check.py
------------------------
Synthetic, hand-verified tests for lfd_gap_check.py, before any real-data
run.
"""

from lfd_gap_check import check_lfd_gap

results = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    results.append(ok)


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


# ─────────────────────────────────────────────────────────────────────
# Test 1: up-direction, open gaps THROUGH the LFD level.
# entry=105, lfd_level=100 (R_denom=5). open=97 (gapped below 100).
#   realistic_exit=97, realistic_R=(97-105)/5=-1.6, worse_by=-0.6
# ─────────────────────────────────────────────────────────────────────
r = check_lfd_gap("up", open_price=97.0, lfd_level=100.0, entry_price=105.0, r_lfd_denom=5.0)
check("Test 1a: gap detected", r.gapped)
check("Test 1b: realistic_exit_price=97.0 (the open, not the LFD level)", approx(r.realistic_exit_price, 97.0))
check("Test 1c: realistic_realized_R=-1.6", approx(r.realistic_realized_R, -1.6), f"got {r.realistic_realized_R}")
check("Test 1d: worse_by_R=-0.6", approx(r.worse_by_R, -0.6), f"got {r.worse_by_R}")

# ─────────────────────────────────────────────────────────────────────
# Test 2: up-direction, open does NOT gap through (open above LFD level,
# only the intrabar low touched it) -- realistic = assumed -1.0R exactly.
# ─────────────────────────────────────────────────────────────────────
r = check_lfd_gap("up", open_price=102.0, lfd_level=100.0, entry_price=105.0, r_lfd_denom=5.0)
check("Test 2a: no gap detected", not r.gapped)
check("Test 2b: realistic_exit_price=100.0 (the LFD level, unchanged)", approx(r.realistic_exit_price, 100.0))
check("Test 2c: realistic_realized_R=-1.0 (unchanged)", approx(r.realistic_realized_R, -1.0))
check("Test 2d: worse_by_R=0.0", approx(r.worse_by_R, 0.0))

# ─────────────────────────────────────────────────────────────────────
# Test 3: boundary case -- open EXACTLY at the LFD level -- not a gap.
# ─────────────────────────────────────────────────────────────────────
r = check_lfd_gap("up", open_price=100.0, lfd_level=100.0, entry_price=105.0, r_lfd_denom=5.0)
check("Test 3: open exactly at LFD level is NOT a gap", not r.gapped and approx(r.worse_by_R, 0.0))

# ─────────────────────────────────────────────────────────────────────
# Test 4: down-direction mirror, gapped.
# entry=95, lfd_level=100 (R_denom=5, since lfd_level-entry=5 for down).
# open=104 (gapped above 100).
#   realistic_exit=104, realistic_R=(95-104)/5=-1.8, worse_by=-0.8
# ─────────────────────────────────────────────────────────────────────
r = check_lfd_gap("down", open_price=104.0, lfd_level=100.0, entry_price=95.0, r_lfd_denom=5.0)
check("Test 4a: gap detected (down)", r.gapped)
check("Test 4b: realistic_realized_R=-1.8", approx(r.realistic_realized_R, -1.8), f"got {r.realistic_realized_R}")
check("Test 4c: worse_by_R=-0.8", approx(r.worse_by_R, -0.8))

# ─────────────────────────────────────────────────────────────────────
# Test 5: down-direction, no gap.
# ─────────────────────────────────────────────────────────────────────
r = check_lfd_gap("down", open_price=98.0, lfd_level=100.0, entry_price=95.0, r_lfd_denom=5.0)
check("Test 5: down, no gap, realized_R=-1.0", not r.gapped and approx(r.realistic_realized_R, -1.0))

n_pass = sum(results)
n_total = len(results)
print(f"\n{'='*60}\n{n_pass}/{n_total} PASSED\n{'='*60}")
if n_pass != n_total:
    raise SystemExit(1)
