"""
Scraper for dps.psx.com.pk (Pakistan Stock Exchange official data source).

Strategy:
- Scrapes PSX data portal web pages directly
- Attempts PSX Market Summary or Daily Data endpoint
- Parses HTML tables to extract OHLCV data for all stocks on a given date
- Returns data in the same format as the original ksestocks.com scraper
"""

import logging
import time
from datetime import date, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import (
    REQUEST_DELAY,
    REQUEST_HEADERS,
    MAX_RETRIES,
    INDEX_SYMBOLS,
    CALENDAR_DAYS_BACK,
    SECTOR_OVERRIDES,
)

logger = logging.getLogger(__name__)

# PSX Data Portal endpoints
PSX_BASE_URL = "https://dps.psx.com.pk"
PSX_DAILY_URL = f"{PSX_BASE_URL}/download/daily"
PSX_HISTORICAL_URL = f"{PSX_BASE_URL}/historical"


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _is_weekday(d: date) -> bool:
    return d.weekday() < 5  # Mon–Fri


def trading_dates_to_scrape(calendar_days: int = CALENDAR_DAYS_BACK) -> list[date]:
    """
    Return weekday dates for the past `calendar_days` calendar days
    (excluding today, since today's session may not be closed yet).
    Sorted oldest → newest.
    """
    today = date.today()
    result = []
    for offset in range(1, calendar_days + 1):
        d = today - timedelta(days=offset)
        if _is_weekday(d):
            result.append(d)
    result.sort()
    return result


def dates_since(last_date: date) -> list[date]:
    """Return weekday dates from the day after `last_date` up to and including today.

    The scraper normally runs at 16:35 PKT, after PSX closes at 15:30 PKT and after
    dps.psx.com.pk publishes final data (~16:00 PKT), so today's date is
    typically safe to request. However, if running before 16:30 PKT (e.g., manual
    morning scrape), only return dates up to yesterday to avoid mislabeling.
    """
    from datetime import datetime, time as dtime

    today = date.today()
    result = []
    d = last_date + timedelta(days=1)

    # Check if current time is before market data is published (16:30 PKT)
    # If so, exclude today from the scrape to avoid mislabeling stale data
    now = datetime.now()
    market_data_time = dtime(16, 30)
    include_today = now.time() >= market_data_time

    max_date = today if include_today else today - timedelta(days=1)

    while d <= max_date:
        if _is_weekday(d):
            result.append(d)
        d += timedelta(days=1)

    if not include_today:
        logger.info(
            "Scraper running before 16:30 PKT (current time: %s). "
            "Excluding today from scrape to avoid mislabeling stale data.",
            now.strftime("%H:%M:%S")
        )

    return result


# ---------------------------------------------------------------------------
# Core scraping from PSX
# ---------------------------------------------------------------------------

def _fetch_html(url: str, session: requests.Session, data: dict | None = None) -> str | None:
    """POST or GET to fetch HTML. Returns HTML or None on failure."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if data:
                resp = session.post(url, data=data, timeout=30)
            else:
                resp = session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            logger.debug(
                "Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, exc
            )
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * attempt)

    logger.warning("All retries exhausted for %s", url)
    return None


def parse_psx_market_data(html: str, target_date: date) -> tuple[list, list, list]:
    """
    Parse PSX Market Data HTML (from daily/historical endpoints).

    Returns:
        sector_rows : list of (symbol, sector)
        price_rows  : list of (symbol, date_str, open, high, low, close, volume)
        index_rows  : list of (symbol, date_str, open, high, low, close)

    Table structure expected:
      - Multiple tables organized by sector
      - Each stock row: Symbol, Company, Open, High, Low, Close, Change%, Volume
      - Index rows in "Market Indexes" section
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    if not tables:
        logger.warning("No tables found in PSX HTML for %s", target_date)
        return [], [], []

    sector_rows: list[tuple[str, str]] = []
    price_rows: list[tuple[str, str, float, float, float, float, int]] = []
    index_rows: list[tuple[str, str, float, float, float, float]] = []
    date_str = target_date.strftime("%Y-%m-%d")

    current_sector: str | None = None

    # Process all tables
    for table in tables:
        rows = table.find_all("tr")

        for row in rows:
            cells = row.find_all("td")

            if not cells:
                continue

            # ---- Detect sector header ----
            # Typically: 2 cells with sector name and trade count
            if len(cells) == 2 and "Number of traded" in cells[1].get_text(strip=True):
                sector_name = cells[0].get_text(strip=True)
                current_sector = sector_name
                continue

            # Single cell header with colspan (alternative format)
            if len(cells) == 1:
                text = cells[0].get_text(strip=True)
                if any(keyword in text for keyword in ["Market Indexes", "Equities", "EQUITY"]):
                    current_sector = text
                continue

            # ---- Skip column header rows ----
            if cells[0].get_text(strip=True) == "Symbol":
                continue

            # ---- Index row (Market Indexes section, 8 cells) ----
            if len(cells) >= 6 and current_sector and "Index" in current_sector:
                symbol = cells[0].get_text(strip=True)
                if symbol in INDEX_SYMBOLS:
                    try:
                        open_text = cells[2].get_text(strip=True).replace(",", "") if len(cells) > 2 else ""
                        high_text = cells[3].get_text(strip=True).replace(",", "") if len(cells) > 3 else ""
                        low_text = cells[4].get_text(strip=True).replace(",", "") if len(cells) > 4 else ""
                        close_text = cells[5].get_text(strip=True).replace(",", "") if len(cells) > 5 else ""

                        close = float(close_text) if close_text else 0
                        if close <= 0:
                            continue

                        high = float(high_text) if high_text else close
                        low = float(low_text) if low_text else close
                        open_ = float(open_text) if open_text else close

                        high = max(high, close)
                        low = min(low, close)

                        index_rows.append((symbol, date_str, open_, high, low, close))
                    except (ValueError, IndexError):
                        logger.debug("Could not parse index row for %s", symbol)
                continue

            # ---- Stock data row (8 cells) ----
            # Columns: Symbol, Company, Open, High, Low, Close, Change%, Volume
            if len(cells) >= 8 and current_sector and "Index" not in current_sector:
                symbol = cells[0].get_text(strip=True)

                # Skip empty rows and index symbols
                if not symbol or symbol in INDEX_SYMBOLS:
                    continue

                try:
                    open_text = cells[2].get_text(strip=True).replace(",", "")
                    high_text = cells[3].get_text(strip=True).replace(",", "")
                    low_text = cells[4].get_text(strip=True).replace(",", "")
                    close_text = cells[5].get_text(strip=True).replace(",", "")
                    vol_text = cells[7].get_text(strip=True).replace(",", "")

                    close = float(close_text) if close_text else 0
                    if close <= 0:
                        continue

                    open_ = float(open_text) if open_text else close
                    high = float(high_text) if high_text else close
                    low = float(low_text) if low_text else close
                    volume = int(float(vol_text)) if vol_text else 0

                    # Sanity: high >= close >= low
                    high = max(high, close)
                    low = min(low, close)

                    price_rows.append((symbol, date_str, open_, high, low, close, volume))
                    sector_rows.append((symbol, current_sector or "Unknown"))

                except (ValueError, IndexError) as exc:
                    logger.debug(
                        "Could not parse stock row for %s on %s: %s", symbol, date_str, exc
                    )

    return sector_rows, price_rows, index_rows


def scrape_date(target_date: date, session: requests.Session) -> tuple[list, list, list]:
    """Scrape one date from PSX. Returns (sector_rows, price_rows, index_rows)."""
    date_str = target_date.strftime("%Y-%m-%d")

    # Strategy 1: Try PSX Daily endpoint with POST
    logger.debug("Attempting PSX Daily endpoint for %s", date_str)
    html = _fetch_html(PSX_DAILY_URL, session, data={"sdate": date_str})

    # Strategy 2: Try PSX Historical endpoint with GET parameter
    if not html:
        logger.debug("Daily endpoint failed, trying Historical endpoint for %s", date_str)
        html = _fetch_html(f"{PSX_HISTORICAL_URL}?date={date_str}", session)

    # Strategy 3: Try alternative format (day/month/year)
    if not html:
        alt_date = target_date.strftime("%d/%m/%Y")
        logger.debug("Historical GET failed, trying alternative date format: %s", alt_date)
        html = _fetch_html(f"{PSX_HISTORICAL_URL}?date={alt_date}", session)

    if not html:
        logger.warning("Could not fetch HTML for %s from any PSX endpoint", date_str)
        return [], [], []

    sector_rows, price_rows, index_rows = parse_psx_market_data(html, target_date)

    if not price_rows:
        logger.info("No trading data for %s (holiday, weekend, or server down)", target_date)

    return sector_rows, price_rows, index_rows


def _price_fingerprint(p_rows: list) -> dict:
    """Build {symbol: (high, low, close)} for stale-data comparison."""
    # Tuple layout: (sym, date, open, high, low, close, vol) — use positions 3,4,5
    return {r[0]: (r[3], r[4], r[5]) for r in p_rows if len(r) >= 6}


def _is_stale(curr: dict, prev: dict, threshold: float = 0.90) -> bool:
    """Return True if >=threshold of common symbols have identical H/L/C — market was closed."""
    if not curr or not prev:
        return False
    common = set(curr) & set(prev)
    if len(common) < 20:
        return False
    matches = sum(1 for sym in common if curr[sym] == prev[sym])
    return (matches / len(common)) >= threshold


def scrape_date_range(
    dates: list[date],
    session: requests.Session | None = None,
    prev_prices: list | None = None,
) -> tuple[list, list, list]:
    """
    Scrape multiple dates sequentially from PSX.
    Returns merged (sector_rows, price_rows, index_rows).

    prev_prices: price rows from the DB's last stored date, used to detect
                 the first date in the batch being a holiday ghost.
    """
    if session is None:
        session = build_session()

    all_sectors: dict[str, str] = {}
    all_prices: list = []
    all_indices: list = []

    prev_fp = _price_fingerprint(prev_prices) if prev_prices else None

    total = len(dates)
    for idx, d in enumerate(dates, 1):
        logger.info("Scraping %s (%d/%d) from dps.psx.com.pk…", d, idx, total)
        s_rows, p_rows, i_rows = scrape_date(d, session)

        if p_rows:
            curr_fp = _price_fingerprint(p_rows)
            if prev_fp is not None and _is_stale(curr_fp, prev_fp):
                # Data is identical to previous session (market closed/not updated yet).
                # Relabel as the previous trading date instead of discarding.
                relabeled_date = d - timedelta(days=1)
                logger.warning(
                    "Data for %s is identical to previous session (market not updated yet). "
                    "Relabeling as %s.", d, relabeled_date
                )
                relabeled_date_str = relabeled_date.strftime("%Y-%m-%d")
                # Update price rows: (symbol, date, open, high, low, close, volume)
                p_rows = [
                    (sym, relabeled_date_str, open_, high, low, close, vol)
                    for sym, _, open_, high, low, close, vol in p_rows
                ]
                # Update index rows: (symbol, date, open, high, low, close)
                i_rows = [
                    (sym, relabeled_date_str, open_, high, low, close)
                    for sym, _, open_, high, low, close in i_rows
                ]
            prev_fp = curr_fp

        # Later sector assignments win (keep the most recent sector mapping)
        for sym, sec in s_rows:
            all_sectors[sym] = SECTOR_OVERRIDES.get(sym, sec)

        all_prices.extend(p_rows)
        all_indices.extend(i_rows)

        if idx < total:
            time.sleep(REQUEST_DELAY)

    sector_list = list(all_sectors.items())
    logger.info(
        "Scraped %d dates from PSX -> %d sector mappings, %d price records, %d index records",
        total, len(sector_list), len(all_prices), len(all_indices),
    )
    return sector_list, all_prices, all_indices
