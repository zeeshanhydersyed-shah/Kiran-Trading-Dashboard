import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect("psx_data.db")
cur = conn.cursor()

# Phase 4 used support_distance_pct — check if pivot_distance_pct is the equivalent
# and what the 953 row count corresponds to
cur.execute("""
    SELECT COUNT(*) FROM setup_log
    WHERE setup_type='BREAKOUT' AND pivot_distance_pct BETWEEN 4 AND 8
""")
print("BREAKOUT + pivot_distance_pct [4,8] count:", cur.fetchone()[0])

# Check if setup_log has a close column via join or differently
# Also check what columns setup_log has relating to price
cur.execute("PRAGMA table_info(setup_log)")
all_cols = [r[1] for r in cur.fetchall()]
print("All setup_log cols:", all_cols)

# Sample some BREAKOUT rows
df = pd.read_sql_query("""
    SELECT * FROM setup_log WHERE setup_type='BREAKOUT'
    AND pivot_distance_pct BETWEEN 4 AND 8 LIMIT 3
""", conn)
print(df.to_string())
