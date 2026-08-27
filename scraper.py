"""
Scraper for ksestocks.com Market Summary.

Strategy: POST to /MarketSummary with sdate=YYYY-MM-DD.
One request returns ALL sectors and ALL stocks for that date.
This is far more efficient than scraping individual stock pages.

SOURCE-DATE INTEGRITY RULES
----------------------------
Rule 1 -- The trading date for every stored record must come from the source
          page itself, never from the system clock. Use get_source_date() to
          read what ksestocks.com is currently publishing.

Rule 2 -- Before storing anything, check whether that source date is already
          in the database.  If it is -> skip.  System clock may only be used
          for logging/audit ("fetched at 14:32").

Rule 3 -- find_db_gaps() detects missing weekdays inside the existing DB
          range so historical gaps can be backfilled.
"""

import logging
import re
import time
from datetime import date, datetime, timedelta

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
    EXCLUDED_SECTORS,
    is_non_equity_symbol,
)

logger = logging.getLogger(__name__)


# Back-compat alias. The old name only covered bare SYMBOL-MONTH futures;
# is_non_equity_symbol() also catches the -MONB/-MONC/-CMON variants plus
# government paper (P0x) and 786/786R. See config.py.
_is_futures_symbol = is_non_equity_symbol


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
    return d.weekday() < 5  # Mon-Fri


# ---------------------------------------------------------------------------
# Source-date extraction  (Rule 1 -- never use the system clock to label data)
# ---------------------------------------------------------------------------

def get_source_date(session: requests.Session) -> date | None:
    """
    Fetch the MarketSummary landing page (GET, no sdate) and extract the
    trading date that ksestocks.com is currently publishing.

    The page contains the text:
        "Latest update was on June 5, 2026."
    which is the authoritative source date.  This function parses that text
    and returns it as a date object.

    Returns None if the page is unreachable or the pattern is not found.
    The system clock is NOT used.  Fetch timestamp is logged for audit only.
    """
    fetched_at = datetime.now().strftime("%H:%M:%S on %Y-%m-%d")
    try:
        resp = session.get(MARKET_SUMMARY_URL, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(
            "get_source_date: could not fetch %s: %s (tried at %s)",
            MARKET_SUMMARY_URL, exc, fetched_at,
        )
        return None

    # Pattern: "Latest update was on Month D, YYYY" or "Month DD, YYYY"
    match = re.search(
        r"[Ll]atest update was on\s+([A-Za-z]+ \d{1,2},?\s*\d{4})",
        resp.text,
        re.IGNORECASE,
    )
    if match:
        raw = match.group(1).strip().rstrip(".")
        # Normalise punctuation/spacing: "June 5, 2026" -> "June 5 2026"
        raw = re.sub(r",?\s+", " ", raw)
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                parsed = datetime.strptime(raw, fmt).date()
                logger.info(
                    "Source date: %s  (parsed from %r, fetched at %s)",
                    parsed, match.group(0).strip(), fetched_at,
                )
                return parsed
            except ValueError:
                continue
        logger.warning(
            "get_source_date: matched text %r but could not parse as date", raw
        )
        return None

    # Build a useful debug snippet: find any mention of "update" first;
    # if none, fall back to the first 1000 chars of the raw page.
    _text = resp.text
    _update_idx = _text.lower().find("update")
    if _update_idx >= 0:
        _snippet_start = max(0, _update_idx - 100)
        _snippet = _text[_snippet_start : _update_idx + 400]
    else:
        _snippet = _text[:1000]

    logger.error(
        "get_source_date: 'Latest update was on' not found in page -- "
        "site structure may have changed.  "
        "Fetched at %s, page length %d chars.  "
        "Debug snippet (+-context around 'update'): %r",
        fetched_at, len(_text), _snippet,
    )
    return None


def new_dates_to_scrape(last_db_date: date, source_date: date) -> list[date]:
    """
    Return weekday dates from last_db_date+1 to source_date (inclusive),
    sorted oldest -> newest.

    This replaces dates_since() for all new scrape runs.  It never touches
    the system clock -- the upper bound comes from get_source_date().
    """
    if source_date <= last_db_date:
        return []
    result: list[date] = []
    d = last_db_date + timedelta(days=1)
    while d <= source_date:
        if _is_weekday(d):
            result.append(d)
        d += timedelta(days=1)
    return result


def find_db_gaps(
    existing_dates: set[str],
    start: date,
    end: date,
    known_holidays: set[date] | None = None,
) -> list[date]:
    """
    Return weekday dates in [start, end] that are absent from existing_dates.

    existing_dates must be a set of 'YYYY-MM-DD' strings already in the DB.
    Weekends are skipped automatically.

    known_holidays: optional set of date objects to exclude from the gap list.
    If provided, any missing weekday that falls on a known holiday is silently
    ignored, preventing spurious backfill attempts and log warnings on every run.

    Typical usage: detect missed days in the last 90 days of DB history.
    """
    _excluded = known_holidays or set()
    gaps: list[date] = []
    d = start
    while d <= end:
        if (
            _is_weekday(d)
            and d.strftime("%Y-%m-%d") not in existing_dates
            and d not in _excluded
        ):
            gaps.append(d)
        d += timedelta(days=1)
    return gaps


def trading_dates_to_scrape(calendar_days: int = CALENDAR_DAYS_BACK) -> list[date]:
    """
    Return weekday dates for the past `calendar_days` calendar days
    (excluding today, since today's session may not be closed yet).
    Sorted oldest -> newest.
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

    Excludes today if it's requested before PSX's ~15:30 PKT close (~10:30
    UTC; a 30-minute margin is added on top). The scheduled cron (17:00 UTC)
    is naturally safe and unaffected by this. This guard exists because a
    manually-triggered run (workflow_dispatch) is not bound to the schedule
    and can fire mid-session -- confirmed root cause of the 2026-07-10
    incident: a ~09:49 UTC manual trigger requested "today" before close,
    ksestocks.com served its latest-complete-session data (still 07-09's)
    for that request, and the scraper stored it under the 07-10 label with
    nothing rejecting the request in the first place. This is a second,
    independent guard alongside the _is_stale() Decimal/float fix below --
    that fix stops bad data already fetched from being stored; this one
    stops the request from being made at all before it's safe to trust.
    """
    from datetime import datetime, time as dtime, timezone

    today = date.today()
    now_utc = datetime.now(timezone.utc).time()
    market_close_utc = dtime(11, 0)  # ~15:30 PKT + 30min safety margin
    max_date = today if now_utc >= market_close_utc else today - timedelta(days=1)

    result = []
    d = last_date + timedelta(days=1)
    while d <= max_date:
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
        price_rows  : list of (symbol, date_str, high, low, close, volume, open)
        index_rows  : list of (symbol, date_str, high, low, close, open)

    Table structure (single large <table>):
      - Section header row   : 2 TDs, second contains "(Number of traded...)"
      - Column header row    : first TD text == "Symbol"
      - Stock data row       : 8 TDs -> Symbol, Company, Open, High, Low, Close, Change, Vol

    Open (cells[2]) is captured here as of 2026-07 -- it was present in every
    response all along but never extracted (see docs/DATA_ACQUISITION_ARCHITECTURE.md
    for the historical-data project that backfilled the resulting gap). It
    follows the same fallback convention as High/Low: if the cell is blank or
    unparseable, default to close rather than leave it missing, matching
    existing behavior for this scraper.
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
    sector_rows:  list[tuple[str, str]]                          = []
    price_rows:   list[tuple[str, str, float, float, float, int, float]] = []
    index_rows:   list[tuple[str, str, float, float, float, float]]      = []
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
            open_text  = cells[2].get_text(strip=True).replace(",", "")
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
                    try:
                        open_ = float(open_text) if open_text else close
                    except ValueError:
                        open_ = close
                    index_rows.append((symbol, date_str, high, low, close, open_))
                except ValueError:
                    pass
            continue

        # ---- Stock data row (8 cells) ----
        # Columns: Symbol, Company, Open, High, Low, Close, Change, Vol
        if len(cells) == 8 and current_sector and current_sector != "Market Indexes":
            symbol     = cells[0].get_text(strip=True)
            open_text  = cells[2].get_text(strip=True).replace(",", "")
            high_text  = cells[3].get_text(strip=True).replace(",", "")
            low_text   = cells[4].get_text(strip=True).replace(",", "")
            close_text = cells[5].get_text(strip=True).replace(",", "")
            vol_text   = cells[7].get_text(strip=True).replace(",", "")

            # Skip index symbols
            if symbol in INDEX_SYMBOLS or not symbol:
                continue

            # Skip non-equity instruments: futures (all series -- SYMBOL-MON,
            # SYMBOL-MONB/C/D, SYMBOL-CMON), government paper (P0x), and
            # 786/786R. Done here, before the row is added to sector_rows /
            # price_rows, so these never enter `prices`, `prices_adjusted`, or
            # the `sectors` table. The historical filter only caught bare
            # SYMBOL-MON and let every other variant through.
            if is_non_equity_symbol(symbol):
                logger.debug("Skipping non-equity symbol %s on %s", symbol, date_str)
                continue

            try:
                close = float(close_text)
            except ValueError:
                logger.debug("Non-numeric close '%s' for %s on %s -- skipping", close_text, symbol, date_str)
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
                open_ = float(open_text) if open_text else close
            except ValueError:
                open_ = close

            try:
                volume = int(float(vol_text)) if vol_text else 0
            except (ValueError, OverflowError):
                volume = 0

            sector_rows.append((symbol, current_sector))
            price_rows.append((symbol, date_str, high, low, close, volume, open_))

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
    """Build {symbol: (high, low, close)} for stale-data comparison.

    Values are coerced to float. prev_prices (passed in from
    get_latest_prices()) returns decimal.Decimal for every numeric column
    when sourced from Postgres, while a fresh scrape's p_rows always holds
    native float. Decimal(x) == float(x) is False even when x is
    numerically identical -- Python compares against the float's exact
    binary value, not its decimal string value -- so without this
    coercion, curr[sym] == prev[sym] fails for every symbol regardless of
    actual staleness, and _is_stale() silently always returns False on
    Postgres. Confirmed root cause of the 2026-07-10 incident: this is why
    the duplicate-data check never fired even though the freshly-scraped
    "07-10" data was a 100% match against the real prior day.
    """
    return {r[0]: (float(r[2]), float(r[3]), float(r[4])) for r in p_rows if len(r) >= 5}


def _is_stale(curr: dict, prev: dict, threshold: float = 0.90) -> bool:
    """Return True if >=threshold of common symbols have identical H/L/C -- market was closed."""
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
        logger.info("Scraping %s (%d/%d)...", d, idx, total)
        s_rows, p_rows, i_rows = scrape_date(d, session)

        if p_rows:
            curr_fp = _price_fingerprint(p_rows)
            if prev_fp is not None and _is_stale(curr_fp, prev_fp):
                logger.warning(
                    "Skipping %s -- PSX returned identical data to previous session "
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
