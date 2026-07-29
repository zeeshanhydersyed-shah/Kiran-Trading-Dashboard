"""
test_research_filters.py
--------------------------
Synthetic tests with hand-verified known answers for research_filters.py.
"""

import pandas as pd
from research_filters import drop_placeholder_zero_bars, exclude_known_artifact_symbols, KNOWN_ARTIFACT_SYMBOLS

results = []

# ------------------------------------------------------------------
# Test 1: exact placeholder pattern (O=H=L=0.00, volume=0, close nonzero)
# is dropped; a genuine bar with the same close is kept.
# ------------------------------------------------------------------
df1 = pd.DataFrame({
    "date": ["2022-01-10", "2022-01-11", "2022-01-12"],
    "open": [460.00, 0.00, 428.00],
    "high": [460.00, 0.00, 428.00],
    "low": [450.00, 0.00, 428.00],
    "close": [455.00, 421.00, 428.00],
    "volume": [400, 0, 200],
})
out1 = drop_placeholder_zero_bars(df1)
ok1 = list(out1["date"]) == ["2022-01-10", "2022-01-12"] and list(out1.index) == [0, 1]
print(f"[{'PASS' if ok1 else 'FAIL'}] placeholder row dropped, index reset contiguous")
if not ok1:
    print(out1)
results.append(ok1)

# ------------------------------------------------------------------
# Test 2: a genuine zero-volume day is NOT dropped if O/H/L are NOT all
# zero (e.g. a real illiquid bar carrying forward a real nonzero OHLC with
# zero volume -- distinct from the placeholder artifact, must be kept).
# ------------------------------------------------------------------
df2 = pd.DataFrame({
    "date": ["2022-01-10"],
    "open": [460.00],
    "high": [460.00],
    "low": [460.00],
    "close": [460.00],
    "volume": [0],
})
out2 = drop_placeholder_zero_bars(df2)
ok2 = len(out2) == 1
print(f"[{'PASS' if ok2 else 'FAIL'}] zero-volume bar with real nonzero OHLC is NOT dropped")
results.append(ok2)

# ------------------------------------------------------------------
# Test 3: a bar with volume > 0 but O/H/L all zero (shouldn't happen in
# practice, but the filter's condition requires volume==0 too -- must NOT
# be dropped by this specific guard since it doesn't match the confirmed
# artifact's exact fingerprint).
# ------------------------------------------------------------------
df3 = pd.DataFrame({
    "date": ["2022-01-10"],
    "open": [0.00],
    "high": [0.00],
    "low": [0.00],
    "close": [421.00],
    "volume": [100],
})
out3 = drop_placeholder_zero_bars(df3)
ok3 = len(out3) == 1
print(f"[{'PASS' if ok3 else 'FAIL'}] O=H=L=0 with nonzero volume does not match the artifact fingerprint, kept")
results.append(ok3)

# ------------------------------------------------------------------
# Test 4: empty DataFrame in, empty DataFrame out (no crash)
# ------------------------------------------------------------------
df4 = pd.DataFrame({"date": [], "open": [], "high": [], "low": [], "close": [], "volume": []})
out4 = drop_placeholder_zero_bars(df4)
ok4 = len(out4) == 0
print(f"[{'PASS' if ok4 else 'FAIL'}] empty input -> empty output, no crash")
results.append(ok4)

# ------------------------------------------------------------------
# Test 5: exclude_known_artifact_symbols drops exactly the 3 known
# near-zero-adjustment-factor symbols, leaves everything else untouched
# and in order.
# ------------------------------------------------------------------
universe = ["OGDC", "SGPL", "LUCK", "DWAE", "KEL", "FRCL", "ISIL"]
out5 = exclude_known_artifact_symbols(universe)
ok5 = out5 == ["OGDC", "LUCK", "KEL", "ISIL"]
print(f"[{'PASS' if ok5 else 'FAIL'}] exclude_known_artifact_symbols drops SGPL/DWAE/FRCL only, order preserved")
if not ok5:
    print(f"    got: {out5}")
results.append(ok5)

# ------------------------------------------------------------------
# Test 6: a universe with none of the artifact symbols is returned
# unchanged (no accidental over-filtering).
# ------------------------------------------------------------------
clean_universe = ["OGDC", "LUCK", "KEL", "ISIL", "TOWL"]
out6 = exclude_known_artifact_symbols(clean_universe)
ok6 = out6 == clean_universe
print(f"[{'PASS' if ok6 else 'FAIL'}] universe with no artifact symbols passes through unchanged")
results.append(ok6)

# ------------------------------------------------------------------
# Test 7: KNOWN_ARTIFACT_SYMBOLS is exactly the 3 confirmed symbols --
# a regression guard so a future edit can't silently add/drop a symbol
# from this list without a test noticing.
# ------------------------------------------------------------------
ok7 = KNOWN_ARTIFACT_SYMBOLS == frozenset({"SGPL", "DWAE", "FRCL"})
print(f"[{'PASS' if ok7 else 'FAIL'}] KNOWN_ARTIFACT_SYMBOLS is exactly {{SGPL, DWAE, FRCL}}")
results.append(ok7)

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
