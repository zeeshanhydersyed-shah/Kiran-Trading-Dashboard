"""
Twitter Audience — Content Generator
======================================
READ-ONLY. Never writes to any database.
Reads psx_data.db → writes twitter_output/drafts.json + chart images.

Run manually or from run_update.bat after the daily scraper.

Usage:
    python content_generator.py
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Allow importing from the pipeline folder
sys.path.insert(0, str(Path(__file__).parent))
from config import EXCLUDED_SECTORS

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger("content_generator")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
DB_PATH    = BASE_DIR / "psx_data.db"
OUTPUT_DIR = BASE_DIR / "twitter_output"
OUTPUT_DIR.mkdir(exist_ok=True)

DRAFTS_FILE = OUTPUT_DIR / "drafts.json"

# ── Read-only DB connection ───────────────────────────────────────────────────
def _conn():
    """Always opens in read-only mode — never writes."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _df(query: str, params=()) -> pd.DataFrame:
    with _conn() as conn:
        return pd.read_sql_query(query, conn, params=params)


# ── 1. Market Breadth ─────────────────────────────────────────────────────────
def build_breadth_content() -> dict:
    """
    Count stocks above / below their 50-day EMA.
    Returns a tweet draft + chart path.
    """
    log.info("Building market breadth content…")

    df = _df("""
        SELECT p.symbol, p.date, p.close
        FROM prices p
        JOIN sectors s ON p.symbol = s.symbol
        WHERE p.date >= date('now', '-120 days')
          AND p.close IS NOT NULL
        ORDER BY p.symbol, p.date
    """)

    if df.empty:
        return {"type": "breadth", "error": "No price data found"}

    df["date"] = pd.to_datetime(df["date"])

    # Compute 50 EMA per symbol
    df = df.sort_values(["symbol", "date"])
    df["ema50"] = df.groupby("symbol")["close"].transform(
        lambda x: x.ewm(span=50, adjust=False).mean()
    )

    # Latest snapshot per symbol
    latest = df.sort_values("date").groupby("symbol").last().reset_index()
    latest = latest.dropna(subset=["ema50"])

    above = (latest["close"] > latest["ema50"]).sum()
    total = len(latest)
    pct   = round(above / total * 100, 1) if total else 0

    below = total - above

    # Regime label
    if pct >= 60:
        regime = "Bullish 🟢"
        emoji  = "📈"
    elif pct >= 40:
        regime = "Neutral ⚪"
        emoji  = "📊"
    else:
        regime = "Bearish 🔴"
        emoji  = "📉"

    today_str = datetime.now().strftime("%d %b %Y")

    # Human, opinionated tweet — tone shifts with market conditions
    if pct >= 70:
        opinion = (
            f"Hard to be bearish when {pct}% of PSX stocks are holding above their 50 EMA.\n\n"
            f"Broad participation. The trend is intact almost everywhere.\n"
            f"This is the environment where you want to be in the market, not watching from the sidelines."
        )
    elif pct >= 60:
        opinion = (
            f"{pct}% of PSX stocks are above their 50 EMA.\n\n"
            f"Breadth is healthy. Not euphoric, but solid.\n"
            f"Selective entries still make sense — the trend has room."
        )
    elif pct >= 50:
        opinion = (
            f"{pct}% of PSX stocks are above their 50 EMA — just barely above the line.\n\n"
            f"The market is holding, but it's not convincing.\n"
            f"I'm watching more than trading in conditions like this."
        )
    elif pct >= 40:
        opinion = (
            f"Only {pct}% of PSX stocks are holding above their 50 EMA.\n\n"
            f"More than half the market is under pressure.\n"
            f"Not the time to be a hero. Patience over aggression."
        )
    else:
        opinion = (
            f"Just {pct}% of PSX stocks above their 50 EMA.\n\n"
            f"The data is telling a clear story — this is a defensive market.\n"
            f"Sometimes the best trade is no trade."
        )

    tweet = f"📊 PSX Market Breadth — {today_str}\n\n{opinion}\n\n#PSX #KSE100 #Pakistan"

    # ── Rolling breadth chart (last 60 trading days) ──────────────────────────
    daily = (
        df.groupby("date")
        .apply(lambda g: (g["close"] > g["ema50"]).sum() / len(g) * 100)
        .reset_index(name="pct_above")
    )
    daily = daily.tail(60)

    fig, ax = plt.subplots(figsize=(9, 4))
    fig.patch.set_facecolor("#0f1117")
    ax.set_facecolor("#0f1117")

    ax.fill_between(daily["date"], daily["pct_above"], 50,
                    where=daily["pct_above"] >= 50, alpha=0.35, color="#22c55e", label="Bullish")
    ax.fill_between(daily["date"], daily["pct_above"], 50,
                    where=daily["pct_above"] < 50,  alpha=0.35, color="#ef4444", label="Bearish")
    ax.plot(daily["date"], daily["pct_above"], color="#7dd3fc", linewidth=1.8)
    ax.axhline(50, color="#475569", linewidth=0.8, linestyle="--")
    ax.axhline(60, color="#22c55e", linewidth=0.5, linestyle=":")
    ax.axhline(40, color="#ef4444", linewidth=0.5, linestyle=":")

    ax.set_ylim(0, 100)
    ax.set_ylabel("% Stocks above 50 EMA", color="#94a3b8", fontsize=9)
    ax.set_title(f"PSX Market Breadth  •  {today_str}", color="#e2e8f0", fontsize=11, pad=10)
    ax.tick_params(colors="#94a3b8", labelsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    for spine in ax.spines.values():
        spine.set_color("#334155")

    chart_path = OUTPUT_DIR / "breadth_chart.png"
    fig.tight_layout()
    fig.savefig(chart_path, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    # ── KSE-100 index chart (last 60 days) ────────────────────────────────────
    kse = _df("""
        SELECT date, close FROM index_prices
        WHERE symbol = 'KSE-100'
          AND date >= date('now', '-90 days')
        ORDER BY date
    """)
    kse_chart_path = None
    if not kse.empty:
        kse["date"]  = pd.to_datetime(kse["date"])
        kse["ema20"] = kse["close"].ewm(span=20, adjust=False).mean()

        fig2, ax2 = plt.subplots(figsize=(9, 3.5))
        fig2.patch.set_facecolor("#0f1117")
        ax2.set_facecolor("#0f1117")
        ax2.plot(kse["date"], kse["close"], color="#7dd3fc", linewidth=1.8, label="KSE-100")
        ax2.plot(kse["date"], kse["ema20"], color="#f59e0b", linewidth=1.2, linestyle="--", label="20 EMA")
        ax2.fill_between(kse["date"], kse["close"], kse["close"].min(), alpha=0.08, color="#7dd3fc")
        ax2.set_title(f"KSE-100 Index  •  {today_str}", color="#e2e8f0", fontsize=11, pad=10)
        ax2.set_ylabel("Index Level", color="#94a3b8", fontsize=9)
        ax2.tick_params(colors="#94a3b8", labelsize=8)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        ax2.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        ax2.legend(fontsize=8, facecolor="#1e293b", labelcolor="#94a3b8", framealpha=0.8)
        plt.setp(ax2.get_xticklabels(), rotation=30, ha="right")
        for spine in ax2.spines.values():
            spine.set_color("#334155")
        kse_chart_path = OUTPUT_DIR / "kse_chart.png"
        fig2.tight_layout()
        fig2.savefig(kse_chart_path, dpi=130, bbox_inches="tight", facecolor=fig2.get_facecolor())
        plt.close(fig2)

    log.info("Breadth: %d/%d above EMA50 (%.1f%%)", above, total, pct)
    return {
        "type":       "breadth",
        "pct_above":  pct,
        "above":      int(above),
        "below":      int(below),
        "total":      int(total),
        "regime":     regime,
        "tweet":      tweet,
        "chart":      str(chart_path),
        "kse_chart":  str(kse_chart_path) if kse_chart_path else None,
    }


# ── 2. Latest Screener Setups ─────────────────────────────────────────────────
def build_setups_content() -> dict:
    """
    Top 3 Pending system setups for a weekly thread.
    Rules:
      - Must be generated within last 2 trading days (fresh)
      - Risk % <= 6% (your max SL rule)
      - Sorted by quality_score DESC
    If setups are stale, returns stale=True so the draft is skipped.
    """
    log.info("Building setups content…")

    df = _df("""
        SELECT symbol, sector, direction, created_date,
               entry_price, stop_loss, target_1r, target_2r,
               risk_pct, stock_perf_30d, quality_score
        FROM trade_setups
        WHERE status  = 'Pending'
          AND source  IN ('System', 'STM')
          AND risk_pct <= 6.0
          AND created_date >= date('now', '-2 days')
        ORDER BY quality_score DESC, created_date DESC
        LIMIT 5
    """)

    # Flag as stale if nothing within 2 days
    stale = df.empty
    if stale:
        df = _df("""
            SELECT symbol, sector, direction, created_date,
                   entry_price, stop_loss, target_1r, target_2r,
                   risk_pct, stock_perf_30d, quality_score
            FROM trade_setups
            WHERE status  = 'Pending'
              AND source  IN ('System', 'STM')
              AND risk_pct <= 6.0
            ORDER BY quality_score DESC, created_date DESC
            LIMIT 5
        """)

    if df.empty:
        return {"type": "setups", "error": "No pending setups found within risk rules"}

    if stale:
        newest_date = df["created_date"].max()
        log.warning("Setups are stale — newest is %s. Skipping tweet draft.", newest_date)
        return {
            "type":  "setups",
            "stale": True,
            "newest_date": newest_date,
            "note": f"Newest qualifying setup is from {newest_date} — too old to post. Wait for fresh screener run.",
        }

    today_str = datetime.now().strftime("%d %b %Y")
    thread    = [
        f"🔍 PSX screener ran this week. Here are the setups it flagged.\n\n"
        f"These are system-generated — I review each one before acting on it.\n"
        f"Not financial advice. 🧵"
    ]

    for _, row in df.head(3).iterrows():
        rr        = round((row["target_1r"] - row["entry_price"]) /
                          abs(row["entry_price"] - row["stop_loss"]), 1) if row["entry_price"] != row["stop_loss"] else 0
        emoji     = "📈" if row["direction"] == "LONG" else "📉"
        direction = "long" if row["direction"] == "LONG" else "short"
        perf_note = f"up {row['stock_perf_30d']:.0f}% in 30 days" if row["stock_perf_30d"] > 0 else f"down {abs(row['stock_perf_30d']):.0f}% in 30 days"

        thread.append(
            f"{emoji} {row['symbol']} — {row['sector'].title()}\n\n"
            f"Setup: {direction.upper()} | Stock is {perf_note}\n"
            f"Entry around {row['entry_price']:.2f}\n"
            f"Stop loss: {row['stop_loss']:.2f} ({row['risk_pct']:.1f}% risk)\n"
            f"Target: {row['target_1r']:.2f} — about {rr}R"
        )

    thread.append(
        f"These setups are from my screener — I don't take all of them.\n"
        f"Execution and context matter more than the signal.\n\n"
        f"#PSX #KSE100 #SwingTrading #Pakistan"
    )

    setups_list = df.head(3).to_dict(orient="records")
    log.info("Setups: %d qualifying setups found (fresh, risk ≤ 6%%)", len(df))
    return {
        "type":   "setups",
        "stale":  False,
        "count":  len(df),
        "setups": setups_list,
        "thread": thread,
    }


# ── 3. Sector Rotation ────────────────────────────────────────────────────────
def build_sector_content() -> dict:
    """Top & bottom 3 sectors by 30-day performance."""
    log.info("Building sector rotation content…")

    # Use the canonical exclusion list from config — never out of sync
    EXCLUDED = EXCLUDED_SECTORS

    df = _df("""
        SELECT p.symbol, s.sector, p.date, p.close
        FROM prices p
        JOIN sectors s ON p.symbol = s.symbol
        WHERE p.date >= date('now', '-45 days')
          AND p.close IS NOT NULL
        ORDER BY p.symbol, p.date
    """)

    if df.empty:
        return {"type": "sectors", "error": "No price data"}

    df["date"] = pd.to_datetime(df["date"])
    df = df[~df["sector"].isin(EXCLUDED)]

    # 30d perf per symbol
    results = []
    for sym, grp in df.groupby("symbol"):
        grp = grp.sort_values("date")
        if len(grp) < 5:
            continue
        latest = grp.iloc[-1]["close"]
        base   = grp.iloc[max(0, len(grp) - 31)]["close"]
        if base and base > 0:
            results.append({
                "symbol": sym,
                "sector": grp.iloc[-1]["sector"],
                "perf":   round((latest - base) / base * 100, 2),
            })

    if not results:
        return {"type": "sectors", "error": "Insufficient history"}

    perf_df = pd.DataFrame(results)
    sector_perf = perf_df.groupby("sector")["perf"].median().reset_index()
    sector_perf = sector_perf.sort_values("perf", ascending=False)

    top3    = sector_perf.head(3)
    bottom3 = sector_perf.tail(3).iloc[::-1]

    today_str = datetime.now().strftime("%d %b %Y")

    # Smart label: only call it "Declining" if sectors are actually negative
    bottom_max_perf = bottom3["perf"].max()
    if bottom_max_perf < 0:
        bottom_label = "🔴 Declining (30d):"
    else:
        bottom_label = "🟡 Underperforming (30d):"

    # Lead with the strongest mover, then give the full picture
    top_sector  = top3.iloc[0]
    bot_sector  = bottom3.iloc[0]
    top_name    = top_sector["sector"].title()
    bot_name    = bot_sector["sector"].title()
    top_perf    = top_sector["perf"]
    bot_perf    = bot_sector["perf"]

    if bot_perf < 0:
        lagging_line = f"{bot_name} is the biggest drag — down {abs(bot_perf):.1f}% over the same period."
    else:
        lagging_line = f"{bot_name} is barely moving at +{bot_perf:.1f}% — money clearly isn't going there."

    tweet = (
        f"📊 PSX Sector Rotation — {today_str}\n\n"
        f"{top_name} is up {top_perf:.1f}% over the last 30 days. "
        f"That's where the real momentum is right now.\n\n"
        f"{lagging_line}\n\n"
        f"Full breakdown 👇\n"
        f"🟢 {top3.iloc[0]['sector'].title()}: +{top3.iloc[0]['perf']:.1f}%\n"
        f"🟢 {top3.iloc[1]['sector'].title()}: +{top3.iloc[1]['perf']:.1f}%\n"
        f"🟢 {top3.iloc[2]['sector'].title()}: +{top3.iloc[2]['perf']:.1f}%\n\n"
        f"🟡 {bottom3.iloc[0]['sector'].title()}: {bottom3.iloc[0]['perf']:+.1f}%\n"
        f"🟡 {bottom3.iloc[1]['sector'].title()}: {bottom3.iloc[1]['perf']:+.1f}%\n"
        f"🟡 {bottom3.iloc[2]['sector'].title()}: {bottom3.iloc[2]['perf']:+.1f}%\n\n"
        f"#PSX #SectorRotation #KSE100 #Pakistan"
    )

    # ── Horizontal bar chart ──────────────────────────────────────────────────
    plot_df = pd.concat([top3, bottom3]).sort_values("perf")

    fig, ax = plt.subplots(figsize=(9, 4))
    fig.patch.set_facecolor("#0f1117")
    ax.set_facecolor("#0f1117")

    # Green for leaders, red for negative, amber for positive-but-lagging
    top3_sectors = set(top3["sector"])
    def bar_color(row):
        if row["sector"] in top3_sectors:
            return "#22c55e"
        return "#ef4444" if row["perf"] < 0 else "#f59e0b"
    colors = [bar_color(r) for _, r in plot_df.iterrows()]
    bars = ax.barh(plot_df["sector"], plot_df["perf"], color=colors, height=0.6)

    for bar, val in zip(bars, plot_df["perf"]):
        ax.text(val + (0.3 if val >= 0 else -0.3), bar.get_y() + bar.get_height() / 2,
                f"{val:+.1f}%", va="center", ha="left" if val >= 0 else "right",
                color="#e2e8f0", fontsize=8)

    ax.axvline(0, color="#475569", linewidth=0.8)
    ax.set_xlabel("30-day median return (%)", color="#94a3b8", fontsize=9)
    ax.set_title(f"PSX Sector Rotation  •  {today_str}", color="#e2e8f0", fontsize=11, pad=10)
    ax.tick_params(colors="#94a3b8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#334155")

    chart_path = OUTPUT_DIR / "sector_chart.png"
    fig.tight_layout()
    fig.savefig(chart_path, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    log.info("Sectors: %d sectors computed", len(sector_perf))
    return {
        "type":    "sectors",
        "top3":    top3.to_dict(orient="records"),
        "bottom3": bottom3.to_dict(orient="records"),
        "tweet":   tweet,
        "chart":   str(chart_path),
    }


# ── 4. Trade Performance Snapshot ─────────────────────────────────────────────
def build_performance_content() -> dict:
    """Monthly win rate, R:R, and a teaser for deeper Substack content."""
    log.info("Building performance snapshot…")

    # Last 30 days closed + actual trades
    df = _df("""
        SELECT outcome, actual_pl_pct, actual_rr, exit_date, symbol, sector
        FROM trade_setups
        WHERE status  = 'Closed'
          AND outcome IS NOT NULL
          AND source IN ('Actual', 'System', 'STM', 'Support Reversal')
          AND actual_entry IS NOT NULL
          AND exit_date >= date('now', '-30 days')
        ORDER BY exit_date DESC
    """)

    if df.empty:
        # Fall back to last 60 days
        df = _df("""
            SELECT outcome, actual_pl_pct, actual_rr, exit_date, symbol, sector
            FROM trade_setups
            WHERE status  = 'Closed'
              AND outcome IS NOT NULL
              AND actual_entry IS NOT NULL
            ORDER BY exit_date DESC
            LIMIT 20
        """)

    if df.empty:
        return {"type": "performance", "error": "No closed trades found"}

    wins    = (df["outcome"] == "Win").sum()
    losses  = (df["outcome"] == "Loss").sum()
    total   = len(df)
    win_pct = round(wins / total * 100, 1) if total else 0
    avg_rr  = round(df["actual_rr"].dropna().mean(), 2) if not df["actual_rr"].dropna().empty else None
    avg_pl  = round(df["actual_pl_pct"].dropna().mean(), 2) if not df["actual_pl_pct"].dropna().empty else None

    period = "last 30 days" if total >= 5 else "recent trades"
    today_str = datetime.now().strftime("%d %b %Y")

    tweet = (
        f"📋 My PSX Trading — {today_str}\n\n"
        f"Performance snapshot ({period}):\n"
        f"  Trades: {total}  |  Wins: {wins}  |  Losses: {losses}\n"
        f"  Win rate: {win_pct}%\n"
    )
    if avg_rr:
        tweet += f"  Avg R:R: {avg_rr}\n"
    if avg_pl is not None:
        tweet += f"  Avg P&L: {avg_pl:+.2f}%\n"

    tweet += (
        "\nFull breakdown in this month's newsletter ↓\n\n"
        "#PSX #Trading #TradingJournal #Pakistan"
    )

    log.info("Performance: %d trades, %.1f%% win rate", total, win_pct)
    return {
        "type":     "performance",
        "total":    int(total),
        "wins":     int(wins),
        "losses":   int(losses),
        "win_pct":  win_pct,
        "avg_rr":   avg_rr,
        "avg_pl":   avg_pl,
        "tweet":    tweet,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def generate_all() -> dict:
    if not DB_PATH.exists():
        log.error("DB not found at %s", DB_PATH)
        return {"error": "DB not found", "generated_at": datetime.now().isoformat()}

    drafts = {
        "generated_at": datetime.now().isoformat(),
        "content": {
            "breadth":     build_breadth_content(),
            "setups":      build_setups_content(),
            "sectors":     build_sector_content(),
            "performance": build_performance_content(),
        }
    }

    with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
        json.dump(drafts, f, indent=2, default=str, ensure_ascii=False)

    log.info("✓ Drafts saved → %s", DRAFTS_FILE)
    return drafts


if __name__ == "__main__":
    result = generate_all()
    print(f"\n✓ Done. Output: {DRAFTS_FILE}")
    for key, val in result.get("content", {}).items():
        status = "✓" if "error" not in val else f"✗ {val['error']}"
        print(f"  {key:<15} {status}")
