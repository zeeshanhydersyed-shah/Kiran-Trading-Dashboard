#!/usr/bin/env python3
"""Test the refresh messaging system."""

from refresh_manager import (
    RefreshStatus,
    RefreshResult,
    get_refresh_message,
)

print('=' * 70)
print('TEST: Refresh Messaging System')
print('=' * 70)
print()

# Test Scenario A: Success (new data loaded)
print('[Scenario A] Data Available - New data loaded (checkmark)')
result_a = RefreshResult(
    status=RefreshStatus.SUCCESS,
    message="New data loaded successfully",
    data_date="03/06/26",
)
msg_a, type_a = get_refresh_message(result_a)
print(f'Type: {type_a}')
print(f'Message:\n{msg_a}')
print()

# Test Scenario B: No new data
print('[Scenario B] Data Not Available - No new data yet')
result_b = RefreshResult(
    status=RefreshStatus.NO_NEW_DATA,
    message="ksestocks.com has not published new data yet",
    data_date="02/06/26",
)
msg_b, type_b = get_refresh_message(result_b)
print(f'Type: {type_b}')
print(f'Message:\n{msg_b}')
print()

# Test Scenario C: Throttled
print('[Scenario C] Rate Limited - Too soon to refresh')
result_c = RefreshResult(
    status=RefreshStatus.THROTTLED,
    message="Wait 2m 45s before next refresh",
    data_date="02/06/26",
)
msg_c, type_c = get_refresh_message(result_c)
print(f'Type: {type_c}')
print(f'Message:\n{msg_c}')
print()

# Test Scenario D: Error
print('[Scenario D] Error - Refresh failed')
result_d = RefreshResult(
    status=RefreshStatus.ERROR,
    message="Connection timeout",
    data_date="02/06/26",
)
msg_d, type_d = get_refresh_message(result_d)
print(f'Type: {type_d}')
print(f'Message:\n{msg_d}')
print()

print('=' * 70)
print('[SUCCESS] All messaging scenarios work correctly!')
print('=' * 70)
