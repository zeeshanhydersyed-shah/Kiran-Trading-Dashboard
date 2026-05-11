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
