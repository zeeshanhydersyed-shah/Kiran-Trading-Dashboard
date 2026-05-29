import os

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

# Support Reversal Pattern Performance (Out-of-sample 2026)
SUPPORT_REVERSAL_STATS = {
    "name": "Support Reversal Pattern",
    "description": "Rejection candles at 200-MA support in uptrends",
    "win_rate_pct": 30.5,
    "loss_rate_pct": 69.5,
    "profit_factor": 1.95,
    "ev_pkr": None,  # Varies by position size
    "risk_reward": 5.03,
    "expectancy_pct": 5.21,
    "sample_size": "~1,800 signals",
    "date_range": "2026 (out-of-sample)",
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
SECTOR_OVERRIDES = {
    "GAL": "AUTOMOBILE ASSEMBLER",
}

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
