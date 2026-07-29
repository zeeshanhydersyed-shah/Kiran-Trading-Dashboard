# Refresh Button Behavior Specification

**Context:** PSX market closes at 16:30 PKT. ksestocks.com publishes EOD data approximately 2-3 hours after close (18:00-19:00 PKT).

---

## Scenario A: Data Available (After-Hours Update)

**Trigger:** User clicks "Refresh Data" at 17:00+ when ksestocks.com HAS published new data

### Expected Behavior

✅ **What Should Happen:**

1. **Fetch New Data**
   - System requests latest data from ksestocks.com
   - Receives June 3 EOD closing data (if market closed June 3)
   - Data passes stale detection (new/different from previous day)

2. **Save to Database**
   - Price records saved with correct date (2026-06-03)
   - Index records saved with correct date
   - Database reflects latest available data

3. **Update Dashboard Display**
   ```
   📊 Data Status
   Stocks Latest Record: 03/06/26  ✓ UPDATED
   Index Latest Record: 03/06/26   ✓ UPDATED
   
   Data updated: 03/06/26 (from ksestocks.com)  ✓ FRESH
   ```

4. **User Notification**
   - Show brief success message: "✓ End-of-day data loaded successfully"
   - Display in sidebar for 3-5 seconds, then fade
   - No error messages

5. **Button State**
   - Show "Loading..." during fetch
   - Re-enable after completion
   - Allow new refresh attempts after 5 minutes

---

## Scenario B: Data Not Available (No Update)

**Trigger:** User clicks "Refresh Data" at 17:00+ when ksestocks.com HASN'T published new data yet

### Expected Behavior

✅ **What Should Happen:**

1. **Attempt Fetch**
   - System requests data from ksestocks.com
   - Receives either:
     - **Old data** (June 2 when expecting June 3)
     - **Empty response** (no data for requested date)

2. **Stale Detection**
   - Recognizes data is from previous day (90%+ price match)
   - Does NOT save stale data to database
   - Does NOT update dashboard

3. **Database Remains Unchanged**
   ```
   Latest in DB: June 2 (unchanged)
   Status: Not updated
   ```

4. **User Notification**
   - Show message: "⏳ No new data available yet. Please try again in a few minutes."
   - Timestamp: "Last successful update: 02/06/26"
   - Show expected availability: "EOD data typically available by 19:00 PKT"

5. **Button State**
   - Remain enabled (allow retries)
   - Show "Loading..." during request
   - Track last refresh time
   - If retried within 2 minutes: show tooltip "Waiting for ksestocks update. Refresh again in [X] minutes."

---

## Rate Limiting & Retry Logic

### User Behavior Rules

```
Click 1 (17:00):  [Fetch] → No data → Message: "Try again in a few minutes"
Click 2 (17:02):  [Cached] → Show: "Too soon. Last attempt: 2 min ago"
Click 3 (17:05):  [Fetch] → Still no data → Message: "Still waiting for ksestocks"
Click 4 (17:15):  [Fetch] → Data available! → Success message
```

### Implementation

- **Throttle requests:** Don't actually scrape if last refresh < 3 minutes ago
- **Cache result:** Store "last refresh time" and "last result" client-side
- **Show wait time:** Tell user when to try again
- **Max retries:** After 30 minutes of "no data", show: "Data is taking longer than usual. Check ksestocks.com directly."

---

## Message Specifications

### Success Messages (Scenario A)

```
✓ End-of-day data loaded
  Latest: 03/06/26 | 601 stocks | 5 indices

[appears in green, fades after 4 seconds]
```

### Info Messages (Scenario B)

```
⏳ No new data available yet
  Last update: 02/06/26
  EOD data typically available by 19:00 PKT
  
[appears in blue/yellow, persists until next successful refresh]
```

### Warning Messages (Extended Wait)

```
⚠ Data delayed beyond usual timeframe
  Last update: 02/06/26 (15+ minutes ago)
  Check ksestocks.com: https://www.ksestocks.com/MarketSummary
  
[appears in orange, persists]
```

---

## Button State Flowchart

```
[Enabled] 
    ↓
User clicks Refresh
    ↓
[Disabled → "Loading..."]
    ↓
Fetch data from ksestocks
    ↓
    ├─ Success: Save & Update
    │   ↓
    │   Show: "✓ Data loaded"
    │   Set: next_retry_allowed = now + 5 minutes
    │   ↓
    │   [Enabled]
    │
    └─ No new data: Don't save
        ↓
        Show: "⏳ No new data yet"
        Set: next_retry_allowed = now + 3 minutes
        ↓
        [Enabled - Allow retry]
```

---

## Specific Recommendations

### Timing

| Event | Time |
|-------|------|
| Market close | 16:30 PKT |
| ksestocks typically updates | 18:00-19:00 PKT |
| Safe to refresh | 18:30+ PKT |
| Give up if no data | After 30 min (17:00 timeout) |

### Button Behavior

✅ **DO:**
- Always keep button enabled (users expect it)
- Show loading state during fetch
- Disable during fetch to prevent double-clicks
- Show user-friendly messages
- Allow rapid clicks with throttling message

❌ **DON'T:**
- Disable button during certain hours
- Auto-refresh in background (unexpected behavior)
- Show technical error messages
- Silently fail with no feedback
- Require manual page refresh

### Message Behavior

✅ **Success messages:**
- Show 3-5 seconds
- Auto-dismiss if new data loaded
- Always show current latest date

✅ **Info messages:**
- Persist in sidebar
- Show expected wait time
- Update if user retries
- Include link to check manually

---

## Implementation Checklist

- [ ] Improve stale data detection to be more reliable
- [ ] Add message system to sidebar
- [ ] Track last refresh time in session state
- [ ] Implement 3-minute throttle with tooltip
- [ ] Show expected availability time (19:00 PKT)
- [ ] Add link to ksestocks.com in "no data" message
- [ ] Test Scenario A (data available)
- [ ] Test Scenario B (data not available)
- [ ] Test rate limiting
- [ ] Test messages display/fade correctly

---

## Current Implementation Gap

**Issue:** Our recent fix prevents scraping "today" entirely. This is TOO conservative.

**What happens now:**
```
Market close: June 3 at 16:30
User refresh: June 3 at 18:30 (data IS available)
Result: System says "Latest=June 3, max_date=June 2, scrape nothing"
Outcome: User never gets same-day data
```

**Better approach:**
- Revert to allowing same-day scraping AFTER market close
- Rely on stale data detection to handle cases where data isn't ready
- Show clear "no new data yet" message instead of silent failure

---

## Recommended Next Steps

1. **Improve stale data detection** to reliably catch when ksestocks returns yesterday's data
2. **Revert dates_since()** to include today if after market close (16:30+)
3. **Add user messaging system** to dashboard sidebar
4. **Test both scenarios** thoroughly

This provides a good user experience while safely handling the timing uncertainty of data availability.
