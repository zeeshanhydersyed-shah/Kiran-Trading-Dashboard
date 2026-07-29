"""
settlement_scraper.py — UIN-Wise Settlement Analysis
=====================================================
Source: https://markets.brecorder.com/clearance/uin-wise-settlement.html

API (confirmed 2026-06-04 — no auth, no browser required):
  GET  https://markets.brecorder.com/ajax/companies/
       → [{brcode, ksecode, fullname, smallname}, ...]   (591 companies)

  POST https://markets.brecorder.com/ajax/clearance_settlmnt/{ksecode}
       body: {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}
       → {0: {date, dt, ksecode, company, tradevolume, tradedvalue,
              settlmntvolume, settlmntvalue, percvolume, percvalue}, ...}

Design:
  - Direct HTTP — requests + concurrent.futures, no browser required
  - Initial scrape:     last 30 calendar days  (DB empty)
  - Incremental scrape: 1 day at a time        (normal daily run)
  - Gap handling:       backfills missing dates without duplicating
  - No-new-data:        returns message "Data is current through YYYY-MM-DD"

DB table: uin_settlement (date, symbol, sett_pct_volume, sett_pct_value)
Signal: sett_pct_value > 70% AND > own N-day rolling avg = accumulation
"""

import os
import re
import time
import logging
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as _date_cls, timedelta

import requests
import pandas as pd

try:
    from config import DB_PATH
except ImportError:
    DB_PATH = os.path.join(os.path.dirname(__file__), "psx_data.db")

logger = logging.getLogger(__name__)

# ── API constants ──────────────────────────────────────────────────────────────
BRECORDER_HOST  = "https://markets.brecorder.com/"
COMPANIES_URL   = BRECORDER_HOST + "ajax/companies/"
SETTLEMENT_URL  = BRECORDER_HOST + "ajax/clearance_settlmnt/{ksecode}"
_API_HEADERS    = {
    "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type":     "application/json",
    "Referer":          BRECORDER_HOST + "clearance/uin-wise-settlement.html",
    "Origin":           BRECORDER_HOST.rstrip("/"),
    "X-Requested-With": "XMLHttpRequest",
}

# ── Scrape config ──────────────────────────────────────────────────────────────
REFERENCE_SYMBOL    = "HBL"   # liquid stock used to probe available settlement dates
INITIAL_DAYS        = 30      # calendar days fetched on first-ever scrape
MAX_WORKERS         = 10      # concurrent API threads
REQUEST_TIMEOUT     = 20      # seconds per HTTP request
COMPANIES_CACHE_TTL = 86400   # seconds before company list is re-fetched (24 h)

# Module-level company list cache
_companies_cache: list | None = None
_companies_cache_ts: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════

@contextmanager
def _get_conn():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_settlement_table():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS uin_settlement (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                date             TEXT NOT NULL,
                symbol           TEXT NOT NULL,
                sett_pct_volume  REAL,
                sett_pct_value   REAL,
                UNIQUE(date, symbol)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_us_date   ON uin_settlement(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_us_symbol ON uin_settlement(symbol)")

        # ── Migration: add columns if the table was created by an older schema ──
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(uin_settlement)").fetchall()
        }
        if "sett_pct_volume" not in existing:
            conn.execute("ALTER TABLE uin_settlement ADD COLUMN sett_pct_volume REAL")
            logger.info("Migration: added sett_pct_volume column to uin_settlement")
        if "sett_pct_value" not in existing:
            conn.execute("ALTER TABLE uin_settlement ADD COLUMN sett_pct_value REAL")
            logger.info("Migration: added sett_pct_value column to uin_settlement")


def upsert_settlement(rows: list):
    """rows: (date, symbol, sett_pct_volume, sett_pct_value)"""
    if not rows:
        return
    with _get_conn() as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO uin_settlement
                (date, symbol, sett_pct_volume, sett_pct_value)
            VALUES (?, ?, ?, ?)
        """, rows)


def get_available_dates_settlement() -> list:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM uin_settlement ORDER BY date DESC"
        ).fetchall()
    return [r["date"] for r in rows]


def get_settlement_df(date_from=None, date_to=None, symbol=None) -> pd.DataFrame:
    conditions, params = [], []
    if date_from:
        conditions.append("date >= ?"); params.append(date_from)
    if date_to:
        conditions.append("date <= ?"); params.append(date_to)
    if symbol:
        conditions.append("symbol = ?"); params.append(symbol.upper())
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with _get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM uin_settlement {where} ORDER BY date DESC, symbol",
            params,
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    for col in ("sett_pct_volume", "sett_pct_value"):
        if col in df.columns:
            df[col] = df[col].round(2)
    return df


def get_rolling_summary(days: int = 10) -> pd.DataFrame:
    available = get_available_dates_settlement()
    if not available:
        return pd.DataFrame()
    cutoff = available[min(days - 1, len(available) - 1)]
    df = get_settlement_df(date_from=cutoff)
    if df.empty:
        return pd.DataFrame()

    latest_date = df["date"].max()
    latest = (
        df[df["date"] == latest_date][["symbol", "sett_pct_value", "sett_pct_volume", "date"]]
        .copy()
        .rename(columns={
            "sett_pct_value":  "latest_sett_pct_value",
            "sett_pct_volume": "latest_sett_pct_volume",
            "date":            "latest_date",
        })
    )
    avgs = (
        df.groupby("symbol")
        .agg(
            avg_sett_pct_value=("sett_pct_value", "mean"),
            avg_sett_pct_volume=("sett_pct_volume", "mean"),
            n_days=("date", "nunique"),
        )
        .round(2).reset_index()
    )
    merged = avgs.merge(latest, on="symbol", how="left")
    merged["flag"] = merged.apply(
        lambda r: "🔴 High Settlement"
        if pd.notna(r.get("latest_sett_pct_value"))
           and r["latest_sett_pct_value"] > 70
           and r["latest_sett_pct_value"] > r["avg_sett_pct_value"]
        else "",
        axis=1,
    )
    return merged.sort_values("latest_sett_pct_value", ascending=False).reset_index(drop=True)


def get_sector_settlement(days: int = 10) -> pd.DataFrame:
    available = get_available_dates_settlement()
    if not available:
        return pd.DataFrame()
    cutoff = available[min(days - 1, len(available) - 1)]
    with _get_conn() as conn:
        try:
            rows = conn.execute("""
                SELECT s.sector,
                       COUNT(DISTINCT u.symbol)                                AS symbol_count,
                       AVG(u.sett_pct_value)                                   AS avg_sett_pct_value,
                       MAX(u.sett_pct_value)                                   AS max_sett_pct_value,
                       SUM(CASE WHEN u.sett_pct_value > 70 THEN 1 ELSE 0 END) AS flagged_count
                FROM uin_settlement u
                JOIN sectors s ON s.symbol = u.symbol
                WHERE u.date >= ?
                GROUP BY s.sector
                ORDER BY avg_sett_pct_value DESC
            """, (cutoff,)).fetchall()
        except Exception:
            return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["avg_sett_pct_value"] = df["avg_sett_pct_value"].round(2)
    df["max_sett_pct_value"] = df["max_sett_pct_value"].round(2)
    return df.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _num(raw):
    if not raw:
        return None
    s = str(raw).strip().replace(",", "").replace("%", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if s in ("", "-", "--", "N/A", "n/a"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(raw: str):
    if not raw:
        return None
    raw = raw.strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return raw[:10]
    m = re.match(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", raw)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    try:
        return pd.to_datetime(raw, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def _is_futures(sym: str) -> bool:
    return bool(re.search(
        r"-(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d*$",
        sym.upper(),
    ))


# ══════════════════════════════════════════════════════════════════════════════
# API LAYER
# ══════════════════════════════════════════════════════════════════════════════

def _api_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_API_HEADERS)
    return s


def _get_companies() -> list:
    """
    Return list of ksecodes (PSX tickers).
    Cached in memory for COMPANIES_CACHE_TTL seconds to avoid repeated lookups.
    """
    global _companies_cache, _companies_cache_ts
    now = time.time()
    if _companies_cache is not None and (now - _companies_cache_ts) < COMPANIES_CACHE_TTL:
        return _companies_cache

    try:
        sess = _api_session()
        resp = sess.get(COMPANIES_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        codes = [
            c["ksecode"].strip().upper()
            for c in data
            if c.get("ksecode") and not _is_futures(c["ksecode"])
        ]
        _companies_cache = codes
        _companies_cache_ts = now
        logger.info("Company list loaded: %d symbols", len(codes))
        return codes
    except Exception as e:
        logger.error("Failed to fetch company list: %s", e)
        return _companies_cache or []   # return stale cache if available


def _fetch_one(ksecode: str, from_date: str, to_date: str,
               session: requests.Session) -> list:
    """
    Fetch settlement data for a single symbol over the given date range.
    Returns [(date, symbol, sett_pct_volume, sett_pct_value), ...]
    Empty list on any error or no data.
    """
    url = SETTLEMENT_URL.format(ksecode=ksecode)
    try:
        resp = session.post(
            url,
            json={"from": from_date, "to": to_date},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        records = list(data.values()) if isinstance(data, dict) else data
        rows = []
        for rec in records:
            date_str = _parse_date(rec.get("date", ""))
            if not date_str:
                continue
            sym = str(rec.get("ksecode") or ksecode).strip().upper()
            if _is_futures(sym):
                continue
            vol_pct = _num(rec.get("percvolume"))
            val_pct = _num(rec.get("percvalue"))
            if vol_pct is not None or val_pct is not None:
                rows.append((date_str, sym, vol_pct, val_pct))
        return rows
    except Exception as e:
        logger.debug("Error fetching %s: %s", ksecode, e)
        return []


def _fetch_all(from_date: str, to_date: str, progress_cb=None) -> list:
    """
    Fetch settlement data for all companies concurrently.

    Args:
        from_date:   YYYY-MM-DD start of range
        to_date:     YYYY-MM-DD end of range
        progress_cb: optional callable(done: int, total: int)

    Returns [(date, symbol, sett_pct_volume, sett_pct_value), ...]
    """
    symbols = _get_companies()
    if not symbols:
        logger.error("No companies available — cannot fetch settlement data.")
        return []

    all_rows = []
    session  = _api_session()
    total    = len(symbols)
    done     = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_one, sym, from_date, to_date, session): sym
            for sym in symbols
        }
        for fut in as_completed(futures):
            done += 1
            rows = fut.result()
            all_rows.extend(rows)
            if progress_cb:
                progress_cb(done, total)

    logger.info("Fetched %d rows for %s → %s", len(all_rows), from_date, to_date)
    return all_rows


def _probe_available_dates(lookback_days: int = 35) -> list:
    """
    Probe the API to discover which trading dates are currently available.
    Uses REFERENCE_SYMBOL over the last `lookback_days` calendar days.
    Returns a sorted list of YYYY-MM-DD strings.
    """
    to_date   = _date_cls.today().isoformat()
    from_date = (_date_cls.today() - timedelta(days=lookback_days)).isoformat()
    try:
        session = _api_session()
        rows = _fetch_one(REFERENCE_SYMBOL, from_date, to_date, session)
        dates = sorted({r[0] for r in rows})
        return dates
    except Exception as e:
        logger.error("Date probe failed: %s", e)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER — PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def scrape_settlement_page() -> list:
    """
    Fetch the latest available settlement date for all symbols.
    Probes the API to find the most recent trading date, then retrieves
    that single day across all companies.

    Returns: [(date, symbol, sett_pct_volume, sett_pct_value), ...]
    """
    api_dates = _probe_available_dates()
    if not api_dates:
        logger.warning("Could not determine latest settlement date from API.")
        return []
    target_date = api_dates[-1]
    logger.info("Fetching settlement data for date: %s", target_date)
    return _fetch_all(target_date, target_date)


def scrape_settlement_bulk(progress_bar=None, status_text=None) -> dict:
    """
    Smart entry point — determines the correct fetch strategy automatically.

    Strategy logic:
      initial     — DB is empty            → fetch last INITIAL_DAYS calendar days
      incremental — 1 new date available   → fetch that single date
      backfill    — multiple dates missing → fetch each missing date, one at a time
      current     — DB is already up-to-date → return no-new-data message

    Args:
        progress_bar: optional st.progress widget
        status_text:  optional st.empty widget for status messages

    Returns:
        {
          "date_scraped": str,    # last date fetched, or "—"
          "rows_saved":   int,    # total rows upserted
          "error":        str|None,
          "message":      str|None,  # set when data is already current
        }
    """
    def _status(msg: str):
        if status_text:
            status_text.text(msg)
        logger.info(msg)

    def _progress(pct: float):
        if progress_bar:
            progress_bar.progress(min(pct, 1.0))

    # ── Step 1: probe API to discover available trading dates ─────────────────
    _status("⏳ Checking available settlement dates…")
    _progress(0.05)
    api_dates = _probe_available_dates(lookback_days=35)

    if not api_dates:
        return {
            "date_scraped": "—",
            "rows_saved":   0,
            "error":        "Could not reach brecorder API or no data available.",
            "message":      None,
        }

    latest_api_date = api_dates[-1]
    db_dates        = set(get_available_dates_settlement())
    missing_dates   = sorted(set(api_dates) - db_dates)

    # ── Step 2: initial load (DB empty) ───────────────────────────────────────
    if not db_dates:
        from_date = (_date_cls.today() - timedelta(days=INITIAL_DAYS)).isoformat()
        to_date   = latest_api_date
        _status(f"⏳ Initial load — fetching last {INITIAL_DAYS} days ({from_date} → {to_date})…")

        def _cb_initial(done, total):
            _progress(0.10 + 0.85 * done / total)
            _status(f"⏳ Initial load — {done}/{total} symbols fetched…")

        all_rows = _fetch_all(from_date, to_date, progress_cb=_cb_initial)
        _progress(0.97)
        if all_rows:
            upsert_settlement(all_rows)
        _progress(1.0)

        dates_saved = sorted({r[0] for r in all_rows})
        n_dates     = len(dates_saved)
        if all_rows:
            _status(f"✅ Initial load complete — {n_dates} trading days saved.")
        return {
            "date_scraped": latest_api_date,
            "rows_saved":   len(all_rows),
            "error":        None if all_rows else "No data returned from API.",
            "message":      f"Initial load complete — {n_dates} trading days saved." if all_rows else None,
        }

    # ── Step 3: already current ───────────────────────────────────────────────
    if not missing_dates:
        msg = f"Data is current through {latest_api_date}."
        _status(f"✅ {msg}")
        _progress(1.0)
        return {
            "date_scraped": latest_api_date,
            "rows_saved":   0,
            "error":        None,
            "message":      msg,
        }

    # ── Step 4: incremental (1 new day) or backfill (multiple gaps) ───────────
    #   Fetch each missing date separately — one at a time — to honour the
    #   "1 day at a time" requirement for incremental runs and to ensure
    #   gaps are filled cleanly without fetching already-present dates.
    total_saved       = 0
    last_date_fetched = "—"
    n_missing         = len(missing_dates)

    for i, target_date in enumerate(missing_dates):
        _status(f"⏳ Fetching {target_date} ({i + 1}/{n_missing})…")

        # Build a scoped progress callback that maps this date's progress
        # into its own slice of the overall bar [0.05 … 0.97].
        _i, _n = i, n_missing
        def _cb(done, total, __i=_i, __n=_n):
            base = 0.05 + 0.92 * __i / __n
            span = 0.92 / __n
            _progress(base + span * done / total)

        rows = _fetch_all(target_date, target_date, progress_cb=_cb)

        if rows:
            upsert_settlement(rows)
            total_saved       += len(rows)
            last_date_fetched  = target_date
            logger.info("Saved %d rows for %s", len(rows), target_date)
        else:
            logger.warning("No data returned for %s — skipping.", target_date)

    _progress(1.0)

    if total_saved == 0:
        return {
            "date_scraped": last_date_fetched,
            "rows_saved":   0,
            "error":        "API returned no data for the missing dates.",
            "message":      None,
        }

    return {
        "date_scraped": last_date_fetched,
        "rows_saved":   total_saved,
        "error":        None,
        "message":      None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC
# ══════════════════════════════════════════════════════════════════════════════

def debug_scrape_settlement() -> dict:
    """
    API connectivity test — no data saved.
    Tests the brecorder API and returns a diagnostic dict compatible with
    the page_flows.py diagnostic display (same keys as the previous
    Playwright-based implementation).
    """
    info: dict = {
        "url":          BRECORDER_HOST + "clearance/uin-wise-settlement.html",
        "api_endpoint": SETTLEMENT_URL.format(ksecode=REFERENCE_SYMBOL),
    }

    to_date   = _date_cls.today().isoformat()
    from_date = (_date_cls.today() - timedelta(days=7)).isoformat()

    try:
        session = _api_session()

        # ── Test 1: company list ──────────────────────────────────────────────
        try:
            resp_co = session.get(COMPANIES_URL, timeout=REQUEST_TIMEOUT)
            info["company_list_status"] = resp_co.status_code
            if resp_co.status_code == 200:
                info["company_count"] = len(resp_co.json())
        except Exception as e:
            info["company_list_error"] = str(e)

        # ── Test 2: settlement data for reference symbol ──────────────────────
        resp = session.post(
            SETTLEMENT_URL.format(ksecode=REFERENCE_SYMBOL),
            json={"from": from_date, "to": to_date},
            timeout=REQUEST_TIMEOUT,
        )
        info["api_status_code"] = resp.status_code

        if resp.status_code != 200:
            info["error"] = "API returned HTTP " + str(resp.status_code)
            return info

        data    = resp.json()
        records = list(data.values()) if isinstance(data, dict) else list(data)

        info["table_found"]     = len(records) > 0
        info["table_row_count"] = len(records)
        info["table_headers"]   = [
            "date", "ksecode", "company",
            "tradevolume", "tradedvalue",
            "settlmntvolume", "settlmntvalue",
            "percvolume", "percvalue",
        ]

        if records:
            r0 = records[0]
            info["site_date"]      = r0.get("date", "")
            info["cfrom_after_js"] = r0.get("date", "")
            info["cto_after_js"]   = r0.get("date", "")
            info["sample_row"]     = [str(v) for v in r0.values()]

        if len(records) > 1:
            info["sample_row_2"] = [str(v) for v in records[1].values()]

        info["all_inputs"] = {
            "source":    "brecorder.com REST API (no browser required)",
            "endpoint":  SETTLEMENT_URL,
            "from":      from_date,
            "to":        to_date,
            "symbol":    REFERENCE_SYMBOL,
            "auth":      "none required",
        }

    except Exception as e:
        info["error"] = str(e)

    return info
