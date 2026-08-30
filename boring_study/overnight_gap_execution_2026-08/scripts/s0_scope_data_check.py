"""s0 -- READ-ONLY data-readiness probe (run against the CLOUD Postgres).

Establishes what a historical extension can and cannot use: per-year open/low/high
coverage in prices_adjusted, KSE-100 index span, market_regime coverage,
corporate-action flags. The verdict from this probe: the cloud has stock prices
only from 2024-08; the deep 2005-2026 history lives in the local psx_data.db
(see s3-s6, which use that).
"""
import pandas as pd
from _paths import cloud_conn

conn = cloud_conn()
cur = conn.cursor()

print("=== prices_adjusted: coverage by year (CLOUD) ===")
cur.execute("""
    SELECT LEFT(date::text,4) AS yr, COUNT(*) AS rows, COUNT(DISTINCT symbol) AS syms,
           ROUND(100.0*SUM(CASE WHEN open IS NULL OR open=0 THEN 1 ELSE 0 END)/COUNT(*),1) AS pct_open_missing,
           ROUND(100.0*SUM(CASE WHEN low  IS NULL OR low=0  THEN 1 ELSE 0 END)/COUNT(*),1) AS pct_low_missing,
           ROUND(100.0*SUM(CASE WHEN high IS NULL OR high=0 THEN 1 ELSE 0 END)/COUNT(*),1) AS pct_high_missing
    FROM prices_adjusted GROUP BY 1 ORDER BY 1
""")
for yr, rows, syms, om, lm, hm in cur.fetchall():
    print(f"  {yr}  rows={rows:>7}  syms={syms:>4}  open_missing={om:>5}%  low_missing={lm:>4}%  high_missing={hm:>4}%")

print("\n=== index_prices KSE-100: coverage by year ===")
cur.execute("""
    SELECT LEFT(date::text,4) AS yr, COUNT(*) AS d,
           ROUND(100.0*SUM(CASE WHEN close IS NULL OR close=0 THEN 1 ELSE 0 END)/COUNT(*),1) AS pct_close_missing
    FROM index_prices WHERE symbol='KSE-100' GROUP BY 1 ORDER BY 1
""")
for yr, d, cm in cur.fetchall():
    print(f"  {yr}  days={d:>4}  close_missing={cm}%")

print("\n=== overall prices_adjusted date range & row count ===")
cur.execute("SELECT MIN(date)::text, MAX(date)::text, COUNT(*) FROM prices_adjusted")
a, b, n = cur.fetchone()
print(f"  {a} -> {b}   {n:,} rows")

print("\n=== market_regime coverage (regime axis) ===")
cur.execute("SELECT MIN(date)::text, MAX(date)::text, COUNT(*) FROM market_regime")
a, b, n = cur.fetchone()
print(f"  {a} -> {b}   {n:,} rows")
cur.execute("SELECT regime, COUNT(*) FROM market_regime GROUP BY 1 ORDER BY 2 DESC")
for regime, n in cur.fetchall():
    print(f"    {regime:<20} {n}")

print("\n=== corporate_action_suspects ===")
cur.execute("SELECT status, COUNT(*), MIN(suspect_date)::text, MAX(suspect_date)::text FROM corporate_action_suspects GROUP BY 1")
for status, n, a, b in cur.fetchall():
    print(f"    {status:<16} {n:>4}   {a} .. {b}")

conn.close()
