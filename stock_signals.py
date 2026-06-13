import sqlite3
import logging
import bisect
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

DB = str(Path(__file__).parent / 'psx_data.db')


def _load_universe(conn):
    cur = conn.cursor()
    cur.execute("SELECT symbol, sector FROM stock_metadata")
    return {row[0]: row[1] for row in cur.fetchall()}


def _load_kse100(conn, from_date, to_date):
    cur = conn.cursor()
    cur.execute(
        "SELECT date, close FROM index_prices WHERE symbol='KSE-100' AND date BETWEEN ? AND ? ORDER BY date",
        (from_date, to_date),
    )
    return cur.fetchall()


def _load_stock_prices(conn, symbols, from_date, to_date):
    placeholders = ','.join('?' * len(symbols))
    cur = conn.cursor()
    cur.execute(
        f"SELECT symbol, date, close FROM prices_adjusted "
        f"WHERE symbol IN ({placeholders}) AND date BETWEEN ? AND ? ORDER BY symbol, date",
        list(symbols) + [from_date, to_date],
    )
    result = {}
    for sym, date, close in cur.fetchall():
        if sym not in result:
            result[sym] = []
        result[sym].append((date, close))
    return result


def _process_trading_dates(conn, trading_dates, kse_list, kse_date_idx,
                            stock_prices, symbol_sector, prev_ranks):
    stock_date_lists = {sym: [p[0] for p in prices] for sym, prices in stock_prices.items()}
    cur = conn.cursor()
    date_count = 0

    for date in trading_dates:
        kse_pos = kse_date_idx.get(date)
        if kse_pos is None:
            continue

        k_today = kse_list[kse_pos][1]
        if kse_pos < 20 or k_today is None:
            continue

        k_20d = kse_list[kse_pos - 20][1]
        if k_20d is None or k_20d == 0:
            continue

        rows = []
        for symbol, sector in symbol_sector.items():
            prices = stock_prices.get(symbol)
            if not prices:
                continue

            date_list = stock_date_lists[symbol]
            pos = bisect.bisect_left(date_list, date)
            if pos >= len(date_list) or date_list[pos] != date:
                continue
            if pos < 20:
                continue

            s_today = prices[pos][1]
            s_20d = prices[pos - 20][1]
            if s_today is None or s_20d is None or s_20d == 0:
                continue

            rs_20 = (s_today / s_20d - 1) * 100 - (k_today / k_20d - 1) * 100

            rs_50 = None
            if pos >= 50 and kse_pos >= 50:
                s_50d = prices[pos - 50][1]
                k_50d = kse_list[kse_pos - 50][1]
                if s_50d and k_50d and s_50d != 0 and k_50d != 0:
                    rs_50 = (s_today / s_50d - 1) * 100 - (k_today / k_50d - 1) * 100

            rows.append({
                'symbol': symbol,
                'sector': sector,
                'rs_score_20': rs_20,
                'rs_score_50': rs_50,
            })

        if not rows:
            continue

        # Global RS rank: descending by rs_score_20, rank 1 = strongest
        rows.sort(key=lambda r: r['rs_score_20'], reverse=True)
        for rank, row in enumerate(rows, 1):
            row['rs_rank'] = rank
            prev = prev_ranks.get(row['symbol'])
            row['rs_rank_prev'] = prev
            row['rank_change'] = (prev - rank) if prev is not None else None

        # Within-sector RS rank: rank 1 = strongest in sector
        sector_groups = defaultdict(list)
        for row in rows:
            sector_groups[row['sector']].append(row)
        for s_rows in sector_groups.values():
            for srank, row in enumerate(
                sorted(s_rows, key=lambda r: r['rs_score_20'], reverse=True), 1
            ):
                row['sector_rs_rank'] = srank

        cur.executemany(
            "INSERT OR REPLACE INTO stock_signals "
            "(date, symbol, rs_score_20, rs_score_50, rs_rank, rs_rank_prev, "
            "rank_change, sector_rs_rank, base_tightness, bos_flag) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
            [
                (date, r['symbol'], r['rs_score_20'], r['rs_score_50'],
                 r['rs_rank'], r['rs_rank_prev'], r['rank_change'], r['sector_rs_rank'])
                for r in rows
            ],
        )
        prev_ranks.update({r['symbol']: r['rs_rank'] for r in rows})

        date_count += 1
        if date_count % 100 == 0:
            conn.commit()
            logger.info(f"  {date_count} dates processed, current: {date}")

    conn.commit()  # flush remainder
    return date_count


def backfill_stock_signals(start_date: str, end_date: str) -> None:
    logger.info(f"Starting backfill: {start_date} → {end_date}")
    conn = sqlite3.connect(DB)
    try:
        symbol_sector = _load_universe(conn)
        lookback_start = (
            datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=120)
        ).strftime('%Y-%m-%d')
        kse_list = _load_kse100(conn, lookback_start, end_date)
        kse_date_idx = {row[0]: i for i, row in enumerate(kse_list)}
        stock_prices = _load_stock_prices(
            conn, set(symbol_sector.keys()), lookback_start, end_date
        )
        trading_dates = [row[0] for row in kse_list if start_date <= row[0] <= end_date]
        total = _process_trading_dates(
            conn, trading_dates, kse_list, kse_date_idx,
            stock_prices, symbol_sector, {}
        )
        logger.info(f"Backfill complete: {total} dates processed.")
    finally:
        conn.close()


def append_latest_stock_signals() -> None:
    conn = sqlite3.connect(DB)
    try:
        cur = conn.cursor()

        cur.execute("SELECT MAX(date) FROM stock_signals")
        last_inserted = cur.fetchone()[0]

        cur.execute(
            "SELECT MAX(date) FROM prices_adjusted "
            "WHERE symbol IN (SELECT symbol FROM stock_metadata)"
        )
        last_prices = cur.fetchone()[0]

        if not last_prices:
            logger.info("No price data available.")
            return
        if last_inserted and last_inserted >= last_prices:
            logger.info(f"stock_signals already up to date at {last_inserted}.")
            return

        start_date = last_inserted or '2015-01-01'
        end_date = last_prices
        logger.info(f"Appending stock_signals: {start_date} → {end_date}")

        symbol_sector = _load_universe(conn)
        lookback_start = (
            datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=120)
        ).strftime('%Y-%m-%d')
        kse_list = _load_kse100(conn, lookback_start, end_date)
        kse_date_idx = {row[0]: i for i, row in enumerate(kse_list)}
        stock_prices = _load_stock_prices(
            conn, set(symbol_sector.keys()), lookback_start, end_date
        )

        prev_ranks = {}
        if last_inserted:
            cur.execute(
                "SELECT symbol, rs_rank FROM stock_signals WHERE date = ?",
                (last_inserted,)
            )
            prev_ranks = {row[0]: row[1] for row in cur.fetchall()}

        trading_dates = [row[0] for row in kse_list if row[0] > start_date]
        total = _process_trading_dates(
            conn, trading_dates, kse_list, kse_date_idx,
            stock_prices, symbol_sector, prev_ranks
        )
        logger.info(f"Append complete: {total} dates processed.")
    finally:
        conn.close()
