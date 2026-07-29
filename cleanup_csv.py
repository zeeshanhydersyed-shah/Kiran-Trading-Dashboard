import os

BASE = os.path.dirname(__file__)

TO_DELETE = [
    "corporate_action_suspects.csv",  # raw unfiltered (all 2443 symbols, -15% threshold)
]

KEEP = "corporate_action_suspects_clean.csv"  # final — date-aware threshold, 302 clean symbols

print("Deleting intermediate CSVs...\n")
for fname in TO_DELETE:
    path = os.path.join(BASE, fname)
    if os.path.exists(path):
        os.remove(path)
        print(f"  Deleted: {fname}")
    else:
        print(f"  Not found (skipped): {fname}")

print(f"\nKept: {KEEP}")
print("Done.")
