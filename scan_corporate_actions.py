"""
Corporate Action Suspect Scanner — PSX
=======================================
Scans the clean 473-symbol universe for price drops >7.5% isolated from
sector peers. Threshold lowered from 15% because PSX circuit breaker makes
anything above 7.5% an anomaly worth reviewing.

READ-ONLY — no writes to psx_data.db.

Run:
    python scan_corporate_actions.py

Output:
    corporate_action_suspects_clean.csv  (in the same directory)
"""

import sqlite3
import os
import csv
from datetime import datetime
from collections import defaultdict

DB_PATH   = os.path.join(os.path.dirname(__file__), "psx_data.db")
OUT_PATH  = os.path.join(os.path.dirname(__file__), "corporate_action_suspects_clean.csv")

# ── thresholds ──────────────────────────────────────────────────────────────
# PSX circuit breaker history:
#   pre-2024  → 7.5%   (flag drops > 7.5%)
#   2024+     → 10.0%  (flag drops > 10%)
THRESHOLD_PRE_2024  = -7.5
THRESHOLD_2024_PLUS = -10.0
CUTOFF_DATE         = "2024-01-01"

PEER_ISOLATION      = -5.0    # peer average must be > this (not a market crash)
MIN_PEERS           = 3       # minimum peers required for isolation check

# ── excluded sectors (clean 473 universe) ───────────────────────────────────
EXCLUDE_SECTORS = {
    "FUTURE CONTRACTS",
    "STOCK INDEX FUTURE CONTRACTS",
    "Unknown Sector",
    "TEXTILE SPINNING",
    "TEXTILE COMPOSITE",
    "MODARABAS",
    "SUGAR & ALLIED INDUSTRIES",
    "INV. BANKS / SECURITIES COS.",
    "INV. BANKS / INV. COS. / SECURITIES COS.",
}

# magnitude buckets  (pct_change ranges, all negative)
BUCKET_50 = (-55.0, -45.0)   # ~1:1 bonus
BUCKET_33 = (-37.0, -30.0)   # ~1:2 bonus
BUCKET_25 = (-28.0, -22.0)   # ~1:3 bonus

PROGRESS_EVERY = 50           # print a progress line every N symbols


# ── helpers ─────────────────────────────────────────────────────────────────

def magnitude_category(pct: float) -> tuple[str, str]:
    """Return (magnitude_category, likely_action) for a pct_change value."""
    lo, hi = pct, pct          # pct is already negative
    if BUCKET_50[0] <= pct <= BUCKET_50[1]:
        return "DROP_50", "Bonus 1:1"
    if BUCKET_33[0] <= pct <= BUCKET_33[1]:
        return "DROP_33", "Bonus 1:2"
    if BUCKET_25[0] <= pct <= BUCKET_25[1]:
        return "DROP_25", "Bonus 1:3"
    return "DROP_OTHER", "Rights/Dividend"


# ── main ────────────────────────────────────────────────────────────────────

def main():
    t_start = datetime.now()
    print("=" * 60)
    print("PSX Corporate Action Suspect Scanner")
    print(f"Started: {t_start:%Y-%m-%d %H:%M:%S}")
    print("=" * 60)

    # ── Step 1 — Reconnaissance ─────────────────────────────────────────────
    print("\n=== STEP 1: RECONNAISSANCE ===")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM prices")
    price_rows = cur.fetchone()[0]
    print(f"prices rows:        {price_rows:>12,}")

    cur.execute("SELECT MIN(date), MAX(date) FROM prices")
    min_date, max_date = cur.fetchone()
    print(f"prices date range:  {min_date} → {max_date}")

    cur.execute("SELECT COUNT(DISTINCT symbol) FROM sectors")
    n_sector_syms = cur.fetchone()[0]
    print(f"sectors symbols:    {n_sector_syms:>12,}")

    cur.execute("SELECT DISTINCT symbol FROM sectors WHERE sector NOT IN ({}) ORDER BY symbol".format(
        ",".join("?" * len(EXCLUDE_SECTORS))
    ), list(EXCLUDE_SECTORS))
    universe = [r[0] for r in cur.fetchall()]
    print(f"Universe size:      {len(universe):>12,}  (excluded sectors filtered)")

    # ── Step 2 — Build sector peer map ──────────────────────────────────────
    print("\n=== STEP 2: SECTOR PEER MAP ===")
    cur.execute("SELECT symbol, sector FROM sectors")
    sym_to_sector = dict(cur.fetchall())

    sector_to_syms = defaultdict(list)
    for sym, sec in sym_to_sector.items():
        sector_to_syms[sec].append(sym)

    n_sectors = len(sector_to_syms)
    avg_per_sector = sum(len(v) for v in sector_to_syms.values()) / n_sectors
    print(f"Sectors:            {n_sectors:>12,}")
    print(f"Avg symbols/sector: {avg_per_sector:>12.1f}")

    # ── Step 3 — Load all price data into memory ─────────────────────────────
    print("\n=== STEP 3: LOADING PRICE DATA ===")
    universe_set = set(universe)
    cur.execute(
        "SELECT symbol, date, close FROM prices "
        "WHERE symbol IN ({}) "
        "ORDER BY symbol, date".format(",".join("?" * len(universe))),
        universe,
    )

    # prices_by_symbol: sym → [(date, close), ...]  (already sorted by date)
    prices_by_symbol = defaultdict(list)
    total_rows = 0
    for sym, date, close in cur.fetchall():
        prices_by_symbol[sym].append((date, close))
        total_rows += 1
    print(f"Loaded {total_rows:,} rows for {len(prices_by_symbol):,} symbols")

    # Build a lookup: (sym, date) → close  — for peer average computation
    close_lookup = {}
    for sym, rows in prices_by_symbol.items():
        for date, close in rows:
            close_lookup[(sym, date)] = close

    con.close()

    # ── Step 4 — Scan for suspects ───────────────────────────────────────────
    print("\n=== STEP 4: SCANNING ===")

    suspects        = []
    skipped_small   = 0
    errors          = 0

    for idx, sym in enumerate(universe, 1):
        if idx % PROGRESS_EVERY == 0 or idx == len(universe):
            print(f"  [{idx:>4}/{len(universe)}] scanned so far …  suspects={len(suspects)}")

        rows = prices_by_symbol.get(sym)
        if not rows or len(rows) < 2:
            continue

        sector = sym_to_sector.get(sym, "UNKNOWN")
        peers  = [s for s in sector_to_syms.get(sector, []) if s != sym]

        try:
            for i in range(1, len(rows)):
                date_prev, close_prev = rows[i - 1]
                date_cur,  close_cur  = rows[i]

                if close_prev is None or close_prev == 0 or close_cur is None:
                    continue

                pct = (close_cur - close_prev) / close_prev * 100.0

                threshold = THRESHOLD_2024_PLUS if date_cur >= CUTOFF_DATE else THRESHOLD_PRE_2024
                if pct >= threshold:
                    continue  # within circuit breaker range — not suspicious

                # Compute peer average on date_cur
                peer_pcts = []
                for p in peers:
                    p_cur  = close_lookup.get((p, date_cur))
                    p_prev = close_lookup.get((p, date_prev))
                    if p_cur is None or p_prev is None or p_prev == 0:
                        continue
                    peer_pcts.append((p_cur - p_prev) / p_prev * 100.0)

                if len(peer_pcts) < MIN_PEERS:
                    skipped_small += 1
                    continue

                peer_avg = sum(peer_pcts) / len(peer_pcts)

                if peer_avg <= PEER_ISOLATION:
                    continue  # market-wide or sector-wide event — skip

                # Confirmed suspect
                mag_cat, likely_action = magnitude_category(pct)

                suspects.append({
                    "symbol":             sym,
                    "date":               date_cur,
                    "close_before":       round(close_prev, 4),
                    "close_after":        round(close_cur,  4),
                    "pct_change":         round(pct, 2),
                    "peer_avg_change":    round(peer_avg, 2),
                    "magnitude_category": mag_cat,
                    "likely_action":      likely_action,
                    "peers_used":         len(peer_pcts),
                    "sector":             sector,
                    "review_status":      "PENDING",
                })

        except Exception as e:
            errors += 1
            print(f"  ERROR on {sym}: {e}")

    # sort
    suspects.sort(key=lambda r: (r["symbol"], r["date"]))

    # ── Step 5 — Write CSV ───────────────────────────────────────────────────
    print("\n=== STEP 5: WRITING CSV ===")
    fieldnames = [
        "symbol", "date", "close_before", "close_after", "pct_change",
        "peer_avg_change", "magnitude_category", "likely_action",
        "peers_used", "sector", "review_status",
    ]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(suspects)
    print(f"Written: {OUT_PATH}")
    print(f"Rows:    {len(suspects):,}")

    # ── Step 6 — Summary Report ──────────────────────────────────────────────
    print("\n=== SUMMARY REPORT ===")
    print(f"Symbols scanned:            {len(universe):,}")
    print(f"Suspect dates found:        {len(suspects):,}")
    print(f"Skipped (small sector):     {skipped_small:,}")
    print(f"Symbol errors:              {errors:,}")

    # by magnitude
    print("\nBreakdown by magnitude:")
    from collections import Counter
    mag_counts = Counter(s["magnitude_category"] for s in suspects)
    for cat, cnt in sorted(mag_counts.items()):
        print(f"  {cat:<15} {cnt:>4}")

    # by sector
    print("\nTop 15 sectors by suspect count:")
    sec_counts = Counter(s["sector"] for s in suspects)
    for sec, cnt in sec_counts.most_common(15):
        print(f"  {sec:<45} {cnt:>4}")

    # date range
    if suspects:
        dates = [s["date"] for s in suspects]
        print(f"\nDate range of suspects:     {min(dates)} → {max(dates)}")

    # top 10 symbols
    print("\nTop 10 symbols by suspect count:")
    sym_counts = Counter(s["symbol"] for s in suspects)
    for sym, cnt in sym_counts.most_common(10):
        print(f"  {sym:<15} {cnt:>3}")

    elapsed = (datetime.now() - t_start).total_seconds()
    print(f"\nCompleted in {elapsed:.1f}s")
    print(f"Output: {OUT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
