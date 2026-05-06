"""
KIRAN Knowledge Base — Support and Resistance
==============================================

Saved for future integration. Do NOT apply to screener logic until explicitly requested.

This module captures the trader's understanding of support and resistance for use
in future KIRAN features: refined entry triggers, dynamic SL placement, breakout
confirmation, and ML feature engineering.

To activate: import this module and call the relevant functions from processor.py
or backtest.py when the time comes.
"""


# =============================================================================
# CORE DEFINITIONS
# =============================================================================

SUPPORT_RESISTANCE_CONCEPTS = {

    "support": {
        "definition": (
            "A price zone where buying interest is strong enough to stop the price "
            "from falling further, often causing a bounce upward. Acts as a floor."
        ),
        "trading_use": [
            "Identify potential LONG entry points near support",
            "Place stop-loss just below support (with buffer)",
            "Take profit near the next resistance level above",
        ],
    },

    "resistance": {
        "definition": (
            "A price zone where selling pressure is strong enough to stop the price "
            "from rising, often causing a reversal downward. Acts as a ceiling."
        ),
        "trading_use": [
            "Identify potential SHORT entry points near resistance",
            "Place stop-loss just above resistance (with buffer)",
            "Take profit near the next support level below",
            "For LONG setups: entry trigger is a confirmed break ABOVE resistance",
        ],
    },

    "role_reversal": {
        "definition": (
            "When price breaks through a resistance level, that level often becomes "
            "new support. Conversely, a broken support level often turns into new resistance."
        ),
        "trading_use": [
            "After a confirmed breakout above resistance, the old resistance becomes "
            "the first support and a natural stop-loss anchor",
            "After a confirmed breakdown below support, the old support becomes "
            "the first resistance and a natural stop-loss anchor for shorts",
        ],
    },

    "zones_not_lines": {
        "definition": (
            "Support and resistance are zones (areas) rather than exact price points. "
            "Price frequently oscillates around these areas before committing to a direction."
        ),
        "trading_use": [
            "Do not expect exact-to-the-pip bounces",
            "Use a tolerance band (e.g. +/-1-2%) around identified levels",
            "Current KIRAN implementation already uses tol=2.0% in _res_tests and _sup_tests",
        ],
    },
}


# =============================================================================
# STRENGTH OF A LEVEL
# =============================================================================

LEVEL_STRENGTH_RULES = {
    "test_count": {
        "rule": "The more times a level is tested and holds, the more significant it is.",
        "kiran_note": (
            "KIRAN already counts resistance tests (_res_tests) and support tests "
            "(_sup_tests) with a minimum of 2 tests required for quality score. "
            "This threshold can be raised to 3+ for higher-conviction setups."
        ),
    },
    "volume_at_level": {
        "rule": (
            "Significant breakouts from these levels are often accompanied by high "
            "trading volume, indicating strong conviction."
        ),
        "kiran_note": (
            "NOT YET IMPLEMENTED. Future feature: compare volume on breakout day "
            "against 10-day average volume. If breakout volume >= 1.5x avg volume, "
            "add +1 to quality_score. Requires volume data (now being backfilled)."
        ),
    },
    "time_at_level": {
        "rule": "The longer price consolidates near a level, the more significant it is.",
        "kiran_note": (
            "Partially implemented via range_window (5, 7, 10 day windows). "
            "Longer consolidation windows = more significant level."
        ),
    },
}


# =============================================================================
# TYPES OF SUPPORT AND RESISTANCE
# =============================================================================

SR_TYPES = {
    "horizontal": {
        "description": "The most common form — key horizontal price levels identified "
                       "from historical highs and lows.",
        "kiran_status": "IMPLEMENTED — _consolidation() identifies horizontal range high/low.",
    },
    "trendline": {
        "description": "Diagonal support/resistance drawn along a series of higher lows "
                       "(uptrend support) or lower highs (downtrend resistance).",
        "kiran_status": "NOT IMPLEMENTED — requires slope fitting over price series.",
    },
    "moving_average": {
        "description": "Dynamic S/R — moving averages (20d, 50d, 200d) often act as "
                       "floating support in uptrends and floating resistance in downtrends.",
        "kiran_status": "NOT IMPLEMENTED — could add MA20/MA50 as additional context.",
    },
    "round_numbers": {
        "description": "Psychological price levels (round numbers) often act as S/R "
                       "because traders cluster orders around them.",
        "kiran_status": "NOT IMPLEMENTED — low priority for PSX context.",
    },
    "previous_high_low": {
        "description": "Prior swing highs/lows are natural S/R levels.",
        "kiran_status": "PARTIALLY — consolidation high/low captures local swing levels.",
    },
    "fibonacci": {
        "description": "Fibonacci retracement levels (38.2%, 50%, 61.8%) within a prior "
                       "move act as S/R during pullbacks.",
        "kiran_status": "NOT IMPLEMENTED — future feature if needed.",
    },
}


# =============================================================================
# KIRAN-SPECIFIC TRADING RULES (User's approach)
# =============================================================================

KIRAN_SR_TRADING_RULES = {
    "entry_long": (
        "Do not buy blindly. Enter LONG only on a confirmed close above resistance "
        "with volume confirmation. Entry price = resistance * (1 + entry_buffer%). "
        "Current KIRAN buffer: 0.5%."
    ),
    "entry_short": (
        "Do not sell blindly. Enter SHORT only on a confirmed close below support "
        "with volume confirmation. Entry price = support * (1 - entry_buffer%). "
        "Current KIRAN buffer: 0.5%."
    ),
    "stop_loss_long": (
        "Stop-loss placed just below the support level of the consolidation range. "
        "SL = support * (1 - sl_buffer%). Current KIRAN buffer: 1.0%."
    ),
    "stop_loss_short": (
        "Stop-loss placed just above the resistance level of the consolidation range. "
        "SL = resistance * (1 + sl_buffer%). Current KIRAN buffer: 1.0%."
    ),
    "target": (
        "T1 = 1R above/below entry (first partial profit). "
        "T2 = 2R above/below entry (full target). "
        "Future enhancement: T3 = next major S/R level above entry (for big movers)."
    ),
    "volume_breakout_rule": (
        "NOT YET ACTIVE. Rule to implement: only accept a breakout as valid if the "
        "breakout candle's volume >= 1.5x the 10-day average volume. This filters "
        "false breakouts on thin volume."
    ),
}


# =============================================================================
# FUTURE KIRAN FEATURES (do not implement until asked)
# =============================================================================

FUTURE_FEATURES = [
    {
        "name": "Volume breakout confirmation",
        "description": (
            "Add volume breakout check to quality_checks. "
            "If breakout-day volume >= 1.5x avg_vol_10d → +1 quality point. "
            "Requires: volume data (now available after backfill)."
        ),
        "priority": "HIGH — directly addresses user concern about false breakouts",
        "files": ["processor.py", "backtest.py"],
    },
    {
        "name": "Dynamic T3 target at next major S/R",
        "description": (
            "Scan price history for the next significant resistance level above entry "
            "(for longs) and use it as T3. Captures big movers that run past T2."
        ),
        "priority": "MEDIUM — addresses observation that T2 is too modest in bull runs",
        "files": ["processor.py", "backtest.py", "dashboard.py"],
    },
    {
        "name": "Role reversal SL adjustment",
        "description": (
            "After a confirmed breakout, adjust SL to the broken resistance level "
            "(now acting as support) rather than the original consolidation low. "
            "Tighter SL = better R-ratio on confirmed moves."
        ),
        "priority": "MEDIUM",
        "files": ["processor.py"],
    },
    {
        "name": "Multi-timeframe S/R levels",
        "description": (
            "Identify S/R levels across multiple lookback windows (20d, 60d, 90d) "
            "and flag setups where multiple timeframes align. Higher alignment = "
            "higher quality score."
        ),
        "priority": "LOW — add after core ML pipeline is complete",
        "files": ["processor.py", "backtest.py"],
    },
]


# =============================================================================
# QUICK REFERENCE — for KIRAN reminder system
# =============================================================================

KIRAN_REMINDER = (
    "S/R knowledge is saved in knowledge_support_resistance.py. "
    "Key pending features: (1) volume breakout confirmation in quality_checks, "
    "(2) dynamic T3 at next resistance, (3) role reversal SL. "
    "Ask user before implementing any of these."
)
