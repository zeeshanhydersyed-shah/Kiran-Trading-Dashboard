import sqlite3
from config import DB_PATH

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute("SELECT id, market_date, trigger_type, stance, response FROM agent_memory ORDER BY id DESC LIMIT 5")
rows = cur.fetchall()
for r in rows:
    print(f"[{r['id']}] {r['market_date']} | {r['trigger_type']}")
    print(f"  stance:   {r['stance']}")
    print(f"  response: {r['response'][:120]}")
    print()
con.close()
