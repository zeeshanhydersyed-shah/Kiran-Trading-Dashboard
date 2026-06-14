import sqlite3
from config import DB_PATH

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS agent_memory (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    market_date       TEXT    NOT NULL,
    trigger_type      TEXT    NOT NULL,
    regime            TEXT,
    zeeshan_input     TEXT,
    stance            TEXT,
    response          TEXT    NOT NULL,
    flagged_setups    TEXT,
    context_snapshot  TEXT,
    model             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER
)
""")

con.commit()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_memory'")
print("Table created:", cur.fetchone())
cur.execute("PRAGMA table_info(agent_memory)")
for row in cur.fetchall():
    print(row)
con.close()
