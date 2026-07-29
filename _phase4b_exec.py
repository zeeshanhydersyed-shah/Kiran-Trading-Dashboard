import sqlite3, time

conn = sqlite3.connect("psx_data.db")
conn.execute("PRAGMA journal_mode=WAL")

print("Creating composite index idx_prices_sym_date ON prices(symbol, date)...")
t0 = time.time()
conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_sym_date ON prices (symbol, date)")
conn.commit()
elapsed = time.time() - t0
print(f"Index created in {elapsed:.1f} seconds.\n")

print("=== EXPLAIN QUERY PLAN 1 — single symbol lookup ===")
rows = conn.execute("""
EXPLAIN QUERY PLAN
SELECT symbol, date, close, volume, high, low
FROM prices
WHERE symbol = 'MEBL'
ORDER BY date DESC
LIMIT 60
""").fetchall()
for r in rows:
    print(" ", r)

print()
print("=== EXPLAIN QUERY PLAN 2 — symbol + date filter ===")
rows = conn.execute("""
EXPLAIN QUERY PLAN
SELECT symbol, date, close, volume
FROM prices
WHERE symbol = 'MEBL' AND date >= '2024-01-01'
ORDER BY date
""").fetchall()
for r in rows:
    print(" ", r)

print()
print("=== EXPLAIN QUERY PLAN 3 — full JOIN query (get_sector_price_data) ===")
rows = conn.execute("""
EXPLAIN QUERY PLAN
SELECT s.symbol, s.sector, p.date,
       COALESCE(p.open, p.close) AS open,
       COALESCE(p.high, p.close) AS high,
       COALESCE(p.low,  p.close) AS low,
       p.close,
       COALESCE(p.volume, 0) AS volume
FROM sectors s
JOIN prices p ON p.symbol = s.symbol
ORDER BY s.symbol, p.date
""").fetchall()
for r in rows:
    print(" ", r)

print()
print("=== All indexes on prices table ===")
rows = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='prices'").fetchall()
for r in rows:
    print(" ", r[0])

conn.close()
