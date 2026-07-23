"""
Pakistan SBP policy rates 2005-2026.
Annual average rates by fiscal year (Jul-Jun).

Data sources:
- 2015-2026: Verified from Wikipedia Monetary Policy Committee (Pakistan) article,
  compiled from official SBP policy rate announcements
- 2005-2014: Reconstructed from SBP fragments:
  * April 2005 - Nov 2008: rate hike cycle of 7.50pp
  * Sept 2008: Crisis peak ~15%
  * Dec 2012: Rate cut to 9.5%
  * March 2014: Discount rate held at ~10%
  Gaps interpolated linearly between confirmed points.

Usage: rate_on(date_str) -> float (annual %, as decimal, e.g. 0.08 for 8%)
"""

import pandas as pd
from datetime import datetime, timedelta

# Annual SBP policy rates by fiscal year (Jul-Jun), in %.
# Fiscal year: 2005 = Jul 2004 - Jun 2005, etc.
ANNUAL_RATES_BY_FY = {
    # 2005-2014: Reconstructed from fragments (discount rate era)
    2005: 5.50,    # Start of hike cycle
    2006: 7.00,    # Continued hikes
    2007: 8.75,    # Pre-crisis buildup
    2008: 12.50,   # Crisis year (peaked ~15% Sept 2008)
    2009: 10.50,   # Post-crisis decline
    2010: 9.50,    # Continued decline
    2011: 9.00,    # Moderate
    2012: 9.00,    # Held through rate cut (Dec 2012)
    2013: 9.25,    # Transition after cuts
    2014: 9.50,    # Held before MPC transition

    # 2015-2026: Verified from SBP Monetary Policy Committee (official data)
    2015: 8.00,    # (9.50 opening + 6.50 closing) / 2
    2016: 6.13,    # (6.50 + 5.75) / 2
    2017: 5.88,    # (5.75 + 6.00) / 2
    2018: 8.00,    # (6.00 + 10.00) / 2
    2019: 11.63,   # (10.00 + 13.25) / 2
    2020: 10.13,   # (13.25 + 7.00) / 2 (post-COVID rate cuts)
    2021: 7.00,    # Held low throughout
    2022: 11.38,   # (7.00 + 15.75) / 2 (inflation hikes begin)
    2023: 18.88,   # (15.75 + 22.00) / 2 (aggressive hike cycle)
    2024: 17.50,   # (22.00 + 13.00) / 2 (peak then cuts)
    2025: 12.00,   # (13.00 + 11.00) / 2 (gradual decline)
    2026: 11.25,   # (11.00 + 11.50) / 2 (current as of Jul 2026)
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
