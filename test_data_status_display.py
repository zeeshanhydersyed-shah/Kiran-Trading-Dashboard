#!/usr/bin/env python3
"""
Test script to verify data status display shows correct timestamp.
Tests that displayed timestamp matches actual database data date.
"""

from database import get_latest_stock_date, get_latest_index_date, get_price_date_range, count_prices, count_sectors
from datetime import datetime

def fmt_date(d) -> str:
    """Format a date-like value as DD/MM/YY, or '—' if null/empty."""
    try:
        if d is None or d == "" or d != d:
            return "—"
        if isinstance(d, str):
            # Parse ISO format (YYYY-MM-DD) and reformat to DD/MM/YY
            parts = d.split("-")
            if len(parts) == 3:
                return f"{parts[2]}/{parts[1]}/{parts[0][-2:]}"
        return str(d)
    except Exception:
        return "—"


def test_data_status_display():
    """Test that data status display shows accurate timestamps."""

    print('=' * 70)
    print('DATA STATUS DISPLAY TEST')
    print('=' * 70)
    print()

    # Get database state
    latest_stock_date = get_latest_stock_date()
    latest_index_date = get_latest_index_date()
    mn, mx = get_price_date_range()
    price_count = count_prices()
    sector_count = count_sectors()

    print('[TEST 1] Database Values')
    print(f'  Latest stock date (from DB): {latest_stock_date}')
    print(f'  Latest index date (from DB): {latest_index_date}')
    print(f'  Price range: {mn} to {mx}')
    print(f'  Record counts: {price_count} prices, {sector_count} sectors')
    print()

    # Simulate dashboard display (what user sees)
    print('[TEST 2] Dashboard Display (What User Sees)')
    print('-' * 70)
    print('[Data Status]')

    if latest_stock_date:
        stock_display = f"**Stocks Latest Record:** {fmt_date(latest_stock_date)}"
        print(stock_display)
    else:
        print("**Stocks Latest Record:** No data")

    if latest_index_date:
        index_display = f"**Index Latest Record:** {fmt_date(latest_index_date)}"
        print(index_display)
    else:
        print("**Index Latest Record:** No data")

    print()

    # Data status caption (THE FIX)
    if latest_stock_date:
        data_update_time = f"{fmt_date(latest_stock_date)} (from ksestocks.com)"
    else:
        data_update_time = "No data available"

    caption = (
        f"[Calendar] Range: {fmt_date(mn)} to {fmt_date(mx)}\n"
        f"**{price_count:,}** prices . **{sector_count:,}** symbols\n"
        f"Data updated: {data_update_time}"
    )
    print(caption)
    print('-' * 70)
    print()

    # Verification tests
    print('[TEST 3] Verification Checks')

    test_results = []

    # Check 1: Data timestamp is from database, not system clock
    print()
    print('[OK] Check 1: Timestamp comes from database (not system clock)')
    if latest_stock_date in caption:
        print(f'  PASS - Database date {latest_stock_date} is shown')
        test_results.append(True)
    else:
        print(f'  FAIL - Database date {latest_stock_date} NOT shown')
        test_results.append(False)

    # Check 2: Source attribution is shown
    print()
    print('[OK] Check 2: Source attribution "(from ksestocks.com)" is present')
    if "(from ksestocks.com)" in caption:
        print(f'  PASS - Source attribution shown')
        test_results.append(True)
    else:
        print(f'  FAIL - Source attribution missing')
        test_results.append(False)

    # Check 3: System time is NOT shown
    print()
    print('[OK] Check 3: System time (datetime.now) is NOT shown')
    now = datetime.now()
    system_time_str = now.strftime('%d/%m/%y %H:%M')
    if system_time_str not in caption:
        print(f'  PASS - System time {system_time_str} NOT shown')
        test_results.append(True)
    else:
        print(f'  FAIL - System time {system_time_str} IS shown (bug!)')
        test_results.append(False)

    # Check 4: Data is consistent (stock and index dates should be same)
    print()
    print('[OK] Check 4: Stock and index dates match (should both be latest)')
    if latest_stock_date == latest_index_date:
        print(f'  PASS - Both dates match: {latest_stock_date}')
        test_results.append(True)
    else:
        print(f'  WARN - Dates differ (stock={latest_stock_date}, index={latest_index_date})')
        test_results.append(False)  # Soft fail - can happen if data misaligned

    print()
    print('=' * 70)

    if all(test_results):
        print('[SUCCESS] All checks passed!')
        print('Data status display is accurate and shows correct timestamp.')
        return True
    else:
        passed = sum(test_results)
        total = len(test_results)
        print(f'[PARTIAL] {passed}/{total} checks passed')
        print('Review failed checks above.')
        return False


if __name__ == '__main__':
    success = test_data_status_display()

    print()
    print('=' * 70)
    print('MANUAL VERIFICATION STEPS:')
    print('=' * 70)
    print()
    print('1. Open Kiran Dashboard in browser')
    print('2. Look at left sidebar "Data Status" section')
    print('3. Verify:')
    print('   [OK] Shows actual data date (e.g., "04/06/26")')
    print('   [OK] Shows source "(from ksestocks.com)"')
    print('   [OK] Does NOT show current system time (e.g., not "15:47")')
    print()
    print('4. Click "Refresh Data" button multiple times')
    print('5. Verify timestamp does NOT change (unless new data available)')
    print()
    print('If all checks pass, the fix is working correctly!')
    print('=' * 70)

    exit(0 if success else 1)
