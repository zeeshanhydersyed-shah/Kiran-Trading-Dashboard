"""
Filter corporate_action_suspects.csv → corporate_action_suspects_clean.csv
Removes excluded sectors. Run: python filter_corporate_actions.py
"""

import csv, os
from collections import Counter

BASE = os.path.dirname(__file__)
SRC  = os.path.join(BASE, "corporate_action_suspects.csv")
DST  = os.path.join(BASE, "corporate_action_suspects_clean.csv")

EXCLUDE = {
    "FUTURE CONTRACTS",
    "STOCK INDEX FUTURE CONTRACTS",
    "Unknown Sector",
    "TEXTILE SPINNING",
    "TEXTILE COMPOSITE",
    "MODARABAS",
    "SUGAR & ALLIED INDUSTRIES",
    "INV. BANKS / SECURITIES COS.",
    "INV. BANKS / INV. COS. / SECURITIES COS.",   # alternate name in DB
}

with open(SRC, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

before = len(rows)
clean  = [r for r in rows if r["sector"].strip() not in EXCLUDE]
after  = len(clean)

fieldnames = list(rows[0].keys())
with open(DST, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(clean)

print(f"Rows before: {before:,}")
print(f"Rows after:  {after:,}")
print(f"Removed:     {before - after:,}")

print("\nBreakdown by magnitude_category (clean file):")
for cat, cnt in sorted(Counter(r["magnitude_category"] for r in clean).items()):
    print(f"  {cat:<15} {cnt:>4}")

print(f"\nSaved: {DST}")
