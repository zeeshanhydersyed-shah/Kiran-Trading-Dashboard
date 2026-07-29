"""
test_pivots.py
--------------
Synthetic tests with hand-verified known answers. No real market data here
on purpose -- if this file doesn't pass, nothing downstream is trustworthy.
"""

from pivots import find_pivots, collapse_frozen_closes, find_pivots_collapsed


def check(name, highs, lows, left, right, expected):
    pivots = find_pivots(highs, lows, left=left, right=right)
    got = {(p.index, p.kind) for p in pivots}
    status = "PASS" if got == expected else "FAIL"
    print(f"[{status}] {name}")
    if got != expected:
        print(f"    expected: {sorted(expected)}")
        print(f"    got:      {sorted(got)}")
    return status == "PASS"


results = []

highs1 = [10, 12, 15, 11, 9, 13, 17]
lows1 = [8, 10, 13, 9, 7, 11, 15]
results.append(check("simple zigzag (left=1,right=1)", highs1, lows1, 1, 1, {(2, "high"), (4, "low")}))

highs2 = [10, 15, 15, 15, 11, 10]
lows2 = [9, 12, 12, 12, 10, 9]
results.append(check("flat plateau tie", highs2, lows2, 1, 1, {(1, "high")}))

highs3 = [10, 11, 12, 13, 25, 13, 12, 11, 10]
lows3 = [9, 10, 11, 12, 20, 12, 11, 10, 9]
results.append(check("single-bar spike", highs3, lows3, 3, 3, {(4, "high")}))

highs4 = [10, 11, 12, 13, 20, 13, 12, 11, 10]
lows4 = [9, 10, 11, 12, 15, 12, 11, 10, 9]
pivots4 = find_pivots(highs4, lows4, left=2, right=2)
hi_pivot = [p for p in pivots4 if p.kind == "high"]
ok = len(hi_pivot) == 1 and hi_pivot[0].index == 4 and hi_pivot[0].confirmed_at == 6
print(f"[{'PASS' if ok else 'FAIL'}] confirmed_at = index + right, no lookahead")
results.append(ok)

short_highs = [10, 11, 12]
short_lows = [9, 10, 11]
ok5 = len(find_pivots(short_highs, short_lows, left=3, right=3)) == 0
print(f"[{'PASS' if ok5 else 'FAIL'}] empty result on short array")
results.append(ok5)

mono_highs = [10, 11, 12, 13, 14, 15, 16]
mono_lows = [9, 10, 11, 12, 13, 14, 15]
ok6 = len(find_pivots(mono_highs, mono_lows, left=2, right=2)) == 0
print(f"[{'PASS' if ok6 else 'FAIL'}] monotonic series produces zero pivots")
results.append(ok6)


# --- collapse_frozen_closes ---

closes7 = [1, 2, 3, 4, 5]
highs7 = [1, 2, 3, 4, 5]
lows7 = [1, 2, 3, 4, 5]
bars7 = collapse_frozen_closes(closes7, highs7, lows7)
ok7 = (len(bars7) == 5 and all(b.run_length == 1 for b in bars7)
       and [b.index for b in bars7] == [0, 1, 2, 3, 4]
       and [b.end_index for b in bars7] == [0, 1, 2, 3, 4])
print(f"[{'PASS' if ok7 else 'FAIL'}] collapse: no frozen runs -> passthrough unchanged")
results.append(ok7)

closes8 = [5, 6, 8, 8, 8, 8, 8, 8, 6, 5]
highs8 = [5, 6, 9, 8, 9, 8, 9, 8, 6, 5]
lows8 = [4, 5, 7, 7, 7, 7, 7, 7, 5, 4]
bars8 = collapse_frozen_closes(closes8, highs8, lows8)
frozen_bar = bars8[2]  # the collapsed run starting at original index 2
ok8 = (len(bars8) == 5 and frozen_bar.index == 2 and frozen_bar.end_index == 7
       and frozen_bar.run_length == 6 and frozen_bar.high == 9 and frozen_bar.low == 7)
print(f"[{'PASS' if ok8 else 'FAIL'}] collapse: one frozen run -> single synthetic bar, high=max/low=min over run")
results.append(ok8)

# --- find_pivots_collapsed: reproduces & fixes the TOWL/ISIL failure mode ---
# A frozen-close run (indices 2-7) with noisy high wobbles inside it.
# Raw find_pivots() on the uncollapsed high series finds 3 separate
# "pivot highs" scattered through the flat span (idx 2, 4, 6) -- exactly
# the spurious multi-pivot-per-plateau bug seen on real TOWL/ISIL data.
# find_pivots_collapsed() must fold that whole run into one bar and
# produce exactly ONE pivot high, positioned at the run's first index.

raw_pivots9 = find_pivots(highs8, lows8, left=1, right=1)
raw_highs9 = [p for p in raw_pivots9 if p.kind == "high"]
ok9_raw_reproduces_bug = {p.index for p in raw_highs9} == {2, 4, 6}
print(f"[{'PASS' if ok9_raw_reproduces_bug else 'FAIL'}] sanity: uncollapsed find_pivots reproduces the 3-spurious-pivot bug")
results.append(ok9_raw_reproduces_bug)

collapsed_pivots9 = find_pivots_collapsed(closes8, highs8, lows8, left=1, right=1)
collapsed_highs9 = [p for p in collapsed_pivots9 if p.kind == "high"]
ok9 = (len(collapsed_highs9) == 1 and collapsed_highs9[0].index == 2
       and collapsed_highs9[0].price == 9 and collapsed_highs9[0].confirmed_at == 8)
print(f"[{'PASS' if ok9 else 'FAIL'}] find_pivots_collapsed: frozen-run wobble collapses to exactly 1 pivot")
results.append(ok9)

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
