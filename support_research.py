"""
Support Pattern Research Engine

Discovers quantitative definitions of "price touches obvious support, weak hands exit,
support absorbs supply, price strongly reclaims and resumes trend."

Multiple support hypothesis testing → pattern detection → signal generation → analysis.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class SupportSignal:
    """Single support touch event with metrics."""
    symbol: str
    date: str
    support_source: str  # which definition found it
    support_level: float
    touch_depth: float  # how much low penetrated below support
    lower_wick: float
    lower_wick_ratio: float
    close_position: float  # (C-L)/(H-L), 0=low 1=high
    recovery_ratio: float  # (C-L)/(H-L) (intraday recovery %)
    body_ratio: float  # |C-O|/range
    range: float
    volume_ma_ratio: float  # current vol / 20-MA vol
    atr: float
    trend_state: str  # uptrend/neutral/downtrend
    trend_sma: float  # SMA50 price
    entry_price: float  # where trader would enter
    stop_price: float  # logical stop below support
    return_5d: Optional[float] = None
    return_10d: Optional[float] = None
    return_20d: Optional[float] = None
    max_favorable: Optional[float] = None
    max_adverse: Optional[float] = None


class SupportDetector:
    """Tests multiple support definitions against historical price data."""

    def __init__(self, df: pd.DataFrame, lookback: int = 60):
        """
        Args:
            df: DataFrame with columns [symbol, date, open, high, low, close, volume]
            lookback: bars to look back for support detection
        """
        self.df = df.copy()
        self.df['date'] = pd.to_datetime(self.df['date'])
        self.df = self.df.sort_values(['symbol', 'date']).reset_index(drop=True)
        self.lookback = lookback

    def detect_swing_lows(self, symbol: str, date_idx: int, window: int = 10) -> List[float]:
        """Previous N bar swing lows (local minima)."""
        sym_data = self.df[self.df['symbol'] == symbol].reset_index(drop=True)
        if date_idx < window + 1:
            return []

        lows = []
        for i in range(1, window + 1):
            idx = date_idx - i
            if idx >= 0:
                lows.append(sym_data.iloc[idx]['low'])
        return sorted(set(lows))

    def detect_volume_cluster(self, symbol: str, date_idx: int, window: int = 20) -> Optional[float]:
        """Price level with highest volume concentration."""
        sym_data = self.df[self.df['symbol'] == symbol].reset_index(drop=True)
        if date_idx < window:
            return None

        hist = sym_data.iloc[date_idx-window:date_idx]
        if len(hist) == 0:
            return None

        # Bucket prices by 5% increments, find highest vol bucket
        min_price, max_price = hist['low'].min(), hist['high'].max()
        bucket_size = (max_price - min_price) * 0.05 + 1e-9

        hist['bucket'] = ((hist['close'] - min_price) / bucket_size).astype(int)
        vol_by_bucket = hist.groupby('bucket')['volume'].sum().idxmax()

        return min_price + vol_by_bucket * bucket_size

    def detect_rolling_min(self, symbol: str, date_idx: int, window: int = 20) -> Optional[float]:
        """Density of recent lows (rolling minimum over window)."""
        sym_data = self.df[self.df['symbol'] == symbol].reset_index(drop=True)
        if date_idx < window:
            return None

        window_data = sym_data.iloc[date_idx-window:date_idx]
        return window_data['low'].min()

    def detect_pivot_point(self, symbol: str, date_idx: int) -> Optional[float]:
        """Standard pivot point support from previous bar."""
        sym_data = self.df[self.df['symbol'] == symbol].reset_index(drop=True)
        if date_idx < 1:
            return None

        prev = sym_data.iloc[date_idx - 1]
        pivot = (prev['high'] + prev['low'] + prev['close']) / 3
        support1 = (pivot * 2) - prev['high']
        return support1

    def detect_horizontal_level(self, symbol: str, date_idx: int, window: int = 30,
                                tolerance_pct: float = 0.02) -> List[float]:
        """Multi-touch horizontal zones (price touches same level multiple times)."""
        sym_data = self.df[self.df['symbol'] == symbol].reset_index(drop=True)
        if date_idx < window:
            return []

        window_data = sym_data.iloc[date_idx-window:date_idx]
        closes = window_data['close'].values

        # Simple clustering: find price levels touched 2+ times
        levels = []
        for i, price in enumerate(closes):
            cluster = [p for p in closes if abs(p - price) / price < tolerance_pct]
            if len(cluster) >= 2:
                levels.append(np.mean(cluster))

        return sorted(set(np.round(levels, 2)))

    def calculate_atr(self, symbol: str, date_idx: int, window: int = 14) -> float:
        """Average True Range."""
        sym_data = self.df[self.df['symbol'] == symbol].reset_index(drop=True)
        if date_idx < window:
            return 0

        data = sym_data.iloc[date_idx-window:date_idx]
        data = data.copy()
        data['tr'] = np.maximum(
            data['high'] - data['low'],
            np.maximum(
                abs(data['high'] - data['close'].shift(1)),
                abs(data['low'] - data['close'].shift(1))
            )
        )
        return data['tr'].mean()

    def calculate_sma(self, symbol: str, date_idx: int, window: int = 50) -> float:
        """Simple moving average."""
        sym_data = self.df[self.df['symbol'] == symbol].reset_index(drop=True)
        if date_idx < window:
            return np.nan

        return sym_data.iloc[date_idx-window:date_idx]['close'].mean()

    def is_support_touched(self, low: float, support: float, atr: float,
                          tolerance_factor: float = 1.0) -> Tuple[bool, float]:
        """
        Check if support was touched.

        Returns: (was_touched, touch_depth_pct)
        """
        tolerance = atr * tolerance_factor
        touch_depth = support - low

        if touch_depth >= 0 and touch_depth <= tolerance:
            return True, touch_depth / support
        return False, touch_depth / support if support != 0 else 0

    def generate_signals(self, tolerance_factor: float = 1.0) -> List[SupportSignal]:
        """Generate all support touch signals."""
        signals = []

        for symbol in self.df['symbol'].unique():
            sym_data = self.df[self.df['symbol'] == symbol].reset_index(drop=True)

            for date_idx in range(max(self.lookback, 50), len(sym_data)):
                row = sym_data.iloc[date_idx]
                o, h, l, c = row['open'], row['high'], row['low'], row['close']
                vol = row.get('volume', 0)

                # Calculate metrics for this candle
                range_val = h - l
                if range_val == 0:
                    continue

                atr = self.calculate_atr(symbol, date_idx)
                sma50 = self.calculate_sma(symbol, date_idx, 50)
                vol_ma20 = sym_data.iloc[max(0, date_idx-20):date_idx]['volume'].mean()

                # Gather all support hypotheses
                all_supports = []

                # 1. Swing lows
                for swing in self.detect_swing_lows(symbol, date_idx, window=15):
                    all_supports.append(('swing_low', swing))

                # 2. Volume cluster
                vc = self.detect_volume_cluster(symbol, date_idx, window=30)
                if vc:
                    all_supports.append(('volume_cluster', vc))

                # 3. Rolling min
                rm = self.detect_rolling_min(symbol, date_idx, window=20)
                if rm:
                    all_supports.append(('rolling_min', rm))

                # 4. Pivot
                pp = self.detect_pivot_point(symbol, date_idx)
                if pp:
                    all_supports.append(('pivot', pp))

                # 5. Horizontal levels
                for level in self.detect_horizontal_level(symbol, date_idx, window=30):
                    all_supports.append(('horizontal', level))

                # Check each support for touch
                for support_source, support_level in all_supports:
                    touched, touch_depth = self.is_support_touched(
                        l, support_level, atr, tolerance_factor
                    )

                    if not touched:
                        continue

                    # Only care about cases where price was below support or near it
                    if l >= support_level - (atr * tolerance_factor):
                        # Calculate pattern metrics
                        lower_wick = min(o, c) - l
                        upper_wick = h - max(o, c)
                        body = abs(c - o)

                        close_pos = (c - l) / range_val if range_val > 0 else 0
                        recovery = close_pos  # same metric

                        # Trend
                        if pd.notna(sma50):
                            if c > sma50 * 1.01:
                                trend = 'uptrend'
                            elif c < sma50 * 0.99:
                                trend = 'downtrend'
                            else:
                                trend = 'neutral'
                        else:
                            trend = 'neutral'

                        # Create signal
                        signal = SupportSignal(
                            symbol=symbol,
                            date=str(row['date'].date()),
                            support_source=support_source,
                            support_level=support_level,
                            touch_depth=touch_depth,
                            lower_wick=lower_wick,
                            lower_wick_ratio=lower_wick / range_val if range_val > 0 else 0,
                            close_position=close_pos,
                            recovery_ratio=recovery,
                            body_ratio=body / range_val if range_val > 0 else 0,
                            range=range_val,
                            volume_ma_ratio=vol / vol_ma20 if vol_ma20 > 0 else 1.0,
                            atr=atr,
                            trend_state=trend,
                            trend_sma=sma50 if pd.notna(sma50) else c,
                            entry_price=h,  # enter on break of high
                            stop_price=support_level - atr * 0.5  # stop below support
                        )
                        signals.append(signal)

        return signals


class SignalAnalyzer:
    """Analyze signal performance and cluster winners."""

    def __init__(self, signals: List[SupportSignal], price_data: pd.DataFrame):
        self.signals = signals
        self.price_data = price_data.copy()
        self.price_data['date'] = pd.to_datetime(self.price_data['date'])

    def forward_test(self, signals: List[SupportSignal], windows: List[int] = [5, 10, 20]) -> List[SupportSignal]:
        """Calculate forward returns for each signal."""
        result = []

        for sig in signals:
            sig_date = pd.to_datetime(sig.date)
            sym_data = self.price_data[self.price_data['symbol'] == sig.symbol]
            sym_data = sym_data.sort_values('date')

            sig_idx = sym_data[sym_data['date'] == sig_date].index
            if len(sig_idx) == 0:
                continue

            sig_idx = sym_data.index.get_loc(sig_idx[0])
            entry_price = sig.entry_price

            # Calculate returns and extremes over forward windows
            forward_data = sym_data.iloc[sig_idx+1:sig_idx+21]  # up to 20 bars forward

            if len(forward_data) == 0:
                continue

            for window in windows:
                if len(forward_data) >= window:
                    price_at_window = forward_data.iloc[window-1]['close']
                    setattr(sig, f'return_{window}d', (price_at_window - entry_price) / entry_price)

            # Max favorable and adverse excursion
            if len(forward_data) > 0:
                sig.max_favorable = (forward_data['high'].max() - entry_price) / entry_price
                sig.max_adverse = (forward_data['low'].min() - entry_price) / entry_price

            result.append(sig)

        return result

    def to_dataframe(self, signals: List[SupportSignal]) -> pd.DataFrame:
        """Convert signals to DataFrame for analysis."""
        rows = []
        for sig in signals:
            rows.append({
                'symbol': sig.symbol,
                'date': sig.date,
                'support_source': sig.support_source,
                'support_level': round(sig.support_level, 2),
                'touch_depth_pct': round(sig.touch_depth * 100, 2),
                'lower_wick_ratio': round(sig.lower_wick_ratio, 3),
                'close_position': round(sig.close_position, 3),
                'recovery_ratio': round(sig.recovery_ratio, 3),
                'body_ratio': round(sig.body_ratio, 3),
                'volume_ma_ratio': round(sig.volume_ma_ratio, 2),
                'trend_state': sig.trend_state,
                'return_5d': round(sig.return_5d, 4) if sig.return_5d else None,
                'return_10d': round(sig.return_10d, 4) if sig.return_10d else None,
                'return_20d': round(sig.return_20d, 4) if sig.return_20d else None,
                'max_favorable': round(sig.max_favorable, 4) if sig.max_favorable else None,
                'max_adverse': round(sig.max_adverse, 4) if sig.max_adverse else None,
            })
        return pd.DataFrame(rows)

    def win_rate_by_source(self, df: pd.DataFrame) -> pd.DataFrame:
        """Win rate and expectancy by support source."""
        results = []
        for source in df['support_source'].unique():
            subset = df[df['support_source'] == source]

            # Win if positive return within 5/10/20 days
            subset_5d = subset[subset['return_5d'].notna()]
            win5 = (subset_5d['return_5d'] > 0).sum() / len(subset_5d) if len(subset_5d) > 0 else 0

            subset_10d = subset[subset['return_10d'].notna()]
            win10 = (subset_10d['return_10d'] > 0).sum() / len(subset_10d) if len(subset_10d) > 0 else 0

            subset_20d = subset[subset['return_20d'].notna()]
            win20 = (subset_20d['return_20d'] > 0).sum() / len(subset_20d) if len(subset_20d) > 0 else 0

            results.append({
                'support_source': source,
                'signals': len(subset),
                'win_rate_5d': round(win5, 3),
                'expectancy_5d': round(subset_5d['return_5d'].mean(), 4) if len(subset_5d) > 0 else 0,
                'win_rate_10d': round(win10, 3),
                'expectancy_10d': round(subset_10d['return_10d'].mean(), 4) if len(subset_10d) > 0 else 0,
                'win_rate_20d': round(win20, 3),
                'expectancy_20d': round(subset_20d['return_20d'].mean(), 4) if len(subset_20d) > 0 else 0,
            })

        return pd.DataFrame(results)

    def win_rate_by_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        """Performance filtered by trend context."""
        results = []
        for trend in ['uptrend', 'neutral', 'downtrend']:
            subset = df[df['trend_state'] == trend]
            if len(subset) == 0:
                continue

            subset_5d = subset[subset['return_5d'].notna()]
            win5 = (subset_5d['return_5d'] > 0).sum() / len(subset_5d) if len(subset_5d) > 0 else 0

            results.append({
                'trend': trend,
                'signals': len(subset),
                'win_rate_5d': round(win5, 3),
                'expectancy_5d': round(subset_5d['return_5d'].mean(), 4) if len(subset_5d) > 0 else 0,
                'avg_recovery': round(subset['recovery_ratio'].mean(), 3),
                'avg_wick_ratio': round(subset['lower_wick_ratio'].mean(), 3),
            })

        return pd.DataFrame(results)
