import sqlite3, sys
sys.path.insert(0, r'C:\Users\Lenovo\psx_pipeline')
from config import DB_PATH
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM setup_log WHERE symbol='MEBL'")
print('MEBL total rows:', cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM setup_log WHERE symbol='MEBL' AND outcome_label IS NOT NULL")
print('MEBL with outcome:', cur.fetchone()[0])
cur.execute("SELECT DISTINCT outcome_label FROM setup_log WHERE symbol='MEBL' ORDER BY outcome_label")
print('outcome_labels:', cur.fetchall())
conn.close()
