"""
page_flows.py — FIPI / LIPI Institutional Flow Tracker
=======================================================
Completely self-contained page. Creates its own `market_flows` table.
Never touches any existing table (read-only cross-reference with trade_setups
for the Exit Watch signal).

Data source : khistocks.com FIPI / LIPI sector-wise pages
              (NCCPL settlement data, delayed)

Sections
--------
1. Data Collection  — scrape today or a historical range
2. Today's Snapshot — who bought / sold what sector
3. Trend Board      — rolling 5 / 10 / 20-day heatmap by sector
4. Decision Signals — Accumulation · Flow Reversal · Distribution · Exit Watch

Wire into dashboard.py
-----------------------
Add "📡 Flows" to the PAGES list and at the bottom of dashboard.py:

    elif cur == PAGES[16]:        # adjust index as needed
        from page_flows import render_flows_page
        render_flows_page()
"""

import os
import sqlite3
import re
import time
import logging
from contextlib import contextmanager
from datetime import date as _date_cls, timedelta

import numpy as np
import pandas as pd
import streamlit as st

try:
    from config import DB_PATH
except ImportError:
    DB_PATH = os.path.join(os.path.dirname(__file__), "psx_data.db")

logger = logging.getLogger(__name__)

# ── Source URLs ────────────────────────────────────────────────────────────────
FIPI_URL = "https://www.khistocks.com/clearance/fipi-sector-wise.html"
LIPI_URL = "https://www.khistocks.com/clearance/lipi-sector-wise.html"

# ── Sector mapping: khistocks/NCCPL label → PSX full sector name ──────────────
# Used to cross-reference flow sectors with the sectors + trade_setups tables.
# khistocks may use various spellings — all variants listed here.
FLOW_TO_PSX: dict[str, str | None] = {
    "CEMENT":                       "CEMENT",
    "FERTILIZER":                   "FERTILIZER",
    "FERTILISERS":                  "FERTILIZER",
    "FERTILIZERS":                  "FERTILIZER",
    "FOOD":                         "FOOD & PERSONAL CARE PRODUCTS",
    "FOOD & PERSONAL CARE":         "FOOD & PERSONAL CARE PRODUCTS",
    "FOOD AND PERSONAL CARE":       "FOOD & PERSONAL CARE PRODUCTS",
    "E&PS":                         "OIL & GAS EXPLORATION COMPANIES",
    "E&P":                          "OIL & GAS EXPLORATION COMPANIES",
    "E & PS":                       "OIL & GAS EXPLORATION COMPANIES",
    "OIL & GAS EXPLORATION":        "OIL & GAS EXPLORATION COMPANIES",
    "OMCS":                         "OIL & GAS MARKETING COMPANIES",
    "OMC":                          "OIL & GAS MARKETING COMPANIES",
    "OIL MARKETING":                "OIL & GAS MARKETING COMPANIES",
    "OIL & GAS MARKETING":          "OIL & GAS MARKETING COMPANIES",
    "IPPS":                         "POWER GENERATION & DISTRIBUTION",
    "IPP":                          "POWER GENERATION & DISTRIBUTION",
    "POWER":                        "POWER GENERATION & DISTRIBUTION",
    "POWER GEN":                    "POWER GENERATION & DISTRIBUTION",
    "BANKS":                        "COMMERCIAL BANKS",
    "BANK":                         "COMMERCIAL BANKS",
    "COMMERCIAL BANKS":             "COMMERCIAL BANKS",
    "TECH":                         "TECHNOLOGY & COMMUNICATION",
    "TECHNOLOGY":                   "TECHNOLOGY & COMMUNICATION",
    "TECHNOLOGY & COMMUNICATION":   "TECHNOLOGY & COMMUNICATION",
    "TEXTILE":                      "TEXTILE COMPOSITE",
    "TEXTILE COMPOSITE":            "TEXTILE COMPOSITE",
    "OTHERS":                       None,   # catch-all — no PSX equivalent
    "OTHER":                        None,
    "ALL OTHERS":                   None,
}

# ── Client classification ──────────────────────────────────────────────────────
# "smart money" = institutions with principal capital at risk
# "retail"      = funds acting on behalf of retail investors
SMART_MONEY_CLIENTS = {
    "FOREIGN CORPORATES", "OVERSEAS PAKISTANI",   # FIPI
    "BANKS/DFIS", "BANKS", "COMPANIES",            # LIPI
    "INSURANCE", "BROKER PROP.",
}
RETAIL_MONEY_CLIENTS = {
    "FOREIGN INDIVIDUAL",                          # FIPI
    "MUTUAL FUNDS", "INDIVIDUALS",                 # LIPI
}

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

@contextmanager
def _get_conn():
    """Open a local SQLite connection (always psx_data.db)."""
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


def init_flows_table():
    """Create market_flows table and indexes if they don't exist."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_flows (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT    NOT NULL,
                flow_type    TEXT    NOT NULL,   -- 'FIPI' or 'LIPI'
                client_type  TEXT    NOT NULL,   -- e.g. 'FOREIGN CORPORATES'
                sector       TEXT    NOT NULL,   -- e.g. 'CEMENT'
                market_type  TEXT    NOT NULL,   -- 'REGULAR', 'OFF-MARKET', etc.
                buy_volume   REAL,
                buy_value    REAL,               -- PKR value
                sell_volume  REAL,
                sell_value   REAL,
                net_volume   REAL,
                net_value    REAL,               -- net PKR (buy_value - sell_value)
                usd_net      REAL,               -- USD equivalent net
                UNIQUE(date, flow_type, client_type, sector, market_type)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mf_date   ON market_flows(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mf_sector ON market_flows(sector)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mf_type   ON market_flows(flow_type)")


def upsert_flows(rows: list[tuple]):
    """Upsert flow rows. Each tuple must match the INSERT column order below."""
    if not rows:
        return
    with _get_conn() as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO market_flows
                (date, flow_type, client_type, sector, market_type,
                 buy_volume, buy_value, sell_volume, sell_value,
                 net_volume, net_value, usd_net)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)


def get_available_dates() -> list[str]:
    """All dates with data, newest first."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM market_flows ORDER BY date DESC"
        ).fetchall()
    return [r["date"] for r in rows]


def get_flows_df(
    date_from: str = None,
    date_to:   str = None,
    flow_type: str = None,
    market_type: str = "REGULAR",
) -> pd.DataFrame:
    """Return market_flows as DataFrame, filtered by parameters."""
    conditions, params = [], []
    if date_from:
        conditions.append("date >= ?"); params.append(date_from)
    if date_to:
        conditions.append("date <= ?"); params.append(date_to)
    if flow_type:
        conditions.append("flow_type = ?"); params.append(flow_type)
    if market_type:
        conditions.append("market_type = ?"); params.append(market_type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with _get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM market_flows {where} ORDER BY date DESC, flow_type, sector",
            params,
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()


def _rolling_sector_pivot(days: int) -> pd.DataFrame:
    """
    For the last `days` dates, return a pivot:
    rows = sector, columns = client_type, values = sum(net_value).
    Also adds synthetic columns: FIPI_total, LIPI_total, total_net.
    """
    available = get_available_dates()
    if not available:
        return pd.DataFrame()

    cutoff = available[min(days - 1, len(available) - 1)]

    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT sector, flow_type, client_type,
                   SUM(net_value)  AS net_val,
                   SUM(usd_net)    AS usd_val
            FROM market_flows
            WHERE date >= ? AND market_type = 'REGULAR'
            GROUP BY sector, flow_type, client_type
        """, (cutoff,)).fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    pivot = df.pivot_table(
        index="sector", columns="client_type",
        values="net_val", aggfunc="sum"
    ).fillna(0)

    # Summary columns
    fipi_cols = [c for c in pivot.columns
                 if c in {"FOREIGN CORPORATES", "FOREIGN INDIVIDUAL", "OVERSEAS PAKISTANI"}]
    lipi_cols = [c for c in pivot.columns if c not in fipi_cols]

    pivot["FIPI_total"]  = pivot[fipi_cols].sum(axis=1)  if fipi_cols  else 0
    pivot["LIPI_total"]  = pivot[lipi_cols].sum(axis=1)  if lipi_cols  else 0
    pivot["total_net"]   = pivot["FIPI_total"] + pivot["LIPI_total"]
    return pivot


def get_active_trade_sectors() -> list[str]:
    """
    Return PSX sector names for all currently Active trades.
    READ-ONLY — never writes to trade_setups.
    """
    try:
        with _get_conn() as conn:
            rows = conn.execute("""
                SELECT DISTINCT s.sector
                FROM trade_setups ts
                JOIN sectors s ON s.symbol = ts.symbol
                WHERE ts.status = 'Active'
            """).fetchall()
        return [r["sector"] for r in rows]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# VALUE CLEANER
# ══════════════════════════════════════════════════════════════════════════════

def _num(raw: str) -> float | None:
    """Convert scraped text to float. Handles commas and accounting negatives."""
    if not raw:
        return None
    s = str(raw).strip().replace(",", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if s in ("", "-", "--", "N/A", "n/a"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(raw: str) -> str | None:
    """Return YYYY-MM-DD from various date formats, or None."""
    if not raw:
        return None
    raw = raw.strip()
    # Already ISO
    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return raw[:10]
    # DD-MM-YYYY  or  DD/MM/YYYY
    m = re.match(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", raw)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    # Month-name formats: 15-May-2026
    try:
        return pd.to_datetime(raw, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PLAYWRIGHT SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

def _scrape_flow_page(url: str, flow_type: str, start_date: str, end_date: str) -> list[tuple]:
    """
    Scrape FIPI or LIPI data for a date range.

    Confirmed page structure (screenshot 2026-05-27):
    ─────────────────────────────────────────────────
    • Two date inputs (text type, YYYY-MM-DD format) for date range
    • #sector, #ctype, #mtype select filters
    • name="fipitable_length" DataTables page-size control
    • #Add visible Submit button — triggers AJAX data load
    • Table has DataTables pagination (next/prev buttons)

    Date inputs are <input type="text"> styled with a datepicker library
    (NOT <input type="date">) — we set them via Playwright fill() + JS events.

    Returns list of 12-tuples ready for upsert_flows().
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.error("Playwright not installed.")
        return []

    results: list[tuple] = []
    col:     dict[str, int] = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            # ── Navigate ─────────────────────────────────────────────────────
            try:
                page.goto(url, timeout=35_000, wait_until="networkidle")
            except PWTimeout:
                try:
                    page.goto(url, timeout=35_000, wait_until="domcontentloaded")
                except PWTimeout:
                    logger.warning("Timeout loading %s", url)
                    browser.close()
                    return []

            time.sleep(3)

            # ── Set date range ────────────────────────────────────────────────
            # Date inputs are <input type="text"> with YYYY-MM-DD values.
            # Strategy: find all visible text inputs whose current value looks
            # like a date, then fill start → first, end → second.
            try:
                date_inputs = [
                    el for el in page.query_selector_all("input")
                    if re.match(r"\d{4}-\d{2}-\d{2}", el.input_value() or "")
                    and el.is_visible()
                ]
                if len(date_inputs) >= 1:
                    date_inputs[0].triple_click()
                    date_inputs[0].fill(start_date)
                    # Trigger datepicker library's change handler
                    page.evaluate(
                        "el => { el.dispatchEvent(new Event('change', {bubbles:true})); "
                        "        el.dispatchEvent(new Event('input',  {bubbles:true})); }",
                        date_inputs[0],
                    )
                if len(date_inputs) >= 2:
                    date_inputs[1].triple_click()
                    date_inputs[1].fill(end_date)
                    page.evaluate(
                        "el => { el.dispatchEvent(new Event('change', {bubbles:true})); "
                        "        el.dispatchEvent(new Event('input',  {bubbles:true})); }",
                        date_inputs[1],
                    )
            except Exception as e:
                logger.debug("Date input not set: %s", e)

            # ── Set filter dropdowns ──────────────────────────────────────────
            for sel_id, val in [("#sector", "all"), ("#ctype", "all"), ("#mtype", "all")]:
                try:
                    el = page.query_selector(sel_id)
                    if el:
                        el.select_option(value=val)
                except Exception:
                    pass

            # DataTables page-size → 100 rows per page.
            # FIPI table name = "fipitable_length", LIPI = "lipitable_length".
            # Try both, plus a generic fallback for any DataTables length select.
            for length_name in ["fipitable_length", "lipitable_length", "DataTables_Table_0_length"]:
                try:
                    length_sel = page.query_selector(f"select[name='{length_name}']")
                    if length_sel:
                        length_sel.select_option(value="100")
                        break
                except Exception:
                    pass
            else:
                # Generic fallback: any select whose options are 10/25/50/100
                try:
                    for sel_el in page.query_selector_all("select"):
                        opts = [o.get_attribute("value") for o in sel_el.query_selector_all("option")]
                        if set(opts) >= {"10", "25", "50", "100"}:
                            sel_el.select_option(value="100")
                            break
                except Exception:
                    pass

            # ── Click Submit (#Add) ───────────────────────────────────────────
            submitted = False
            for btn_sel in ["#Add", "button:has-text('Submit')", "input[type='submit']",
                            "button[type='submit']", "#btnSubmit"]:
                try:
                    btn = page.query_selector(btn_sel)
                    if btn and btn.is_visible():
                        btn.click()
                        submitted = True
                        break
                except Exception:
                    pass
            if not submitted:
                logger.warning("Submit button not found on %s", url)

            # ── Paginated extraction loop ─────────────────────────────────────
            # DataTables loads via AJAX; we loop through pages until the Next
            # button is disabled.
            page_num = 0
            while True:
                page_num += 1

                # Wait for table rows on first page; shorter wait on subsequent
                if page_num == 1:
                    try:
                        page.wait_for_selector("table tbody tr td", timeout=15_000)
                    except PWTimeout:
                        try:
                            page.wait_for_load_state("networkidle", timeout=10_000)
                        except PWTimeout:
                            pass
                        time.sleep(3)
                else:
                    time.sleep(1.5)

                # Find the DataTables table (FIPI=fipitable, LIPI=lipitable)
                table = (
                    page.query_selector("table#fipitable")
                    or page.query_selector("table#lipitable")
                    or page.query_selector("table.dataTable")
                    or page.query_selector("table")
                )
                if not table:
                    break

                # Build column map from header on first page only
                if page_num == 1:
                    all_rows = table.query_selector_all("tr")
                    if len(all_rows) < 2:
                        logger.warning(
                            "Table empty after Submit for %s %s→%s (page=%d)",
                            flow_type, start_date, end_date, page_num,
                        )
                        break

                    hdr_cells = all_rows[0].query_selector_all("th, td")
                    headers   = [c.inner_text().strip().upper() for c in hdr_cells]
                    logger.debug("%s headers: %s", flow_type, headers)

                    for i, h in enumerate(headers):
                        if "CLIENT" in h:                  col["client"] = i
                        elif "DATE" in h:                  col.setdefault("date", i)
                        elif "SECTOR" in h:                col["sector"] = i
                        elif "MARKET" in h:                col["market"] = i
                        elif "BUY" in h and "VOL" in h:    col["bvol"] = i
                        elif "BUY" in h and "VAL" in h:    col["bval"] = i
                        elif "BUY" in h:                   col.setdefault("bval", i)
                        elif "SELL" in h and "VOL" in h:   col["svol"] = i
                        elif "SELL" in h and "VAL" in h:   col["sval"] = i
                        elif "SELL" in h:                  col.setdefault("sval", i)
                        elif "NET" in h and "VOL" in h:    col["nvol"] = i
                        elif "NET" in h and "VAL" in h:    col["nval"] = i
                        elif "NET" in h:                   col.setdefault("nval", i)
                        elif "USD" in h:                   col["usd"] = i

                    # Positional fallback
                    if len(col) < 5:
                        col = {
                            "client": 1, "date": 2, "sector": 3, "market": 4,
                            "bvol": 5, "bval": 6, "svol": 7, "sval": 8,
                            "nvol": 9, "nval": 10, "usd": 11,
                        }

                # Extract tbody rows on this page
                tbody_rows = table.query_selector_all("tbody tr")
                new_on_page = 0
                for row in tbody_rows:
                    cells = row.query_selector_all("td")
                    if len(cells) < 5:
                        continue

                    def _c(key: str) -> str:
                        idx = col.get(key)
                        if idx is None or idx >= len(cells):
                            return ""
                        return cells[idx].inner_text().strip()

                    client_raw = _c("client").upper().strip()
                    sector_raw = _c("sector").upper().strip()
                    mkt_raw    = _c("market").upper().strip()
                    date_raw   = _c("date")

                    if not client_raw or not sector_raw:
                        continue
                    if "FUTURE" in mkt_raw:
                        continue

                    row_date = _parse_date(date_raw) or end_date

                    if "OFF" in mkt_raw:
                        mkt = "OFF-MARKET"
                    elif "REGULAR" in mkt_raw or mkt_raw in ("REG", ""):
                        mkt = "REGULAR"
                    else:
                        mkt = mkt_raw or "REGULAR"

                    results.append((
                        row_date, flow_type,
                        client_raw, sector_raw, mkt,
                        _num(_c("bvol")), _num(_c("bval")),
                        _num(_c("svol")), _num(_c("sval")),
                        _num(_c("nvol")), _num(_c("nval")),
                        _num(_c("usd")),
                    ))
                    new_on_page += 1

                # DataTables "Next" button — disabled on last page.
                # Try multiple selector patterns (varies by DataTables version).
                next_btn = (
                    page.query_selector(".dataTables_paginate .next:not(.disabled)")
                    or page.query_selector(".paginate_button.next:not(.disabled)")
                )
                if not next_btn:
                    break   # no enabled Next button → we're on the last page

                # Double-check via class attribute (belt-and-suspenders)
                btn_class = next_btn.get_attribute("class") or ""
                if "disabled" in btn_class.lower():
                    break
                if not next_btn.is_visible():
                    break

                next_btn.click()
                time.sleep(0.5)   # brief pause before waiting for next page rows

            browser.close()

    except Exception as e:
        logger.error("Unhandled error scraping %s %s→%s: %s", flow_type, start_date, end_date, e)

    return results


def debug_scrape_flow_page(url: str, flow_type: str) -> dict:
    """
    Diagnostic helper — navigates to the FIPI or LIPI page, waits for data,
    and returns metadata about what was found without saving anything.
    Use the "🔬 Test Connection" button in the UI to call this.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return {"error": "Playwright not installed"}

    info: dict = {"url": url, "flow_type": flow_type}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            try:
                page.goto(url, timeout=35_000, wait_until="networkidle")
            except PWTimeout:
                page.goto(url, timeout=35_000, wait_until="domcontentloaded")

            time.sleep(3)

            info["landed_url"] = page.url
            info["page_title"] = page.title()

            # Check for date inputs — includes text inputs with date-like values
            # (khistocks uses styled text inputs, NOT <input type="date">)
            all_inputs = page.query_selector_all("input")
            date_inputs = [
                el for el in all_inputs
                if el.get_attribute("type") in ("date", None, "text", "")
                and (
                    re.match(r"\d{4}-\d{2}-\d{2}", el.input_value() or "")
                    or "date" in (el.get_attribute("name") or "").lower()
                    or "date" in (el.get_attribute("id") or "").lower()
                )
            ]
            info["date_inputs"] = [
                {
                    "type":  el.get_attribute("type"),
                    "name":  el.get_attribute("name"),
                    "id":    el.get_attribute("id"),
                    "value": el.input_value() if el.is_visible() else "(hidden)",
                    "visible": el.is_visible(),
                }
                for el in date_inputs
            ]

            # Check for select elements
            selects = page.query_selector_all("select")
            info["selects"] = []
            for i, sel_el in enumerate(selects):
                opts = sel_el.query_selector_all("option")
                info["selects"].append({
                    "index": i,
                    "id": sel_el.get_attribute("id"),
                    "name": sel_el.get_attribute("name"),
                    "options": [
                        {"text": o.inner_text().strip(), "value": o.get_attribute("value")}
                        for o in opts
                    ]
                })

            # Check for buttons
            buttons = page.query_selector_all("button, input[type='submit']")
            info["buttons"] = [
                {"text": b.inner_text().strip()[:50], "type": b.get_attribute("type"),
                 "id": b.get_attribute("id"), "visible": b.is_visible()}
                for b in buttons
            ]

            # Table state
            try:
                page.wait_for_selector("table tbody tr td", timeout=8_000)
            except PWTimeout:
                pass

            table = page.query_selector("#table_data table") or page.query_selector("table")
            if table:
                rows = table.query_selector_all("tr")
                info["table_found"] = True
                info["table_row_count"] = len(rows)
                if rows:
                    hdr_cells = rows[0].query_selector_all("th, td")
                    info["table_headers"] = [c.inner_text().strip() for c in hdr_cells]
                if len(rows) > 1:
                    sample_cells = rows[1].query_selector_all("td")
                    info["sample_row"] = [c.inner_text().strip() for c in sample_cells]
            else:
                info["table_found"] = False

            browser.close()

    except Exception as e:
        info["error"] = str(e)

    return info


def scrape_bulk(
    start_date: str,
    end_date:   str,
    progress_bar,
    status_text,
    targets: list[tuple[str, str]] | None = None,
) -> dict:
    """
    Scrape FIPI and/or LIPI for [start_date, end_date].

    targets — list of (flow_type, url) pairs to scrape.
              Defaults to both FIPI + LIPI if not specified.

    DB UNIQUE constraint on (date, flow_type, client_type, sector, market_type)
    means re-scraping an existing date is safe — duplicates are silently replaced.
    """
    if targets is None:
        targets = [("FIPI", FIPI_URL), ("LIPI", LIPI_URL)]

    rows_saved = 0
    failed     = 0
    n          = len(targets)

    for i, (flow_type, url) in enumerate(targets):
        progress_bar.progress(i / n)
        status_text.text(f"⏳ Scraping {flow_type} ({start_date} → {end_date})…")

        rows = _scrape_flow_page(url, flow_type, start_date, end_date)
        if rows:
            upsert_flows(rows)
            rows_saved += len(rows)
        else:
            failed += 1

        time.sleep(1.0)

    progress_bar.progress(1.0)

    return {
        "dates_attempted": f"{start_date} → {end_date}",
        "rows_saved":       rows_saved,
        "failed":           failed,
    }


# ══════════════════════════════════════════════════════════════════════════════
# DECISION SIGNALS
# ══════════════════════════════════════════════════════════════════════════════

def compute_signals(roll10: pd.DataFrame, roll5: pd.DataFrame, roll20: pd.DataFrame) -> list[dict]:
    """
    Broad observation signals from rolling flow pivots.
    All logic is directional (sign of net) — no hard value thresholds
    so it works regardless of whether the stored unit is PKR or USD.

    Signal tiers:
      strong   — clear institutional conviction (both FIPI+LIPI agree)
      positive — one-sided buying hint, worth watching
      negative — selling pressure detected
      warning  — active trade at risk
      neutral  — mixed / inconclusive but notable

    Returns list of dicts: {type, sector, detail, severity, tier}
    """
    if roll10.empty:
        return []

    signals = []

    # Reverse map: PSX sector name → flow sector label
    psx_to_flow = {}
    for flow_lbl, psx_name in FLOW_TO_PSX.items():
        if psx_name and psx_name not in psx_to_flow:
            psx_to_flow[psx_name] = flow_lbl

    active_psx_sectors  = get_active_trade_sectors()
    active_flow_sectors = {psx_to_flow.get(s, s.upper()) for s in active_psx_sectors}

    def _v(v):
        """Compact signed number — unit-agnostic label."""
        sign = "+" if v >= 0 else ""
        if abs(v) >= 1_000_000:
            return f"{sign}{v/1_000_000:.1f}M"
        if abs(v) >= 1_000:
            return f"{sign}{v/1_000:.0f}K"
        return f"{sign}{v:.1f}"

    for sector in roll10.index:
        fipi_10   = float(roll10.loc[sector].get("FIPI_total", 0) or 0)
        lipi_10   = float(roll10.loc[sector].get("LIPI_total", 0) or 0)
        total_10  = float(roll10.loc[sector].get("total_net",  0) or 0)
        companies_10 = float(roll10.loc[sector].get("COMPANIES", 0) or 0)
        mf_10     = float(roll10.loc[sector].get("MUTUAL FUNDS", 0) or 0)

        fipi_5 = lipi_5 = total_5 = 0.0
        if not roll5.empty and sector in roll5.index:
            fipi_5  = float(roll5.loc[sector].get("FIPI_total", 0) or 0)
            lipi_5  = float(roll5.loc[sector].get("LIPI_total", 0) or 0)
            total_5 = float(roll5.loc[sector].get("total_net",  0) or 0)

        fipi_20 = total_20 = 0.0
        if not roll20.empty and sector in roll20.index:
            fipi_20  = float(roll20.loc[sector].get("FIPI_total", 0) or 0)
            total_20 = float(roll20.loc[sector].get("total_net",  0) or 0)

        # ── STRONG BUY: both FIPI and LIPI net positive (10d) ─────────────
        if fipi_10 > 0 and lipi_10 > 0 and total_10 > 0:
            signals.append({
                "type": "🟢🟢 Strong Buy Interest",
                "sector": sector,
                "detail": (
                    f"FIPI 10d: {_v(fipi_10)} · LIPI 10d: {_v(lipi_10)}\n"
                    f"Foreign AND local institutions both net buyers — broad conviction."
                ),
                "severity": "strong", "tier": 1,
            })

        # ── ACCUMULATION: foreigners selling but local companies buying ───
        elif fipi_10 < 0 and companies_10 > 0:
            signals.append({
                "type": "🟢 Accumulation",
                "sector": sector,
                "detail": (
                    f"FIPI 10d: {_v(fipi_10)} · Local Companies 10d: {_v(companies_10)}\n"
                    f"Foreigners selling, informed local capital absorbing — classic accumulation."
                ),
                "severity": "positive", "tier": 2,
            })

        # ── FLOW REVERSAL: 20d was negative but 5d has turned positive ───
        elif total_20 < 0 and total_5 > 0:
            signals.append({
                "type": "⚡ Flow Reversal",
                "sector": sector,
                "detail": (
                    f"20d net: {_v(total_20)} · 5d net: {_v(total_5)}\n"
                    f"Sustained outflow is turning — early buying hint, watch for follow-through."
                ),
                "severity": "positive", "tier": 2,
            })

        # ── FIPI BUYING ALONE (LIPI flat/negative) ────────────────────────
        elif fipi_10 > 0 and lipi_10 <= 0:
            signals.append({
                "type": "🔵 Foreign Buying",
                "sector": sector,
                "detail": (
                    f"FIPI 10d: {_v(fipi_10)} · LIPI 10d: {_v(lipi_10)}\n"
                    f"Foreigners net buyers, locals not following yet — watch for confirmation."
                ),
                "severity": "positive", "tier": 3,
            })

        # ── LOCAL BUYING ALONE (FIPI flat/negative) ───────────────────────
        elif lipi_10 > 0 and companies_10 > 0 and fipi_10 <= 0:
            signals.append({
                "type": "🟡 Local Accumulation",
                "sector": sector,
                "detail": (
                    f"LIPI 10d: {_v(lipi_10)} · FIPI 10d: {_v(fipi_10)}\n"
                    f"Local companies buying while foreigners stay out — less conviction but worth noting."
                ),
                "severity": "neutral", "tier": 3,
            })

        # ── MUTUAL FUND BUYING (retail-side positive signal) ─────────────
        elif mf_10 > 0 and total_10 > 0 and fipi_10 > 0:
            signals.append({
                "type": "🟡 Broad Participation",
                "sector": sector,
                "detail": (
                    f"FIPI 10d: {_v(fipi_10)} · Mutual Funds 10d: {_v(mf_10)}\n"
                    f"Both institutional and fund flows positive — broad demand."
                ),
                "severity": "neutral", "tier": 3,
            })

        # ── DISTRIBUTION: both FIPI and LIPI selling ─────────────────────
        elif total_10 < 0 and fipi_10 < 0 and lipi_10 < 0:
            signals.append({
                "type": "🔴 Distribution",
                "sector": sector,
                "detail": (
                    f"FIPI 10d: {_v(fipi_10)} · LIPI 10d: {_v(lipi_10)}\n"
                    f"Both foreign and local institutions net sellers — broad exit."
                ),
                "severity": "negative", "tier": 4,
            })

        # ── FOREIGN SELLING (LIPI holding) ────────────────────────────────
        elif fipi_10 < 0 and lipi_10 >= 0:
            signals.append({
                "type": "🟠 Foreign Outflow",
                "sector": sector,
                "detail": (
                    f"FIPI 10d: {_v(fipi_10)} · LIPI 10d: {_v(lipi_10)}\n"
                    f"Foreigners reducing exposure, locals absorbing. Monitor closely."
                ),
                "severity": "neutral", "tier": 4,
            })

    # ── Sector rotation: biggest mover in each direction (5d) ────────────
    if not roll5.empty and "total_net" in roll5.columns:
        sorted_sectors = roll5["total_net"].sort_values()
        if len(sorted_sectors) >= 2:
            top_buy    = sorted_sectors.idxmax()
            top_sell   = sorted_sectors.idxmin()
            buy_val    = sorted_sectors.max()
            sell_val   = sorted_sectors.min()
            if buy_val > 0:
                signals.append({
                    "type": "📊 Top Inflow (5d)",
                    "sector": top_buy,
                    "detail": f"Strongest 5d net inflow: {_v(buy_val)}. Highest institutional interest this week.",
                    "severity": "positive", "tier": 2,
                })
            if sell_val < 0:
                signals.append({
                    "type": "📊 Top Outflow (5d)",
                    "sector": top_sell,
                    "detail": f"Largest 5d net outflow: {_v(sell_val)}. Most active selling this week.",
                    "severity": "negative", "tier": 4,
                })

    # ── Exit Watch: active trade sectors with 5d selling ─────────────────
    for sector in active_flow_sectors:
        if not roll5.empty and sector in roll5.index:
            total_5 = float(roll5.loc[sector].get("total_net", 0) or 0)
            if total_5 < 0:
                signals.append({
                    "type": "⚠️ Exit Watch",
                    "sector": sector,
                    "detail": (
                        f"Active trade in this sector. "
                        f"5d institutional net: {_v(total_5)}\n"
                        f"Institutions selling into your position — review your stop."
                    ),
                    "severity": "warning", "tier": 0,
                })

    # Sort: warnings first, then strong, then by tier
    tier_order = {"warning": -1, "strong": 0, "positive": 1, "neutral": 2, "negative": 3}
    signals.sort(key=lambda s: (tier_order.get(s["severity"], 5), s.get("tier", 5)))

    return signals


# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT PAGE RENDERER
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# INTELLIGENCE ENGINE — helpers (called by _render_intelligence_section)
# ══════════════════════════════════════════════════════════════════════════════

_FLOW_SECTOR_MAP_INTEL = {
    "CEMENT":           "CEMENT",
    "COMM. BANKS":      "COMMERCIAL BANKS",
    "FERTILIZER":       "FERTILIZER",
    "FOOD & PERSON.":   "FOOD & PERSONAL CARE PRODUCTS",
    "OIL & GAS EXP.":   "OIL & GAS EXPLORATION COMPANIES",
    "OIL & GAS MKTG.":  "OIL & GAS MARKETING COMPANIES",
    "POWER GEN.":       "POWER GENERATION & DISTRIBUTION",
    "TECH. & COMM.":    "TECHNOLOGY & COMMUNICATION",
    "TEXTILE COMP.":    "TEXTILE COMPOSITE",
}

_SMART_CLIENTS_INTEL = {
    "FOREIGN CORPORATES", "OVERSEAS PAKISTANI",
    "BANKS / DFI", "COMPANIES", "INSURANCE COMPANIES", "BROKER PROPRIETARY TRADING",
}

_INTEL_LOG_PATH = os.path.join(os.path.dirname(__file__), "sector_flows_log.csv")


@st.cache_data(ttl=3600, show_spinner=False)
def _intel_load_flows_agg() -> pd.DataFrame:
    """Load + aggregate raw flows into (date, sector) frame with buy_ratio, rolling metrics."""
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT date, sector, flow_type, client_type,
                   buy_volume, sell_volume, net_volume, buy_value, sell_value
            FROM market_flows
            WHERE sector NOT IN ('ALL OTHER SECTORS','DEBT MARKET')
              AND market_type = 'REGULAR'
            ORDER BY date, sector
        """).fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df["is_smart"] = df["client_type"].isin(_SMART_CLIENTS_INTEL)
    df["abs_buy"]  = df["buy_volume"].clip(lower=0)
    df["abs_sell"] = df["sell_volume"].abs()

    grp = df.groupby(["date", "sector"])
    agg = grp.agg(
        total_buy_vol  =("abs_buy",    "sum"),
        total_sell_vol =("abs_sell",   "sum"),
        total_net_vol  =("net_volume", "sum"),
    ).reset_index()

    smart = (
        df[df["is_smart"]]
        .groupby(["date", "sector"])
        .agg(smart_buy_vol=("abs_buy", "sum"), smart_sell_vol=("abs_sell", "sum"))
        .reset_index()
    )
    agg = agg.merge(smart, on=["date", "sector"], how="left").fillna(0)

    act = agg["total_buy_vol"] + agg["total_sell_vol"]
    agg["buy_ratio"] = np.where(act > 0, agg["total_buy_vol"] / act, np.nan)

    smart_act = agg["smart_buy_vol"] + agg["smart_sell_vol"]
    agg["smart_buy_ratio"] = np.where(smart_act > 0, agg["smart_buy_vol"] / smart_act, np.nan)

    agg = agg.sort_values(["sector", "date"])

    agg["buy_ratio_3d_avg"] = (
        agg.groupby("sector")["buy_ratio"]
        .transform(lambda x: x.rolling(3, min_periods=1).mean())
    )
    agg["buy_ratio_5d_avg"] = (
        agg.groupby("sector")["buy_ratio"]
        .transform(lambda x: x.rolling(5, min_periods=1).mean())
    )

    def _consec(series, thr=0.55):
        result, count = [], 0
        for v in series:
            count = (count + 1) if (pd.notna(v) and v > thr) else 0
            result.append(count)
        return result

    consec_all = []
    for _, grp2 in agg.groupby("sector"):
        consec_all.extend(_consec(grp2["buy_ratio"].values))
    agg["consec_buy_days"] = consec_all

    agg["vol_zscore"] = (
        agg.groupby("sector")["total_buy_vol"]
        .transform(lambda x: (x - x.rolling(20, min_periods=5).mean())
                              / (x.rolling(20, min_periods=5).std() + 1e-9))
    )

    agg["psx_sector"] = agg["sector"].map(_FLOW_SECTOR_MAP_INTEL)
    return agg.reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def _intel_load_prices() -> pd.DataFrame:
    """Sector median close per day for the tracked sectors (Jan 2026+)."""
    psx_sectors = list(_FLOW_SECTOR_MAP_INTEL.values())
    placeholders = ",".join("?" * len(psx_sectors))
    with _get_conn() as conn:
        rows = conn.execute(f"""
            SELECT p.date, s.sector, AVG(p.close) AS close
            FROM prices p
            JOIN sectors s ON p.symbol = s.symbol
            WHERE s.sector IN ({placeholders})
              AND p.date >= '2026-01-01'
            GROUP BY p.date, s.sector
            ORDER BY s.sector, p.date
        """, psx_sectors).fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df["ret_1d"] = df.groupby("sector")["close"].pct_change()
    return df


def _intel_build_fwd_returns(agg: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Attach fwd returns to the agg frame for pattern analysis."""
    sp = prices.rename(columns={"sector": "psx_sector"}).sort_values(["psx_sector", "date"])
    for lag in [5, 10, 20]:
        sp[f"ret_fwd_{lag}d"] = (
            sp.groupby("psx_sector")["close"]
            .transform(lambda x: x.shift(-lag) / x - 1)
        )
    sp["ret_prior_5d"] = (
        sp.groupby("psx_sector")["close"]
        .transform(lambda x: x / x.shift(5) - 1)
    )
    return agg.merge(
        sp[["date", "psx_sector", "ret_prior_5d",
            "ret_fwd_5d", "ret_fwd_10d", "ret_fwd_20d"]],
        on=["date", "psx_sector"], how="left",
    )


def _intel_pattern_stats(df: pd.DataFrame, mask: pd.Series, horizon: str = "ret_fwd_5d") -> dict:
    try:
        from scipy import stats as _stats
        sub = df[mask & df[horizon].notna()][horizon]
        if len(sub) < 5:
            return {"n": len(sub), "win_rate": None, "avg_ret": None, "p": None}
        wr  = float((sub > 0).mean())
        avg = float(sub.mean() * 100)
        _, p = _stats.ttest_1samp(sub, 0)
        return {"n": len(sub), "win_rate": wr, "avg_ret": round(avg, 2), "p": round(float(p), 4)}
    except Exception:
        return {"n": 0, "win_rate": None, "avg_ret": None, "p": None}


def _intel_run_patterns(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    df["buy_ratio_lag3"] = df.groupby("sector")["buy_ratio"].shift(3)

    patterns = [
        {
            "name": "SUSTAINED_ACCUMULATION",
            "label": "Sustained Accumulation",
            "desc": "3+ consecutive days buy_ratio > 55%",
            "mask": df["consec_buy_days"] >= 3,
        },
        {
            "name": "ACCUMULATION_DIVERGENCE",
            "label": "Accumulation Divergence",
            "desc": "3d avg buy_ratio > 62% + sector flat/down prior 5d",
            "mask": (df["buy_ratio_3d_avg"] > 0.62) & (df["ret_prior_5d"].fillna(0) < 0.02),
        },
        {
            "name": "FLOW_MOMENTUM_TRANSITION",
            "label": "Flow Momentum Transition",
            "desc": "Buy ratio flipped <45% → >60% in 3 days",
            "mask": (df["buy_ratio"] > 0.60) & (df["buy_ratio_lag3"].fillna(1) < 0.45),
        },
        {
            "name": "VOLUME_SPIKE_BUYING",
            "label": "Volume Spike + Buying",
            "desc": "Buy vol z-score > 1.5 AND buy_ratio > 60%",
            "mask": (df["vol_zscore"] > 1.5) & (df["buy_ratio"] > 0.60),
        },
        {
            "name": "DISTRIBUTION",
            "label": "Distribution Warning",
            "desc": "3d avg buy_ratio < 40% (persistent selling)",
            "mask": df["buy_ratio_3d_avg"] < 0.40,
        },
    ]

    results = []
    for p in patterns:
        s5  = _intel_pattern_stats(df, p["mask"], "ret_fwd_5d")
        s10 = _intel_pattern_stats(df, p["mask"], "ret_fwd_10d")
        results.append({**p, "stats_5d": s5, "stats_10d": s10})

    return results


def _intel_correlations(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sector, grp in df.dropna(subset=["buy_ratio", "ret_fwd_5d"]).groupby("sector"):
        grp = grp.sort_values("date")
        full = grp["buy_ratio"].corr(grp["ret_fwd_5d"])
        last30 = grp.tail(30)
        c30 = last30["buy_ratio"].corr(last30["ret_fwd_5d"]) if len(last30) >= 8 else None
        rows.append({
            "sector": sector,
            "n": len(grp),
            "corr_full": round(float(full), 3) if pd.notna(full) else None,
            "corr_30d":  round(float(c30),  3) if c30 and pd.notna(c30) else None,
        })
    return pd.DataFrame(rows).sort_values("corr_full", key=lambda x: x.abs(), ascending=False)


def _intel_generate_signals(agg: pd.DataFrame, prices: pd.DataFrame) -> list[dict]:
    """Generate today's actionable signals and auto-save to log CSV."""
    latest = agg["date"].max()
    today_agg = agg[agg["date"] == latest]
    sp = prices.rename(columns={"sector": "psx_sector"}).sort_values(["psx_sector", "date"])

    def _sector_ret(psx_sec, days):
        s = sp[sp["psx_sector"] == psx_sec]
        if len(s) < days + 1:
            return None
        return round((s["close"].iloc[-1] / s["close"].iloc[-1 - days] - 1) * 100, 2)

    signals = []
    for _, row in today_agg.iterrows():
        r = row.to_dict()
        psx = r.get("psx_sector")
        if not psx:
            continue
        ret5 = _sector_ret(psx, 5) if psx else None

        checks = [
            ("SUSTAINED_ACCUMULATION",   r.get("consec_buy_days", 0) >= 3, "🟢 BUY BIAS",  "3+ day buy streak"),
            ("ACCUMULATION_DIVERGENCE",  r.get("buy_ratio_3d_avg", 0) > 0.62 and (ret5 or 0) < 2, "🟢 BUY BIAS", "Strong buying into flat sector"),
            ("VOLUME_SPIKE_BUYING",      r.get("vol_zscore", 0) > 1.5 and r.get("buy_ratio", 0) > 0.60, "🟢 BUY BIAS", "Volume surge + buying"),
            ("DISTRIBUTION_WARNING",     r.get("buy_ratio_3d_avg", 1) < 0.40, "🔴 AVOID",   "Persistent selling pressure"),
        ]
        for sig_name, cond, action, trigger in checks:
            if cond:
                strength = "STRONG" if (
                    r.get("consec_buy_days", 0) >= 5 or
                    r.get("buy_ratio", 0) > 0.70 or
                    r.get("buy_ratio_3d_avg", 1) < 0.35
                ) else "MODERATE"
                signals.append({
                    "date":            latest.date().isoformat(),
                    "sector":          r["sector"],
                    "signal_type":     sig_name,
                    "action":          action,
                    "strength":        strength,
                    "trigger":         trigger,
                    "buy_ratio":       round(r.get("buy_ratio", 0), 3),
                    "buy_ratio_3d":    round(r.get("buy_ratio_3d_avg", 0), 3),
                    "consec_buy_days": r.get("consec_buy_days", 0),
                    "vol_zscore":      round(r.get("vol_zscore", 0), 2),
                    "ret_5d_pct":      ret5,
                    "outcome":         "PENDING",
                    "fwd_5d_actual":   None,
                })

    # Auto-save new signals to CSV journal
    if signals:
        _intel_save_signals(signals)

    return signals


def _intel_save_signals(signals: list[dict]):
    """Upsert signals into sector_flows_log.csv."""
    new_df = pd.DataFrame(signals)
    if os.path.exists(_INTEL_LOG_PATH):
        existing = pd.read_csv(_INTEL_LOG_PATH)
        keys = set(zip(existing["date"].astype(str), existing["sector"], existing["signal_type"]))
        to_add = new_df[~new_df.apply(
            lambda r: (r["date"], r["sector"], r["signal_type"]) in keys, axis=1
        )]
        if not to_add.empty:
            combined = pd.concat([existing, to_add], ignore_index=True)
            combined.to_csv(_INTEL_LOG_PATH, index=False)
    else:
        new_df.to_csv(_INTEL_LOG_PATH, index=False)


def _intel_validate_signals(agg: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Fill in fwd_5d_actual for matured PENDING signals and mark WIN/LOSS."""
    if not os.path.exists(_INTEL_LOG_PATH):
        return pd.DataFrame()

    journal = pd.read_csv(_INTEL_LOG_PATH)
    if journal.empty:
        return journal

    sp = prices.rename(columns={"sector": "psx_sector"}).sort_values(["psx_sector", "date"])
    today = pd.Timestamp.today()
    changed = False

    for idx, row in journal.iterrows():
        if str(row.get("outcome", "")) != "PENDING":
            continue
        try:
            sig_date = pd.to_datetime(row["date"])
        except Exception:
            continue
        if (today - sig_date).days < 5:
            continue
        if pd.notna(row.get("fwd_5d_actual")):
            continue

        psx_sec = agg[agg["sector"] == row["sector"]]["psx_sector"].dropna()
        if psx_sec.empty:
            continue
        psx_sec = psx_sec.iloc[0]
        s = sp[sp["psx_sector"] == psx_sec].sort_values("date")
        base = s[s["date"] <= sig_date]
        fwd  = s[s["date"] >  sig_date]
        if base.empty or len(fwd) < 5:
            continue

        ret5 = round((fwd["close"].iloc[4] / base["close"].iloc[-1] - 1) * 100, 2)
        journal.at[idx, "fwd_5d_actual"] = ret5
        if row["signal_type"] == "DISTRIBUTION_WARNING":
            outcome = "WIN" if ret5 < -1 else ("LOSS" if ret5 > 1 else "BREAKEVEN")
        else:
            outcome = "WIN" if ret5 > 1 else ("LOSS" if ret5 < -1 else "BREAKEVEN")
        journal.at[idx, "outcome"] = outcome
        changed = True

    if changed:
        journal.to_csv(_INTEL_LOG_PATH, index=False)

    return journal


def _stat_badge(s: dict) -> str:
    """Return a short HTML badge string for pattern stats."""
    if not s or s["n"] < 5:
        return f"<span style='color:#6b7280'>n={s['n'] if s else 0} — building data</span>"
    sig_color = "#15803d" if (s["win_rate"] or 0) >= 0.65 else "#92400e"
    sig_label = "✅ Significant" if (
        (s["win_rate"] or 0) >= 0.65 and s["n"] >= 10 and (s["p"] or 1) < 0.05
    ) else "⏳ Building"
    return (
        f"n={s['n']} &nbsp;·&nbsp; "
        f"win <b style='color:{sig_color}'>{int((s['win_rate'] or 0)*100)}%</b> &nbsp;·&nbsp; "
        f"avg {s['avg_ret']:+.1f}% &nbsp;·&nbsp; "
        f"p={s['p']} &nbsp; <span style='color:{sig_color}'>{sig_label}</span>"
    )


def _render_intelligence_section(available: list, n_dates: int):
    """Section 5 — renders inside render_flows_page()."""
    st.markdown("#### 🧠 Intelligence Engine")
    st.caption(
        "Correlates FIPI/LIPI flows with subsequent price performance. "
        "Hunts for statistically validated patterns. Confidence builds over 6–8 weeks. "
        "Signals are auto-saved to `sector_flows_log.csv` for validation."
    )

    if n_dates < 3:
        st.info("Need at least 3 days of flows data. Keep scraping daily.")
        return

    with st.spinner("Running intelligence engine…"):
        agg    = _intel_load_flows_agg()
        prices = _intel_load_prices()

    if agg.empty or prices.empty:
        st.warning("No data to analyse yet.")
        return

    # Validate past signals silently
    journal = _intel_validate_signals(agg, prices)

    tab_snap, tab_patterns, tab_corr, tab_journal = st.tabs([
        "📊 Sector Snapshot", "🔬 Pattern Analysis", "📈 Correlations", "📓 Signal Journal"
    ])

    # ── TAB 1: SECTOR SNAPSHOT ──────────────────────────────────────────────
    with tab_snap:
        st.caption("Latest day's flow metrics per sector + today's actionable signals.")

        latest  = agg["date"].max()
        today_agg = agg[agg["date"] == latest].copy()

        sp = prices.rename(columns={"sector": "psx_sector"}).sort_values(["psx_sector", "date"])

        def _ret(psx_sec, days):
            s = sp[sp["psx_sector"] == psx_sec]
            if len(s) < days + 1:
                return None
            return round((s["close"].iloc[-1] / s["close"].iloc[-1 - days] - 1) * 100, 2)

        rows_snap = []
        for _, r in today_agg.iterrows():
            psx = r.get("psx_sector")
            rows_snap.append({
                "Sector":       r["sector"],
                "BuyRatio":     round(r.get("buy_ratio", 0) * 100, 1) if pd.notna(r.get("buy_ratio")) else None,
                "SmartBuyR":    round(r.get("smart_buy_ratio", 0) * 100, 1) if pd.notna(r.get("smart_buy_ratio")) else None,
                "3d Avg":       round(r.get("buy_ratio_3d_avg", 0) * 100, 1) if pd.notna(r.get("buy_ratio_3d_avg")) else None,
                "Streak":       int(r.get("consec_buy_days", 0)),
                "VolZ":         round(r.get("vol_zscore", 0), 2) if pd.notna(r.get("vol_zscore")) else None,
                "Perf 1d%":     _ret(psx, 1) if psx else None,
                "Perf 5d%":     _ret(psx, 5) if psx else None,
            })

        snap_df = pd.DataFrame(rows_snap).sort_values("BuyRatio", ascending=False)

        def _color_buyratio(val):
            if val is None:
                return ""
            if val >= 65:
                return "background-color:#bbf7d0"
            if val >= 55:
                return "background-color:#dcfce7"
            if val <= 35:
                return "background-color:#fee2e2"
            if val <= 45:
                return "background-color:#fef9c3"
            return ""

        styled = snap_df.style.applymap(_color_buyratio, subset=["BuyRatio", "3d Avg"])
        st.dataframe(styled, hide_index=True, use_container_width=True)
        st.caption(f"Data as of: **{latest.date()}** · 🟢 ≥65% · 🟡 55–65% · 🔴 ≤35%")

        # Signals for today
        st.markdown("**📡 Signals Firing Today**")
        signals = _intel_generate_signals(agg, prices)
        if not signals:
            st.success("✅ No extreme signals today — neutral flow picture.")
        else:
            for s in signals:
                color = "#bbf7d0" if "BUY" in s["action"] else "#fee2e2"
                border = "#15803d" if "BUY" in s["action"] else "#dc2626"
                st.markdown(
                    f"""<div style="background:{color}; border-left:4px solid {border};
                    border-radius:6px; padding:10px 14px; margin-bottom:8px;">
                    <strong>{s['action']}</strong> &nbsp;·&nbsp;
                    <strong>{s['sector']}</strong> &nbsp;·&nbsp;
                    <span style="color:#374151">{s['strength']}</span><br/>
                    <span style="font-size:0.82rem; color:#374151;">
                    {s['trigger']} &nbsp;·&nbsp;
                    BuyR {s['buy_ratio']:.1%} &nbsp;·&nbsp;
                    3d avg {s['buy_ratio_3d']:.1%} &nbsp;·&nbsp;
                    Streak {int(s['consec_buy_days'])}d &nbsp;·&nbsp;
                    VolZ {s['vol_zscore']:+.1f} &nbsp;·&nbsp;
                    Sector 5d: {s['ret_5d_pct']}%
                    </span></div>""",
                    unsafe_allow_html=True,
                )

    # ── TAB 2: PATTERN ANALYSIS ─────────────────────────────────────────────
    with tab_patterns:
        st.caption(
            "Statistical analysis of historical pattern occurrences vs forward returns. "
            "Needs 10+ occurrences + p<0.05 + win≥65% to be called significant."
        )

        with st.spinner("Running pattern analysis…"):
            df_fwd   = _intel_build_fwd_returns(agg, prices)
            patterns = _intel_run_patterns(df_fwd)

        sig_count = sum(
            1 for p in patterns
            if (p["stats_5d"]["win_rate"] or 0) >= 0.65
            and p["stats_5d"]["n"] >= 10
            and (p["stats_5d"]["p"] or 1) < 0.05
        )
        st.caption(f"**{sig_count}** statistically significant patterns so far (need 10+ occurrences)")

        for p in patterns:
            s5  = p["stats_5d"]
            s10 = p["stats_10d"]
            is_sig = (s5["n"] >= 10 and (s5["win_rate"] or 0) >= 0.65 and (s5["p"] or 1) < 0.05)
            label = "✅ SIGNIFICANT" if is_sig else ("⏳ Building" if s5["n"] >= 5 else "🔸 Too few data points")
            header_color = "#15803d" if is_sig else ("#92400e" if s5["n"] >= 5 else "#6b7280")

            with st.expander(f"{p['label']}  ·  {label}", expanded=is_sig):
                st.caption(p["desc"])
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**5-day forward return:**")
                    st.markdown(_stat_badge(s5), unsafe_allow_html=True)
                with c2:
                    st.markdown("**10-day forward return:**")
                    st.markdown(_stat_badge(s10), unsafe_allow_html=True)

                # Show historical occurrences table
                if st.checkbox(f"Show occurrences", key=f"occ_{p['name']}"):
                    mask = {
                        "SUSTAINED_ACCUMULATION":  df_fwd["consec_buy_days"] >= 3,
                        "ACCUMULATION_DIVERGENCE": (df_fwd["buy_ratio_3d_avg"] > 0.62) & (df_fwd["ret_prior_5d"].fillna(0) < 0.02),
                        "FLOW_MOMENTUM_TRANSITION": (df_fwd["buy_ratio"] > 0.60) & (df_fwd["buy_ratio_lag3"].fillna(1) < 0.45)
                                                    if "buy_ratio_lag3" in df_fwd.columns else (df_fwd["buy_ratio"] > 0.60),
                        "VOLUME_SPIKE_BUYING":      (df_fwd["vol_zscore"] > 1.5) & (df_fwd["buy_ratio"] > 0.60),
                        "DISTRIBUTION":             df_fwd["buy_ratio_3d_avg"] < 0.40,
                    }.get(p["name"], pd.Series(False, index=df_fwd.index))

                    occ = df_fwd[mask][["date","sector","buy_ratio","buy_ratio_3d_avg","ret_fwd_5d","ret_fwd_10d"]].copy()
                    occ = occ.dropna(subset=["ret_fwd_5d"])
                    occ["buy_ratio"] = (occ["buy_ratio"] * 100).round(1)
                    occ["buy_ratio_3d_avg"] = (occ["buy_ratio_3d_avg"] * 100).round(1)
                    occ["ret_fwd_5d"] = (occ["ret_fwd_5d"] * 100).round(2)
                    occ["ret_fwd_10d"] = (occ["ret_fwd_10d"] * 100).round(2)
                    st.dataframe(occ, hide_index=True, use_container_width=True)

    # ── TAB 3: CORRELATIONS ─────────────────────────────────────────────────
    with tab_corr:
        st.caption(
            "Pearson correlation: buy_ratio today vs 5-day forward sector return. "
            "|corr| > 0.20 is worth tracking. Negative = buying flows follow price run-ups (chasing)."
        )

        with st.spinner("Computing correlations…"):
            df_fwd2 = _intel_build_fwd_returns(agg, prices) if "ret_fwd_5d" not in agg.columns else agg
            corr_df = _intel_correlations(df_fwd2 if "ret_fwd_5d" in df_fwd2.columns else _intel_build_fwd_returns(agg, prices))

        if corr_df.empty:
            st.info("Not enough data for correlation yet.")
        else:
            def _corr_color(val):
                if val is None:
                    return ""
                if val >= 0.25:
                    return "background-color:#bbf7d0"
                if val >= 0.10:
                    return "background-color:#dcfce7"
                if val <= -0.25:
                    return "background-color:#fee2e2"
                if val <= -0.10:
                    return "background-color:#fef9c3"
                return ""

            styled_corr = corr_df.style.applymap(_corr_color, subset=["corr_full", "corr_30d"])
            st.dataframe(styled_corr, hide_index=True, use_container_width=True)

            st.caption(
                "🟢 Positive correlation: flow buying predicts sector gains. "
                "🔴 Negative: buyers may be chasing existing moves. "
                "Watch for sectors where corr flips from negative → positive over time."
            )

            # Interesting finding callout
            neg_sectors = corr_df[corr_df["corr_full"].notna() & (corr_df["corr_full"] < -0.25)]["sector"].tolist()
            if neg_sectors:
                st.warning(
                    f"**Counter-intuitive finding:** {', '.join(neg_sectors)} show negative buy→return correlation. "
                    "This may mean institutional buying in these sectors tends to follow recent price strength (chasing), "
                    "not precede it. Treat buy signals in these sectors with extra skepticism until more data accumulates."
                )

    # ── TAB 4: SIGNAL JOURNAL ───────────────────────────────────────────────
    with tab_journal:
        st.caption("All generated signals with outcomes as they mature (5-day window).")

        if not os.path.exists(_INTEL_LOG_PATH) or journal.empty:
            st.info("No signals logged yet. Run the engine for a few days.")
        else:
            # Summary stats
            closed = journal[journal["outcome"].isin(["WIN", "LOSS", "BREAKEVEN"])]
            pending = journal[journal["outcome"] == "PENDING"]

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Total Signals", len(journal))
            mc2.metric("Pending", len(pending))
            mc3.metric("Resolved", len(closed))
            win_rate = f"{(closed['outcome']=='WIN').sum() / len(closed):.0%}" if len(closed) > 0 else "—"
            mc4.metric("Win Rate", win_rate)

            # Filter
            filter_type = st.selectbox(
                "Filter by signal type",
                ["All"] + sorted(journal["signal_type"].unique().tolist()),
                key="journal_filter",
            )
            show = journal if filter_type == "All" else journal[journal["signal_type"] == filter_type]
            show = show.sort_values("date", ascending=False)

            def _outcome_color(val):
                if val == "WIN":      return "background-color:#bbf7d0"
                if val == "LOSS":     return "background-color:#fee2e2"
                if val == "PENDING":  return "background-color:#fef9c3"
                return ""

            styled_j = show.style.applymap(_outcome_color, subset=["outcome"])
            st.dataframe(styled_j, hide_index=True, use_container_width=True)

            if st.button("🔄 Force Re-validate Signals", key="intel_revalidate"):
                _intel_load_flows_agg.clear()
                _intel_load_prices.clear()
                st.rerun()


def render_flows_page():
    """Entry point — called from dashboard.py."""

    init_flows_table()

    st.markdown("### 📡 Institutional Flows — FIPI / LIPI")
    st.caption(
        "Daily settlement data from NCCPL via khistocks.com. "
        "Tracks where foreign and local institutional money is flowing "
        "across PSX sectors. Regular market only — futures excluded from all signals."
    )

    available = get_available_dates()
    n_dates   = len(available)

    # ── Top stats ─────────────────────────────────────────────────────────────
    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("Trading Days Stored",  n_dates)
    sc2.metric("Latest Date",  available[0]  if available else "—")
    sc3.metric("Earliest Date", available[-1] if available else "—")

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — DATA COLLECTION
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("#### 🔄 Data Collection")

    # Playwright check
    playwright_ok = True
    try:
        import playwright  # noqa: F401
    except ImportError:
        playwright_ok = False
        st.warning(
            "⚠️ Playwright not installed.\n\n"
            "```\npip install playwright\nplaywright install chromium\n```"
        )

    today_str = _date_cls.today().isoformat()

    # Flow type selector — run FIPI, LIPI, or both independently
    flow_choice = st.radio(
        "Which flow to scrape?",
        ["Both FIPI + LIPI", "FIPI only", "LIPI only"],
        horizontal=True,
        key="flows_choice",
    )
    FLOW_TARGETS = {
        "Both FIPI + LIPI": [("FIPI", FIPI_URL), ("LIPI", LIPI_URL)],
        "FIPI only":         [("FIPI", FIPI_URL)],
        "LIPI only":         [("LIPI", LIPI_URL)],
    }

    tab_today, tab_hist = st.tabs(["📅 Scrape Today", "📚 Scrape Historical Range"])

    with tab_today:
        st.caption(
            "Scrapes today's FIPI + LIPI data. Run after ~16:30 PKT once "
            "NCCPL settlement data is published on khistocks."
        )
        col_btn, col_info = st.columns([1, 3])
        with col_btn:
            run_today = st.button(
                "⬇️ Get Today's Flows",
                type="primary",
                disabled=not playwright_ok,
                key="flows_today",
            )
        with col_info:
            if today_str in available:
                st.success(f"✅ Today ({today_str}) is already in the database.")
            elif available:
                st.info(f"Latest in DB: **{available[0]}**. Today not yet scraped.")
            else:
                st.info("No data yet.")

        if run_today:
            pb  = st.progress(0.0)
            txt = st.empty()
            res = scrape_bulk(today_str, today_str, pb, txt,
                              targets=FLOW_TARGETS[flow_choice])
            pb.progress(1.0)
            if res["rows_saved"]:
                st.success(f"✅ {res['rows_saved']} rows saved.")
                st.rerun()
            else:
                st.warning(
                    "No data returned — market may be closed or data not yet "
                    "published. Try 🔬 Test Connection below."
                )

    with tab_hist:
        st.caption(
            "Scrape a historical date range in one pass. "
            "The page accepts a date range filter — all matching days are "
            "returned across paginated results. Already-saved dates are safely "
            "overwritten (no duplicates created)."
        )
        hc1, hc2 = st.columns(2)
        hist_start = hc1.date_input(
            "From", value=_date_cls.today() - timedelta(days=90), key="fh_start"
        )
        hist_end = hc2.date_input(
            "To", value=_date_cls.today(), key="fh_end"
        )

        n_days = (hist_end - hist_start).days + 1
        n_weekdays = sum(
            1 for i in range(n_days)
            if (_date_cls.fromisoformat(str(hist_start)) + timedelta(days=i)).weekday() < 5
        )
        already = sum(
            1 for i in range(n_days)
            if (_date_cls.fromisoformat(str(hist_start)) + timedelta(days=i)).isoformat()
            in set(available)
        )
        st.caption(
            f"Range: **{n_weekdays}** weekdays · "
            f"**{already}** already in DB · "
            f"**{n_weekdays - already}** new days expected"
        )

        if st.button(
            f"🚀 Scrape {flow_choice} · {str(hist_start)} → {str(hist_end)}",
            type="primary",
            disabled=not playwright_ok,
            key="flows_hist",
        ):
            pb  = st.progress(0.0)
            txt = st.empty()
            res = scrape_bulk(str(hist_start), str(hist_end), pb, txt,
                              targets=FLOW_TARGETS[flow_choice])
            pb.progress(1.0)
            if res["rows_saved"]:
                st.success(
                    f"✅ Done — **{res['rows_saved']:,} rows** saved "
                    f"({res['dates_attempted']})."
                )
            else:
                st.warning(
                    f"No rows returned for {res['dates_attempted']}. "
                    "Market may have been closed or page structure changed."
                )
            if res["failed"]:
                st.caption(f"{res['failed']} flow type(s) returned no data.")
            st.rerun()

    # ── Diagnostic test ───────────────────────────────────────────────────────
    with st.expander("🔬 Test Connection (diagnose scraper)", expanded=False):
        st.caption(
            "Navigates to the FIPI or LIPI page with a real browser, waits for the "
            "AJAX table to load, then reports what was found — without saving anything. "
            "Run this first if the bulk scraper returns no data."
        )
        diag_flow = st.radio("Test page", ["FIPI", "LIPI"], horizontal=True, key="flows_diag_type")
        diag_url  = FIPI_URL if diag_flow == "FIPI" else LIPI_URL

        if st.button("🔬 Run Connection Test", key="flows_diag_btn", disabled=not playwright_ok):
            with st.spinner(f"Loading {diag_flow} page…"):
                diag = debug_scrape_flow_page(diag_url, diag_flow)

            if "error" in diag:
                st.error(f"Error: {diag['error']}")
            else:
                st.write(f"**Landed URL:** `{diag.get('landed_url')}`")
                st.write(f"**Page title:** {diag.get('page_title')}")
                found = diag.get("table_found", False)
                nrows = diag.get("table_row_count", 0)
                if found and nrows > 1:
                    st.success(f"✅ Table found with **{nrows} rows** (including header).")
                    st.write(f"**Headers:** {diag.get('table_headers')}")
                    st.write(f"**Sample row:** {diag.get('sample_row')}")
                elif found:
                    st.warning(f"Table element found but only {nrows} rows — data didn't load.")
                else:
                    st.error("No table found on the page.")

                if diag.get("date_inputs"):
                    st.write("**Date inputs found:**")
                    st.json(diag["date_inputs"])
                else:
                    st.warning("No date input found — date filtering may not work.")

                if diag.get("selects"):
                    st.write("**Select dropdowns:**")
                    st.json(diag["selects"])

                if diag.get("buttons"):
                    st.write("**Buttons:**")
                    st.json(diag["buttons"])

    if not available:
        st.info("No data yet. Scrape at least one day to see charts and signals.")
        return

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — TODAY'S SNAPSHOT
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("#### 📊 Latest Day Snapshot")
    st.caption(f"Data for **{available[0]}** · REGULAR market only")

    day_df = get_flows_df(
        date_from=available[0], date_to=available[0], market_type="REGULAR"
    )

    if day_df.empty:
        st.info("No REGULAR market data for the latest date.")
    else:
        col_fipi, col_lipi = st.columns(2)

        # ── FIPI by sector ────────────────────────────────────────────────────
        with col_fipi:
            st.markdown("**🌏 FIPI — Foreign Net by Sector**")
            fipi = day_df[day_df["flow_type"] == "FIPI"].copy()
            if not fipi.empty:
                sec_net = (
                    fipi.groupby("sector")["net_value"]
                    .sum()
                    .reset_index()
                    .rename(columns={"net_value": "Net (USD Mn)"})
                )
                sec_net["Net (USD Mn)"]   = sec_net["Net (USD Mn)"].round(2)
                sec_net["Flow"]          = sec_net["Net (USD Mn)"].apply(
                    lambda v: "🟢 In" if v >= 0 else "🔴 Out"
                )
                sec_net = sec_net.sort_values("Net (USD Mn)")
                st.dataframe(sec_net, hide_index=True, use_container_width=True)

                total_fipi = fipi["net_value"].sum()
                st.metric(
                    "FIPI Grand Total",
                    f"{total_fipi:+,.0f}",
                    delta="Net Inflow" if total_fipi >= 0 else "Net Outflow",
                    delta_color="normal" if total_fipi >= 0 else "inverse",
                )

        # ── LIPI by client type ───────────────────────────────────────────────
        with col_lipi:
            st.markdown("**🏦 LIPI — Local Institutional by Client**")
            lipi = day_df[day_df["flow_type"] == "LIPI"].copy()
            if not lipi.empty:
                client_net = (
                    lipi.groupby("client_type")["net_value"]
                    .sum()
                    .reset_index()
                    .rename(columns={"net_value": "Net (USD Mn)"})
                )
                client_net["Net (USD Mn)"] = client_net["Net (USD Mn)"].round(2)
                client_net["Money Type"]  = client_net["client_type"].apply(
                    lambda c: "🧠 Institutional" if c.upper() in SMART_MONEY_CLIENTS
                              else "👥 Retail/Funds" if c.upper() in RETAIL_MONEY_CLIENTS
                              else "—"
                )
                client_net["Flow"] = client_net["Net (USD Mn)"].apply(
                    lambda v: "🟢 Buying" if v >= 0 else "🔴 Selling"
                )
                client_net = client_net.sort_values("Net (USD Mn)", ascending=False)
                st.dataframe(
                    client_net[["client_type", "Money Type", "Net (USD Mn)", "Flow"]],
                    hide_index=True, use_container_width=True
                )

                # Smart vs Retail divergence callout
                smart_net  = lipi[lipi["client_type"].str.upper().isin(SMART_MONEY_CLIENTS)]["net_value"].sum()
                retail_net = lipi[lipi["client_type"].str.upper().isin(RETAIL_MONEY_CLIENTS)]["net_value"].sum()
                sm1, sm2   = st.columns(2)
                sm1.metric("🧠 Institutional",  f"{smart_net:+,.0f}")
                sm2.metric("👥 Retail/Funds",  f"{retail_net:+,.0f}")

                if smart_net > 0 and retail_net < 0:
                    st.success("Smart buying · Retail selling — **accumulation pattern**")
                elif smart_net < 0 and retail_net > 0:
                    st.warning("Smart selling · Retail buying — **distribution pattern**")

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — TREND BOARD
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("#### 📅 Trend Board — Rolling Flows by Sector")

    roll_days = st.radio(
        "Window",
        options=[5, 10, 20],
        format_func=lambda x: f"{x}-day",
        horizontal=True,
        key="flows_window",
    )

    if n_dates < 2:
        st.info("Need at least 2 days of data for the trend board.")
    else:
        # Daily totals for the heatmap (sector × date grid)
        avail_for_window = available[:roll_days]
        cutoff = avail_for_window[-1]

        with _get_conn() as conn:
            hm_rows = conn.execute("""
                SELECT date, sector,
                       SUM(CASE WHEN flow_type='FIPI' THEN net_value ELSE 0 END) AS fipi_net,
                       SUM(CASE WHEN flow_type='LIPI' THEN net_value ELSE 0 END) AS lipi_net,
                       SUM(net_value) AS total_net
                FROM market_flows
                WHERE date >= ? AND market_type = 'REGULAR'
                GROUP BY date, sector
                ORDER BY sector, date
            """, (cutoff,)).fetchall()

        if hm_rows:
            hm_df = pd.DataFrame([dict(r) for r in hm_rows])

            # ── Summary bar: sector × rolling total ──────────────────────────
            sector_summary = (
                hm_df.groupby("sector")[["fipi_net", "lipi_net", "total_net"]]
                .sum()
                .sort_values("total_net")
            )
            sector_summary.columns = ["FIPI Net", "LIPI Net", "Total Net"]

            tb_col1, tb_col2 = st.columns(2)
            with tb_col1:
                st.caption(f"**Foreign (FIPI) Net — {roll_days}d rolling**")
                st.bar_chart(sector_summary[["FIPI Net"]], height=280)
            with tb_col2:
                st.caption(f"**Local Institutional (LIPI) Net — {roll_days}d rolling**")
                st.bar_chart(sector_summary[["LIPI Net"]], height=280)

            # ── Heatmap: sector rows × date columns ───────────────────────────
            st.markdown(f"**Daily Total Net — {roll_days}d grid** *(raw values from source — unit TBC)*")
            pivot = (
                hm_df.pivot_table(
                    index="sector", columns="date",
                    values="total_net", aggfunc="sum"
                ).fillna(0)
            )
            # Sort sectors: biggest net seller at top, biggest buyer at bottom
            pivot["_sort"] = pivot.sum(axis=1)
            pivot = pivot.sort_values("_sort").drop(columns="_sort")

            def _cell_color(v):
                if pd.isna(v) or v == 0: return ""
                if v > 0:  return "background-color:#dcfce7; color:#166534"
                return             "background-color:#fee2e2; color:#991b1b"

            st.caption("🟢 Green = net inflow · 🔴 Red = net outflow · Unit TBC (confirm via 🔬 diagnostic)")
            st.dataframe(
                pivot.style.map(_cell_color).format("{:+.1f}"),
                use_container_width=True,
            )

            # ── FIPI vs LIPI divergence table ─────────────────────────────────
            with st.expander("🔍 FIPI vs LIPI Divergence Detail", expanded=False):
                div_df = sector_summary.copy()
                div_df["Divergence"] = div_df.apply(
                    lambda r: "🟢 Accumulation"
                              if r["FIPI Net"] < 0 and r["LIPI Net"] > 0
                              else ("🔴 Distribution"
                                    if r["FIPI Net"] < 0 and r["LIPI Net"] < 0
                                    else ("💰 Foreign Buying"
                                          if r["FIPI Net"] > 0
                                          else "—")),
                    axis=1,
                )
                st.dataframe(div_df.reset_index(), hide_index=True, use_container_width=True)

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 4 — DECISION SIGNALS
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("#### 🎯 Decision Signals")
    st.caption(
        "Auto-computed from rolling flows. Needs 5+ days to be reliable. "
        "Exit Watch cross-references your currently Active trades (read-only)."
    )

    if n_dates < 5:
        st.info(
            f"Signals activate after **5 days** of data — "
            f"you have **{n_dates}** so far. Keep scraping daily."
        )
    else:
        roll5  = _rolling_sector_pivot(5)
        roll10 = _rolling_sector_pivot(10)
        roll20 = _rolling_sector_pivot(min(20, n_dates))

        signals = compute_signals(roll10, roll5, roll20)

        if not signals:
            st.success("✅ No active signals. Flow picture looks neutral across all sectors.")
        else:
            bg_map = {
                "strong":   "#bbf7d0",
                "positive": "#dcfce7",
                "neutral":  "#f0f9ff",
                "warning":  "#fef9c3",
                "negative": "#fee2e2",
            }
            border_map = {
                "strong":   "#15803d",
                "positive": "#16a34a",
                "neutral":  "#0284c7",
                "warning":  "#ca8a04",
                "negative": "#dc2626",
            }
            # already sorted by tier inside compute_signals
            for sig in signals:
                sev  = sig.get("severity", "neutral")
                bg   = bg_map.get(sev, "#f8fafc")
                bdr  = border_map.get(sev, "#94a3b8")
                detail_html = sig["detail"].replace("\n", "<br/>")
                st.markdown(
                    f"""<div style="background:{bg}; border-left:4px solid {bdr};
                    border-radius:6px; padding:10px 14px; margin-bottom:10px;">
                    <strong>{sig['type']}</strong>
                    &nbsp;·&nbsp;
                    <strong style="font-size:1rem">{sig['sector']}</strong><br/>
                    <span style="font-size:0.82rem; color:#374151;">{detail_html}</span>
                    </div>""",
                    unsafe_allow_html=True,
                )

    # ── Raw data inspector ────────────────────────────────────────────────────
    with st.expander("🗃️ Raw Data Inspector", expanded=False):
        if available:
            inspect_date = st.selectbox(
                "Select date", options=available[:60], key="flows_inspect_date"
            )
            mkt_filter = st.radio(
                "Market", ["REGULAR", "OFF-MARKET", "All"],
                horizontal=True, key="flows_inspect_mkt"
            )
            raw = get_flows_df(
                date_from=inspect_date,
                date_to=inspect_date,
                market_type=None if mkt_filter == "All" else mkt_filter,
            )
            if not raw.empty:
                show_cols = [
                    "date", "flow_type", "client_type", "sector", "market_type",
                    "buy_value", "sell_value", "net_value", "usd_net",
                ]
                show_cols = [c for c in show_cols if c in raw.columns]
                st.dataframe(raw[show_cols], hide_index=True, use_container_width=True)
                st.caption(f"Total rows: {len(raw)}")
            else:
                st.info("No data for selected date/market.")

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 5 — INTELLIGENCE ENGINE
    # ══════════════════════════════════════════════════════════════════════════
    _render_intelligence_section(available, n_dates)

    st.divider()
    st.caption(
        "**Reading guide —** "
        "FIPI = foreign money (Corps + Individuals + Overseas) · "
        "LIPI = local institutions (Banks, Companies, Mutual Funds, Insurance, Broker Prop.) · "
        "**Institutional** = principal-at-risk players (banks, corporates, insurance, broker prop.) · "
        "**Retail/Funds** = mutual funds + individual investors · "
        "🟢🟢 Strong Buy = FIPI + LIPI both net positive · "
        "🟢 Accumulation = foreigners selling, local companies absorbing · "
        "⚡ Flow Reversal = 20d net negative turning positive in 5d · "
        "🔵 Foreign Buying = FIPI positive, locals neutral · "
        "🟡 Local Accumulation = LIPI companies buying, FIPI out · "
        "🔴 Distribution = both FIPI + LIPI net sellers · "
        "⚠️ Exit Watch = institutions selling into your active position. "
        "**Signals are observations only** — accumulate 4+ weeks of data before acting on them."
    )
