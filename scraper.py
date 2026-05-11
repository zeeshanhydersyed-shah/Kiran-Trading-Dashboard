"""
Scraper for ksestocks.com Market Summary.

Strategy: POST to /MarketSummary with sdate=YYYY-MM-DD.
One request returns ALL sectors and ALL stocks for that date.
This is far more efficient than scraping individual stock pages.
"""

import logging
import time
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from config import (
    MARKET_SUMMARY_URL,
    REQUEST_DELAY,
    REQUEST_HEADERS,
    MAX_RETRIES,
    INDEX_SYMBOLS,
    CALENDAR_DAYS_BACK,
    SECTOR_OVERRIDES,
)

logger = logging.getLogger(__name__)


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

    The scraper runs at 16:35 PKT, after PSX closes at 15:30 PKT and after
    ksestocks.com publishes final data (~16:15–16:30 PKT), so today's date is
    safe to request.
    """
    today = date.today()
    result = []
    d = last_date + timedelta(days=1)
    while d <= today:
        if _is_weekday(d):
            result.append(d)
        d += timedelta(days=1)
    return result


# ---------------------------------------------------------------------------
# Core scraping
# ---------------------------------------------------------------------------

def _fetch_html(target_date: date, session: requests.Session) -> str | None:
    """POST to Market Summary for a specific date; return HTML or None on failure."""
    date_str = target_date.strftime("%Y-%m-%d")
    payload = {"sdate": date_str}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(MARKET_SUMMARY_URL, data=payload, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            logger.warning(
                "Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, date_str, exc
            )
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * attempt)

    logger.error("All retries exhausted for %s", date_str)
    return None


def parse_market_summary(html: str, target_date: date) -> tuple[list, list]:
    """
    Parse Market Summary HTML.

    Returns:
        sector_rows : list of (symbol, sector)
        price_rows  : list of (symbol, date_str, close)

    Table structure (single large <table>):
      - Section header row   : 2 TDs, second contains "(Number of traded…)"
      - Column header row    : first TD text == "Symbol"
      - Stock data row       : 8 TDs → Symbol, Company, Open, High, Low, Close, Change, Vol
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    # The main data table is the last (and largest) one
    data_table = tables[-1] if tables else None
    if not data_table:
        logger.warning("No table found in HTML for %s", target_date)
        return [], []

    rows = data_table.find_all("tr")

    current_sector: str | None = None
    sector_rows:  list[tuple[str, str]]           = []
    price_rows:   list[tuple[str, str, float, float, float, int]] = []
    index_rows:   list[tuple[str, str, float, float, float]]      = []
    date_str = target_date.strftime("%Y-%m-%d")

    for row in rows:
        cells = row.find_all("td")

        if not cells:
            continue

        # ---- Detect section/sector header ----
        # Two cells; second one contains company-count text OR one cell with colspan
        if len(cells) == 2:
            second_text = cells[1].get_text(strip=True)
            if "Number of traded companies" in second_text or second_text == "":
                sector_name = cells[0].get_text(strip=True)
                current_sector = sector_name
                continue

        # ---- Skip column header rows ----
        if cells[0].get_text(strip=True) == "Symbol":
            continue

        # ---- Index row (Market Indexes section, 8 cells) ----
        # Capture KSE-100 and siblings into index_prices
        if len(cells) == 8 and current_sector == "Market Indexes":
            symbol     = cells[0].get_text(strip=True)
            high_text  = cells[3].get_text(strip=True).replace(",", "")
            low_text   = cells[4].get_text(strip=True).replace(",", "")
            close_text = cells[5].get_text(strip=True).replace(",", "")
            if symbol and symbol not in ("Symbol",):
                try:
                    close = float(close_text)
                    high  = float(high_text)  if high_text  else close
                    low   = float(low_text)   if low_text   else close
                    high  = max(high, close)
                    low   = min(low,  close)
                    index_rows.append((symbol, date_str, high, low, close))
                except ValueError:
                    pass
            continue

        # ---- Stock data row (8 cells) ----
        # Columns: Symbol, Company, Open, High, Low, Close, Change, Vol
        if len(cells) == 8 and current_sector and current_sector != "Market Indexes":
            symbol     = cells[0].get_text(strip=True)
            high_text  = cells[3].get_text(strip=True).replace(",", "")
            low_text   = cells[4].get_text(strip=True).replace(",", "")
            close_text = cells[5].get_text(strip=True).replace(",", "")
            vol_text   = cells[7].get_text(strip=True).replace(",", "")

            # Skip index symbols
            if symbol in INDEX_SYMBOLS or not symbol:
                continue

            try:
                close = float(close_text)
            except ValueError:
                logger.debug("Non-numeric close '%s' for %s on %s — skipping", close_text, symbol, date_str)
                continue

            if close <= 0:
                continue

            try:
                high = float(high_text) if high_text else close
            except ValueError:
                high = close

            try:
                low = float(low_text) if low_text else close
            except ValueError:
                low = close

            # Sanity: high >= close >= low (can be violated on bad data)
            high = max(high, close)
            low  = min(low,  close)

            try:
                volume = int(float(vol_text)) if vol_text else 0
            except (ValueError, OverflowError):
                volume = 0

            sector_rows.append((symbol, current_sector))
            price_rows.append((symbol, date_str, high, low, close, volume))

    return sector_rows, price_rows, index_rows


def scrape_date(target_date: date, session: requests.Session) -> tuple[list, list, list]:
    """Scrape one date. Returns (sector_rows, price_rows, index_rows). Empty lists if no data."""
    html = _fetch_html(target_date, session)
    if not html:
        return [], [], []

    sector_rows, price_rows, index_rows = parse_market_summary(html, target_date)

    if not price_rows:
        logger.info("No trading data for %s (holiday or weekend)", target_date)

    return sector_rows, price_rows, index_rows


def _price_fingerprint(p_rows: list) -> dict:
    """Build {symbol: (high, low, close)} for stale-data comparison."""
    return {r[0]: (r[2], r[3], r[4]) for r in p_rows if len(r) >= 5}


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
    Scrape multiple dates sequentially.
    Returns merged (sector_rows, price_rows, index_rows).

    prev_prices: price rows from the DB's last stored date, used to detect
                 the first date in the batch being a holiday ghost.
    """
    if session is None:
        session = build_session()

    all_sectors: dict[str, str] = {}
    all_prices:  list = []
    all_indices: list = []

    prev_fp = _price_fingerprint(prev_prices) if prev_prices else None

    total = len(dates)
    for idx, d in enumerate(dates, 1):
        logger.info("Scraping %s (%d/%d)…", d, idx, total)
        s_rows, p_rows, i_rows = scrape_date(d, session)

        if p_rows:
            curr_fp = _price_fingerprint(p_rows)
            if prev_fp is not None and _is_stale(curr_fp, prev_fp):
                logger.warning(
                    "Skipping %s — PSX returned identical data to previous session "
                    "(market closed / public holiday). No rows stored.", d
                )
                if idx < total:
                    time.sleep(REQUEST_DELAY)
                continue
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
        "Scraped %d dates -> %d sector mappings, %d price records, %d index records",
        total, len(sector_list), len(all_prices), len(all_indices),
    )
    return sector_list, all_prices, all_indices
