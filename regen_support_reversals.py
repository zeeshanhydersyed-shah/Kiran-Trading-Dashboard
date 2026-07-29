"""Regenerate Support Reversal setups from current price data and save to DB."""
import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

from database import get_sector_price_data, save_trade_setup
from processor import generate_support_reversal_setups, compute_sector_rankings, compute_stock_performance
import pandas as pd

print("Loading price data...")
raw = get_sector_price_data()
df = pd.DataFrame(raw)

sector_map = dict(zip(df["symbol"], df["sector"]))
stock_30d = compute_stock_performance(df, window=30)
sector_df = compute_sector_rankings(stock_30d, compute_stock_performance(df, window=10))
sector_rank_map = dict(zip(sector_df["sector"], sector_df["rank"]))

print("Running screener...")
setups = generate_support_reversal_setups(
    df, sector_map, sector_rank_map=sector_rank_map
)

longs  = [s for s in setups if s["direction"] == "LONG"]
shorts = [s for s in setups if s["direction"] == "SHORT"]
print(f"Generated: {len(longs)} LONG  {len(shorts)} SHORT")

print("Saving to DB...")
saved = 0
for s in setups:
    try:
        save_trade_setup(s)
        saved += 1
    except Exception as e:
        print(f"  Skip {s['symbol']}: {e}")

print(f"Saved {saved} setups.")
print()
print("=== LONG signals ===")
for s in longs:
    print(f"  {s['symbol']:10} entry={s['entry_price']:>8}  {s['notes']}")
print()
print("=== SHORT signals ===")
for s in shorts:
    print(f"  {s['symbol']:10} entry={s['entry_price']:>8}  {s['notes']}")
