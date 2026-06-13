# Phase 2: Improved Refresh Logic - COMPLETE ✓

**Status:** Implemented and Tested  
**Date:** June 4, 2026  
**Focus:** Revert dates_since() to allow same-day scraping + Improve stale data detection

---

## Changes Made

### 1. **dates_since()** Reverted to Allow Same-Day Scraping

**File:** `scraper.py` (lines 63-97)

**Before:**
- Always excluded "today" entirely
- Conservative but prevented same-day data from ever being scraped

**After:**
- Includes today if current time >= 16:30 PKT (market close time)
- Falls back to excluding today if before market close
- Relies on stale detection to handle cases where data isn't ready

**Key Logic:**
```python
now = datetime.now()
market_close_time = dtime(16, 30)
include_today = now.time() >= market_close_time
max_date = today if include_today else today - timedelta(days=1)
```

---

### 2. **Improved Stale Data Detection**

**File:** `scraper.py` (lines 266-315)

**Changes:**

#### A. Better Fingerprint (OHLCV instead of HLC)
- **Before:** Only compared High, Low, Close (3 values)
- **After:** Includes Open, High, Low, Close, Volume (5 values)
- **Why:** Volume changes quickly; better detection of stale vs. fresh data

#### B. Higher Threshold (92% instead of 90%)
- **Before:** 90% match = stale
- **After:** 92% match = stale
- **Why:** Reduces false positives when there are minor price movements

#### C. Enhanced Logging
- Added detailed logging for all detection cases
- Shows percentage of unchanged symbols
- Distinguishes between "stale" (92%+) and "partial update warning" (70-92%)

#### D. Minimum Symbol Count
- Requires at least 15 common symbols (was 20)
- More flexible for smaller datasets

**New Detection Logic:**
```python
matches / common_count >= 0.92  # Stale if 92%+ identical
70% < matches < 92%              # Warning level (possible lag)
< 70%                            # Fresh data
```

---

### 3. **Enhanced Relabeling with Better Diagnostics**

**File:** `scraper.py` (lines 321-332)

**Changes:**
- Changed logging level from `warning` to `critical` for relabel events
- Added detailed message: `"Relabeling data: Requested=X but ksestocks returned Y data"`
- Shows record counts being relabeled: `"Relabeling N price records + M index records"`

**Example Log Output:**
```
CRITICAL: Relabeling data: Requested=2026-06-04 but ksestocks returned 2026-06-04 data 
(market not updated yet). Relabeling 601 price records + 5 index records to 2026-06-03.
```

---

## Test Results

### Test 1: dates_since() Behavior ✓
```
Current time: 20:37:28 PKT (after 16:30)
Expected: Include today (2026-06-04)
Result: PASS - dates_since() correctly includes today
```

### Test 2: Stale Detection Accuracy ✓

**Case 1: 100% Match (Stale Data)**
```
Test: Identical OHLCV for all symbols
Result: PASS - Correctly detected as stale
Log: "Stale data detected: 25/25 (100.0%) symbols unchanged"
```

**Case 2: 80% Match (Partial Update)**
```
Test: 5 out of 25 symbols changed
Result: PASS - Correctly NOT detected as stale
Log: "Partial match warning: 20/25 (80.0%) symbols unchanged"
```

**Case 3: 0% Match (Fresh Data)**
```
Test: All symbols changed
Result: PASS - Correctly NOT detected as stale
```

### Test 3: End-to-End Refresh ✓

**Scenario: Data Available**
```
Time: After market close + after ksestocks updates
Result: NEW data successfully loaded
  Status: SUCCESS
  Message: "[SUCCESS] End-of-day data loaded"
  Timestamp: 2026-06-04 20:38:47
```

**Scenario: Data Not Available Yet**
```
Time: Refresh attempted before data is available
Result: Clear message to user
  Status: NO_NEW_DATA
  Message: "[PENDING] No new data available yet"
          "Last update: 2026-06-04"
          "EOD data typically available by 19:00 PKT"
```

---

## How It Works: Phase 2 Flow

```
User clicks "Refresh Data"
     ↓
dates_since() checks current time
     ├─ After 16:30? Include today
     └─ Before 16:30? Exclude today
     ↓
Scrape requested dates
     ↓
For each date:
     ├─ Fetch data from ksestocks
     ├─ Build OHLCV fingerprint
     ├─ Compare to previous date's fingerprint
     ├─ If 92%+ match (stale):
     │  └─ Relabel to previous date
     │     (log at CRITICAL level)
     └─ Otherwise: Keep as-is
     ↓
Save to database
     ↓
Detect if new data was added
     ├─ New date added → SUCCESS message
     └─ No new data → PENDING message
     ↓
Display message to user
```

---

## Key Improvements Over Phase 1

| Aspect | Phase 1 | Phase 2 |
|--------|---------|---------|
| Same-day scraping | ❌ Blocked | ✓ Allowed after 16:30 |
| Fingerprint | HLC (3 values) | OHLCV (5 values) |
| Stale threshold | 90% | 92% |
| Logging detail | Warning level | Critical level |
| Minimum symbols | 20 | 15 |

---

## Behavior Differences from Phase 1

### Before Phase 2
```
User refresh at 17:00 (after market close, data available):
  dates_since() → excludes today
  → No dates to scrape
  → No new data message (misleading)
```

### After Phase 2
```
User refresh at 17:00:
  dates_since() → includes today (after 16:30)
  → Scrapes June 4 data
  → Stale detection: fresh ✓
  → Saves June 4 data
  → Shows [SUCCESS] message
```

---

## Files Modified

1. **scraper.py**
   - `dates_since()` — lines 63-97
   - `_price_fingerprint()` — lines 266-275
   - `_is_stale()` — lines 278-315
   - `scrape_date_range()` — lines 321-332 (enhanced logging)

---

## Files Unchanged But Utilized

- `refresh_manager.py` — Phase 1 messaging system (used by Phase 2)
- `dashboard.py` — Refresh button handler (displays Phase 2 messages)
- `main.py` — Entry point (calls dates_since)

---

## Validation Checklist

- [x] dates_since() includes today if after 16:30 PKT
- [x] dates_since() excludes today if before 16:30 PKT
- [x] Stale detection works for 100% match (stale)
- [x] Stale detection works for 80% match (fresh enough)
- [x] Stale detection works for 0% match (fresh)
- [x] Relabeling logic maintains correct dates
- [x] End-to-end refresh shows correct messages
- [x] Both scenarios tested (data available, not available)
- [x] Logging is informative and actionable

---

## Known Behaviors

### When Data IS Available (After ksestocks publishes)
1. User clicks Refresh at 17:00+ (after 16:30 market close)
2. System requests June 4 data (today)
3. ksestocks returns June 4 data (fresh, different from June 3)
4. Stale detection: < 92% match ✓ (fresh)
5. Data saved with correct date
6. User sees: **[SUCCESS] End-of-day data loaded**

### When Data NOT Available Yet (Before ksestocks publishes)
1. User clicks Refresh before ksestocks updates (rare, but possible)
2. System requests June 4 data
3. ksestocks returns June 3 data (stale, not updated)
4. Stale detection: 92%+ match (stale)
5. Data relabeled to June 3, not saved as June 4
6. User sees: **[PENDING] No new data available yet**

---

## Edge Cases Handled

1. **Requesting a weekend date** → Returns empty, not saved
2. **Requesting a holiday** → Returns stale data, gets relabeled to previous trading day
3. **Requesting a future date** → Returns previous day's data, stale detection catches it
4. **Partial data updates** → 80% match range warns but doesn't mark as stale
5. **Market delay** → User gets [PENDING] message with wait time and retry instructions

---

## Future Improvements (Not in Phase 2)

1. Add retry logic with exponential backoff
2. Track "last successful refresh" time vs. "last refresh attempt" time separately
3. Add a UI progress indicator for "waiting for data"
4. Automatically retry after N minutes if data not available
5. Alert if ksestocks is down (no data for 2+ hours after close)

---

## Phase 2 Complete ✓

Phase 2 successfully enables same-day scraping with intelligent stale detection. Combined with Phase 1's messaging system, the dashboard now provides clear user feedback for both "data available" and "data not available" scenarios.

The system is now production-ready for handling real-world timing variations in ksestocks.com data publication.

---

**Next Steps:** None required. Phase 2 is complete and tested.
