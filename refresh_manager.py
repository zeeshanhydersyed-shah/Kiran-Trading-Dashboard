#!/usr/bin/env python3
"""
Manage refresh operations and user messaging.

SOURCE-DATE INTEGRITY
─────────────────────
execute_refresh_with_tracking() now extracts the authoritative trading date
from the ksestocks.com source page BEFORE running any scrape.  All
user-facing messages reference that source date — never "today" or the
system clock.

Provides:
1. Execute refresh with source-date pre-check
2. Return user-facing messages that clearly state the source data date
3. Rate limiting (3-minute cool-down)
"""

import logging
from datetime import datetime, timedelta

from database import get_latest_stock_date, count_prices

logger = logging.getLogger(__name__)


class RefreshStatus:
    """Enum-like class for refresh status."""
    SUCCESS      = "success"
    NO_NEW_DATA  = "no_new_data"
    ERROR        = "error"
    THROTTLED    = "throttled"


class RefreshResult:
    """Result of a refresh operation."""

    def __init__(
        self,
        status: str,
        message: str,
        data_date: str | None = None,
        source_date: str | None = None,
    ):
        self.status      = status
        self.message     = message
        self.data_date   = data_date   # latest date now in DB
        self.source_date = source_date  # date extracted from ksestocks.com
        self.timestamp   = datetime.now()

    def to_dict(self):
        return {
            "status":      self.status,
            "message":     self.message,
            "data_date":   self.data_date,
            "source_date": self.source_date,
            "timestamp":   self.timestamp.isoformat(),
        }


def get_refresh_message(result: RefreshResult) -> tuple[str, str]:
    """
    Get display message and Streamlit message type for a RefreshResult.

    Returns: (message_text, message_type)
    message_type: "success" | "info" | "warning" | "error"

    Messages always reference the SOURCE date from ksestocks.com, never the
    system clock or "today".
    """
    src  = result.source_date or result.data_date or "unknown"
    data = result.data_date   or "unknown"

    if result.status == RefreshStatus.SUCCESS:
        return (
            f"✅ Data for {src} has been added\n"
            f"Source: ksestocks.com  |  DB latest: {data}",
            "success",
        )
    elif result.status == RefreshStatus.NO_NEW_DATA:
        return (
            f"Already have data for {src} — no action taken\n"
            f"ksestocks.com has not published a new trading session yet.\n"
            f"EOD data is typically available by 19:00 PKT.",
            "info",
        )
    elif result.status == RefreshStatus.THROTTLED:
        return (
            f"Please wait before refreshing again\n{result.message}",
            "warning",
        )
    else:  # ERROR
        return (result.message, "error")


def execute_refresh_with_tracking(cmd_update_func) -> RefreshResult:
    """
    Execute a refresh and track what changed.

    Steps:
    1. Extract the authoritative source date from ksestocks.com.
    2. Compare against the DB's latest date.
       - If source_date ≤ db_latest → NO_NEW_DATA (return immediately, no scrape).
    3. Run cmd_update_func() — which now also uses source-date extraction
       internally (double-safety).
    4. Confirm the new DB date matches the source date.

    The system clock is used only for logging/throttle timing — never to
    label data or decide what to scrape.
    """
    try:
        from scraper import get_source_date, build_session

        # ── Step 1: extract source date ───────────────────────────────────────
        session     = build_session()
        source_date = get_source_date(session)

        if source_date is None:
            return RefreshResult(
                status      = RefreshStatus.ERROR,
                message     = (
                    "Could not read the trading date from ksestocks.com.  "
                    "The site may be temporarily unavailable.  "
                    "No data was stored."
                ),
                data_date   = get_latest_stock_date(),
                source_date = None,
            )

        source_date_str = source_date.strftime("%Y-%m-%d")
        db_before       = get_latest_stock_date()

        logger.info(
            "execute_refresh: source=%s  db_before=%s",
            source_date_str, db_before,
        )

        # ── Step 2: pre-scrape check ──────────────────────────────────────────
        if db_before and db_before >= source_date_str:
            return RefreshResult(
                status      = RefreshStatus.NO_NEW_DATA,
                message     = f"ksestocks.com shows {source_date_str} — already in database.",
                data_date   = db_before,
                source_date = source_date_str,
            )

        # ── Step 3: run scrape ────────────────────────────────────────────────
        count_before = count_prices()
        cmd_update_func()
        count_after  = count_prices()
        db_after     = get_latest_stock_date()

        logger.info(
            "execute_refresh: db_after=%s  prices %d→%d",
            db_after, count_before, count_after,
        )

        # ── Step 4: confirm result ────────────────────────────────────────────
        if db_after and db_after >= source_date_str:
            return RefreshResult(
                status      = RefreshStatus.SUCCESS,
                message     = f"Data for {source_date_str} loaded successfully.",
                data_date   = db_after,
                source_date = source_date_str,
            )
        else:
            # Scrape ran but source date wasn't stored — possibly a holiday
            # that returned empty data, or an unexpected error.
            return RefreshResult(
                status      = RefreshStatus.NO_NEW_DATA,
                message     = (
                    f"Scrape completed but no data for {source_date_str} was stored.  "
                    f"This date may be a public holiday or the site returned empty data."
                ),
                data_date   = db_after,
                source_date = source_date_str,
            )

    except Exception as e:
        logger.exception("execute_refresh_with_tracking failed: %s", e)
        return RefreshResult(
            status    = RefreshStatus.ERROR,
            message   = f"Refresh failed: {str(e)}",
            data_date = get_latest_stock_date(),
        )


def check_refresh_throttle(session_state) -> RefreshResult | None:
    """
    Return a THROTTLED RefreshResult if the user refreshed less than 3 minutes
    ago, otherwise return None (OK to proceed).
    """
    last_refresh_time = session_state.get("last_refresh_time")
    if not last_refresh_time:
        return None

    min_wait          = timedelta(minutes=3)
    time_since        = datetime.now() - last_refresh_time

    if time_since < min_wait:
        secs_remaining = int((min_wait - time_since).total_seconds())
        minutes        = secs_remaining // 60
        secs           = secs_remaining % 60
        return RefreshResult(
            status    = RefreshStatus.THROTTLED,
            message   = f"Wait {minutes}m {secs}s before next refresh",
            data_date = get_latest_stock_date(),
        )

    return None


def record_refresh_time(session_state):
    """Record when a refresh was attempted (used for throttling)."""
    session_state.last_refresh_time = datetime.now()


def get_source_date_cached(session_state, max_age_seconds: int = 1800):
    """
    Return the latest source date from ksestocks.com, using a session-state
    cache to avoid a network call on every page render.

    Returns: (source_date_str | None, fetched_at: datetime | None)

    max_age_seconds: how old the cached value can be before re-fetching
                     (default 30 minutes).
    """
    cached_date    = session_state.get("_ksestocks_source_date")
    cached_at      = session_state.get("_ksestocks_source_date_fetched_at")
    cache_is_fresh = (
        cached_date is not None
        and cached_at is not None
        and (datetime.now() - cached_at).total_seconds() < max_age_seconds
    )

    if cache_is_fresh:
        return cached_date, cached_at

    now = datetime.now()
    try:
        from scraper import get_source_date, build_session
        session     = build_session()
        source_date = get_source_date(session)

        source_date_str = source_date.strftime("%Y-%m-%d") if source_date else None
        # Always stamp fetched_at so the caller knows "we tried" even on failure
        session_state["_ksestocks_source_date"]           = source_date_str
        session_state["_ksestocks_source_date_fetched_at"] = now
        return source_date_str, now

    except Exception as exc:
        logger.warning("get_source_date_cached: fetch attempt failed: %s", exc)
        # Stamp fetched_at = now so sidebar knows we tried (even if result is None)
        session_state["_ksestocks_source_date"]           = None
        session_state["_ksestocks_source_date_fetched_at"] = now
        return None, now
