"""
Cross-verify OGDC prices by scraping directly from source for key dates.
"""
import sys, requests
sys.path.insert(0, r"C:\Users\Lenovo\psx_pipeline")
from bs4 import BeautifulSoup
from config import MARKET_SUMMARY_URL, REQUEST_HEADERS

def scrape_ogdc_for_date(date_str):
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    resp = session.post(MARKET_SUMMARY_URL, data={"sdate": date_str}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")
    data_table = tables[-1] if tables else None
    if not data_table:
        return None

    current_sector = None
    for row in data_table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        if len(cells) == 2:
            txt = cells[1].get_text(strip=True)
            if "Number of traded companies" in txt or txt == "":
                current_sector = cells[0].get_text(strip=True)
            continue
        if len(cells) == 8:
            symbol = cells[0].get_text(strip=True)
            if symbol == "OGDC":
                high   = cells[3].get_text(strip=True).replace(",","")
                low    = cells[4].get_text(strip=True).replace(",","")
                close  = cells[5].get_text(strip=True).replace(",","")
                vol    = cells[7].get_text(strip=True).replace(",","")
                return {
                    "date": date_str,
                    "sector": current_sector,
                    "high": high, "low": low, "close": close, "volume": vol
                }
    return None

check_dates = [
    "2025-05-09",   # user's start date
    "2025-05-12",
    "2025-05-13",   # big spike day
    "2025-07-31",   # breakout day
    "2025-08-01",   # explosion day
    "2025-08-04",   # user's end date
]

print(f"\n{'Date':<12}  {'Sector':<30}  {'High':>8}  {'Low':>8}  {'Close':>8}  {'Volume':>12}")
print("-" * 82)
for d in check_dates:
    result = scrape_ogdc_for_date(d)
    if result:
        print(f"{result['date']:<12}  {result['sector']:<30}  {result['high']:>8}  {result['low']:>8}  {result['close']:>8}  {result['volume']:>12}")
    else:
        print(f"{d:<12}  NOT FOUND")
