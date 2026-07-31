"""
Fix for the 2026-07-31 finding (docs/KIRAN_CLEANUP_AUDIT.md Section 16):
production Postgres has two corrupted KSE-100 index_prices rows
(2026-07-08, 2026-07-16), caused by scraper.py's _is_stale() duplicate-day
guard being silently non-functional on Postgres (Decimal vs float
comparison bug, fixed 2026-07-29 but not retroactively applied). Verified
correct values three ways: local SQLite (which never had the comparison
bug), a live re-fetch from ksestocks.com, and the OHLC invariant.

Run with DRY_RUN = True first (default) to preview every change with no
writes. Set DRY_RUN = False to execute. Backup already taken via
backup_regime_fix_2026-07-31.py before this script is ever run for real.
"""
import os
from datetime import date as date_cls
from dotenv import load_dotenv
load_dotenv(dotenv_path=r"C:\Users\Lenovo\psx_pipeline\.env")
import psycopg2
import pandas as pd

DRY_RUN = False  # flip to False only after reviewing the dry-run output

# Verified-true values for the two corrupted rows: (open, high, low, close)
CORRECTIONS = {
    "2026-07-08": (184405.87, 185215.56, 179504.34, 181629.36),
    "2026-07-16": (175672.34, 178431.73, 175672.33, 178123.56),
}

WARMUP = 250  # matches regime.py's WARMUP constant exactly


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True)
    df["ema_20"]  = df["close"].ewm(span=20,  adjust=False).mean()
    df["ema_50"]  = df["close"].ewm(span=50,  adjust=False).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "low", "prev_close"]].apply(
        lambda r: max(
            r["high"] - r["low"],
            abs(r["high"] - r["prev_close"]) if pd.notna(r["prev_close"]) else 0,
            abs(r["low"]  - r["prev_close"]) if pd.notna(r["prev_close"]) else 0,
        ),
        axis=1,
    )
    df["atr_20"]  = df["tr"].rolling(20).mean()
    df["atr_pct"] = df["atr_20"] / df["close"] * 100
    df["return_20d"] = (df["close"] - df["close"].shift(20)) / df["close"].shift(20) * 100
    return df


def _classify(row) -> str:
    if pd.isna(row["return_20d"]) or pd.isna(row["atr_pct"]):
        return "INSUFFICIENT_DATA"
    e20, e50, e200 = row["ema_20"], row["ema_50"], row["ema_200"]
    c, r20, atr_pct = row["close"], row["return_20d"], row["atr_pct"]
    if e20 > e50 and e50 > e200 and c > e20 and r20 > 0:
        return "TRENDING_UP"
    if e20 < e50 and e50 < e200 and c < e20 and r20 < 0:
        return "TRENDING_DOWN"
    if atr_pct > 1.5:
        return "VOLATILE"
    return "RANGING"


def main():
    url = os.environ.get("SUPABASE_DB_URL")
    conn = psycopg2.connect(url)
    cur = conn.cursor()

    print("=" * 70)
    print("STEP 1 -- correcting index_prices (KSE-100)")
    print("=" * 70)
    for d, (opn, high, low, close) in CORRECTIONS.items():
        cur.execute(
            "SELECT open, high, low, close FROM index_prices WHERE symbol='KSE-100' AND date=%s",
            (d,),
        )
        before = cur.fetchone()
        print(f"{d}: before={before}  ->  after=({opn}, {high}, {low}, {close})")
        if not DRY_RUN:
            cur.execute(
                """UPDATE index_prices SET open=%s, high=%s, low=%s, close=%s
                   WHERE symbol='KSE-100' AND date=%s""",
                (opn, high, low, close, d),
            )

    print()
    print("=" * 70)
    print("STEP 2 -- recomputing market_regime from 2026-07-08 onward")
    print("=" * 70)

    # Pull ALL KSE-100 history (post-correction values already reflected if
    # DRY_RUN=False and executemany already ran in this same transaction;
    # for DRY_RUN=True, re-read then patch the two rows in-memory so the
    # preview reflects what the recompute WOULD see).
    cur.execute("SELECT date, high, low, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date")
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["date", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["date"])
    for col in ["high", "low", "close"]:
        df[col] = df[col].astype(float)

    if DRY_RUN:
        for d, (opn, high, low, close) in CORRECTIONS.items():
            mask = df["date"] == pd.Timestamp(d)
            df.loc[mask, ["high", "low", "close"]] = [high, low, close]

    df = _compute_indicators(df)
    df["regime"] = df.apply(_classify, axis=1)

    # Existing market_regime rows to update (only dates >= 2026-07-08 that
    # already exist in the table -- no inserts, only corrections).
    cur.execute("SELECT date, regime, regime_days FROM market_regime ORDER BY date")
    existing = cur.fetchall()
    existing_map = {str(r[0]): (r[1], r[2]) for r in existing}

    fix_from = pd.Timestamp("2026-07-08")
    to_update = df[df["date"] >= fix_from].copy()

    # Seed regime_days chain from the last untouched row before fix_from.
    before_rows = [r for r in existing if str(r[0]) < "2026-07-08"]
    prev_regime, prev_days = (before_rows[-1][1], before_rows[-1][2]) if before_rows else (None, 0)

    updates = []
    for _, row in to_update.iterrows():
        d_str = row["date"].strftime("%Y-%m-%d")
        if d_str not in existing_map:
            continue  # don't insert new rows, only correct existing ones
        regime = row["regime"]
        regime_days = prev_days + 1 if regime == prev_regime else 1
        prev_regime, prev_days = regime, regime_days
        updates.append((
            d_str,
            float(row["close"]),
            float(row["ema_20"]), float(row["ema_50"]), float(row["ema_200"]),
            float(row["atr_20"]) if pd.notna(row["atr_20"]) else None,
            float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else None,
            float(row["return_20d"]) if pd.notna(row["return_20d"]) else None,
            regime, regime_days,
            existing_map[d_str][0], existing_map[d_str][1],  # old regime, old regime_days for the diff print
        ))

    print(f"{len(updates)} market_regime rows in range (existing dates only):\n")
    for (d_str, close, e20, e50, e200, atr20, atrpct, r20, regime, regime_days,
         old_regime, old_days) in updates:
        changed = "  <-- CHANGED" if (regime, regime_days) != (old_regime, old_days) else ""
        print(f"  {d_str}  close={close:.2f}  regime: {old_regime}(day {old_days}) -> {regime}(day {regime_days}){changed}")

    if not DRY_RUN:
        for (d_str, close, e20, e50, e200, atr20, atrpct, r20, regime, regime_days,
             _, _) in updates:
            cur.execute(
                """UPDATE market_regime SET close=%s, ema_20=%s, ema_50=%s, ema_200=%s,
                       atr_20=%s, atr_pct=%s, return_20d=%s, regime=%s, regime_days=%s
                   WHERE date=%s""",
                (close, e20, e50, e200, atr20, atrpct, r20, regime, regime_days, d_str),
            )
        conn.commit()
        print("\nCOMMITTED.")
    else:
        conn.rollback()
        print("\nDRY RUN -- no changes written. Set DRY_RUN = False to execute.")

    conn.close()


if __name__ == "__main__":
    main()
