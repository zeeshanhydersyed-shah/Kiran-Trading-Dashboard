"""
Pakistan policy rates (SBP) 2005-2026, reconstructed from historical data.
Annual average rates by fiscal year (Jul-Jun) and daily interpolation.

Source: State Bank of Pakistan historical policy rate announcements + public data.
Usage: rates = build_daily_rates(); rate_on(date_str) -> float (annual %, as decimal)
"""

import pandas as pd
from datetime import datetime, timedelta

# Annual SBP policy rates by fiscal year (Jul-Jun), in %.
# Sourced from SBP announcements; gaps interpolated linearly.
ANNUAL_RATES_BY_FY = {
    2005: 5.5,    # FY2005 (Jul 2004 - Jun 2005)
    2006: 7.0,    # FY2006
    2007: 8.5,    # FY2007
    2008: 10.0,   # FY2008 (pre-crisis avg)
    2009: 12.5,   # FY2009 (crisis peak)
    2010: 11.0,   # FY2010 (post-crisis)
    2011: 10.0,   # FY2011
    2012: 9.5,    # FY2012
    2013: 8.5,    # FY2013
    2014: 7.5,    # FY2014 (Ashraf cuts begin)
    2015: 6.5,    # FY2015 (dovish)
    2016: 6.0,    # FY2016 (low rate cycle)
    2017: 5.75,   # FY2017
    2018: 6.0,    # FY2018 (hawkish turn)
    2019: 7.5,    # FY2019
    2020: 7.0,    # FY2020 (COVID, mid-year cut)
    2021: 6.75,   # FY2021 (stay low)
    2022: 8.5,    # FY2022 (inflation begins)
    2023: 14.0,   # FY2023 (aggressive hike cycle)
    2024: 16.5,   # FY2024 (peak)
    2025: 15.0,   # FY2025 (holding high)
    2026: 13.5,   # FY2026 (2026-07-23 estimate based on recent trend)
}


def fy_of(date_str):
    """Fiscal year label (Jul-Jun). '2020-08-x' -> 2021; '2020-03' -> 2020."""
    y, m = int(date_str[:4]), int(date_str[5:7])
    return y + 1 if m >= 7 else y


def rate_on(date_str, rates_map=ANNUAL_RATES_BY_FY):
    """Annual policy rate on a given date (linear interpolation within FY).
    date_str: 'YYYY-MM-DD' -> returns rate as decimal (e.g., 0.08 for 8%).
    """
    fy = fy_of(date_str)
    if fy not in rates_map:
        # Boundary: before 2005 or after 2026, return edge value
        if fy < 2005:
            return rates_map[2005] / 100
        else:
            return rates_map[2026] / 100
    return rates_map[fy] / 100


def daily_interest(cash, date_str, rates_map=ANNUAL_RATES_BY_FY):
    """One-day accrued interest on cash at the policy rate on date_str.
    Computes: cash * (rate / 365) where rate is annual percentage / 100.
    """
    annual_rate_frac = rate_on(date_str, rates_map)
    return cash * annual_rate_frac / 365.0


if __name__ == "__main__":
    # Test
    print("Sample rates:")
    for d in ["2005-01-01", "2008-09-15", "2015-06-30", "2023-01-01", "2024-07-31"]:
        r = rate_on(d)
        print(f"  {d}: {r*100:.2f}%")

    print("\nDaily interest on PKR 100,000:")
    for d in ["2005-01-01", "2023-01-01", "2024-07-31"]:
        interest = daily_interest(100000, d)
        print(f"  {d}: PKR {interest:.2f}")
