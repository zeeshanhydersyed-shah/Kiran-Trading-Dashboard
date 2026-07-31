# Support Reversal Setup - Complete Criteria

**Version:** 2.0  
**Status:** 🔴 KILLED 2026-07-23 — not a live strategy, kept for historical record only  
**Expected Expectancy:** ~~+5.2% per trade~~ **-1.88% net** (full 21.5-year path-aware retest, 16,425 trades, negative in all five eras)  
**Risk:Reward Ratio:** ~~5.03x~~ **1.51x** (full-period, path-aware)  

> **Re-audited 2026-07-23 and confirmed dead — do not trade this setup.** The original
> +5.2%/5.03x headline below was a look-ahead artefact: the "trailing stop" was never
> simulated on a real price path (`max(max_favorable - 2%, return_20d)`, no path
> ordering, no check the stop was hit first) and was measured on a single quarter
> (2026-01-01 to 2026-04-08, 360 signals) mislabeled as "out-of-sample". A genuine
> path-aware re-run across the full 2005-2026 history (1,580,310 bars, 16,425 filled
> signals) gives WR 29.1%, R:R 1.51x, **-1.88% net of costs**, negative in every one of
> five eras and 21 of 22 individual years. The screener is disabled in the live
> pipeline (`processor.py`'s `generate_support_reversal_setups` returns an empty list;
> `config.py`'s `SUPPORT_REVERSAL_STATS` carries the corrected numbers). Everything
> below this notice describes the pattern as it was originally specified and tested —
> read it as history, not as a plan to execute. Full verdict:
> `C:\Users\Lenovo\RESEARCH_LOG.md`, "Support/Resistance + Support Reversal" row.

---

## What This Setup Is

A **rejection candle at support** in a strong uptrend. Price approaches a key support level, briefly touches/penetrates it, then quickly recovers **within the same candle**. This indicates weak sellers at support and strong reversal momentum.

---

## ENTRY CRITERIA (All Must Be True)

### 1. Trend Filter: 200-MA Uptrend
- **Close > 200-Day SMA × 1.01**
  - Price must be above the 200-day moving average
  - Minimum 1% above to confirm uptrend
  - Purpose: Only trade in established uptrends, avoid choppy markets

### 2. Rejection Candle: High Lower Wick
- **Lower Wick Ratio > 60%**
  - `(min(Open, Close) - Low) / (High - Low) > 0.60`
  - At least 60% of the candle range is below the close
  - Indicates strong rejection of lower prices within candle

### 3. Rejection Candle: Strong Recovery
- **Recovery Ratio > 75%**
  - `(Close - Low) / (High - Low) > 0.75`
  - Close in top 25% of the candle's range
  - Shows price recovered strongly from the lows within same candle

### 4. Support Touch
- **Low touches or slightly penetrates pivot point support**
  - Support level = (Previous High + Previous Low + Previous Close) / 3
  - Support1 = (Pivot × 2) - Previous High
  - Touch if: `Low <= Support1 + 1 point`

---

## ENTRY

**Entry Price:** 1 point above the candle's High
- Entry = Candle High + 1 point
- Wait for confirmation: candle closes and reversal candle appears
- Do NOT chase; if price has moved 2%+ above, skip the setup
- Entry based on **volatility/price action**, not time (intraday entry possible)

---

## STOP LOSS

**Hard Stop: -6% Below Entry**
- Stop = Entry × 0.94
- **Non-negotiable.** If price hits this, exit immediately
- No trailing or discretion at -6%
- Purpose: Risk management, defined downside

---

## EXIT STRATEGY

**Trailing Stop (Active Management)**
- **Trail by 2% from the highest price reached**
- As price goes UP, move stop up to protect profits
- Exit when price falls 2% from its peak during the trade

**Example:**
- Entry: 100
- Price reaches: 115 (peak)
- Trailing stop: 115 - 2% = 113
- If price then falls to 112, stop is hit → **Exit at 113**
- If price continues to 120, stop moves to 118

---

## HOLD PERIOD

**Primary Target: 20-Day Hold**
- Hold for at least 20 trading days
- Do NOT exit early for small 2-3% gains
- Let trailing stop manage the exit
- If trailing stop hasn't hit by 20 days, hold beyond

**Minimum Hold:** 5 days  
**Maximum Hold:** Until trailing stop hit (no time-based exit)

---

## PERFORMANCE METRICS (From Live Testing)

| Metric | Value |
|--------|-------|
| **Win Rate** | 30.5% |
| **Average Win** | +10.27% |
| **Average Loss** | -2.04% |
| **Risk:Reward** | 5.03x |
| **Expectancy** | +5.21% per trade |
| **Trades for 10% gain** | 2 trades |

**Your Current System:** 3.36% expectancy, 1.72x R:R  
**This Setup:** +5.21% expectancy, 5.03x R:R  
**Edge:** +1.85% better expectancy

---

## QUALITY FILTERS (Optional - For Higher Conviction)

Apply these for fewer but higher-quality setups:

- **Recovery Ratio > 75%** (vs 75% baseline)
- **Lower Wick Ratio > 60%** (vs 60% baseline)
- **Volume > 1.5x average** (optional)

**Result:** Fewer signals, slightly better win rate

---

## RULES & DISCIPLINE

### DO:
✅ Enter only when **all entry criteria** are met  
✅ Use **exactly 1 point above high** as entry  
✅ Place **hard stop at -6%** immediately  
✅ **Trail the stop** as price rises  
✅ Hold for at least **20 days**  
✅ Track **all metrics** (entry, SL, exit, return)  

### DON'T:
❌ Chase if price has moved 2%+ above high  
❌ Deviate from -6% hard stop (no discretion)  
❌ Exit early on small gains  
❌ Use this in downtrends or below 200-MA  
❌ Trade without a defined stop loss  
❌ Average down or add to losing positions  

---

## TRADE MANAGEMENT

| Event | Action |
|-------|--------|
| **Entry** | Place 6% hard stop immediately. Start trailing stop tracking. |
| **+2% gain** | Move stop to breakeven (entry price). Protect capital. |
| **+5% gain** | Trail stop at (current_high - 2%) |
| **+10% gain** | Trail stop is now at -5% max (protecting 5% gain) |
| **20 days passed** | Continue holding. Stop manages exit, no time exit. |
| **Stop hit** | Exit position. Record trade metrics. |

---

## POSITION SIZING

**Risk Rule:** 1% of portfolio per trade
- If account = 1,000,000 PKR
- Risk per trade = 10,000 PKR
- Position size = 10,000 / (entry - stop_loss)

**Example:**
- Entry: 100, Stop: 94 (6% risk)
- Risk per trade: 10,000
- Position size: 10,000 / 6 = 1,667 shares

---

## EXPECTED BEHAVIOR

### Over 10 Trades:
- **~3 trades win** (avg +10%)
- **~7 trades lose** (avg -2%)
- **Net expectancy:** +5.2% across 10 trades
- **Required to hit 10% portfolio gain:** 2 winning setup executions

### Market Conditions:
- **Trending markets:** Higher win rates (40%+)
- **Choppy markets:** Lower win rates (20-25%)
- **Strong uptrends:** Best performance (consistent 30%+ win rate)

---

## DAILY IMPLEMENTATION

1. **Each trading day:** Scan for setups meeting ALL criteria
2. **On signal:** Place entry order (high + 1), SL (-6%)
3. **Monitor:** Trail the stop daily as price moves
4. **Record:** Log entry, SL, exit, return, date
5. ~~**Weekly review:** Check performance vs 5.21% expected~~ — moot, screener is disabled (see status banner above)

---

## WHY THIS WORKS

1. **200-MA filters noise** → Only strong uptrends
2. **Rejection candle is observable** → Price *actually* rejected lower prices
3. **High wick + recovery** → Not a fluke, shows real rejection
4. **Trailing stop captures full move** → Doesn't cap winners at arbitrary levels
5. ~~**5.21% edge beats the market** → Positive expectancy over time~~ — this was the artefact; the real full-period edge is -1.88% net, see status banner above

---

## RED FLAGS - DO NOT TRADE IF:

🚫 Stock is below 200-MA (not in uptrend)  
🚫 Wick ratio < 60% (not a strong rejection)  
🚫 Recovery ratio < 75% (price didn't recover enough)  
🚫 No clear pivot support (entry signal invalid)  
🚫 Penny stock or low volume (hard to exit)  
🚫 Company news/earnings imminent (gap risk)  

---

## TRACKING

Save every setup with:
- Date, Symbol
- Entry price, SL, target
- 5d/10d/20d return
- Win/Loss flag
- Actual exit price
- Trailing stop hit? (Y/N)

**Monthly Review:** ~~Calculate actual win rate, compare to 30.5% expected, track average wins/losses, verify 5.21% expectancy~~ — moot, screener disabled 2026-07-23 (see status banner above)

---

## REVISION HISTORY

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-05-21 | Initial criteria document. 200-MA, 75% recovery, 60% wick, trailing 2% stop. Expected 5.21% EV. |
| 2.0 | 2026-07-31 | KILLED. Re-audit (2026-07-23, recorded in RESEARCH_LOG.md) found the 5.21% headline was a look-ahead artefact measured on one quarter; full 21.5-year path-aware retest gives -1.88% net, negative in all five eras. Screener disabled in the live pipeline. Doc kept for historical record, status banner added at top, live-monitoring instructions struck through as moot. |

