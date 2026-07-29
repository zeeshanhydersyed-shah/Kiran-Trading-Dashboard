import sqlite3
from config import DB_PATH

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("=== QUERY 1 - Percentile Distribution ===")
cur.execute("""
SELECT
  ROUND(MIN(fwd_return_10d), 2) AS min,
  ROUND(AVG(CASE WHEN pct <= 0.05 THEN fwd_return_10d END), 2) AS p5,
  ROUND(AVG(CASE WHEN pct <= 0.10 THEN fwd_return_10d END), 2) AS p10,
  ROUND(AVG(CASE WHEN pct <= 0.25 THEN fwd_return_10d END), 2) AS p25,
  ROUND(AVG(CASE WHEN pct <= 0.50 THEN fwd_return_10d END), 2) AS p50,
  ROUND(AVG(CASE WHEN pct <= 0.75 THEN fwd_return_10d END), 2) AS p75,
  ROUND(AVG(CASE WHEN pct <= 0.90 THEN fwd_return_10d END), 2) AS p90,
  ROUND(AVG(CASE WHEN pct <= 0.95 THEN fwd_return_10d END), 2) AS p95,
  ROUND(MAX(fwd_return_10d), 2) AS max
FROM (
  SELECT fwd_return_10d,
    PERCENT_RANK() OVER (ORDER BY fwd_return_10d) AS pct
  FROM setup_log
  WHERE fwd_return_10d IS NOT NULL
)
""")
row = cur.fetchone()
cols = ['min','p5','p10','p25','p50','p75','p90','p95','max']
for c, v in zip(cols, row):
    print("  {:>4}: {}".format(c, v))

print()
print("=== QUERY 2 - Bucket Distribution ===")
cur.execute("""
SELECT
  CASE
    WHEN fwd_return_10d < -15 THEN 'A: < -15pct'
    WHEN fwd_return_10d < -10 THEN 'B: -15 to -10pct'
    WHEN fwd_return_10d < -7  THEN 'C: -10 to -7pct'
    WHEN fwd_return_10d < -5  THEN 'D: -7 to -5pct'
    WHEN fwd_return_10d < -3  THEN 'E: -5 to -3pct'
    WHEN fwd_return_10d < 0   THEN 'F: -3 to 0pct'
    WHEN fwd_return_10d < 3   THEN 'G: 0 to 3pct'
    WHEN fwd_return_10d < 6   THEN 'H: 3 to 6pct'
    WHEN fwd_return_10d < 10  THEN 'I: 6 to 10pct'
    WHEN fwd_return_10d < 15  THEN 'J: 10 to 15pct'
    ELSE                           'K: > 15pct'
  END AS bucket,
  COUNT(*) AS cnt,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct_of_total
FROM setup_log
WHERE fwd_return_10d IS NOT NULL
GROUP BY bucket
ORDER BY bucket
""")
print("  {:<22} {:>7} {:>6}".format("bucket", "cnt", "pct"))
for r in cur.fetchall():
    print("  {:<22} {:>7} {:>5}%".format(r[0], r[1], r[2]))

print()
print("=== QUERY 3 - Bucket by setup_type ===")
cur.execute("""
SELECT
  setup_type,
  CASE
    WHEN fwd_return_10d < -15 THEN 'A: < -15pct'
    WHEN fwd_return_10d < -10 THEN 'B: -15 to -10pct'
    WHEN fwd_return_10d < -7  THEN 'C: -10 to -7pct'
    WHEN fwd_return_10d < -5  THEN 'D: -7 to -5pct'
    WHEN fwd_return_10d < -3  THEN 'E: -5 to -3pct'
    WHEN fwd_return_10d < 0   THEN 'F: -3 to 0pct'
    WHEN fwd_return_10d < 3   THEN 'G: 0 to 3pct'
    WHEN fwd_return_10d < 6   THEN 'H: 3 to 6pct'
    WHEN fwd_return_10d < 10  THEN 'I: 6 to 10pct'
    WHEN fwd_return_10d < 15  THEN 'J: 10 to 15pct'
    ELSE                           'K: > 15pct'
  END AS bucket,
  COUNT(*) AS cnt
FROM setup_log
WHERE fwd_return_10d IS NOT NULL
GROUP BY setup_type, bucket
ORDER BY setup_type, bucket
""")
print("  {:<22} {:<22} {:>7}".format("setup_type", "bucket", "cnt"))
for r in cur.fetchall():
    print("  {:<22} {:<22} {:>7}".format(r[0], r[1], r[2]))

print()
print("=== QUERY 4 - Regime-Conditional Averages ===")
cur.execute("""
SELECT
  setup_type, regime, COUNT(*) AS cnt,
  ROUND(AVG(fwd_return_10d), 2) AS avg_10d,
  ROUND(AVG(fwd_return_5d), 2)  AS avg_5d,
  ROUND(AVG(fwd_return_20d), 2) AS avg_20d
FROM setup_log
WHERE fwd_return_10d IS NOT NULL
GROUP BY setup_type, regime
ORDER BY setup_type, avg_10d DESC
""")
print("  {:<22} {:<12} {:>7} {:>8} {:>8} {:>8}".format(
    "setup_type", "regime", "cnt", "avg_10d", "avg_5d", "avg_20d"))
for r in cur.fetchall():
    print("  {:<22} {:<12} {:>7} {:>8} {:>8} {:>8}".format(
        str(r[0]), str(r[1]), r[2], str(r[3]), str(r[4]), str(r[5])))

print()
print("=== QUERY 5 - Win/Loss Rate at Multiple Thresholds ===")
cur.execute("""
SELECT
  threshold,
  COUNT(*) AS total,
  SUM(CASE WHEN fwd_return_10d > 6   THEN 1 ELSE 0 END) AS winners,
  SUM(CASE WHEN fwd_return_10d < threshold THEN 1 ELSE 0 END) AS losers,
  ROUND(SUM(CASE WHEN fwd_return_10d > 6 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS win_pct,
  ROUND(SUM(CASE WHEN fwd_return_10d < threshold THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS loss_pct
FROM setup_log
CROSS JOIN (
  SELECT -3 AS threshold UNION ALL
  SELECT -4 UNION ALL
  SELECT -5 UNION ALL
  SELECT -7 UNION ALL
  SELECT -10
) thresholds
WHERE fwd_return_10d IS NOT NULL
GROUP BY threshold
ORDER BY threshold DESC
""")
print("  {:>10} {:>8} {:>8} {:>8} {:>8} {:>9}".format(
    "threshold", "total", "winners", "losers", "win_pct", "loss_pct"))
for r in cur.fetchall():
    print("  {:>10} {:>8} {:>8} {:>8} {:>8} {:>9}".format(
        r[0], r[1], r[2], r[3], r[4], r[5]))

conn.close()
