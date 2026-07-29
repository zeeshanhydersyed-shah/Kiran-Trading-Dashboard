"""
test_triangle.py
-----------------
Synthetic tests with hand-verified known answers for triangle assembly.
"""

from datetime import date
from boundaries import Boundary
from triangle import compute_apex, classify_triangle, assemble_triangle, is_forced_line

results = []


def mk(slope, intercept, touches):
    return Boundary(slope=slope, intercept=intercept, touch_indices=touches, all_candidate_indices=touches)


u1 = mk(-0.5, 100, [0, 10, 20])
l1 = mk(0.5, 50, [0, 10, 20])
apex1 = compute_apex(u1, l1)
ok1 = apex1 is not None and abs(apex1[0] - 50) < 0.01 and abs(apex1[1] - 75) < 0.01
print(f"[{'PASS' if ok1 else 'FAIL'}] apex computed correctly for converging lines")
results.append(ok1)

kind1 = classify_triangle(u1, l1, window_start_index=0, window_end_index=20)
ok1b = kind1 == "symmetrical"
print(f"[{'PASS' if ok1b else 'FAIL'}] symmetrical triangle classified correctly")
results.append(ok1b)

tri1 = assemble_triangle(u1, l1, window_start_index=0, window_end_index=20,
                          start_date=date(2020, 1, 1), end_date=date(2020, 2, 1))
ok1c = tri1 is not None and tri1.kind == "symmetrical"
print(f"[{'PASS' if ok1c else 'FAIL'}] symmetrical triangle assembled end-to-end")
results.append(ok1c)

u2 = mk(0.0001, 100, [0, 10, 20])
l2 = mk(0.5, 50, [0, 10, 20])
kind2 = classify_triangle(u2, l2, window_start_index=0, window_end_index=20)
ok2 = kind2 == "ascending"
print(f"[{'PASS' if ok2 else 'FAIL'}] ascending triangle classified correctly")
results.append(ok2)

u3 = mk(-0.5, 100, [0, 10, 20])
l3 = mk(0.0001, 50, [0, 10, 20])
kind3 = classify_triangle(u3, l3, window_start_index=0, window_end_index=20)
ok3 = kind3 == "descending"
print(f"[{'PASS' if ok3 else 'FAIL'}] descending triangle classified correctly")
results.append(ok3)

u4 = mk(0.3, 100, [0, 10, 20])
l4 = mk(0.5, 50, [0, 10, 20])
kind4 = classify_triangle(u4, l4, window_start_index=0, window_end_index=20)
ok4 = kind4 is None
print(f"[{'PASS' if ok4 else 'FAIL'}] both-rising pair correctly rejected as not a triangle")
results.append(ok4)

u5 = mk(-0.5, 40, [0, 10, 20])
l5 = mk(0.5, 10, [0, 10, 20])
tri5 = assemble_triangle(u5, l5, window_start_index=0, window_end_index=35,
                          start_date=date(2020, 1, 1), end_date=date(2020, 2, 1))
ok5 = tri5 is None
print(f"[{'PASS' if ok5 else 'FAIL'}] apex-already-behind-window correctly rejected")
results.append(ok5)

u6 = mk(-0.2, 100, [0, 10, 20])
l6 = mk(0.2, 50, [0, 10, 20])
kind6_check = classify_triangle(u6, l6, window_start_index=0, window_end_index=20)
assert kind6_check == "symmetrical", f"test 6 setup invalid -- expected symmetrical classification, got {kind6_check}"
tri6 = assemble_triangle(u6, l6, window_start_index=0, window_end_index=20,
                          start_date=date(2020, 1, 1), end_date=date(2020, 2, 1))
ok6 = tri6 is None
print(f"[{'PASS' if ok6 else 'FAIL'}] apex-too-far-ahead correctly rejected (genuinely non-flat inputs)")
results.append(ok6)

u7 = mk(-0.5, 100, [0, 10, 20])
l7 = mk(0.5, 50, [0])
tri7 = assemble_triangle(u7, l7, window_start_index=0, window_end_index=20,
                          start_date=date(2020, 1, 1), end_date=date(2020, 2, 1),
                          min_touches=2)
ok7 = tri7 is None
print(f"[{'PASS' if ok7 else 'FAIL'}] insufficient touch count correctly rejected")
results.append(ok7)

u8 = mk(-0.5, 100, [0, 10, 20])
l8 = mk(-0.5, 50, [0, 10, 20])
apex8 = compute_apex(u8, l8)
ok8 = apex8 is None
print(f"[{'PASS' if ok8 else 'FAIL'}] parallel lines correctly return no apex")
results.append(ok8)

tri9a = assemble_triangle(u1, l1, window_start_index=0, window_end_index=20,
                           start_date=date(2020, 1, 1), end_date=date(2020, 1, 21))
tri9b = assemble_triangle(u1, l1, window_start_index=0, window_end_index=20,
                           start_date=date(2020, 1, 1), end_date=date(2021, 1, 1))
ok9 = (tri9a is not None and tri9b is not None
       and tri9a.duration_days == 20 and tri9b.duration_days == 366)
print(f"[{'PASS' if ok9 else 'FAIL'}] duration reflects calendar days, not bar count")
results.append(ok9)

u10 = mk(-0.05, 100, [75, 78, 80])
l10 = mk(0.3, 10, [75, 78, 80])
kind10 = classify_triangle(u10, l10, window_start_index=0, window_end_index=80)
ok10 = kind10 == "symmetrical"
print(f"[{'PASS' if ok10 else 'FAIL'}] touch-clustering regression: window-based flatness catches real drift touch-span would miss")
results.append(ok10)

cramped = mk(-0.1, 100, [70, 74, 78])
ok11 = is_forced_line(cramped, window_start_index=0, window_end_index=100)
print(f"[{'PASS' if ok11 else 'FAIL'}] cramped touches (small span) correctly flagged as forced")
results.append(ok11)

u11 = cramped
l11 = mk(0.1, 10, [10, 40, 78])
tri11 = assemble_triangle(u11, l11, window_start_index=0, window_end_index=100,
                           start_date=date(2020, 1, 1), end_date=date(2020, 4, 10))
ok11b = tri11 is None
print(f"[{'PASS' if ok11b else 'FAIL'}] assemble_triangle rejects pair when one boundary is a forced line")
results.append(ok11b)

near_dupe = mk(-0.1, 100, [0, 50, 51])
ok12 = is_forced_line(near_dupe, window_start_index=0, window_end_index=100)
print(f"[{'PASS' if ok12 else 'FAIL'}] near-duplicate adjacent touches correctly flagged as forced")
results.append(ok12)

well_spaced = mk(-0.1, 100, [0, 40, 100])
ok13 = not is_forced_line(well_spaced, window_start_index=0, window_end_index=100)
print(f"[{'PASS' if ok13 else 'FAIL'}] well-spaced touches correctly NOT flagged as forced")
results.append(ok13)

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
if all(results):
    print("All synthetic triangle-assembly tests pass. Ready for visual overlay against real PSX candidates.")
else:
    print("DO NOT PROCEED until all synthetic tests pass.")
