#!/usr/bin/env python3
"""Trace what dates the scraper will request."""

from datetime import date, datetime, timedelta, time as dtime

print('=' * 70)
print('TRACE DATE LOGIC - What does dates_since() return?')
print('=' * 70)
print()

# Simulate what happens
latest_date = date(2026, 6, 3)  # DB currently has June 3

print(f'Latest date in database: {latest_date}')
print()

# Simulate dates_since() logic
today = date.today()
print(f'Today: {today}')
print(f'Current time: {datetime.now().strftime("%H:%M:%S")}')
print()

# Check time logic
now = datetime.now()
market_data_time = dtime(16, 30)  # 4:30 PM
include_today = now.time() >= market_data_time

print(f'Market data time threshold: {market_data_time.strftime("%H:%M")} PKT')
print(f'Current time >= threshold: {include_today}')
print()

# Calculate max_date
max_date = today if include_today else today - timedelta(days=1)
print(f'max_date (will scrape up to): {max_date}')
print()

# Calculate what dates will be scraped
result = []
d = latest_date + timedelta(days=1)

print(f'Starting from: {latest_date} + 1 day = {d}')
print()
print('Dates that will be scraped:')

while d <= max_date:
    if d.weekday() < 5:  # Mon-Fri
        result.append(d)
        print(f'  {d} (weekday={d.strftime("%A")})')
    d += timedelta(days=1)

print()
print(f'RESULT: {len(result)} dates will be scraped')
print()

if len(result) > 0:
    print(f'Problem: Will scrape {result[-1]}, but ksestocks.com only has June 3!')
    print()
    print('Why: dates_since() assumes if it\'s after 16:30 PKT, today\'s data is available.')
    print('But ksestocks.com may not have published today\'s data yet!')
