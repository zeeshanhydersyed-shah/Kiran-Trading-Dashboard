import os
import re

BASE_URL = "https://www.ksestocks.com"
MARKET_SUMMARY_URL = f"{BASE_URL}/MarketSummary"

DB_PATH = os.path.join(os.path.dirname(__file__), "psx_data.db")

# How many calendar days back to scan when building initial history
# 45 calendar days ~ 30+ trading days after excluding weekends/holidays
CALENDAR_DAYS_BACK = 45

# Target trading days for performance window
TRADING_DAYS_WINDOW = 30

# Polite delay between HTTP requests (seconds)
REQUEST_DELAY = 2.0

# Max retries on network errors
MAX_RETRIES = 3

# Scheduler: run at 16:30 PKT (PSX closes ~15:30, data updates shortly after)
SCHEDULER_HOUR = 16
SCHEDULER_MINUTE = 30
SCHEDULER_TIMEZONE = "Asia/Karachi"

# ---------------------------------------------------------------------------
# Trading System Benchmark (Your Current System Performance)
# Updated: 2026-05-21
# Source: Historical trading results
# ---------------------------------------------------------------------------
BENCHMARK = {
    "name": "Current System",
    "description": "Kiran's existing multi-pattern screener",
    "win_rate_pct": 48.0,
    "loss_rate_pct": 52.0,
    "profit_factor": 1.58,
    "ev_pkr": 1942,
    "risk_reward": 1.73,
    "expectancy_pct": 3.34,
    "sample_size": "100+ trades",
    "date_range": "2024-2026",
}

# Support Reversal Pattern — KILLED 2026-07-23
# Re-audit found the +5.21% expectancy was a look-ahead artefact: the "trailing stop"
# never simulated path ordering, retroactively taking max(favorable − 2%, return_20d).
# Full 21.5-year path-aware retest over all eras: -1.88% net. DEAD.
# Archive reference: C:\Users\Lenovo\RESEARCH_LOG.md line 36, verdict section.
SUPPORT_REVERSAL_STATS = {
    "name": "Support Reversal Pattern [KILLED]",
    "description": "Rejection candles at 200-MA support — disproven 2026-07-23, -1.88% net full period",
    "win_rate_pct": 29.1,  # Full-period path-aware, not dead 30.5
    "loss_rate_pct": 70.9,
    "profit_factor": None,  # Does not apply to negative EV
    "ev_pkr": None,
    "risk_reward": 1.51,  # Full-period, not dead 5.03
    "expectancy_pct": -1.88,  # Net of costs, not dead +5.21
    "sample_size": "16,425 filled (full 21.5-year retest)",
    "date_range": "2005-01-01 → 2026-06-05 (all eras negative)",
}

# HTTP headers to mimic a browser visit
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.ksestocks.com/",
}

# Symbols to skip (market-wide indices, not individual stocks)
INDEX_SYMBOLS = {"KSE-100", "KSE-30", "KSE-ALL", "KSE-MI30", "KSE-MIALL"}

# ---------------------------------------------------------------------------
# DFC-eligible symbols (Deliverable Futures Contract market, PSX)
# Only these stocks can be shorted. List reviewed and updated every quarter.
# Last updated: 2026-Q2
# ---------------------------------------------------------------------------
DFC_SYMBOLS = {
    "AGHA", "AGL",     "AGP",     "AICL",   "AIRLINK", "AKBL",   "ASL",
    "ATRL", "AVN",     "BAFL",    "BAHL",   "BIPL",    "BML",    "BOP",
    "CHCC", "CNERGY",  "CPHL",    "CSAP",   "DCL",     "DCR",    "DFML",
    "DGKC", "EFERT",   "ENGROH",  "EPCL",   "FABL",    "FATIMA", "FCCL",
    "FCEPL","FCL",     "FFC",     "FFL",    "FLYNG",   "GAL",    "GATM",
    "GCIL", "GGL",     "GHGL",    "GHNI",   "GLAXO",   "HBL",    "HUBC",
    "HUMNL","ILP",     "IMAGE",   "INIL",   "ISL",     "JSGBETF","JSMFETF",
    "KAPCO","KEL",     "KOHC",    "KOSM",   "LOTCHEM", "LUCK",   "MARI",
    "MCB",  "MEBL",    "MLCF",    "MTL",    "MUGHAL",  "MZNPETF","NATF",
    "NBP",  "NBPGETF", "NCPL",    "NETSOL", "NITGETF", "NML",    "NPL",
    "NRL",  "OCTOPUS", "OGDC",    "PACE",   "PAEL",    "PIAHCLA","PIBTL",
    "PIOC", "POL",     "POWER",   "PPL",    "PREMA",   "PRL",    "PSO",
    "PTC",  "SAZEW",   "SEARL",   "SNBL",   "SNGP",    "SSGC",   "SYM",
    "SYS",  "TELE",    "TGL",     "THCCL",  "TOMCL",   "TPLP",   "TREET",
    "TRG",  "UBL",     "UNITY",   "UPLPETF","WAVES",   "WAVESAPP","WTL",
    "YOUW",
}

# Sectors excluded from performance rankings.
# Includes derivatives, financials-of-financials, and sectors with thin/noisy data.
# Symbols whose sector is wrong on ksestocks.com and must be overridden.
# GAL (Ghandhara Automobiles) lands in the site's "Unknown Sector" bucket
# even though PSX officially classifies it as an Automobile Assembler.
#
# 2026-08-27 sector-mapping fix: ksestocks.com misclassifies the symbols below
# into "Unknown Sector" or a stale label. Corrected here so the scraper writes
# the right sector into the `sectors` table, and so they flow into
# stock_metadata / the signal tables. APPAREL is a deliberate new local sector
# (not a ksestocks.com label), so these overrides are load-bearing — there is
# no scraped value to fall back to.
SECTOR_OVERRIDES = {
    "GAL":      "AUTOMOBILE ASSEMBLER",
    "SYM":      "TECHNOLOGY & COMMUNICATION",
    "BML":      "COMMERCIAL BANKS",
    "FCL":      "CABLE & ELECTRICAL GOODS",
    "WAVESAPP": "CABLE & ELECTRICAL GOODS",
    "MSOT":     "APPAREL",   # was TEXTILE COMPOSITE
    "INKL":     "APPAREL",   # was TEXTILE COMPOSITE
    "IMAGE":    "APPAREL",   # was SYNTHETIC & RAYON (stale label)
}

# Symbols the ksestocks.com feed drops into "Unknown Sector" (or an excluded
# sector) that we nonetheless track and wire fully into stock_metadata + the
# signal tables. Their real sector comes from SECTOR_OVERRIDES above. This is a
# hard include-list: build_stock_metadata.py adds these regardless of what the
# scraped `sectors` row currently says.
UNIVERSE_WHITELIST = {"SYM", "BML", "FCL", "WAVESAPP"}

# ---------------------------------------------------------------------------
# Non-equity instruments — must never enter prices / prices_adjusted.
# ---------------------------------------------------------------------------
# PSX single-stock & index futures: BASE-MON, BASE-MONB/C/D (parallel series),
# BASE-CMON (cash-settled / hand-delivery series). The historical filter only
# caught the bare BASE-MON form and leaked every suffixed variant into both
# `prices` and the `sectors` table.
_FUT_MONTHS = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
FUTURES_SYMBOL_RE = re.compile(rf"^[A-Z0-9]+-C?(?:{_FUT_MONTHS})[A-Z]?$")

# Government debt paper listed on PSX: P<tenor:2d><type:3a><maturity:6d>,
# e.g. P01GIS200826, P05FRR300530, P10FRZ220136. Filtered only downstream in
# the screener today, never at ingestion.
GOVT_PAPER_SYMBOL_RE = re.compile(r"^P\d{2}[A-Z]{3}\d{6}$")

# Other non-equity tickers seen in the feed.
NON_EQUITY_SYMBOLS = {"786", "786R"}


def is_non_equity_symbol(symbol: str) -> bool:
    """True for PSX futures (all series), government paper, and misc non-equity
    tickers that must never enter prices / prices_adjusted."""
    s = (symbol or "").strip().upper()
    if not s:
        return False
    return (
        s in NON_EQUITY_SYMBOLS
        or bool(GOVT_PAPER_SYMBOL_RE.match(s))
        or bool(FUTURES_SYMBOL_RE.match(s))
    )

# ---------------------------------------------------------------------------
# Agent preferences — edit these to match your personal trading style
# ---------------------------------------------------------------------------

# Minimum average daily volume (shares) for a stock to be considered by the agent.
# Protects against thin/illiquid stocks like STML.
AGENT_MIN_VOLUME = 50_000

# Maximum stop-loss % the agent should suggest. Setups wider than this are skipped.
# You said ~6% is your max — the agent will not suggest anything wider.
AGENT_MAX_SL_PCT = 6.0

# Sectors you personally trade in. Agent will PRIORITISE these.
# Leave empty [] to let the agent consider all non-excluded sectors.
AGENT_PREFERRED_SECTORS = [
    # Examples — uncomment / add your actual preferred sectors:
    # "CEMENT",
    # "COMMERCIAL BANKS",
    # "OIL & GAS EXPLORATION COMPANIES",
    # "FERTILIZER",
    # "TECHNOLOGY & COMMUNICATION",
]

# Sectors you never trade. Agent will skip stocks from these entirely.
AGENT_AVOIDED_SECTORS: set = set()  # add sector names as strings if needed

# ---------------------------------------------------------------------------
# Sectors excluded from performance rankings.
# Includes derivatives, financials-of-financials, and sectors with thin/noisy data.
EXCLUDED_SECTORS = {
    "CLOSE - END MUTUAL FUND",
    "INV. BANKS / INV. COS. / SECURITIES COS.",
    "LEASING COMPANIES",
    "LEATHER & TANNERIES",
    "MODARABAS",
    "SUGAR & ALLIED INDUSTRIES",
    "SYNTHETIC & RAYON",
    "TEXTILE SPINNING",
    "TEXTILE WEAVING",
    "TOBACCO",
    "VANASPATI & ALLIED INDUSTRIES",
    "WOOLLEN",
    "Unknown Sector",
    "FUTURE CONTRACTS",
    "STOCK INDEX FUTURE CONTRACTS",
}
