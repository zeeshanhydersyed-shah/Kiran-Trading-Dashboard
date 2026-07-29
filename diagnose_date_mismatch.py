#!/usr/bin/env python3
"""Diagnose date mismatch between dashboard display and actual database."""

from database import get_latest_stock_date, get_latest_index_date, get_conn
from datetime import datetime

print('=' * 70)
print('DATE MISMATCH DIAGNOSIS')
print('=' * 70)
print()

# Get latest dates
latest_stock = get_latest_stock_date()
latest_index = get_latest_index_date()

print('[STEP 1] Database Latest Dates')
print(f'  Latest stock date (ISO): {latest_stock}')
print(f'  Latest index date (ISO): {latest_index}')
print()

# Format as DD/MM/YY
if latest_stock:
    parts = latest_stock.split('-')  # YYYY-MM-DD
    formatted = f"{parts[2]}/{parts[1]}/{parts[0][-2:]}"  # DD/MM/YY
    actual_date = datetime.strptime(latest_stock, '%Y-%m-%d').strftime('%B %d, %Y')
    print(f'  Latest stock date (DD/MM/YY): {formatted}')
    print(f'  Actual calendar date: {actual_date}')
print()

# Query the database to see what data is there
print('[STEP 2] Check Sample Data from Latest Date')
with get_conn() as conn:
    rows = conn.execute(
        'SELECT symbol, date, close, volume FROM prices WHERE date = ? LIMIT 5',
        (latest_stock,)
    ).fetchall()

    if rows:
        print(f'  Found {len(rows)} records for {latest_stock}:')
        for row in rows:
            print(f'    {row["symbol"]}: Close={row["close"]}, Vol={row["volume"]}')
    else:
        print(f'  ERROR: No records found for {latest_stock}!')
print()

# Check if there's data from previous day
print('[STEP 3] Check Previous Days for Comparison')
if latest_stock:
    parts = latest_stock.split('-')
    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])

    # Go back one day
    prev_day = day - 1
    if prev_day < 1:
        prev_month = month - 1
        if prev_month < 1:
            prev_year = year - 1
            prev_month = 12
            prev_day = 31
        else:
            prev_day = 30  # Simplified

    prev_date_str = f'{year:04d}-{prev_month:02d}-{prev_day:02d}'

    with get_conn() as conn:
        prev_rows = conn.execute(
            'SELECT COUNT(*) as cnt FROM prices WHERE date = ?',
            (prev_date_str,)
        ).fetchone()

        if prev_rows and prev_rows['cnt'] > 0:
            print(f'  {prev_date_str}: {prev_rows["cnt"]} records found')
        else:
            print(f'  {prev_date_str}: No records')
print()

print('[STEP 4] Dashboard Will Display')
if latest_stock:
    parts = latest_stock.split('-')
    formatted = f"{parts[2]}/{parts[1]}/{parts[0][-2:]}"
    print(f'  Data updated: {formatted} (from ksestocks.com)')
print()

print('=' * 70)
print('DIAGNOSIS COMPLETE')
print('=' * 70)
