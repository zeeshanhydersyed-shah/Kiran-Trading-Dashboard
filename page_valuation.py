"""
page_valuation.py — Fundamental Research Studio (v3)
=====================================================
McKinsey-grade equity research pipeline.

  Upload Annual Report PDF  →  AI extracts financial data + management text
  →  Income Statement / Balance Sheet / Cash Flow (multi-year, with growth rates)
  →  Health Scorecard: Piotroski F-Score · Altman Z-Score · DuPont · 30+ ratios
  →  Valuation Suite: DCF · Graham · P/E · P/B · EV/EBITDA · DDM · EPV
  →  Stress Tests: Sensitivity Tornado · Scenario Matrix · Monte Carlo
  →  AI Analysis: management commentary · growth drivers · red flags · crosscheck
  →  Investment Decision: composite score · fair value range · entry timing from DB

Data source: PDF annual reports from khistocks.com, PSX, or company IR pages.
  Go to khistocks.com/company-information/annual-reports/TICKER.html,
  select year, download PDF, upload here.

HOW TO USE IN dashboard.py (unchanged):
    elif st.session_state.page == "💰 Valuation":
        from page_valuation import render_valuation_page
        render_valuation_page()

Dependencies (install once):
    pip install pdfplumber plotly
    (groq and anthropic already installed via agent.py)
"""

import io
import json
import logging
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

# ── Load .env so GROQ_API_KEY etc. are available when running locally ──────────
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    pass  # python-dotenv not installed — rely on environment variables directly

# ── Optional dependencies ──────────────────────────────────────────────────────
try:
    import pdfplumber
    _PDF_OK = True
except ImportError:
    _PDF_OK = False

try:
    import plotly.express as px
    import plotly.graph_objects as go
    _PLOTLY_OK = True
except ImportError:
    _PLOTLY_OK = False

try:
    from config import DB_PATH
except ImportError:
    DB_PATH = os.path.join(os.path.dirname(__file__), "psx_data.db")

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# A.  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

KSE100_CONSTITUENTS: list[tuple[str, str]] = [
    ("ABL","Allied Bank Limited"),("ABOT","Abbott Laboratories Pakistan"),
    ("AHCL","Arif Habib Corporation"),("AICL","Adamjee Insurance"),
    ("AGP","AGP Limited"),("AIRLINK","Air Link Communication"),
    ("AKBL","Askari Bank"),("APL","Attock Petroleum"),
    ("ATRL","Attock Refinery"),("ATLH","Atlas Honda"),
    ("BAFL","Bank Alfalah"),("BAHL","Bank AL Habib"),
    ("BOP","Bank of Punjab"),("BWCL","Bestway Cement"),
    ("CHCC","Cherat Cement"),("CNERGY","Cnergyico PK"),
    ("COLG","Colgate-Palmolive Pakistan"),("DGKC","D.G. Khan Cement"),
    ("EFERT","Engro Fertilizers"),("ENGROH","Engro Holdings"),
    ("FABL","Faysal Bank"),("FATIMA","Fatima Fertilizer"),
    ("FCCL","Fauji Cement"),("FFC","Fauji Fertilizer"),
    ("GAL","Ghandhara Automobiles"),("GLAXO","GlaxoSmithKline Pakistan"),
    ("HBL","Habib Bank"),("HCAR","Honda Atlas Cars"),
    ("HINOON","Highnoon Laboratories"),("HMB","Habib Metropolitan Bank"),
    ("HUBC","Hub Power Company"),("INDU","Indus Motor Company"),
    ("ISL","International Steels"),("KAPCO","Kot Addu Power"),
    ("KEL","K-Electric"),("KOHC","Kohat Cement"),
    ("LCI","Lucky Core Industries"),("LOTCHEM","Lotte Chemical Pakistan"),
    ("LUCK","Lucky Cement"),("MARI","Mari Energies"),
    ("MCB","MCB Bank"),("MEBL","Meezan Bank"),
    ("MLCF","Maple Leaf Cement"),("MTL","Millat Tractors"),
    ("NATF","National Foods"),("NBP","National Bank of Pakistan"),
    ("NESTLE","Nestle Pakistan"),("NML","Nishat Mills"),
    ("OGDC","Oil & Gas Development Company"),("PAEL","Pak Elektron"),
    ("PAKT","Pakistan Tobacco"),("PIOC","Pioneer Cement"),
    ("PKGS","Packages Limited"),("POL","Pakistan Oilfields"),
    ("POWER","Power Cement"),("PPL","Pakistan Petroleum"),
    ("PSO","Pakistan State Oil"),("PTC","Pakistan Telecommunication"),
    ("SAZEW","Sazgar Engineering"),("SCBPL","Standard Chartered Bank Pak"),
    ("SEARL","The Searle Company"),("SHFA","Shifa International Hospitals"),
    ("SNGP","Sui Northern Gas"),("SSGC","Sui Southern Gas"),
    ("SYS","Systems Limited"),("THALL","Thal Limited"),
    ("TGL","Tariq Glass"),("TRG","TRG Pakistan"),
    ("UBL","United Bank"),("UPFL","Unilever Pakistan Foods"),
]

# PSX sector-average multiples (approximate historical ranges)
SECTOR_MULTIPLES: dict[str, dict] = {
    "CEMENT":                {"pe": 8.0,  "pb": 1.5, "ev_ebitda": 5.0},
    "COMMERCIAL BANKS":      {"pe": 6.0,  "pb": 1.0, "ev_ebitda": None},
    "OIL & GAS EXPLORATION": {"pe": 5.0,  "pb": 1.2, "ev_ebitda": 4.0},
    "FERTILIZER":            {"pe": 7.0,  "pb": 2.0, "ev_ebitda": 5.5},
    "AUTOMOBILE ASSEMBLERS": {"pe": 10.0, "pb": 2.5, "ev_ebitda": 7.0},
    "PHARMACEUTICAL":        {"pe": 12.0, "pb": 2.0, "ev_ebitda": 8.0},
    "POWER GENERATION":      {"pe": 6.0,  "pb": 0.8, "ev_ebitda": 6.0},
    "TEXTILE COMPOSITE":     {"pe": 6.0,  "pb": 0.8, "ev_ebitda": 4.5},
    "FOOD & PERSONAL CARE":  {"pe": 14.0, "pb": 3.5, "ev_ebitda": 9.0},
    "TECHNOLOGY":            {"pe": 15.0, "pb": 4.0, "ev_ebitda": 10.0},
    "DEFAULT":               {"pe": 8.0,  "pb": 1.5, "ev_ebitda": 5.5},
}

# Standardised internal key → display label for financial statements
INCOME_KEYS = [
    ("revenue",         "Revenue / Net Sales"),
    ("cogs",            "Cost of Sales / COGS"),
    ("gross_profit",    "Gross Profit"),
    ("dist_costs",      "Distribution Costs"),
    ("admin_exp",       "Admin Expenses"),
    ("other_income",    "Other Operating Income"),
    ("ebit",            "EBIT / Operating Profit"),
    ("finance_costs",   "Finance Costs"),
    ("pbt",             "Profit Before Tax (PBT)"),
    ("tax",             "Taxation"),
    ("pat",             "Profit After Tax (PAT)"),
    ("eps",             "EPS (Basic, PKR)"),
    ("dps",             "DPS (PKR)"),
]

BS_KEYS = [
    ("ppe",             "Property Plant & Equipment"),
    ("intangibles",     "Intangible Assets"),
    ("lt_investments",  "Long-term Investments"),
    ("total_nca",       "Total Non-Current Assets"),
    ("inventories",     "Inventories"),
    ("receivables",     "Trade Receivables"),
    ("cash",            "Cash & Bank Balances"),
    ("total_ca",        "Total Current Assets"),
    ("total_assets",    "TOTAL ASSETS"),
    ("lt_debt",         "Long-term Debt / Financing"),
    ("total_ncl",       "Total Non-Current Liabilities"),
    ("st_debt",         "Short-term Borrowings"),
    ("payables",        "Trade & Other Payables"),
    ("total_cl",        "Total Current Liabilities"),
    ("total_liabilities","TOTAL LIABILITIES"),
    ("share_capital",   "Share Capital"),
    ("retained_earnings","Retained Earnings"),
    ("total_equity",    "TOTAL EQUITY"),
    ("shares",          "Shares Outstanding (M)"),
]

CF_KEYS = [
    ("cfo",             "Cash from Operations (CFO)"),
    ("capex",           "Capital Expenditure (CAPEX)"),
    ("fcf",             "Free Cash Flow (FCF)"),
    ("cfi",             "Cash from Investing (CFI)"),
    ("dividends_paid",  "Dividends Paid"),
    ("cff",             "Cash from Financing (CFF)"),
    ("closing_cash",    "Closing Cash Balance"),
]

AI_EXTRACTION_PROMPT = """You are a financial data extraction specialist for Pakistani company annual reports.
Extract financial data from the text below. Return ONLY a JSON object.

Rules:
- All monetary values in PKR MILLIONS (convert if stated in thousands: ÷1000; if billions: ×1000)
- EPS and DPS in PKR per share (not millions)
- Shares Outstanding in millions
- If a value is not found in the text, use null
- Do NOT calculate or infer — only extract explicitly stated numbers
- Extract data for each fiscal year available (usually 1-5 years)

Return format:
{
  "years": [2024, 2023, ...],
  "data": {
    "2024": {
      "revenue": null_or_number,
      "cogs": null_or_number,
      "gross_profit": null_or_number,
      "dist_costs": null_or_number,
      "admin_exp": null_or_number,
      "other_income": null_or_number,
      "ebit": null_or_number,
      "finance_costs": null_or_number,
      "pbt": null_or_number,
      "tax": null_or_number,
      "pat": null_or_number,
      "eps": null_or_number,
      "dps": null_or_number,
      "ppe": null_or_number,
      "intangibles": null_or_number,
      "lt_investments": null_or_number,
      "total_nca": null_or_number,
      "inventories": null_or_number,
      "receivables": null_or_number,
      "cash": null_or_number,
      "total_ca": null_or_number,
      "total_assets": null_or_number,
      "lt_debt": null_or_number,
      "total_ncl": null_or_number,
      "st_debt": null_or_number,
      "payables": null_or_number,
      "total_cl": null_or_number,
      "total_liabilities": null_or_number,
      "share_capital": null_or_number,
      "retained_earnings": null_or_number,
      "total_equity": null_or_number,
      "shares": null_or_number,
      "cfo": null_or_number,
      "capex": null_or_number,
      "cfi": null_or_number,
      "dividends_paid": null_or_number,
      "cff": null_or_number,
      "closing_cash": null_or_number
    }
  }
}

ANNUAL REPORT TEXT:
"""

AI_MGMT_PROMPT = """You are a senior equity analyst reviewing a Pakistani company's annual report.
Analyse ALL sections: management commentary, directors' report, MD&A, notes to accounts, and segment reporting.

Return ONLY a valid JSON object with exactly these keys:

{
  "executive_summary": "2-3 sentence summary of the company's year",
  "growth_drivers": ["driver 1", "driver 2", "driver 3"],
  "risks": ["risk 1", "risk 2", "risk 3"],
  "red_flags": ["accounting concern", "related party issue", "going concern flag"],
  "management_tone": "Optimistic / Cautious / Defensive / Neutral",
  "outlook_score": 7,
  "key_metrics_mentioned": {"Revenue growth": "12%", "Capacity utilization": "88%"},
  "capital_allocation": "Dividend policy, CAPEX plans, debt repayment strategy",
  "competitive_position": "Moat, market share, competitive dynamics",
  "segment_breakdown": [
    {"segment": "Pakistan Cement", "revenue_share_pct": 60, "notes": "dominant segment"},
    {"segment": "Export / International", "revenue_share_pct": 25, "notes": "growing"}
  ],
  "associate_companies": [
    {"name": "LCI / ICI Pakistan", "stake_pct": 75, "carrying_value_m": 45000, "notes": "key subsidiary"}
  ],
  "debt_maturity": "LT debt PKR 9B: 2025 PKR 3B due, 2026 PKR 3B, 2027+ PKR 3B",
  "one_off_items": [
    {"description": "exchange loss on foreign currency debt", "amount_m": 2500, "impact": "reduced PAT"},
    {"description": "gain on disposal", "amount_m": 500, "impact": "inflated PAT"}
  ],
  "capacity_info": "Total cement capacity 15.75 Mtpa, utilization 88%, Congo plant 1.5 Mtpa",
  "export_local_mix": "Export 35%, Local 65% of dispatches by volume",
  "future_capex": "Congo expansion +1 Mtpa (PKR 8B, completion 2026), Pakistan brownfield TBD",
  "normalized_pat_note": "Reported PAT adjusted for: [one-offs]. Normalized PAT estimate: PKR X million"
}

All monetary amounts in PKR millions. Use null or [] for fields not found in the text.

ANNUAL REPORT TEXT:
"""


# ══════════════════════════════════════════════════════════════════════════════
# B.  DATABASE
# ══════════════════════════════════════════════════════════════════════════════

@contextmanager
def _get_conn():
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


def init_valuation_tables():
    with _get_conn() as conn:
        # KSE-100 reference
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kse100_constituents (
                symbol TEXT PRIMARY KEY, company_name TEXT NOT NULL, sector TEXT
            )
        """)
        try:
            conn.execute("ALTER TABLE kse100_constituents ADD COLUMN sector TEXT")
        except Exception:
            pass

        # Financial line items — one row per (ticker, year, key)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fs_line_items (
                ticker  TEXT    NOT NULL,
                year    INTEGER NOT NULL,
                key     TEXT    NOT NULL,
                value   REAL,
                PRIMARY KEY (ticker, year, key)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fs_ticker ON fs_line_items(ticker)")

        # AI analysis results
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fs_analysis (
                ticker             TEXT    NOT NULL,
                year               INTEGER NOT NULL,
                executive_summary  TEXT,
                growth_drivers     TEXT,
                risks              TEXT,
                red_flags          TEXT,
                management_tone    TEXT,
                outlook_score      REAL,
                key_metrics        TEXT,
                capital_allocation TEXT,
                competitive_pos    TEXT,
                analyzed_at        TEXT    DEFAULT (datetime('now')),
                PRIMARY KEY (ticker, year)
            )
        """)

        # Valuation findings / research journal (kept from v2)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS valuation_findings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker        TEXT,
                research_date TEXT,
                current_price REAL,
                dcf_value     REAL,
                pe_value      REAL,
                pb_value      REAL,
                graham_value  REAL,
                bear_value    REAL,
                base_value    REAL,
                bull_value    REAL,
                conviction    INTEGER,
                decision      TEXT,
                thesis        TEXT,
                assumptions   TEXT,
                created_at    TEXT DEFAULT (datetime('now'))
            )
        """)

    _seed_constituents()


def _seed_constituents():
    with _get_conn() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO kse100_constituents (symbol, company_name) VALUES (?, ?)",
            KSE100_CONSTITUENTS,
        )
        try:
            conn.execute("""
                UPDATE kse100_constituents
                SET sector = (SELECT sector FROM sectors WHERE sectors.symbol = kse100_constituents.symbol LIMIT 1)
                WHERE sector IS NULL
            """)
        except Exception:
            pass


def get_kse100() -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT symbol, company_name, sector FROM kse100_constituents ORDER BY symbol").fetchall()
    return [dict(r) for r in rows]


def get_last_price(ticker: str) -> float:
    with _get_conn() as conn:
        row = conn.execute("SELECT close FROM prices WHERE symbol=? ORDER BY date DESC LIMIT 1", (ticker,)).fetchone()
    return float(row["close"]) if row else 0.0


def save_financials(ticker: str, data: dict[int, dict]):
    """data = {year: {key: value, ...}}"""
    rows = []
    for year, kv in data.items():
        for key, val in kv.items():
            rows.append((ticker, int(year), key, val))
    with _get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO fs_line_items (ticker, year, key, value) VALUES (?,?,?,?)",
            rows,
        )


def load_financials(ticker: str) -> dict[int, dict]:
    """Returns {year: {key: value}}"""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT year, key, value FROM fs_line_items WHERE ticker=? ORDER BY year DESC",
            (ticker,)
        ).fetchall()
    result: dict[int, dict] = {}
    for r in rows:
        result.setdefault(r["year"], {})[r["key"]] = r["value"]
    return result


def get_years(ticker: str) -> list[int]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT year FROM fs_line_items WHERE ticker=? ORDER BY year DESC",
            (ticker,)
        ).fetchall()
    return [r["year"] for r in rows]


def save_analysis(ticker: str, year: int, analysis: dict):
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO fs_analysis
              (ticker, year, executive_summary, growth_drivers, risks, red_flags,
               management_tone, outlook_score, key_metrics, capital_allocation, competitive_pos, analyzed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        """, (
            ticker, year,
            analysis.get("executive_summary"),
            json.dumps(analysis.get("growth_drivers", [])),
            json.dumps(analysis.get("risks", [])),
            json.dumps(analysis.get("red_flags", [])),
            analysis.get("management_tone"),
            analysis.get("outlook_score"),
            json.dumps(analysis.get("key_metrics_mentioned", {})),
            analysis.get("capital_allocation"),
            analysis.get("competitive_position"),
        ))


def load_analysis(ticker: str, year: int) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM fs_analysis WHERE ticker=? AND year=?", (ticker, year)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ["growth_drivers", "risks", "red_flags", "key_metrics"]:
        try:
            d[k] = json.loads(d[k] or "[]")
        except Exception:
            d[k] = []
    return d


def save_finding(f: dict) -> int:
    with _get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO valuation_findings
               (ticker,research_date,current_price,dcf_value,pe_value,pb_value,graham_value,
                bear_value,base_value,bull_value,conviction,decision,thesis,assumptions)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f["ticker"], f["research_date"], f.get("current_price"),
             f.get("dcf_value"), f.get("pe_value"), f.get("pb_value"), f.get("graham_value"),
             f.get("bear_value"), f.get("base_value"), f.get("bull_value"),
             f.get("conviction"), f.get("decision"), f.get("thesis"), f.get("assumptions"))
        )
        return cur.lastrowid


def get_library(ticker: str | None = None) -> pd.DataFrame:
    with _get_conn() as conn:
        sql = "SELECT * FROM valuation_findings"
        params: tuple = ()
        if ticker:
            sql += " WHERE ticker=?"
            params = (ticker,)
        sql += " ORDER BY created_at DESC LIMIT 100"
        rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# C.  PDF EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def extract_pdf_text(file_bytes: bytes) -> tuple[str, str]:
    """
    Extract all text from a PDF.
    Returns (full_text, mda_section_text).
    mda_section is the MD&A / Directors Report / Review of Operations section.
    """
    if not _PDF_OK:
        return "", ""

    full_pages = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                full_pages.append(txt)

    full_text = "\n".join(full_pages)

    # Extract MD&A section — look for common section headers
    mda_keywords = [
        "directors' report", "directors report", "chairman's review", "chairman review",
        "management discussion", "review of operations", "chief executive",
        "md&a", "business review", "operational review"
    ]
    end_keywords = [
        "statement of financial position", "balance sheet",
        "statement of profit", "profit and loss", "income statement",
        "independent auditor", "auditors' report", "notes to the"
    ]

    full_lower = full_text.lower()
    mda_start = -1
    for kw in mda_keywords:
        idx = full_lower.find(kw)
        if idx != -1 and (mda_start == -1 or idx < mda_start):
            mda_start = idx

    mda_end = len(full_text)
    if mda_start != -1:
        for kw in end_keywords:
            idx = full_lower.find(kw, mda_start + 500)
            if idx != -1 and idx < mda_end:
                mda_end = idx

    mda_text = full_text[mda_start:mda_end] if mda_start != -1 else full_text[:8000]

    return full_text, mda_text


# ══════════════════════════════════════════════════════════════════════════════
# C2.  CSV IMPORT  (khistocks.com 5-file export format)
# ══════════════════════════════════════════════════════════════════════════════
# CSV format: row 0 = header ("Year", 2025, 2024, …), col 0 = line item name.
# Values are in PKR full units → we divide by 1,000,000 → PKR millions.
# Mapping prefix rules:
#   "^key"  → share-count column  (÷1,000,000 → millions of shares)
#   "~key"  → per-share / ratio   (no monetary scaling)
#   "+key"  → inventory component (monetary, combined into "inventories")
#   "key"   → regular monetary    (÷1,000,000)

_BS_MAP: dict[str, str] = {
    # ── Non-current assets ────────────────────────────────────────────────────
    "fixed assets":                     "ppe",
    "property, plant and equipment":    "ppe",
    "property plant and equipment":     "ppe",
    "tangible fixed assets":            "ppe",
    "right of use":                     "ppe",
    "investments":                      "lt_investments",
    "long term investments":            "lt_investments",
    "long-term investments":            "lt_investments",
    "investment in subsidiaries":       "lt_investments",
    "investment in associates":         "lt_investments",
    "intangible":                       "intangibles",
    "goodwill":                         "intangibles",
    "total non-current assets":         "total_nca",
    "non current assets":               "total_nca",
    # ── Current assets ────────────────────────────────────────────────────────
    "cash in hand and bank":            "cash",
    "cash and bank balances":           "cash",
    "cash & cash equivalents":          "cash",
    "cash and cash equivalents":        "cash",
    "stores and spares":                "+stores",
    "stock in trade":                   "+stock",
    "inventories":                      "inventories",
    "trade debts":                      "receivables",
    "trade receivables":                "receivables",
    "debtors":                          "receivables",
    "current assets":                   "total_ca",
    "total current assets":             "total_ca",
    # ── Totals ────────────────────────────────────────────────────────────────
    "total assets":                     "total_assets",
    # ── Liabilities ───────────────────────────────────────────────────────────
    "interest bearing long term":       "lt_debt",
    "long term borrowings":             "lt_debt",
    "long-term borrowings":             "lt_debt",
    "long term financing":              "lt_debt",
    "long-term financing":              "lt_debt",
    "non interest bearing long term":   "total_ncl",
    "total non-current liabilities":    "total_ncl",
    "interest bearing short term":      "st_debt",
    "short term borrowings":            "st_debt",
    "short-term borrowings":            "st_debt",
    "running finance":                  "st_debt",
    "trades payables":                  "payables",
    "trade payables":                   "payables",
    "trade and other payables":         "payables",
    "creditors":                        "payables",
    "total current liabilities":        "total_cl",
    "current liabilities":              "total_cl",
    "total liabilities":                "total_liabilities",
    # ── Equity ────────────────────────────────────────────────────────────────
    "paid up capital":                  "share_capital",
    "share capital":                    "share_capital",
    "paid-up capital":                  "share_capital",
    "reserves":                         "retained_earnings",
    "retained earnings":                "retained_earnings",
    "shareholders equity":              "total_equity",
    "shareholder equity":               "total_equity",
    "shareholders' equity":             "total_equity",
    "total equity":                     "total_equity",
    # ── Shares (special) ──────────────────────────────────────────────────────
    "number of shares":                 "^shares",
    "no. of shares":                    "^shares",
    "no of shares":                     "^shares",
    "number of ordinary shares":        "^shares",
}

_IS_MAP: dict[str, str] = {
    "net sales":                        "revenue",
    "net revenue":                      "revenue",
    "revenue from contracts":           "revenue",
    "sales - net":                      "revenue",
    "turnover":                         "revenue",
    "cost of sales":                    "cogs",
    "cost of goods sold":               "cogs",
    "cost of revenue":                  "cogs",
    "gross profit":                     "gross_profit",
    "distribution costs":               "dist_costs",
    "selling and distribution":         "dist_costs",
    "selling expenses":                 "dist_costs",
    "administrative expenses":          "admin_exp",
    "admin expenses":                   "admin_exp",
    "general and admin":                "admin_exp",
    "other income":                     "other_income",
    "other operating income":           "other_income",
    "operating profit":                 "ebit",
    "profit from operations":           "ebit",
    "earnings before interest and tax": "ebit",
    "ebit":                             "ebit",
    "finance costs":                    "finance_costs",
    "finance charges":                  "finance_costs",
    "financial charges":                "finance_costs",
    "interest expense":                 "finance_costs",
    "profit before tax":                "pbt",
    "pbt":                              "pbt",
    "taxation":                         "tax",
    "income tax":                       "tax",
    "profit after tax":                 "pat",
    "net profit":                       "pat",
    "profit for the year":              "pat",
    "earnings per share":               "~eps",
    "earning per share":                "~eps",
    "eps":                              "~eps",
    "dividend per share":               "~dps",
    "dps":                              "~dps",
    "depreciation and amortization":    "depreciation",
    "depreciation":                     "depreciation",
    "amortization":                     "depreciation",
}

_CF_MAP: dict[str, str] = {
    "cash generated from operations":   "cfo",
    "cash flows from operating":        "cfo",
    "net cash from operating":          "cfo",
    "net cash generated from operating":"cfo",
    "operating activities":             "cfo",
    "capital expenditure":              "capex",
    "purchase of property, plant":      "capex",
    "additions to property":            "capex",
    "additions to fixed assets":        "capex",
    "purchase of fixed assets":         "capex",
    "net cash used in investing":       "cfi",
    "investing activities":             "cfi",
    "dividends paid":                   "dividends_paid",
    "dividend paid":                    "dividends_paid",
    "net cash from financing":          "cff",
    "financing activities":             "cff",
    "cash at end of year":              "closing_cash",
    "cash at the end of the year":      "closing_cash",
    "closing cash":                     "closing_cash",
    "cash at end":                      "closing_cash",
    "free cash flow":                   "fcf",
    "depreciation and amortization":    "depreciation",
    "depreciation":                     "depreciation",
}

_EQ_MAP: dict[str, str] = {
    "cash dividend":                    "dividends_paid",
    "dividends paid":                   "dividends_paid",
    "dividend paid":                    "dividends_paid",
    "annual dividend per share":        "~dps",
    "dividend per share":               "~dps",
    "profit for the year":              "pat",
    "total equity":                     "total_equity",
    "shareholder equity":               "total_equity",
    "retained earnings":                "retained_earnings",
}

_RATIO_MAP: dict[str, str] = {
    "earnings per share":               "~eps",
    "earning per share":                "~eps",
    "eps":                              "~eps",
    "dividend per share":               "~dps",
    "dps":                              "~dps",
    "book value per share":             "~bvps",
    "book value/share":                 "~bvps",
    "current ratio":                    "~current_ratio_csv",
    "return on equity":                 "~roe_pct_csv",
    "return on assets":                 "~roa_pct_csv",
    "return on asset":                  "~roa_pct_csv",
    "debt/equity":                      "~de_ratio_csv",
    "debt to equity":                   "~de_ratio_csv",
    "price to earning":                 "~pe_hist",
    "price earnings":                   "~pe_hist",
    "market price":                     "~market_price_csv",
    "dividend yield":                   "~div_yield_pct",
    "payout ratio":                     "~payout_pct",
    "gross profit margin":              "~gpm_pct_csv",
    "net profit margin":                "~npm_pct_csv",
    "interest coverage":                "~icr_csv",
}

_FILE_MAPS: dict[str, dict] = {
    "bs":    _BS_MAP,
    "is":    _IS_MAP,
    "cf":    _CF_MAP,
    "eq":    _EQ_MAP,
    "ratio": _RATIO_MAP,
}


def _match_label(raw: str, mapping: dict[str, str]) -> str | None:
    """Match a CSV row label → internal key. Longer keywords take priority (avoids 'equity' beating 'total equity')."""
    clean = raw.lower().strip().lstrip("*•- ").strip()
    for kw in sorted(mapping, key=len, reverse=True):
        if kw in clean:
            return mapping[kw]
    return None


def _parse_num(cell) -> float | None:
    """Parse a CSV cell — handles commas, blanks, dashes."""
    s = str(cell).strip().replace(",", "").replace(" ", "")
    if s in ("", "-", "—", "N/A", "n/a", "nan", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_csv_financials(csv_bytes: bytes, file_type: str) -> dict[int, dict]:
    """
    Parse one khistocks.com financial CSV.
    Returns {year_int: {internal_key: value_in_PKR_millions}}.
    """
    import io as _io
    mapping = _FILE_MAPS.get(file_type, {})
    if not mapping:
        return {}

    df = None
    # Try tab-separated first (copy-paste from browser), then comma
    for sep in ("\t", ",", ";"):
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                candidate = pd.read_csv(
                    _io.BytesIO(csv_bytes), sep=sep, header=0, index_col=0,
                    encoding=enc, thousands=","
                )
                if candidate.shape[1] >= 2:   # must have at least 2 year columns
                    df = candidate
                    break
            except Exception:
                pass
        if df is not None:
            break
    if df is None or df.empty:
        return {}

    # Identify year columns (integers 2000–2035)
    year_cols: dict[int, str] = {}
    for col in df.columns:
        try:
            yr = int(str(col).strip().replace(",", "").split(".")[0])
            if 2000 <= yr <= 2035:
                year_cols[yr] = str(col)
        except ValueError:
            pass
    if not year_cols:
        return {}

    result: dict[int, dict] = {}

    for row_label in df.index:
        if pd.isna(row_label):
            continue
        internal_key = _match_label(str(row_label), mapping)
        if not internal_key:
            continue

        for yr, col_name in year_cols.items():
            try:
                raw = df.at[row_label, col_name]
            except Exception:
                continue
            v = _parse_num(raw)
            if v is None:
                continue

            if internal_key.startswith("^"):
                actual = internal_key[1:]       # "^shares" → "shares"
                scaled = v / 1_000_000          # units → millions of shares
            elif internal_key.startswith("~"):
                actual = internal_key[1:]       # "~eps" → "eps"
                scaled = v                      # per-share / ratio: no scaling
            elif internal_key.startswith("+"):
                actual = internal_key           # keep + prefix; combined below
                scaled = v / 1_000_000
            else:
                actual = internal_key
                scaled = v / 1_000_000          # PKR units → PKR millions

            result.setdefault(yr, {})[actual] = round(scaled, 3)

    # Post-process each year
    for yr, kv in result.items():
        stores = kv.pop("+stores", 0) or 0
        stock  = kv.pop("+stock",  0) or 0
        if "inventories" not in kv and (stores or stock):
            kv["inventories"] = round(stores + stock, 3)
        if "fcf" not in kv and "cfo" in kv and "capex" in kv:
            kv["fcf"] = round(kv["cfo"] + kv["capex"], 3)
        if "gross_profit" not in kv and "revenue" in kv and "cogs" in kv:
            kv["gross_profit"] = round(kv["revenue"] - kv["cogs"], 3)

    return result


def merge_csv_datasets(*datasets: dict[int, dict]) -> dict[int, dict]:
    """Merge multiple {year: {key: val}} dicts. Later datasets win on key conflicts."""
    merged: dict[int, dict] = {}
    for ds in datasets:
        for yr, kv in ds.items():
            merged.setdefault(yr, {}).update(kv)
    return merged


# ══════════════════════════════════════════════════════════════════════════════
# D.  AI EXTRACTION & ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def _get_ai_client():
    """Returns (client, 'groq') — Groq only. Never falls back to Anthropic."""
    groq_key = os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_KEY")
    if groq_key:
        try:
            from groq import Groq
            return Groq(api_key=groq_key), "groq"
        except Exception as e:
            logger.error("Groq client init failed: %s", e)
    return None, None


def ai_call(prompt: str, max_tokens: int = 4096) -> str | None:
    """Make an AI call. Returns the response text or None."""
    client, provider = _get_ai_client()
    if client is None:
        return None
    try:
        if provider == "groq":
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.1,
            )
            return resp.choices[0].message.content
        elif provider == "anthropic":
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text
    except Exception as e:
        logger.error("AI call failed: %s", e)
        return None


def ai_extract_financials(pdf_text: str, ticker: str) -> dict[int, dict] | None:
    """Send PDF text to AI and get structured financial data back."""
    # Truncate to avoid token limits — focus on financial statement pages
    # Search for the financial statements section first
    lower = pdf_text.lower()
    fs_start = -1
    for kw in ["statement of profit", "profit and loss", "income statement",
                "statement of financial position", "balance sheet"]:
        idx = lower.find(kw)
        if idx != -1 and (fs_start == -1 or idx < fs_start):
            fs_start = idx

    if fs_start > 0:
        relevant_text = pdf_text[max(0, fs_start - 500):fs_start + 15000]
    else:
        relevant_text = pdf_text[:16000]  # First 16k chars

    prompt = AI_EXTRACTION_PROMPT + relevant_text[:16000]
    raw = ai_call(prompt, max_tokens=4096)
    if not raw:
        return None

    # Parse JSON — handle markdown code blocks
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group())
            except Exception:
                return None
        else:
            return None

    if "data" not in parsed:
        return None

    result: dict[int, dict] = {}
    for year_str, kv in parsed["data"].items():
        try:
            yr = int(year_str)
        except ValueError:
            continue
        cleaned = {}
        for k, v in kv.items():
            if v is not None:
                try:
                    cleaned[k] = float(v)
                except (ValueError, TypeError):
                    pass
        # Compute FCF if not given
        if "fcf" not in cleaned and "cfo" in cleaned and "capex" in cleaned:
            cleaned["fcf"] = cleaned["cfo"] + cleaned["capex"]  # capex is negative in most reports
        result[yr] = cleaned

    return result if result else None


def ai_analyze_management(mda_text: str, ticker: str) -> dict | None:
    """Analyse MD&A / Directors Report text."""
    prompt = AI_MGMT_PROMPT + mda_text[:12000]
    raw = ai_call(prompt, max_tokens=2048)
    if not raw:
        return None
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# E.  FINANCIAL CALCULATORS & RATIOS
# ══════════════════════════════════════════════════════════════════════════════

def _g(d: dict, key: str, default: float = 0.0) -> float:
    """Safe getter — returns float or default."""
    v = d.get(key)
    return float(v) if v is not None else default


def derive_metrics(d: dict) -> dict:
    """Compute derived metrics not always explicit in the report."""
    out = dict(d)
    ta = _g(d, "total_assets", 1)
    equity = _g(d, "total_equity")
    pat = _g(d, "pat")
    rev = _g(d, "revenue")
    ebit = _g(d, "ebit")
    cfo = _g(d, "cfo")
    capex = _g(d, "capex")
    shares = _g(d, "shares")
    ca = _g(d, "total_ca")
    cl = _g(d, "total_cl")
    lt_debt = _g(d, "lt_debt")
    st_debt = _g(d, "st_debt")
    cash = _g(d, "cash")
    gp = _g(d, "gross_profit")

    if "gross_profit" not in d and "revenue" in d and "cogs" in d:
        out["gross_profit"] = rev - _g(d, "cogs")
        gp = out["gross_profit"]

    out["total_debt"] = lt_debt + st_debt
    out["net_debt"] = lt_debt + st_debt - cash
    out["working_capital"] = ca - cl
    out["fcf"] = d.get("fcf") or (cfo + capex)  # capex negative

    # Market-cap linked — computed later when price is known
    if shares > 0:
        out["bvps"] = equity / shares
        if pat != 0:
            out["roe"] = pat / max(equity, 1)
            out["roa"] = pat / ta
            out["eps_calc"] = pat / shares
        if rev > 0:
            out["gross_margin"] = gp / rev
            out["net_margin"] = pat / rev
            out["ebit_margin"] = ebit / rev
            out["asset_turnover"] = rev / ta
        if ca > 0 and cl > 0:
            out["current_ratio"] = ca / cl
        if rev > 0:
            out["interest_coverage"] = ebit / max(_g(d, "finance_costs"), 1)

    return out


def calc_ratios(curr: dict) -> dict[str, dict]:
    """
    Return a structured ratio dict:
      {category: [{name, value, benchmark, status}]}
    """
    d = derive_metrics(curr)
    ta = _g(d, "total_assets", 1)
    equity = _g(d, "total_equity", 1)

    def pct(v): return f"{v*100:.1f}%"
    def x(v):   return f"{v:.2f}x"
    def r(v):   return f"{v:.2f}"
    def na():   return "—"

    def status(v, good_min, ok_min):
        if v is None or v == 0:
            return "⚪"
        if v >= good_min:
            return "🟢"
        if v >= ok_min:
            return "🟡"
        return "🔴"

    ratios = {
        "📈 Profitability": [
            {"name": "Gross Margin",     "value": pct(d.get("gross_margin", 0)),    "bench": ">30%",  "status": status(d.get("gross_margin"), .30, .15)},
            {"name": "EBIT Margin",      "value": pct(d.get("ebit_margin", 0)),     "bench": ">15%",  "status": status(d.get("ebit_margin"), .15, .05)},
            {"name": "Net Margin",       "value": pct(d.get("net_margin", 0)),      "bench": ">10%",  "status": status(d.get("net_margin"), .10, .03)},
            {"name": "ROE",              "value": pct(d.get("roe", 0)),             "bench": ">15%",  "status": status(d.get("roe"), .15, .08)},
            {"name": "ROA",              "value": pct(d.get("roa", 0)),             "bench": ">5%",   "status": status(d.get("roa"), .05, .02)},
            {"name": "ROIC (approx)",    "value": pct(d.get("ebit", 0) * (1 - 0.29) / max(equity + _g(d, "total_debt"), 1)),
             "bench": ">10%", "status": "⚪"},
        ],
        "💧 Liquidity": [
            {"name": "Current Ratio",    "value": x(d.get("current_ratio", 0)),    "bench": ">1.5x", "status": status(d.get("current_ratio"), 1.5, 1.0)},
            {"name": "Quick Ratio",      "value": x((_g(d,"total_ca") - _g(d,"inventories")) / max(_g(d,"total_cl"), 1)),
             "bench": ">1.0x", "status": status((_g(d,"total_ca") - _g(d,"inventories")) / max(_g(d,"total_cl"), 1), 1.0, 0.7)},
            {"name": "Cash Ratio",       "value": x(_g(d,"cash") / max(_g(d,"total_cl"), 1)), "bench": ">0.2x", "status": "⚪"},
            {"name": "Working Capital",  "value": f"PKR {d.get('working_capital', 0):,.0f}M", "bench": ">0", "status": "🟢" if d.get("working_capital", 0) > 0 else "🔴"},
        ],
        "🏗️ Leverage": [
            {"name": "Debt/Equity",      "value": x(_g(d,"total_debt") / max(equity, 1)),  "bench": "<1.0x", "status": status(1 - _g(d,"total_debt")/max(equity, 1), 0, -1)},
            {"name": "Net Debt/EBITDA",  "value": r(_g(d,"net_debt") / max(_g(d,"ebit") * 1.3, 1)), "bench": "<3x",  "status": "⚪"},
            {"name": "Debt/Assets",      "value": pct(_g(d,"total_debt") / ta),             "bench": "<40%",  "status": "⚪"},
            {"name": "Interest Coverage","value": x(d.get("interest_coverage", 0)),         "bench": ">3x",   "status": status(d.get("interest_coverage"), 3.0, 1.5)},
            {"name": "Equity Ratio",     "value": pct(equity / ta),                         "bench": ">30%",  "status": status(equity / ta, .40, .25)},
        ],
        "⚙️ Efficiency": [
            {"name": "Asset Turnover",   "value": x(d.get("asset_turnover", 0)),    "bench": ">0.5x",  "status": status(d.get("asset_turnover"), 0.5, 0.3)},
            {"name": "Inventory Turns",  "value": x(_g(d,"cogs") / max(_g(d,"inventories"), 1)), "bench": ">4x", "status": "⚪"},
            {"name": "Receivables Days", "value": f"{365 / max(_g(d,'revenue') / max(_g(d,'receivables'), 1), 0.01):.0f} days",
             "bench": "<60d", "status": "⚪"},
            {"name": "Cash Conversion",  "value": pct(_g(d,"cfo") / max(_g(d,"pat"), 1)),  "bench": ">80%",  "status": status(_g(d,"cfo") / max(_g(d,"pat"), 1), 0.8, 0.5)},
        ],
    }
    return ratios


def calc_piotroski(curr: dict, prev: dict) -> tuple[int, list[dict]]:
    """Piotroski F-Score (0-9). Returns (score, signals_list)."""
    c = derive_metrics(curr)
    p = derive_metrics(prev) if prev else {}

    ta = max(_g(c, "total_assets"), 1)
    p_ta = max(_g(p, "total_assets"), 1)

    def sig(name, category, passed, value_str):
        return {"signal": name, "category": category, "passed": passed, "value": value_str}

    signals = []
    score = 0

    # Profitability
    roa = _g(c, "pat") / ta
    s = roa > 0
    signals.append(sig("F1 · ROA > 0", "Profitability", s, f"ROA = {roa*100:.1f}%"))
    score += s

    cfo = _g(c, "cfo")
    s = cfo > 0
    signals.append(sig("F2 · Operating Cash Flow > 0", "Profitability", s, f"CFO = {cfo:,.0f}M"))
    score += s

    roa_prev = _g(p, "pat") / p_ta if p else 0
    s = roa > roa_prev
    signals.append(sig("F3 · ROA improving YoY", "Profitability", s, f"Δ = {(roa - roa_prev)*100:+.1f}%"))
    score += s

    accrual = cfo / ta
    s = accrual > roa
    signals.append(sig("F4 · Cash Earnings > Accrual Earnings (CFO/Assets > ROA)", "Profitability", s, f"CFO/TA = {accrual*100:.1f}%"))
    score += s

    # Leverage & Liquidity
    lev = _g(c, "lt_debt") / ta
    lev_p = _g(p, "lt_debt") / p_ta if p else lev
    s = lev <= lev_p
    signals.append(sig("F5 · Long-term Leverage not increasing", "Leverage", s, f"LT Debt/TA = {lev*100:.1f}%"))
    score += s

    cr = _g(c, "total_ca") / max(_g(c, "total_cl"), 1)
    cr_p = _g(p, "total_ca") / max(_g(p, "total_cl"), 1) if p else cr
    s = cr >= cr_p
    signals.append(sig("F6 · Current Ratio improving", "Leverage", s, f"Current Ratio = {cr:.2f}x"))
    score += s

    sh = _g(c, "shares")
    sh_p = _g(p, "shares") if p else sh
    s = sh_p == 0 or sh <= sh_p * 1.01
    signals.append(sig("F7 · No share dilution", "Leverage", s, f"Shares = {sh:.1f}M"))
    score += s

    # Efficiency
    gm = _g(c, "gross_profit") / max(_g(c, "revenue"), 1)
    gm_p = _g(p, "gross_profit") / max(_g(p, "revenue"), 1) if p else gm
    s = gm >= gm_p
    signals.append(sig("F8 · Gross Margin improving", "Efficiency", s, f"GM = {gm*100:.1f}%"))
    score += s

    at_ = _g(c, "revenue") / ta
    at_p = _g(p, "revenue") / p_ta if p else at_
    s = at_ >= at_p
    signals.append(sig("F9 · Asset Turnover improving", "Efficiency", s, f"AT = {at_:.2f}x"))
    score += s

    return score, signals


def calc_altman_z(curr: dict, market_cap_m: float) -> tuple[float, str, dict]:
    """Altman Z-Score. Returns (z, zone, components)."""
    d = derive_metrics(curr)
    ta = max(_g(d, "total_assets"), 1)
    wc = _g(d, "working_capital")
    re_ = _g(d, "retained_earnings")
    ebit = _g(d, "ebit")
    tl = max(_g(d, "total_liabilities"), 1)
    rev = _g(d, "revenue")

    x1 = wc / ta
    x2 = re_ / ta
    x3 = ebit / ta
    x4 = market_cap_m / tl
    x5 = rev / ta

    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5

    if z > 2.99:
        zone = "🟢 Safe Zone (Z > 2.99)"
    elif z > 1.81:
        zone = "🟡 Grey Zone (1.81–2.99)"
    else:
        zone = "🔴 Distress Zone (Z < 1.81)"

    components = {
        "X1 (WC/Assets)":   round(x1, 3),
        "X2 (RE/Assets)":   round(x2, 3),
        "X3 (EBIT/Assets)": round(x3, 3),
        "X4 (Mkt/Liab)":    round(x4, 3),
        "X5 (Rev/Assets)":  round(x5, 3),
    }
    return round(z, 2), zone, components


def calc_dupont(curr: dict) -> dict:
    """DuPont ROE decomposition: ROE = Net Margin × Asset Turnover × Equity Multiplier."""
    d = derive_metrics(curr)
    nm = _g(d, "net_margin")
    at = _g(d, "asset_turnover")
    em = _g(d, "total_assets") / max(_g(d, "total_equity"), 1)
    roe = nm * at * em
    return {
        "Net Margin":        round(nm * 100, 2),
        "× Asset Turnover":  round(at, 3),
        "× Equity Multiplier": round(em, 3),
        "= ROE":             round(roe * 100, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# F.  VALUATION MODELS
# ══════════════════════════════════════════════════════════════════════════════

def _upside(price, value):
    if not price or not value:
        return None
    return round((value - price) / price * 100, 1)


def _mos(price, intrinsic):
    """Margin of safety %."""
    if not price or not intrinsic or intrinsic <= 0:
        return None
    return round((intrinsic - price) / intrinsic * 100, 1)


def calc_dcf(fcf: float, g1: float, g2: float, g_t: float, wacc: float,
             y1: int, y2: int, shares: float, net_debt: float) -> float | None:
    if wacc <= g_t or shares <= 0 or fcf == 0:
        return None
    pv, cf, t = 0.0, fcf, 0
    for _ in range(y1):
        t += 1; cf *= (1 + g1); pv += cf / (1 + wacc) ** t
    for _ in range(y2):
        t += 1; cf *= (1 + g2); pv += cf / (1 + wacc) ** t
    tv = cf * (1 + g_t) / (wacc - g_t)
    pv += tv / (1 + wacc) ** t
    return round((pv - net_debt) / shares, 2)


def calc_graham(eps: float, bvps: float) -> float | None:
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return None
    return round(math.sqrt(22.5 * eps * bvps), 2)


def calc_pe_val(eps: float, pe: float) -> float | None:
    return round(eps * pe, 2) if eps and pe and eps > 0 and pe > 0 else None


def calc_pb_val(bvps: float, pb: float) -> float | None:
    return round(bvps * pb, 2) if bvps and pb and bvps > 0 and pb > 0 else None


def calc_ev_ebitda_val(ebit: float, da_pct: float, net_debt: float, shares: float, multiple: float) -> float | None:
    """EV/EBITDA valuation. da_pct = D&A as % of revenue (estimate if unknown)."""
    if not ebit or not shares or shares <= 0:
        return None
    denom = max(1 - da_pct, 0.01)  # guard divide-by-zero when da_pct approaches 1
    ebitda = ebit / denom  # rough: EBITDA ≈ EBIT / (1 - D&A margin)
    ev = ebitda * multiple
    equity_val = ev - net_debt
    return round(equity_val / shares, 2) if equity_val > 0 else None


def calc_ddm(dps: float, roe: float, payout: float, wacc: float) -> float | None:
    """Gordon Growth DDM: P = DPS / (wacc - g)  where g = ROE × (1 - payout)."""
    if not dps or not wacc or dps <= 0:
        return None
    g = max(roe * (1 - payout), 0.0) if roe and payout else 0.04
    if wacc <= g:
        return None
    return round(dps / (wacc - g), 2)


def calc_epv(ebit: float, tax_rate: float, wacc: float, shares: float, net_debt: float) -> float | None:
    """Earnings Power Value: sustainable earnings capitalised at WACC (no growth assumed)."""
    if not ebit or not wacc or wacc <= 0 or shares <= 0:
        return None
    nopat = ebit * (1 - tax_rate)
    epv = nopat / wacc
    return round((epv - net_debt) / shares, 2)


# ── Advanced valuation methods ─────────────────────────────────────────────────

def calc_owner_earnings(pat: float, depreciation: float, maintenance_capex: float,
                         shares: float) -> float | None:
    """
    Buffett Owner Earnings = PAT + D&A − Maintenance CAPEX. All PKR millions.
    Returns PKR per share.
    """
    if not shares or shares <= 0:
        return None
    oe_total = pat + depreciation - abs(maintenance_capex)
    return round(oe_total / shares, 2)


def calc_graham_growth(eps: float, growth_pct: float, rf_pct: float = 9.0) -> float | None:
    """
    Graham Growth Formula: V = EPS × (8.5 + 2g) × (4.4 / Y)
    growth_pct: expected 5-yr EPS CAGR in % (e.g. 12 for 12%)
    rf_pct:     current AAA / PIB yield in % (adjust for Pakistan)
    """
    if not eps or eps <= 0 or rf_pct <= 0:
        return None
    return round(eps * (8.5 + 2 * growth_pct) * (4.4 / rf_pct), 2)


def calc_lynch_value(eps: float, growth_pct: float) -> float | None:
    """Peter Lynch: Fair P/E = growth rate. Value = EPS × growth_pct (PEG = 1.0)."""
    if not eps or eps <= 0 or not growth_pct or growth_pct <= 0:
        return None
    return round(eps * growth_pct, 2)


def calc_sotp(segments: list[dict], net_debt: float, shares: float) -> float | None:
    """
    Sum-of-Parts: sum segment EVs, subtract net debt, divide by shares.
    Each segment: {"name": str, "ev_m": float}  (ev_m in PKR millions)
    """
    if not segments or not shares or shares <= 0:
        return None
    total_ev = sum(float(s.get("ev_m") or 0) for s in segments)
    if total_ev <= 0:
        return None
    equity_val = total_ev - net_debt
    return round(equity_val / shares, 2) if equity_val > 0 else None


# ══════════════════════════════════════════════════════════════════════════════
# G.  STRESS TESTS
# ══════════════════════════════════════════════════════════════════════════════

def monte_carlo(base_fcf: float, g1: float, wacc: float, g_t: float,
                shares: float, net_debt: float, n: int = 5000) -> np.ndarray:
    """Run n DCF simulations with normally-distributed growth assumption."""
    rng = np.random.default_rng(42)
    g1_sims = rng.normal(g1, abs(g1) * 0.4, n)
    g2_sims = rng.normal(g1 * 0.5, abs(g1) * 0.3, n)
    wacc_sims = rng.normal(wacc, 0.01, n)

    results = []
    for g1s, g2s, ws in zip(g1_sims, g2_sims, wacc_sims):
        v = calc_dcf(base_fcf, g1s, g2s, g_t, max(ws, g_t + 0.01), 5, 5, shares, net_debt)
        if v is not None and v > 0:
            results.append(v)

    return np.array(results)


def sensitivity_table(base_fcf: float, base_g1: float, base_wacc: float,
                       g_t: float, shares: float, net_debt: float) -> pd.DataFrame:
    """
    Sensitivity: vary g1 and WACC ±30% from base.
    Returns a pivot table: WACC (rows) × Growth (cols).
    """
    g1_range = np.linspace(base_g1 * 0.4, base_g1 * 1.6, 5)
    wacc_range = np.linspace(base_wacc * 0.8, base_wacc * 1.2, 5)

    matrix = []
    for w in wacc_range:
        row = []
        for g in g1_range:
            v = calc_dcf(base_fcf, g, g * 0.5, g_t, max(w, g_t + 0.005), 5, 5, shares, net_debt)
            row.append(v or 0)
        matrix.append(row)

    cols = [f"g={g*100:.0f}%" for g in g1_range]
    idx  = [f"WACC={w*100:.1f}%" for w in wacc_range]
    return pd.DataFrame(matrix, index=idx, columns=cols)


def tornado_data(base_fcf: float, g1: float, wacc: float, g_t: float,
                  shares: float, net_debt: float) -> pd.DataFrame:
    """
    Tornado chart: show how ±20% change in each input swings the DCF value.
    """
    base = calc_dcf(base_fcf, g1, g1 * 0.5, g_t, wacc, 5, 5, shares, net_debt) or 0

    def swing(name, low_args, high_args):
        low  = calc_dcf(*low_args) or 0
        high = calc_dcf(*high_args) or 0
        return {"Input": name, "Low": low, "High": high, "Swing": abs(high - low)}

    rows = [
        swing("Phase-1 Growth",
              (base_fcf, g1 * 0.6,  g1 * 0.3,  g_t, wacc, 5, 5, shares, net_debt),
              (base_fcf, g1 * 1.4,  g1 * 0.7,  g_t, wacc, 5, 5, shares, net_debt)),
        swing("WACC",
              (base_fcf, g1, g1 * 0.5, g_t, wacc * 0.85, 5, 5, shares, net_debt),
              (base_fcf, g1, g1 * 0.5, g_t, wacc * 1.15, 5, 5, shares, net_debt)),
        swing("Terminal Growth",
              (base_fcf, g1, g1 * 0.5, max(g_t * 0.5, 0.01), wacc, 5, 5, shares, net_debt),
              (base_fcf, g1, g1 * 0.5, min(g_t * 1.5, wacc - 0.01), wacc, 5, 5, shares, net_debt)),
        swing("Base FCF",
              (base_fcf * 0.8, g1, g1 * 0.5, g_t, wacc, 5, 5, shares, net_debt),
              (base_fcf * 1.2, g1, g1 * 0.5, g_t, wacc, 5, 5, shares, net_debt)),
        swing("Net Debt",
              (base_fcf, g1, g1 * 0.5, g_t, wacc, 5, 5, shares, net_debt * 1.3),
              (base_fcf, g1, g1 * 0.5, g_t, wacc, 5, 5, shares, net_debt * 0.7)),
    ]
    df = pd.DataFrame(rows).sort_values("Swing", ascending=True)
    return df, base


# ══════════════════════════════════════════════════════════════════════════════
# H.  UI SECTION RENDERERS
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_m(v) -> str:
    """Format PKR millions value for display."""
    if v is None:
        return "—"
    v = float(v)
    if abs(v) >= 1000:
        return f"{v/1000:,.1f}B"
    return f"{v:,.1f}M"


def _color_cell(v, ref=None):
    """Return colored string for growth display."""
    if v is None or v == 0:
        return "—"
    v = float(v)
    if ref is not None:
        pct = (v - float(ref)) / max(abs(float(ref)), 1) * 100
        arrow = "▲" if pct > 0 else "▼"
        return f"{arrow} {pct:+.1f}%"
    return f"{v:+.1f}%"


def render_statements_tab(data: dict[int, dict]):
    """Tab: Financial Statements — multi-year with growth rates."""
    years = sorted(data.keys(), reverse=True)
    if not years:
        st.info("No financial data loaded yet.")
        return

    def make_table(key_list: list[tuple], section_name: str):
        rows = []
        for key, label in key_list:
            row = {"Line Item": label}
            for i, yr in enumerate(years):
                v = data[yr].get(key)
                row[str(yr)] = _fmt_m(v) if v is not None else "—"
                if i > 0 and v is not None:
                    prev = data[years[i]].get(key)
                    if prev and prev != 0:
                        pct = (v - prev) / abs(prev) * 100
                        row[f"YoY {yr}"] = f"{pct:+.1f}%"
            rows.append(row)
        df = pd.DataFrame(rows)

        # Bold separator rows (subtotals)
        subtotals = {"Gross Profit", "EBIT / Operating Profit", "Profit Before Tax (PBT)",
                     "Profit After Tax (PAT)", "TOTAL ASSETS", "TOTAL LIABILITIES",
                     "TOTAL EQUITY", "Free Cash Flow"}

        def style_row(row):
            styles = [""] * len(row)
            if row["Line Item"] in subtotals:
                styles = ["font-weight: bold; background-color: #f0f4f8"] * len(row)
            return styles

        st.markdown(f"**{section_name}** &nbsp; *(PKR Millions unless noted)*")
        st.dataframe(
            df.style.apply(style_row, axis=1),
            hide_index=True,
            use_container_width=True,
        )

    t_is, t_bs, t_cf = st.tabs(["📊 Income Statement", "🏦 Balance Sheet", "💸 Cash Flow"])

    with t_is:
        make_table(INCOME_KEYS, "Income Statement")
        # Revenue trend chart
        revs = {yr: data[yr].get("revenue") for yr in years if data[yr].get("revenue")}
        if len(revs) >= 2 and _PLOTLY_OK:
            fig = go.Figure()
            fig.add_bar(x=list(revs.keys()), y=[v / 1000 for v in revs.values()],
                        name="Revenue (PKR B)", marker_color="#3b82f6")
            pats = {yr: data[yr].get("pat") for yr in years if data[yr].get("pat")}
            if pats:
                fig.add_scatter(x=list(pats.keys()), y=[v / 1000 for v in pats.values()],
                                name="PAT (PKR B)", mode="lines+markers",
                                line=dict(color="#10b981", width=3),
                                yaxis="y2")
            fig.update_layout(
                title="Revenue & Profit After Tax", height=320, yaxis_title="PKR Billions",
                yaxis2=dict(overlaying="y", side="right", title="PAT"),
                legend=dict(orientation="h", y=1.12),
            )
            st.plotly_chart(fig, use_container_width=True)

    with t_bs:
        bs_keys_all = [(k, l) for k, l in BS_KEYS]
        make_table(bs_keys_all, "Balance Sheet")

    with t_cf:
        make_table(CF_KEYS, "Cash Flow Statement")
        # FCF trend chart
        fcfs = {yr: data[yr].get("fcf") for yr in years if data[yr].get("fcf")}
        if len(fcfs) >= 2 and _PLOTLY_OK:
            colors = ["#10b981" if v >= 0 else "#ef4444" for v in fcfs.values()]
            fig = go.Figure(go.Bar(
                x=list(fcfs.keys()), y=[v / 1000 for v in fcfs.values()],
                marker_color=colors, name="FCF"
            ))
            fig.update_layout(title="Free Cash Flow (PKR B)", height=280)
            st.plotly_chart(fig, use_container_width=True)


def render_health_tab(curr: dict, prev: dict, price: float):
    """Tab: Health Scorecard — Piotroski, Altman Z, DuPont, Ratios."""

    hc1, hc2, hc3 = st.columns(3)

    # ── Piotroski ──────────────────────────────────────────────────────────────
    with hc1:
        st.markdown("### Piotroski F-Score")
        score, signals = calc_piotroski(curr, prev)
        colour = "🟢" if score >= 7 else ("🟡" if score >= 5 else "🔴")
        verdict = "Strong" if score >= 7 else ("Average" if score >= 5 else "Weak")
        st.metric(f"{colour} Score", f"{score} / 9", delta=verdict)
        st.caption("8-9 = Strong Quality · 5-7 = Average · 0-4 = Weak")
        for cat in ["Profitability", "Leverage", "Efficiency"]:
            st.markdown(f"**{cat}**")
            for s in [x for x in signals if x["category"] == cat]:
                icon = "✅" if s["passed"] else "❌"
                st.markdown(f"{icon} {s['signal']}  \n`{s['value']}`")

    # ── Altman Z ───────────────────────────────────────────────────────────────
    with hc2:
        st.markdown("### Altman Z-Score")
        d = derive_metrics(curr)
        shares = _g(d, "shares")
        mktcap = price * shares if price and shares else 0
        z, zone, components = calc_altman_z(curr, mktcap)
        st.metric("Z-Score", str(z))
        st.markdown(f"**{zone}**")
        st.caption("Safe > 2.99 · Grey 1.81–2.99 · Distress < 1.81")
        st.markdown("**Components:**")
        for k, v in components.items():
            st.markdown(f"- {k}: `{v}`")

    # ── DuPont ─────────────────────────────────────────────────────────────────
    with hc3:
        st.markdown("### DuPont ROE Decomposition")
        dp = calc_dupont(curr)
        for label, val in dp.items():
            if label.startswith("="):
                st.metric(label, f"{val:.1f}%")
            else:
                st.markdown(f"**{label}:** `{val}`")
        st.caption("ROE = Net Margin × Asset Turnover × Equity Multiplier")

    st.divider()

    # ── Ratio Dashboard ────────────────────────────────────────────────────────
    st.markdown("### 📐 Ratio Dashboard")
    ratios = calc_ratios(curr)
    for cat, ratio_list in ratios.items():
        st.markdown(f"**{cat}**")
        cols = st.columns(len(ratio_list))
        for col, r in zip(cols, ratio_list):
            with col:
                st.metric(r["name"], r["value"])
                st.caption(f"Bench: {r['bench']}  {r['status']}")
        st.write("")


def render_valuation_tab(curr: dict, price: float, sector: str, ticker: str = ""):
    """Tab: Full Valuation Suite."""
    d = derive_metrics(curr)
    shares = _g(d, "shares")
    net_debt = _g(d, "net_debt")
    fcf = _g(d, "fcf")
    pat = _g(d, "pat")
    eps = _g(d, "eps") or (pat / shares if shares > 0 else 0)
    bvps = d.get("bvps") or (_g(d, "total_equity") / shares if shares > 0 else 0)
    dps = _g(d, "dps")
    ebit = _g(d, "ebit")
    roe = d.get("roe") or 0
    sector_mults = SECTOR_MULTIPLES.get(sector.upper() if sector else "DEFAULT",
                                        SECTOR_MULTIPLES["DEFAULT"])

    st.markdown("### 💰 Valuation Assumptions")
    va1, va2, va3 = st.columns(3)
    with va1:
        st.markdown("**DCF Growth Rates**")
        g1    = st.slider("Phase 1 Growth (%)", -10, 50, 15, key="vt_g1") / 100
        g2    = st.slider("Phase 2 Growth (%)", 0, 30, 8,  key="vt_g2") / 100
        g_t   = st.slider("Terminal Growth (%)", 1, 8, 4,  key="vt_gt") / 100
        y1    = st.slider("Phase 1 Years", 3, 7, 5, key="vt_y1")
        y2    = st.slider("Phase 2 Years", 3, 7, 5, key="vt_y2")
    with va2:
        st.markdown("**Discount & Multiples**")
        wacc  = st.slider("WACC (%)", 8, 25, 14, key="vt_wacc") / 100
        tgt_pe = st.number_input("Target P/E", value=sector_mults["pe"], min_value=1.0, step=0.5, key="vt_pe")
        tgt_pb = st.number_input("Target P/B", value=sector_mults["pb"], min_value=0.1, step=0.1, key="vt_pb")
        tgt_ev = st.number_input("Target EV/EBITDA", value=sector_mults["ev_ebitda"] or 6.0,
                                  min_value=1.0, step=0.5, key="vt_ev")
    with va3:
        st.markdown("**Other**")
        tax_r  = st.slider("Tax Rate (%)", 15, 40, 29, key="vt_tax") / 100
        da_pct = st.slider("D&A as % of Revenue (%)", 1, 15, 5, key="vt_da") / 100
        payout = st.slider("Dividend Payout Ratio (%)", 0, 100, 50, key="vt_payout") / 100
        fcf_override = st.number_input("FCF Override (PKR M, 0 = use from data)",
                                        value=0.0, min_value=-99999.0, step=100.0, key="vt_fcf_ov")

    # All monetary values from derive_metrics are already in PKR Millions.
    # calc_dcf / calc_epv / calc_ev_ebitda_val all expect PKR millions + shares in millions → output is PKR/share.
    # fcf_override label says "PKR M" so treat it directly as millions.
    base_fcf = fcf_override if fcf_override != 0 else (fcf if fcf else pat)  # PKR M

    st.divider()
    st.markdown("### 📊 Valuation Results")

    # Compute all methods
    dcf_val   = calc_dcf(base_fcf, g1, g2, g_t, wacc, y1, y2, shares, net_debt) if base_fcf and shares > 0 else None
    graham_v  = calc_graham(eps, bvps)
    pe_val    = calc_pe_val(eps, tgt_pe)
    pb_val    = calc_pb_val(bvps, tgt_pb)
    ev_val    = calc_ev_ebitda_val(ebit, da_pct, net_debt, shares, tgt_ev) if ebit and shares > 0 else None
    ddm_val   = calc_ddm(dps, roe, payout, wacc) if dps else None
    epv_val   = calc_epv(ebit, tax_r, wacc, shares, net_debt) if ebit and shares > 0 else None

    methods = [
        ("DCF (Two-Stage)", dcf_val, "Primary — based on free cash flow discounted at WACC"),
        ("Graham Number", graham_v, "Ben Graham's upper limit for defensive purchase (√22.5×EPS×BVPS)"),
        ("P/E Multiple", pe_val, f"EPS × {tgt_pe:.1f}x target P/E"),
        ("P/B Multiple", pb_val, f"BVPS × {tgt_pb:.1f}x target P/B"),
        ("EV/EBITDA", ev_val, f"EBITDA × {tgt_ev:.1f}x minus Net Debt / Shares"),
        ("DDM (Gordon Growth)", ddm_val, "Dividend Discount — only valid for dividend-paying stocks"),
        ("EPV (No-Growth)", epv_val, "Earnings Power Value — NOPAT/WACC (zero-growth conservative floor)"),
    ]

    # Summary table
    summary_rows = []
    valid_upsides = []
    for name, val, note in methods:
        if val is not None:
            up = _upside(price, val)
            mos = _mos(price, val)
            rating = ("🟢 Buy" if up and up >= 20 else
                      "🟡 Hold" if up and up >= 0 else
                      "🔴 Avoid") if up is not None else "⚪ N/A"
            summary_rows.append({
                "Method": name, "Fair Value (PKR)": f"{val:,.2f}",
                "Current Price": f"{price:,.2f}" if price else "—",
                "Upside": f"{up:+.1f}%" if up is not None else "—",
                "MoS": f"{mos:.1f}%" if mos is not None else "—",
                "Signal": rating, "Note": note,
            })
            if up is not None:
                valid_upsides.append(up)
        else:
            summary_rows.append({
                "Method": name, "Fair Value (PKR)": "—",
                "Current Price": "—", "Upside": "—", "MoS": "—",
                "Signal": "⚪ N/A", "Note": note,
            })

    st.dataframe(pd.DataFrame(summary_rows), hide_index=True, use_container_width=True)

    # Consensus
    if valid_upsides:
        avg_up = sum(valid_upsides) / len(valid_upsides)
        med_up = sorted(valid_upsides)[len(valid_upsides) // 2]
        c1, c2 = st.columns(2)
        c1.metric("Avg Upside across models", f"{avg_up:+.1f}%")
        c2.metric("Median Upside", f"{med_up:+.1f}%")

    # Value range bar chart
    vals = {n: v for n, v, _ in methods if v is not None}
    if price and vals and _PLOTLY_OK:
        fig = go.Figure()
        fig.add_bar(
            x=list(vals.keys()), y=list(vals.values()),
            marker_color=["#10b981" if v > price else "#ef4444" for v in vals.values()],
            name="Fair Value",
        )
        fig.add_hline(y=price, line_dash="dash", line_color="#f59e0b",
                      annotation_text=f"Market Price PKR {price:,.0f}", annotation_position="top right")
        fig.update_layout(title="Fair Value Estimates vs Market Price", height=350,
                          yaxis_title="PKR per share", xaxis_tickangle=-20)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.markdown("### 🔬 Advanced Valuation Methods")

    adv1, adv2 = st.columns(2)

    # ── Owner Earnings ─────────────────────────────────────────────────────────
    with adv1:
        st.markdown("**📐 Owner Earnings (Buffett)**")
        da_from_data = _g(d, "depreciation")
        da_input = st.number_input(
            "D&A — PKR M (auto-filled from CF/IS data)",
            value=float(da_from_data) if da_from_data else 0.0,
            step=100.0, key="vt_da_input")
        total_capex_abs = abs(_g(d, "capex") or 0)
        maint_pct = st.slider("Maintenance CAPEX (% of total CAPEX)", 20, 80, 40, 5, key="vt_maint_pct")
        maint_capex = total_capex_abs * maint_pct / 100
        st.caption(f"Total CAPEX: PKR {total_capex_abs:,.0f}M → Maintenance: PKR {maint_capex:,.0f}M")
        oe_val = calc_owner_earnings(pat, da_input, maint_capex, shares)
        if oe_val:
            oe_dcf = calc_dcf(pat + da_input - maint_capex, g1, g2, g_t, wacc, y1, y2, shares, net_debt)
            st.metric("Owner Earnings / Share", f"PKR {oe_val:,.2f}")
            if oe_dcf:
                up = _upside(price, oe_dcf)
                st.metric("Owner Earnings DCF", f"PKR {oe_dcf:,.2f}",
                          delta=f"{up:+.1f}% upside" if up is not None else None)
        else:
            oe_dcf = None
            st.caption("Enter D&A and ensure PAT + Shares are in the data.")

    # ── Graham Growth + Lynch ─────────────────────────────────────────────────
    with adv2:
        st.markdown("**📈 Growth-Based Valuations**")
        growth_input = st.number_input("Expected 5-yr EPS CAGR (%)",
                                        value=12.0, min_value=-20.0, max_value=60.0,
                                        step=1.0, key="vt_growth_input")
        rf_input = st.number_input("Risk-Free Rate / PIB Yield (%)",
                                    value=12.0, min_value=1.0, max_value=25.0,
                                    step=0.5, key="vt_rf_input")
        graham_g_val = calc_graham_growth(eps, growth_input, rf_input)
        lynch_val    = calc_lynch_value(eps, growth_input)
        if graham_g_val:
            up = _upside(price, graham_g_val)
            st.metric("Graham Growth Value", f"PKR {graham_g_val:,.2f}",
                      delta=f"{up:+.1f}%" if up is not None else None)
            st.caption(f"EPS {eps:.2f} × (8.5 + 2×{growth_input:.0f}%) × (4.4÷{rf_input:.0f}%)")
        if lynch_val:
            up = _upside(price, lynch_val)
            st.metric("Lynch Fair Value  (PEG = 1)", f"PKR {lynch_val:,.2f}",
                      delta=f"{up:+.1f}%" if up is not None else None)
            st.caption(f"EPS {eps:.2f} × {growth_input:.0f} = Fair P/E equals growth rate")

    st.divider()

    # ── SOTP Builder ───────────────────────────────────────────────────────────
    st.markdown("### 🏗️ Sum-of-Parts (SOTP)")
    st.caption("Value each business / investment separately. Essential for conglomerates.")

    sotp_key = f"_sotp_{ticker}"
    if sotp_key not in st.session_state:
        st.session_state[sotp_key] = [{"name": "Core Business", "ev_m": 0.0}]

    segs = st.session_state[sotp_key]
    if st.button("➕ Add Segment", key="sotp_add"):
        segs.append({"name": f"Segment {len(segs)+1}", "ev_m": 0.0})
        st.rerun()

    for i, seg in enumerate(segs):
        sc1, sc2, sc3 = st.columns([2, 2, 0.5])
        segs[i]["name"] = sc1.text_input("Segment / Asset",  seg["name"],  key=f"sotp_n_{i}")
        segs[i]["ev_m"] = float(sc2.number_input(
            "EV / Value (PKR M)", value=float(seg["ev_m"]), step=500.0, key=f"sotp_v_{i}"))
        if sc3.button("🗑️", key=f"sotp_del_{i}") and len(segs) > 1:
            segs.pop(i); st.rerun()

    sotp_val = calc_sotp(segs, net_debt, shares) if any(s["ev_m"] > 0 for s in segs) else None
    if sotp_val:
        total_ev_s = sum(s["ev_m"] for s in segs)
        up = _upside(price, sotp_val)
        st.metric("SOTP Intrinsic Value", f"PKR {sotp_val:,.2f}",
                  delta=f"{up:+.1f}% vs market" if up is not None else None)
        st.caption(
            f"Total EV: PKR {total_ev_s/1000:,.1f}B  ·  "
            f"Net Debt: PKR {net_debt/1000:,.1f}B  ·  "
            f"Equity: PKR {(total_ev_s-net_debt)/1000:,.1f}B  ·  "
            f"Shares: {shares:.0f}M")
    else:
        st.info("Enter segment values above to compute SOTP fair value.")

    st.divider()

    # ── Bull / Base / Bear Scenario Targets ────────────────────────────────────
    st.markdown("### 🎯 Bull / Base / Bear Price Targets")
    sc_bear, sc_base, sc_bull = st.columns(3)
    scenario_results: dict[str, float] = {}

    for col, label, icon, def_g, def_w in [
        (sc_bear, "Bear",  "🐻", max(g1 * 0.25, -0.03), min(wacc * 1.20, 0.30)),
        (sc_base, "Base",  "📊", g1,                      wacc),
        (sc_bull, "Bull",  "🐂", g1 * 1.60,               wacc * 0.88),
    ]:
        with col:
            st.markdown(f"**{icon} {label} Case**")
            sg = st.number_input(f"Growth (%)", value=round(def_g * 100, 1),
                                  step=1.0, format="%.1f", key=f"sc_{label}_g") / 100
            sw = st.number_input(f"WACC (%)",   value=round(def_w * 100, 1),
                                  step=0.5, format="%.1f", key=f"sc_{label}_w") / 100
            sv = calc_dcf(base_fcf, sg, sg * 0.5, g_t, max(sw, g_t + 0.005), y1, y2, shares, net_debt)
            if sv:
                up = _upside(price, sv)
                st.metric(f"{label} Value", f"PKR {sv:,.2f}",
                          delta=f"{up:+.1f}%" if up is not None else None)
                scenario_results[label] = sv

    if len(scenario_results) == 3 and price and _PLOTLY_OK:
        fig = go.Figure()
        colors = {"Bear": "#ef4444", "Base": "#3b82f6", "Bull": "#10b981"}
        fig.add_bar(x=list(scenario_results.keys()),
                    y=list(scenario_results.values()),
                    marker_color=[colors[k] for k in scenario_results], width=0.4)
        fig.add_hline(y=price, line_dash="dash", line_color="#f59e0b",
                      annotation_text=f"Market PKR {price:,.0f}")
        fig.update_layout(title="Scenario Targets vs Market Price", height=260,
                          yaxis_title="PKR / share", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    # Store for decision tab + stress test
    st.session_state["_val_models"] = {
        "dcf": dcf_val, "graham": graham_v, "pe": pe_val, "pb": pb_val,
        "ev": ev_val, "ddm": ddm_val, "epv": epv_val,
        "oe_dcf":   locals().get("oe_dcf"),
        "graham_g": locals().get("graham_g_val"),
        "lynch":    locals().get("lynch_val"),
        "sotp":     locals().get("sotp_val"),
        "bear": scenario_results.get("Bear"),
        "base": scenario_results.get("Base"),
        "bull": scenario_results.get("Bull"),
        "g1": g1, "g2": g2, "g_t": g_t, "wacc": wacc,
        "base_fcf": base_fcf, "shares": shares, "net_debt": net_debt,
    }


def render_stress_tab(curr: dict, price: float):
    """Tab: Stress Tests — Tornado, Scenario Matrix, Monte Carlo."""
    vm = st.session_state.get("_val_models", {})
    # base_fcf is stored in PKR millions (matches what calc_dcf expects)
    base_fcf_m = vm.get("base_fcf", 0)   # PKR M
    shares     = vm.get("shares", 1)
    net_debt_m = vm.get("net_debt", 0)   # PKR M
    g1   = vm.get("g1", 0.12)
    wacc = vm.get("wacc", 0.14)
    g_t  = vm.get("g_t", 0.04)

    if not base_fcf_m or not shares:
        st.warning("Complete the Valuation tab first to set base assumptions.")
        return

    st_t1, st_t2, st_t3 = st.tabs(["🌪️ Sensitivity Tornado", "📐 Scenario Matrix", "🎲 Monte Carlo"])

    with st_t1:
        st.markdown("**How much does each input move the DCF value?** (±20% perturbation)")
        tdf, base = tornado_data(base_fcf_m, g1, wacc, g_t, shares, net_debt_m)
        if base and _PLOTLY_OK:
            fig = go.Figure()
            fig.add_bar(
                y=tdf["Input"], x=tdf["High"] - base,
                orientation="h", name="Upside", marker_color="#10b981"
            )
            fig.add_bar(
                y=tdf["Input"], x=tdf["Low"] - base,
                orientation="h", name="Downside", marker_color="#ef4444"
            )
            fig.add_vline(x=0, line_width=2, line_color="#374151")
            fig.update_layout(
                title=f"Tornado Chart — Base DCF = PKR {base:,.2f}",
                barmode="overlay", height=350,
                xaxis_title="Change from Base Value (PKR)",
                legend=dict(orientation="h", y=1.12),
            )
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(tdf[["Input", "Low", "High", "Swing"]].style.format({
            "Low": "PKR {:,.2f}", "High": "PKR {:,.2f}", "Swing": "PKR {:,.2f}"
        }), hide_index=True, use_container_width=True)

    with st_t2:
        st.markdown("**DCF sensitivity: Phase-1 Growth (columns) × WACC (rows)**")
        tbl = sensitivity_table(base_fcf_m, g1, wacc, g_t, shares, net_debt_m)
        if _PLOTLY_OK and price:
            # Color relative to current price
            fig = px.imshow(
                tbl, text_auto=".0f",
                color_continuous_scale=["#ef4444", "#fbbf24", "#10b981"],
                aspect="auto", title="DCF Fair Value Matrix (PKR)"
            )
            fig.update_layout(height=320)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.dataframe(tbl.style.format("{:.0f}"), use_container_width=True)
        if price:
            st.caption(f"Values above PKR {price:,.0f} (current price) represent upside.")

    with st_t3:
        st.markdown("**5,000 random DCF scenarios — normally distributed growth rates**")
        if st.button("▶ Run Monte Carlo (5,000 simulations)", key="mc_run"):
            with st.spinner("Running 5,000 simulations…"):
                sim = monte_carlo(base_fcf_m, g1, wacc, g_t, shares, net_debt_m, n=5000)

            if len(sim) > 100 and _PLOTLY_OK:
                p10, p50, p90 = np.percentile(sim, [10, 50, 90])
                fig = go.Figure()
                fig.add_histogram(x=sim, nbinsx=80, name="Simulations",
                                   marker_color="#3b82f6", opacity=0.7)
                for val, label, color in [
                    (p10, f"P10 = PKR {p10:,.0f}", "#ef4444"),
                    (p50, f"P50 = PKR {p50:,.0f}", "#10b981"),
                    (p90, f"P90 = PKR {p90:,.0f}", "#6366f1"),
                ]:
                    fig.add_vline(x=val, line_dash="dash", line_color=color,
                                  annotation_text=label, annotation_position="top")
                if price:
                    fig.add_vline(x=price, line_width=2, line_color="#f59e0b",
                                  annotation_text=f"Market PKR {price:,.0f}", annotation_position="bottom right")
                fig.update_layout(title="Monte Carlo Fair Value Distribution",
                                  height=380, xaxis_title="DCF Value (PKR)", yaxis_title="Frequency")
                st.plotly_chart(fig, use_container_width=True)

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("P10 (Bear)", f"PKR {p10:,.0f}")
                col2.metric("P50 (Base)", f"PKR {p50:,.0f}")
                col3.metric("P90 (Bull)", f"PKR {p90:,.0f}")
                if price:
                    prob_above = (sim > price).mean() * 100
                    col4.metric("Prob. Above Market", f"{prob_above:.0f}%")


def render_ai_tab(ticker: str, year: int):
    """Tab: AI Management Commentary Analysis."""
    analysis = load_analysis(ticker, year)

    if not analysis:
        st.info("No AI analysis saved for this report yet. Upload a report and run analysis above.")
        return

    st.markdown(f"### 🤖 AI Analysis — {ticker} FY{year}")

    # Executive Summary
    if analysis.get("executive_summary"):
        st.info(f"**Executive Summary**\n\n{analysis['executive_summary']}")

    st.divider()

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**🚀 Growth Drivers**")
        for item in (analysis.get("growth_drivers") or []):
            st.markdown(f"✅ {item}")

        st.markdown("")
        st.markdown("**🏆 Competitive Position**")
        st.write(analysis.get("competitive_pos") or "—")

        st.markdown("")
        st.markdown("**💰 Capital Allocation**")
        st.write(analysis.get("capital_allocation") or "—")

    with c2:
        st.markdown("**⚠️ Key Risks**")
        for item in (analysis.get("risks") or []):
            st.markdown(f"⚠️ {item}")

        red_flags = analysis.get("red_flags") or []
        if red_flags:
            st.markdown("")
            st.markdown("**🚨 Red Flags**")
            for flag in red_flags:
                st.error(f"🚩 {flag}")

    st.divider()

    m_tone  = analysis.get("management_tone") or "—"
    m_score = analysis.get("outlook_score")
    key_mets = analysis.get("key_metrics") or {}

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Management Tone", m_tone)
    if m_score:
        mc2.metric("Outlook Score", f"{m_score} / 10")
    if key_mets:
        with mc3:
            st.markdown("**What mgmt highlighted:**")
            for k, v in (key_mets if isinstance(key_mets, dict) else {}).items():
                st.markdown(f"- {k}: **{v}**")

    # ── Extended qualitative fields ────────────────────────────────────────────
    segs   = analysis.get("segment_breakdown")
    assocs = analysis.get("associate_companies")
    oneoffs = analysis.get("one_off_items")
    capacity = analysis.get("capacity_info")
    export_mix = analysis.get("export_local_mix")
    fut_capex  = analysis.get("future_capex")
    norm_note  = analysis.get("normalized_pat_note")
    debt_mat   = analysis.get("debt_maturity")

    if any([segs, assocs, oneoffs, capacity, export_mix, fut_capex, debt_mat, norm_note]):
        st.divider()
        ex1, ex2 = st.columns(2)

        with ex1:
            if segs:
                st.markdown("**📊 Segment Breakdown**")
                for s in segs:
                    pct = s.get("revenue_share_pct", "?")
                    st.markdown(f"- **{s.get('segment','?')}** — {pct}%  \n"
                                f"  _{s.get('notes','')}_")

            if assocs:
                st.markdown("")
                st.markdown("**🏢 Associate Companies**")
                for a in assocs:
                    val_m = a.get("carrying_value_m")
                    val_str = f"  PKR {val_m:,.0f}M" if val_m else ""
                    st.markdown(f"- **{a.get('name','?')}** — {a.get('stake_pct','?')}% stake{val_str}  \n"
                                f"  _{a.get('notes','')}_")

            if capacity:
                st.markdown("")
                st.markdown("**🏭 Capacity & Operations**")
                st.write(capacity)
            if export_mix:
                st.markdown(f"**🌍 Export / Local Mix:** {export_mix}")

        with ex2:
            if oneoffs:
                st.markdown("**⚠️ One-Off P&L Items (Normalisation)**")
                for item in oneoffs:
                    amt = item.get("amount_m", 0)
                    st.markdown(f"- {item.get('description','?')} — PKR {amt:,.0f}M  \n"
                                f"  _{item.get('impact','')}_")
            if norm_note:
                st.info(f"**Normalised PAT:** {norm_note}")

            if debt_mat:
                st.markdown("")
                st.markdown("**📅 Debt Maturity**")
                st.write(debt_mat)
            if fut_capex:
                st.markdown("")
                st.markdown("**🔨 Future CAPEX Plans**")
                st.write(fut_capex)


def render_decision_tab(ticker: str, year: int, curr: dict, price: float):
    """Tab: Investment Decision — composite score + entry timing."""
    d = derive_metrics(curr)
    vm = st.session_state.get("_val_models", {})
    analysis = load_analysis(ticker, year)

    # Composite score (out of 100)
    score = 0
    breakdown = []

    # Quality (40 pts) — Piotroski (20) + Altman (10) + ROE (10)
    p_score, _ = calc_piotroski(curr, {})
    q_pts = round(p_score / 9 * 20)
    breakdown.append(("Piotroski F-Score", q_pts, 20, f"{p_score}/9"))
    score += q_pts

    shares = _g(d, "shares")
    mktcap = price * shares if price and shares else 0
    z, zone, _ = calc_altman_z(curr, mktcap)
    z_pts = 10 if z > 2.99 else (7 if z > 1.81 else 3)
    breakdown.append(("Altman Z-Score", z_pts, 10, f"Z = {z}"))
    score += z_pts

    roe = d.get("roe") or 0
    roe_pts = 10 if roe > 0.20 else (7 if roe > 0.12 else 4 if roe > 0.05 else 0)
    breakdown.append(("Return on Equity", roe_pts, 10, f"{roe*100:.1f}%"))
    score += roe_pts

    # Valuation (40 pts)
    upsides = [_upside(price, vm[k]) for k in ["dcf", "graham", "pe", "pb"]
               if vm.get(k) and price]
    upsides = [u for u in upsides if u is not None]
    if upsides:
        avg_up = sum(upsides) / len(upsides)
        v_pts = round(min(max((avg_up + 20) / 80 * 40, 0), 40))
    else:
        v_pts = 0
    breakdown.append(("Valuation Upside (avg)", v_pts, 40,
                      f"{sum(upsides)/len(upsides):+.1f}%" if upsides else "—"))
    score += v_pts

    # Outlook (20 pts) — from AI analysis
    if analysis:
        o_s = analysis.get("outlook_score") or 5
        o_pts = round(o_s / 10 * 20)
        rf = len(analysis.get("red_flags") or [])
        o_pts = max(0, o_pts - rf * 3)  # penalise red flags
    else:
        o_pts = 10  # neutral
    breakdown.append(("Management Outlook (AI)", o_pts, 20,
                      f"Score {analysis.get('outlook_score', '—') if analysis else '—'}/10"))
    score += o_pts

    # Final verdict
    if score >= 75:
        verdict = "🟢 STRONG BUY"
    elif score >= 60:
        verdict = "🟡 BUY"
    elif score >= 45:
        verdict = "🟠 WATCH"
    elif score >= 30:
        verdict = "🟠 HOLD"
    else:
        verdict = "🔴 AVOID"

    # Display
    dc1, dc2 = st.columns([1, 2])
    with dc1:
        st.metric("Composite Score", f"{score} / 100")
        st.markdown(f"## {verdict}")
        if price and upsides:
            dcf_v = vm.get("dcf")
            bear_v = vm.get("epv")
            bull_v = vm.get("ev")
            if dcf_v:
                st.metric("Base Fair Value (DCF)", f"PKR {dcf_v:,.2f}",
                           delta=f"{_upside(price, dcf_v):+.1f}% upside" if _upside(price, dcf_v) else None)

    with dc2:
        st.markdown("**Score Breakdown**")
        bdf = pd.DataFrame(breakdown, columns=["Component", "Score", "Max", "Detail"])
        bdf["% of Max"] = (bdf["Score"] / bdf["Max"] * 100).round(0).astype(int).astype(str) + "%"
        st.dataframe(bdf, hide_index=True, use_container_width=True)

    st.divider()

    # Entry Timing — check trade setups DB
    st.markdown("### ⏰ Entry Timing (from Trade DB)")
    st.caption("Strong fundamentals ✓ — now look for the right technical entry.")
    try:
        import sqlite3
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            setups = conn.execute("""
                SELECT * FROM trade_setups
                WHERE symbol=? AND status='Pending'
                ORDER BY created_date DESC LIMIT 5
            """, (ticker,)).fetchall()

        if setups:
            st.success(f"✅ {len(setups)} active pending setup(s) found in the DB for {ticker}")
            df_setups = pd.DataFrame([dict(r) for r in setups])
            show_cols = [c for c in ["symbol","created_date","entry","stop_loss","target",
                                     "risk_pct","source","kiran_score"] if c in df_setups.columns]
            st.dataframe(df_setups[show_cols], hide_index=True, use_container_width=True)
        else:
            st.info(f"No Pending setups in DB for {ticker}. "
                    "The Screener will generate one when the technical conditions align.")
    except Exception:
        st.info("Could not query trade setups DB.")

    st.divider()

    # Research journal
    st.markdown("### 📓 Save Research Finding")
    j1, j2 = st.columns([3, 1])
    with j1:
        thesis    = st.text_area("Investment thesis", height=100, key="dec_thesis")
        assumps   = st.text_area("Key assumptions", height=60, key="dec_assumps")
    with j2:
        conviction = st.select_slider("Conviction", [1,2,3,4,5], 3,
                                       format_func=lambda x: "⭐"*x, key="dec_conv")
        decision   = st.radio("Decision", ["Strong Buy","Buy","Watch","Pass","Avoid"],
                              index=2, key="dec_decision")

    if st.button("💾 Save Finding", type="primary", key="dec_save"):
        finding = {
            "ticker": ticker, "research_date": str(date.today()), "current_price": price,
            "dcf_value": vm.get("dcf"), "pe_value": vm.get("pe"), "pb_value": vm.get("pb"),
            "graham_value": vm.get("graham"),
            "bear_value": vm.get("epv"), "base_value": vm.get("dcf"), "bull_value": vm.get("ev"),
            "conviction": conviction, "decision": decision, "thesis": thesis, "assumptions": assumps,
        }
        rid = save_finding(finding)
        st.success(f"✅ Finding #{rid} saved — {decision} ({conviction}/5 conviction)")


# ══════════════════════════════════════════════════════════════════════════════
# I.  MAIN PAGE RENDERER
# ══════════════════════════════════════════════════════════════════════════════

def render_valuation_page():
    init_valuation_tables()

    st.markdown("### 💰 Fundamental Research Studio")
    st.caption(
        "Upload a company annual report PDF → AI extracts financial statements → "
        "run McKinsey-grade analysis: ratios, valuation, stress tests, management commentary, entry timing."
    )

    if not _PDF_OK:
        st.warning("Install pdfplumber for PDF extraction: `pip install pdfplumber`  "
                   "You can still enter data manually.")
    if not _PLOTLY_OK:
        st.warning("Install plotly for advanced charts: `pip install plotly`")

    # ── Company selection ──────────────────────────────────────────────────────
    all_cos = get_kse100()
    ticker_to_name = {c["symbol"]: c["company_name"] for c in all_cos}
    ticker_to_sector = {c["symbol"]: c.get("sector") or "DEFAULT" for c in all_cos}
    all_labels = [f"{c['symbol']} — {c['company_name']}" for c in all_cos]

    col_sym, col_yr, col_custom = st.columns([3, 1, 1])
    with col_sym:
        sel_label = st.selectbox("Company", all_labels, key="vs_ticker")
    with col_yr:
        sel_year  = st.number_input("Fiscal Year", value=2024, min_value=2000,
                                     max_value=2030, step=1, key="vs_year")
    with col_custom:
        custom = st.text_input("Or type symbol", placeholder="e.g. LUCK", key="vs_custom").strip().upper()

    ticker = custom if custom else (sel_label.split(" — ")[0] if sel_label else "")
    if not ticker:
        st.info("Select a company to begin.")
        return

    company_name = ticker_to_name.get(ticker, ticker)
    sector       = ticker_to_sector.get(ticker, "DEFAULT")
    price        = get_last_price(ticker)
    existing_yrs = get_years(ticker)

    # Header
    h1, h2, h3, h4 = st.columns([3, 1, 1, 1])
    with h1: st.markdown(f"## {company_name} &nbsp; `{ticker}`")
    with h2:
        if price: st.metric("Last Price", f"PKR {price:,.2f}")
        else:     st.metric("Last Price", "No price data")
    with h3:
        if price and existing_yrs:
            # Always use LATEST year's shares — current price × current share count
            all_fin = load_financials(ticker)
            latest_shares_yr = max(all_fin.keys()) if all_fin else sel_year
            shares_latest = _g(all_fin.get(latest_shares_yr, {}), "shares")
            mktcap = price * shares_latest / 1e3 if shares_latest else 0
            if mktcap: st.metric("Mkt Cap", f"PKR {mktcap:,.1f}B")
    with h4:
        st.metric("Years in DB", len(existing_yrs) if existing_yrs else "None")

    st.divider()

    # ── CSV Import (primary data source) ──────────────────────────────────────
    with st.expander("📊 Import Financial Data (CSV — primary)", expanded=not existing_yrs):
        st.markdown(
            "**Where to get the CSVs:** Go to [khistocks.com](https://www.khistocks.com), "
            f"search **{ticker}**, open Financial Data, and download all 5 tabs as CSV.  \n"
            "Upload all 5 below. Data typically covers 10–15 years in one go."
        )
        cv1, cv2 = st.columns(2)
        cv3, cv4 = st.columns(2)
        cv5, _   = st.columns(2)
        f_bs    = cv1.file_uploader("Balance Sheet",      type=["csv","txt"], key="csv_bs")
        f_is    = cv2.file_uploader("Income Statement",   type=["csv","txt"], key="csv_is")
        f_cf    = cv3.file_uploader("Cash Flow",          type=["csv","txt"], key="csv_cf")
        f_eq    = cv4.file_uploader("Equity Statement",   type=["csv","txt"], key="csv_eq")
        f_ratio = cv5.file_uploader("Ratios",             type=["csv","txt"], key="csv_ratio")

        csv_status_key = f"_csv_status_{ticker}"
        for lvl, msg in st.session_state.get(csv_status_key, []):
            getattr(st, lvl)(msg)

        if st.button("⚡ Import All CSVs", type="primary", key="csv_import_btn"):
            st.session_state[csv_status_key] = []
            log = st.session_state[csv_status_key]
            merged: dict[int, dict] = {}

            for fobj, ftype, fname in [
                (f_bs,    "bs",    "Balance Sheet"),
                (f_is,    "is",    "Income Statement"),
                (f_cf,    "cf",    "Cash Flow"),
                (f_eq,    "eq",    "Equity"),
                (f_ratio, "ratio", "Ratios"),
            ]:
                if fobj:
                    parsed = parse_csv_financials(fobj.read(), ftype)
                    if parsed:
                        yrs = sorted(parsed.keys())
                        log.append(("success",
                            f"✅ {fname}: {len(parsed)} years ({yrs[0]}–{yrs[-1]}), "
                            f"{sum(len(v) for v in parsed.values())} data points"))
                        merged = merge_csv_datasets(merged, parsed)
                    else:
                        log.append(("warning",
                            f"⚠️ {fname}: nothing extracted — check that 'Year' is the first column header"))

            if merged:
                save_financials(ticker, merged)
                all_yrs = sorted(merged.keys())
                log.append(("success",
                    f"✅ **Saved {len(all_yrs)} years of data** ({all_yrs[0]}–{all_yrs[-1]}) "
                    f"— {sum(len(v) for v in merged.values())} total data points"))
            else:
                log.append(("error", "No data imported. Upload at least one CSV file."))

            st.rerun()

    # ── PDF Upload (qualitative AI analysis only) ──────────────────────────────
    with st.expander("📄 Annual Report PDF — AI Qualitative Analysis", expanded=False):
        st.markdown(
            "Upload the **latest** annual report PDF. AI will extract: segment breakdown, "
            "associate companies, one-off P&L items, debt maturity, capacity, export/local mix, "
            f"future CAPEX plans.  \n"
            f"→ [Download from khistocks.com](https://www.khistocks.com/company-information/annual-reports/{ticker}.html)"
        )
        pdf_file = st.file_uploader("Annual Report PDF", type=["pdf"], key="vs_upload")
        ai_status_key = f"_ai_status_{ticker}"
        for lvl, msg in st.session_state.get(ai_status_key, []):
            getattr(st, lvl)(msg)

        if pdf_file and st.button("🤖 Run AI Qualitative Analysis", type="primary", key="vs_qual_btn"):
            st.session_state[ai_status_key] = []
            log = st.session_state[ai_status_key]

            if not _PDF_OK:
                log.append(("error", "pdfplumber not installed. Run: pip install pdfplumber"))
            else:
                with st.spinner("Extracting PDF text…"):
                    full_text, mda_text = extract_pdf_text(pdf_file.read())
                chars = len(full_text)
                log.append(("info", f"📄 Extracted **{chars:,} characters**"
                                     + ("" if chars > 5000 else " — PDF may be scanned/image-based")))
                if chars < 1000:
                    log.append(("error", "Too little text — try a text-based PDF."))
                else:
                    client, _ = _get_ai_client()
                    if client is None:
                        log.append(("error", "Groq key not found. Add GROQ_API_KEY to .env"))
                    else:
                        with st.spinner("AI analysing segments, notes, management tone…"):
                            mgmt = ai_analyze_management(full_text[:14000], ticker)
                        if mgmt:
                            save_analysis(ticker, sel_year, mgmt)
                            segs  = len(mgmt.get("segment_breakdown") or [])
                            assoc = len(mgmt.get("associate_companies") or [])
                            oneoff = len(mgmt.get("one_off_items") or [])
                            log.append(("success",
                                f"✅ Analysis saved — {segs} segments · {assoc} associates · "
                                f"{oneoff} one-off items identified"))
                        else:
                            log.append(("warning", "Could not parse AI analysis. Try again."))
            st.rerun()

    # ── Manual data entry ─────────────────────────────────────────────────────
    with st.expander("✏️ Manual Data Entry / Override", expanded=False):
        st.caption(f"Enter or correct financial data for {ticker} FY{sel_year}. All values in PKR Millions.")
        loaded = load_financials(ticker).get(sel_year, {})

        def _ni(label, key, cols):
            return cols.number_input(label, value=float(loaded.get(key) or 0.0),
                                      step=100.0, key=f"me_{key}")

        me_cols = st.columns(3)
        st.markdown("**Income Statement**")
        ic = st.columns(4)
        revenue   = _ni("Revenue",         "revenue",   ic[0])
        cogs      = _ni("Cost of Sales",   "cogs",      ic[1])
        ebit      = _ni("EBIT",            "ebit",      ic[2])
        pat       = _ni("PAT",             "pat",       ic[3])

        ic2 = st.columns(4)
        fin_costs = _ni("Finance Costs",   "finance_costs", ic2[0])
        pbt       = _ni("PBT",             "pbt",       ic2[1])
        eps_i     = _ni("EPS (PKR)",       "eps",       ic2[2])
        dps_i     = _ni("DPS (PKR)",       "dps",       ic2[3])

        st.markdown("**Balance Sheet**")
        bc = st.columns(4)
        total_assets = _ni("Total Assets", "total_assets", bc[0])
        total_eq   = _ni("Total Equity",   "total_equity", bc[1])
        lt_debt    = _ni("LT Debt",        "lt_debt",   bc[2])
        cash_i     = _ni("Cash",           "cash",      bc[3])

        bc2 = st.columns(4)
        ca_i    = _ni("Current Assets",    "total_ca",  bc2[0])
        cl_i    = _ni("Current Liab.",     "total_cl",  bc2[1])
        shares_i = _ni("Shares (M)",       "shares",    bc2[2])
        re_i    = _ni("Retained Earnings", "retained_earnings", bc2[3])

        st.markdown("**Cash Flow**")
        cc = st.columns(3)
        cfo_i   = _ni("Cash from Ops",     "cfo",       cc[0])
        capex_i = _ni("CAPEX (negative)",  "capex",     cc[1])
        fcf_i   = _ni("FCF",               "fcf",       cc[2])

        if st.button("💾 Save Manual Entry", key="me_save"):
            manual_data = {
                sel_year: {k: v for k, v in {
                    "revenue": revenue, "cogs": cogs, "ebit": ebit, "pat": pat,
                    "finance_costs": fin_costs, "pbt": pbt, "eps": eps_i, "dps": dps_i,
                    "total_assets": total_assets, "total_equity": total_eq,
                    "lt_debt": lt_debt, "cash": cash_i,
                    "total_ca": ca_i, "total_cl": cl_i,
                    "shares": shares_i, "retained_earnings": re_i,
                    "cfo": cfo_i, "capex": capex_i, "fcf": fcf_i,
                    "gross_profit": (revenue - cogs) if revenue and cogs else 0,
                }.items() if v != 0.0}
            }
            save_financials(ticker, manual_data)
            st.success(f"✅ Data saved for {ticker} FY{sel_year}")
            st.rerun()

    st.divider()

    # ── Analysis tabs ──────────────────────────────────────────────────────────
    all_data = load_financials(ticker)
    years_avail = sorted(all_data.keys(), reverse=True)

    if not years_avail:
        st.info("No financial data yet. Upload a PDF or fill in manual entry above.")
        return

    # Pick primary year
    primary_yr = sel_year if sel_year in all_data else years_avail[0]
    curr_data  = all_data[primary_yr]
    prev_yrs   = [y for y in years_avail if y < primary_yr]
    prev_data  = all_data[prev_yrs[0]] if prev_yrs else {}

    st.markdown(f"**Analysing: {company_name} — FY{primary_yr}** &nbsp; `{price and f'PKR {price:,.2f}' or 'No price'}`")
    # Detect share count change vs most recent year — warn about stock splits
    latest_yr = years_avail[0]
    if latest_yr != primary_yr:
        sh_curr  = _g(all_data.get(primary_yr, {}), "shares")
        sh_latest = _g(all_data.get(latest_yr, {}), "shares")
        if sh_curr and sh_latest and abs(sh_latest / max(sh_curr, 1) - 1) > 0.10:
            ratio = round(sh_latest / sh_curr, 2)
            st.warning(
                f"⚠️ **Share count changed** between FY{primary_yr} ({sh_curr:,.0f}M shares) "
                f"and FY{latest_yr} ({sh_latest:,.0f}M shares) — ratio {ratio}x "
                f"(likely stock split or bonus shares). "
                f"Valuations use FY{primary_yr} share count. "
                f"Switch year selector to FY{latest_yr} for current-share-count valuations."
            )
    if len(years_avail) > 1:
        st.caption(f"Multi-year data available: {years_avail}")

    tab_fs, tab_health, tab_val, tab_stress, tab_ai, tab_dec = st.tabs([
        "📊 Statements", "🏥 Health Score", "💰 Valuation",
        "🧪 Stress Test", "🤖 AI Insights", "🎯 Decision"
    ])

    with tab_fs:
        render_statements_tab(all_data)

    with tab_health:
        render_health_tab(curr_data, prev_data, price)

    with tab_val:
        render_valuation_tab(curr_data, price, sector, ticker)

    with tab_stress:
        render_stress_tab(curr_data, price)

    with tab_ai:
        render_ai_tab(ticker, primary_yr)

    with tab_dec:
        render_decision_tab(ticker, primary_yr, curr_data, price)

    st.divider()

    # ── Research Library ───────────────────────────────────────────────────────
    with st.expander("📚 Research Library", expanded=False):
        lib = get_library(ticker)
        if lib.empty:
            st.info("No saved findings yet.")
        else:
            st.dataframe(lib[[c for c in [
                "ticker","research_date","current_price","dcf_value","decision","conviction","thesis"
            ] if c in lib.columns]], hide_index=True, use_container_width=True)
