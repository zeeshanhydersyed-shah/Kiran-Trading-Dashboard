import sqlite3, csv, os

BASE = os.path.dirname(__file__)
db = sqlite3.connect(os.path.join(BASE, "psx_data.db"))
cur = db.cursor()

tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]

print("=== DB STATE CHECK ===\n")

# prices vs prices_adjusted
for t in ["prices", "prices_adjusted"]:
    if t in tables:
        cnt = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t:25s}  {cnt:>12,} rows  ✓ exists")
    else:
        print(f"{'prices_adjusted':25s}  {'':>12}       ✗ NOT FOUND")

# bonus events auto-adjusted
print("\n--- Bonus events (auto-adjusted) ---")
CSV = os.path.join(BASE, "corporate_action_suspects_clean.csv")
cats = {"DROP_50": 0, "DROP_33": 0, "DROP_25": 0, "DROP_OTHER_PENDING": 0, "DROP_OTHER_CONFIRMED": 0}
with open(CSV, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        cat    = row["magnitude_category"]
        status = row["review_status"].strip().upper()
        if cat == "DROP_50":   cats["DROP_50"] += 1
        elif cat == "DROP_33": cats["DROP_33"] += 1
        elif cat == "DROP_25": cats["DROP_25"] += 1
        elif status == "CONFIRMED": cats["DROP_OTHER_CONFIRMED"] += 1
        else: cats["DROP_OTHER_PENDING"] += 1

print(f"  DROP_50  auto-adjusted : {cats['DROP_50']:>5}")
print(f"  DROP_33  auto-adjusted : {cats['DROP_33']:>5}")
print(f"  DROP_25  auto-adjusted : {cats['DROP_25']:>5}")
print(f"  DROP_OTHER CONFIRMED   : {cats['DROP_OTHER_CONFIRMED']:>5}  (applied if you ran --all)")
print(f"  DROP_OTHER PENDING     : {cats['DROP_OTHER_PENDING']:>5}  (not yet applied)")

db.close()
