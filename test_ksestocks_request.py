#!/usr/bin/env python3
"""Test what ksestocks.com returns when requesting June 4 data."""

import requests
from bs4 import BeautifulSoup
from datetime import date

print('=' * 70)
print('TEST: What does ksestocks.com return for June 4?')
print('=' * 70)
print()

# Try to fetch June 4 data
url = "https://www.ksestocks.com/MarketSummary"
payload = {"sdate": "2026-06-04"}

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

print(f'POST to: {url}')
print(f'Payload: {payload}')
print()

try:
    resp = requests.post(url, data=payload, headers=headers, timeout=10)
    print(f'Status: {resp.status_code}')
    print(f'Content length: {len(resp.text)} bytes')
    print()

    # Parse and check what's in it
    soup = BeautifulSoup(resp.text, 'html.parser')
    tables = soup.find_all('table')
    print(f'Tables found: {len(tables)}')
    print()

    if tables:
        # Look for Market Indexes section
        for i, table in enumerate(tables):
            rows = table.find_all('tr')
            # Check if this table has index data
            text = table.get_text()
            if 'KSE-100' in text:
                print(f'[Table {i}] Contains KSE-100 data')
                # Look for date in the table
                if '2026' in text:
                    print(f'  Contains 2026 dates')
                # Count rows
                print(f'  Rows: {len(rows)}')
                # Look for specific stock data
                stocks_found = 0
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 8:
                        symbol = cells[0].get_text(strip=True)
                        if symbol and len(symbol) <= 10 and symbol.isupper():
                            if not any(x in symbol for x in ['-', '(']):
                                stocks_found += 1
                                if stocks_found <= 3:
                                    close = cells[5].get_text(strip=True)
                                    print(f'    Sample: {symbol} = {close}')
                                if stocks_found == 3:
                                    break
                print(f'  Total stocks in table: ~{stocks_found}')
                print()

    # Key question: does it have June 4 or June 3 data?
    if '2026-06-04' in resp.text or '04/06/2026' in resp.text or 'June 4' in resp.text:
        print('Result: Returns JUNE 4 data')
    elif '2026-06-03' in resp.text or '03/06/2026' in resp.text or 'June 3' in resp.text:
        print('Result: Returns JUNE 3 data (stale!)')
    else:
        print('Result: Date unclear from content')

except Exception as e:
    print(f'Error: {e}')

print()
print('=' * 70)
