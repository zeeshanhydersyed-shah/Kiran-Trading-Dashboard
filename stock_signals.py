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


def _load_stock_prices_with_volume(conn, symbols, from_date, to_date):
    placeholders = ','.join('?' * len(symbols))
    cur = conn.cursor()
    cur.execute(
        f"SELECT symbol, date, close, volume, high FROM prices_adjusted "
        f"WHERE symbol IN ({placeholders}) AND date BETWEEN ? AND ? ORDER BY symbol, date",
        list(symbols) + [from_date, to_date],
    )
    result = {}
    for sym, date, close, volume, high in cur.fetchall():
        if sym not in result:
            result[sym] = []
        result[sym].append((date, close, volume, high))
    return result


def _ema(prices_close: list, pos: int, period: int):
    """Exponential moving average at position pos using Wilder/standard multiplier.
    Returns None if not enough data."""
    if pos < period - 1:
        return None
    k = 2 / (period + 1)
    # seed with SMA of first `period` values
    window = [prices_close[i] for i in range(pos - period + 1, pos + 1)]
    if any(v is None for v in window):
        return None
    ema = sum(window) / period
    # refine with full history back to max(0, pos-3*period) for stability
    start = max(0, pos - 3 * period)
    seed_start = start + period - 1
    if seed_start > pos:
        return ema
    seed_window = [prices_close[i] for i in range(start, start + period)]
    if any(v is None for v in seed_window):
        return ema
    ema = sum(seed_window) / period
    for i in range(start + period, pos + 1):
        if prices_close[i] is None:
            return None
        ema = prices_close[i] * k + ema * (1 - k)
    return ema


def _build_pivot_lookup(stock_prices_vol: dict) -> dict:
    """Pre-compute pivot_high, pivot_distance_pct, bos_flag for every (symbol, date).

    stock_prices_vol values: list of (date, close, volume, high) sorted by date ASC.
    Returns: {symbol: {date: (pivot_high, pivot_distance_pct, bos_flag)}}
    """
    lookup = {}
    for symbol, prices in stock_prices_vol.items():
        n = len(prices)
        confirmed_pivots = []  # (bar_index, high_value), appended in order → sorted by index
        sym_lookup = {}

        for pos in range(n):
            # Confirm pivot at i = pos-10 once right side (10 bars) is available
            i = pos - 10
            if i >= 10:  # need 10 bars on the left side as well
                hi = prices[i][3]
                if hi is not None:
                    left_ok = all(
                        prices[j][3] is not None and prices[j][3] < hi
                        for j in range(i - 10, i)
                    )
                    right_ok = all(
                        prices[j][3] is not None and prices[j][3] < hi
                        for j in range(i + 1, i + 11)
                    )
                    if left_ok and right_ok:
                        confirmed_pivots.append((i, hi))

            date = prices[pos][0]
            close = prices[pos][1]
            ph = pd_pct = bf = None

            if confirmed_pivots and close is not None:
                lower = pos - 50
                for ci, ch in reversed(confirmed_pivots):
                    if ci >= lower:
                        ph = ch
                        pd_pct = (ph - close) / ph * 100
                        bf = 1 if pd_pct < 0 else 0
                        break

            sym_lookup[date] = (ph, pd_pct, bf)

        lookup[symbol] = sym_lookup
    return lookup


def _compute_bt_vc(prices_vol, pos):
    """Return (base_tightness, vol_contraction, avg_vol_10d) for position pos in a symbol's price list.

    prices_vol: list of (date, close, volume) sorted by date ASC.
    Per spec: if any volume in the window is NULL or zero, both metrics are NULL.
    """
    bt = None
    vc = None

    if pos >= 19:
        window_close = [prices_vol[i][1] for i in range(pos - 19, pos + 1)]
        if all(c is not None for c in window_close):
            mid = sum(window_close) / 20
            variance = sum((c - mid) ** 2 for c in window_close) / 20
            std = variance ** 0.5
            bt = (4 * std / mid * 100) if mid != 0 else None

    if pos >= 9:
        vols_10 = [prices_vol[i][2] for i in range(pos - 9, pos + 1)]
        vols_50 = [prices_vol[i][2] for i in range(max(0, pos - 49), pos + 1)]
        if (all(v is not None and v != 0 for v in vols_10) and
                all(v is not None and v != 0 for v in vols_50)):
            avg10 = sum(vols_10) / 10
            avg50 = sum(vols_50) / len(vols_50)
            vc = avg10 / avg50 * 100
        else:
            bt = None  # volume issue nullifies both per spec

    avg_vol_10d = None
    if pos >= 9:
        vols_10 = [prices_vol[i][2] for i in range(pos - 9, pos + 1)]
        if all(v is not None and v != 0 for v in vols_10):
            avg_vol_10d = sum(vols_10) / 10
    return bt, vc, avg_vol_10d


def _process_trading_dates(conn, trading_dates, kse_list, kse_date_idx,
                            stock_prices, symbol_sector, prev_ranks,
                            stock_prices_vol=None, pivot_lookup=None):
    stock_date_lists = {sym: [p[0] for p in prices] for sym, prices in stock_prices.items()}
    vol_date_lists = (
        {sym: [p[0] for p in prices] for sym, prices in stock_prices_vol.items()}
        if stock_prices_vol else {}
    )
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

            bt = None
            vc = None
            avv = None
            if stock_prices_vol:
                vol_prices = stock_prices_vol.get(symbol)
                if vol_prices:
                    vdl = vol_date_lists[symbol]
                    vpos = bisect.bisect_left(vdl, date)
                    if vpos < len(vdl) and vdl[vpos] == date:
                        bt, vc, avv = _compute_bt_vc(vol_prices, vpos)

            ph = pd_pct = bf = None
            if pivot_lookup:
                ph, pd_pct, bf = pivot_lookup.get(symbol, {}).get(date, (None, None, None))

            # stage2_bull: close > EMA20 > EMA50 > EMA200, all EMAs stacked
            stage2 = None
            if pos >= 199:
                closes = [prices[i][1] for i in range(pos - 3 * 200, pos + 1)] if pos >= 3 * 200 else [prices[i][1] for i in range(pos + 1)]
                e20  = _ema(closes, len(closes) - 1, 20)
                e50  = _ema(closes, len(closes) - 1, 50)
                e200 = _ema(closes, len(closes) - 1, 200)
                if e20 is not None and e50 is not None and e200 is not None:
                    stage2 = 1 if (s_today > e20 > e50 > e200) else 0

            rows.append({
                'symbol': symbol,
                'sector': sector,
                'rs_score_20': rs_20,
                'rs_score_50': rs_50,
                'base_tightness': bt,
                'vol_contraction': vc,
                'avg_vol_10d': avv,
                'pivot_high': ph,
                'pivot_distance_pct': pd_pct,
                'bos_flag': bf,
                'stage2_bull': stage2,
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
            "rank_change, sector_rs_rank, base_tightness, bos_flag, vol_contraction, avg_vol_10d, "
            "pivot_high, pivot_distance_pct, stage2_bull) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (date, r['symbol'], r['rs_score_20'], r['rs_score_50'],
                 r['rs_rank'], r['rs_rank_prev'], r['rank_change'], r['sector_rs_rank'],
                 r.get('base_tightness'), r.get('bos_flag'), r.get('vol_contraction'),
                 r.get('avg_vol_10d'), r.get('pivot_high'), r.get('pivot_distance_pct'),
                 r.get('stage2_bull'))
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

        # Load full price history (close + volume) from earliest date so 20/50-bar
        # lookbacks for base_tightness and vol_contraction are always accurate.
        stock_prices_vol = _load_stock_prices_with_volume(
            conn, set(symbol_sector.keys()), '2015-01-01', end_date
        )

        pivot_lookup = _build_pivot_lookup(stock_prices_vol)

        trading_dates = [row[0] for row in kse_list if row[0] > start_date]
        total = _process_trading_dates(
            conn, trading_dates, kse_list, kse_date_idx,
            stock_prices, symbol_sector, prev_ranks,
            stock_prices_vol=stock_prices_vol,
            pivot_lookup=pivot_lookup,
        )
        logger.info(f"Append complete: {total} dates processed.")
    finally:
        conn.close()


def update_base_tightness_vol_contraction() -> None:
    """Backfill base_tightness and vol_contraction for all rows in stock_signals."""
    logger.info("Starting base_tightness + vol_contraction backfill...")
    conn = sqlite3.connect(DB)
    try:
        symbol_sector = _load_universe(conn)
        symbols = list(symbol_sector.keys())
        placeholders = ','.join('?' * len(symbols))
        cur = conn.cursor()

        cur.execute(
            f"SELECT symbol, date, close, volume FROM prices_adjusted "
            f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
            symbols,
        )

        price_data: dict[str, list] = {}
        for sym, date, close, volume in cur.fetchall():
            if sym not in price_data:
                price_data[sym] = []
            price_data[sym].append((date, close, volume))

        updates = []
        total_processed = 0

        for symbol, prices in price_data.items():
            for pos in range(len(prices)):
                date = prices[pos][0]
                bt, vc, avv = _compute_bt_vc(prices, pos)
                updates.append((bt, vc, avv, date, symbol))
                total_processed += 1

                if len(updates) >= 10_000:
                    cur.executemany(
                        "UPDATE stock_signals "
                        "SET base_tightness = ?, vol_contraction = ?, avg_vol_10d = ? "
                        "WHERE date = ? AND symbol = ?",
                        updates,
                    )
                    conn.commit()
                    logger.info(f"  {total_processed:,} rows processed...")
                    updates = []

        if updates:
            cur.executemany(
                "UPDATE stock_signals "
                "SET base_tightness = ?, vol_contraction = ?, avg_vol_10d = ? "
                "WHERE date = ? AND symbol = ?",
                updates,
            )
            conn.commit()

        logger.info(f"Backfill complete. Total rows processed: {total_processed:,}")

        cur.execute("SELECT COUNT(*) FROM stock_signals")
        total_rows = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM stock_signals WHERE base_tightness IS NULL")
        bt_nulls = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM stock_signals WHERE vol_contraction IS NULL")
        vc_nulls = cur.fetchone()[0]
        logger.info(f"  Total rows in stock_signals : {total_rows:,}")
        logger.info(f"  base_tightness  NULLs remaining: {bt_nulls:,}")
        logger.info(f"  vol_contraction NULLs remaining: {vc_nulls:,}")
    finally:
        conn.close()


def backfill_stage2_bull() -> None:
    """Add stage2_bull column (if missing) and compute it for all existing rows."""
    logger.info("Starting stage2_bull backfill...")
    conn = sqlite3.connect(DB)
    try:
        cur = conn.cursor()
        # Add column if not present (safe to run multiple times)
        try:
            cur.execute("ALTER TABLE stock_signals ADD COLUMN stage2_bull INTEGER")
            conn.commit()
            logger.info("  Added stage2_bull column.")
        except Exception:
            pass  # column already exists

        symbol_sector = _load_universe(conn)
        symbols = list(symbol_sector.keys())
        placeholders = ','.join('?' * len(symbols))

        cur.execute(
            f"SELECT symbol, date, close FROM prices_adjusted "
            f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
            symbols,
        )
        price_data: dict[str, list] = {}
        for sym, date, close in cur.fetchall():
            if sym not in price_data:
                price_data[sym] = []
            price_data[sym].append((date, close))

        updates = []
        total = 0
        for symbol, prices in price_data.items():
            closes = [p[1] for p in prices]
            for pos, (date, close) in enumerate(prices):
                if pos < 199 or close is None:
                    continue
                e20  = _ema(closes, pos, 20)
                e50  = _ema(closes, pos, 50)
                e200 = _ema(closes, pos, 200)
                if e20 is None or e50 is None or e200 is None:
                    continue
                s2 = 1 if (close > e20 > e50 > e200) else 0
                updates.append((s2, date, symbol))
                total += 1
                if len(updates) >= 10_000:
                    cur.executemany(
                        "UPDATE stock_signals SET stage2_bull = ? WHERE date = ? AND symbol = ?",
                        updates,
                    )
                    conn.commit()
                    logger.info(f"  {total:,} rows updated...")
                    updates = []

        if updates:
            cur.executemany(
                "UPDATE stock_signals SET stage2_bull = ? WHERE date = ? AND symbol = ?",
                updates,
            )
            conn.commit()

        cur.execute("SELECT COUNT(*) FROM stock_signals WHERE stage2_bull = 1")
        stage2_count = cur.fetchone()[0]
        logger.info(f"Backfill complete. {total:,} rows computed, {stage2_count:,} stage2_bull=1.")
    finally:
        conn.close()


def recompute_symbol_signals(symbol: str) -> int:
    """Deletes and recomputes all stock_signals rows for a single symbol."""
    conn = sqlite3.connect(DB)
    try:
        cur = conn.cursor()

        cur.execute("SELECT sector FROM stock_metadata WHERE symbol = ?", (symbol,))
        row = cur.fetchone()
        if not row:
            logger.warning(f"recompute_symbol_signals: {symbol} not in stock_metadata")
            return 0
        sector = row[0]

        cur.execute("DELETE FROM stock_signals WHERE symbol = ?", (symbol,))
        conn.commit()

        cur.execute(
            "SELECT MIN(date), MAX(date) FROM prices_adjusted WHERE symbol = ?",
            (symbol,)
        )
        date_range = cur.fetchone()
        if not date_range or not date_range[0]:
            logger.warning(f"recompute_symbol_signals: no price data for {symbol}")
            return 0

        from_date = (
            datetime.strptime(date_range[0], '%Y-%m-%d') - timedelta(days=120)
        ).strftime('%Y-%m-%d')
        to_date = date_range[1]

        kse_list = _load_kse100(conn, from_date, to_date)
        kse_date_idx = {row[0]: i for i, row in enumerate(kse_list)}

        stock_prices = _load_stock_prices(conn, {symbol}, from_date, to_date)
        stock_prices_vol = _load_stock_prices_with_volume(conn, {symbol}, '2015-01-01', to_date)
        pivot_lookup = _build_pivot_lookup(stock_prices_vol)

        trading_dates = [r[0] for r in kse_list if r[0] >= date_range[0]]

        _process_trading_dates(
            conn, trading_dates, kse_list, kse_date_idx,
            stock_prices, {symbol: sector}, {},
            stock_prices_vol=stock_prices_vol,
            pivot_lookup=pivot_lookup,
        )

        cur.execute("SELECT COUNT(*) FROM stock_signals WHERE symbol = ?", (symbol,))
        n = cur.fetchone()[0]
        print(f"{symbol} — stock_signals recomputed ({n} rows)")
        return n
    finally:
        conn.close()


def update_pivot_signals() -> None:
    """Backfill pivot_high, pivot_distance_pct, and bos_flag for all rows in stock_signals."""
    logger.info("Starting pivot_high + pivot_distance_pct + bos_flag backfill...")
    conn = sqlite3.connect(DB)
    try:
        symbol_sector = _load_universe(conn)
        symbols = list(symbol_sector.keys())
        placeholders = ','.join('?' * len(symbols))
        cur = conn.cursor()

        cur.execute(
            f"SELECT symbol, date, close, high FROM prices_adjusted "
            f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
            symbols,
        )

        price_data: dict[str, list] = {}
        for sym, date, close, high in cur.fetchall():
            if sym not in price_data:
                price_data[sym] = []
            price_data[sym].append((date, close, high))

        updates = []
        total_processed = 0

        for symbol, prices in price_data.items():
            n = len(prices)
            confirmed_pivots = []  # (bar_index, high_value), appended in order

            for pos in range(n):
                # Confirm pivot at i = pos-10 once right side (10 bars) is available
                i = pos - 10
                if i >= 10:  # need 10 bars on the left side as well
                    hi = prices[i][2]
                    if hi is not None:
                        left_ok = all(
                            prices[j][2] is not None and prices[j][2] < hi
                            for j in range(i - 10, i)
                        )
                        right_ok = all(
                            prices[j][2] is not None and prices[j][2] < hi
                            for j in range(i + 1, i + 11)
                        )
                        if left_ok and right_ok:
                            confirmed_pivots.append((i, hi))

                date = prices[pos][0]
                close = prices[pos][1]
                ph = pd_pct = bf = None

                if confirmed_pivots and close is not None:
                    lower = pos - 50
                    for ci, ch in reversed(confirmed_pivots):
                        if ci >= lower:
                            ph = ch
                            pd_pct = (ph - close) / ph * 100
                            bf = 1 if pd_pct < 0 else 0
                            break

                updates.append((ph, pd_pct, bf, date, symbol))
                total_processed += 1

                if len(updates) >= 10_000:
                    cur.executemany(
                        "UPDATE stock_signals "
                        "SET pivot_high = ?, pivot_distance_pct = ?, bos_flag = ? "
                        "WHERE date = ? AND symbol = ?",
                        updates,
                    )
                    conn.commit()
                    updates = []

                if total_processed > 0 and total_processed % 50_000 == 0:
                    logger.info(f"  {total_processed:,} rows processed...")

        if updates:
            cur.executemany(
                "UPDATE stock_signals "
                "SET pivot_high = ?, pivot_distance_pct = ?, bos_flag = ? "
                "WHERE date = ? AND symbol = ?",
                updates,
            )
            conn.commit()

        logger.info(f"Backfill complete. Total rows processed: {total_processed:,}")

        cur.execute("SELECT COUNT(*) FROM stock_signals WHERE pivot_high IS NULL")
        ph_nulls = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM stock_signals WHERE bos_flag = 1")
        bos_count = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM stock_signals WHERE pivot_distance_pct BETWEEN 0 AND 3"
        )
        near_pivot = cur.fetchone()[0]
        logger.info(f"  pivot_high NULLs remaining : {ph_nulls:,}")
        logger.info(f"  bos_flag = 1 (breakouts)   : {bos_count:,}")
        logger.info(f"  pivot_distance_pct 0–3%    : {near_pivot:,}")
    finally:
        conn.close()
