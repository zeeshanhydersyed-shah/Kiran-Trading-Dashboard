import pandas as pd
import numpy as np
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

@dataclass
class SRZone:
    """Represents a Support/Resistance Zone"""
    high: float
    low: float
    mid: float
    strength: float  # 0-100 score
    touches: int
    last_touch_idx: int
    type: str  # 'support', 'resistance', 'neutral'
    is_active: bool  # Whether price is currently testing it
    volatility_adjusted: bool
    volume_weighted: float  # 0-1, how much volume confirmed it

    @property
    def width(self) -> float:
        return self.high - self.low

    @property
    def age(self) -> int:
        """How many bars old this zone is"""
        return len(self.last_touch_idx) if isinstance(self.last_touch_idx, (list, tuple)) else 0


class ImprovedSupportResistanceChannels:
    """
    Advanced Support/Resistance Zone Detector with:
    - Volatility-adjusted zones (ATR-based)
    - Trend detection & context
    - Volume-weighted strength
    - Adaptive pivot detection
    - Smart zone merging
    - Fractal-based pivot finding
    """

    def __init__(self,
                 pivot_period: int = 10,
                 base_channel_width_pct: float = 5.0,
                 min_strength: int = 1,
                 max_channels: int = 6,
                 loopback_period: int = 290,
                 atr_period: int = 14,
                 trend_period: int = 50,
                 volume_filter: bool = True,
                 merge_nearby_zones: bool = True,
                 adaptive_pivots: bool = True):
        """
        Initialize the improved indicator.

        Args:
            pivot_period: Base bars for pivot detection
            base_channel_width_pct: Base channel width (1-8%)
            min_strength: Minimum touches required
            max_channels: Max zones to show
            loopback_period: How far back to analyze
            atr_period: Period for ATR calculation (volatility)
            trend_period: Period for trend detection
            volume_filter: Require volume confirmation
            merge_nearby_zones: Merge overlapping/close zones
            adaptive_pivots: Use dynamic pivot periods based on trend
        """
        self.pivot_period = pivot_period
        self.base_channel_width_pct = base_channel_width_pct
        self.min_strength = min_strength
        self.max_channels = max_channels
        self.loopback_period = loopback_period
        self.atr_period = atr_period
        self.trend_period = trend_period
        self.volume_filter = volume_filter
        self.merge_nearby_zones = merge_nearby_zones
        self.adaptive_pivots = adaptive_pivots

    # ==================== VOLATILITY & TREND ====================

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range for volatility measurement"""
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())

        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    def calculate_trend(self, df: pd.DataFrame, period: int = 50) -> str:
        """
        Detect trend direction.
        Returns: 'uptrend', 'downtrend', 'ranging'
        """
        sma = df['close'].rolling(window=period).mean()
        current = df['close'].iloc[-1]
        avg = sma.iloc[-1]
        std = df['close'].rolling(window=period).std().iloc[-1]

        if current > avg + std * 0.5:
            return 'uptrend'
        elif current < avg - std * 0.5:
            return 'downtrend'
        else:
            return 'ranging'

    def get_dynamic_pivot_period(self, trend: str) -> int:
        """
        Adjust pivot period based on trend.
        - Uptrend/Downtrend: Use smaller periods (more sensitive)
        - Ranging: Use larger periods (filter noise)
        """
        if trend in ['uptrend', 'downtrend']:
            return max(5, self.pivot_period - 3)
        else:
            return min(15, self.pivot_period + 2)

    def get_adjusted_channel_width(self, df: pd.DataFrame, atr: pd.Series) -> float:
        """
        Adjust channel width based on volatility.
        Higher volatility = wider zones (less false breakouts)
        """
        current_atr = atr.iloc[-1]
        avg_atr = atr.tail(50).mean()

        volatility_ratio = current_atr / avg_atr if avg_atr > 0 else 1.0

        # Scale width by volatility (1.5x vol = 1.5x wider zones)
        adjusted_width = self.base_channel_width_pct * volatility_ratio

        # Clamp between reasonable bounds
        return np.clip(adjusted_width, 1.0, 12.0)

    # ==================== PIVOT DETECTION ====================

    def find_fractal_pivots(self, df: pd.DataFrame, period: int = 10) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
        """
        Find pivot highs and lows using fractal pattern.
        A fractal high: center bar higher than 'period' bars on each side.
        More reliable than simple high/low.
        """
        ph_list = []
        pl_list = []

        p = period

        for i in range(p, len(df) - p):
            high_val = df['high'].iloc[i]
            low_val = df['low'].iloc[i]

            # Check if it's a pivot high (fractal)
            if high_val >= df['high'].iloc[i-p:i].max() and \
               high_val > df['high'].iloc[i+1:i+p+1].max():
                ph_list.append((i, high_val))

            # Check if it's a pivot low (fractal)
            if low_val <= df['low'].iloc[i-p:i].min() and \
               low_val < df['low'].iloc[i+1:i+p+1].min():
                pl_list.append((i, low_val))

        return ph_list, pl_list

    def filter_pivots_by_volume(self, df: pd.DataFrame, pivots: List[Tuple[int, float]]) -> List[Tuple[int, float]]:
        """Filter out pivots that occurred on unusually low volume"""
        if 'volume' not in df.columns or not self.volume_filter:
            return pivots

        avg_volume = df['volume'].rolling(window=20).mean()
        filtered = []

        for idx, price in pivots:
            pivot_volume = df['volume'].iloc[idx]
            avg_vol = avg_volume.iloc[idx]

            # Keep pivots with at least 70% of average volume
            if pivot_volume >= avg_vol * 0.7:
                filtered.append((idx, price))

        return filtered

    # ==================== ZONE CALCULATION ====================

    def get_sr_level(self, pivot_idx: int, pivot_value: float,
                     all_pivots: List[Tuple[int, float]],
                     max_width: float) -> Tuple[float, float, int]:
        """Find S/R zone boundaries for a pivot"""
        lo = pivot_value
        hi = pivot_value
        num_pivots = 0

        for _, pv in all_pivots:
            if pv <= hi:
                width = hi - pv
            else:
                width = pv - lo

            if width <= max_width:
                if pv <= hi:
                    lo = min(lo, pv)
                else:
                    hi = max(hi, pv)
                num_pivots += 1

        return hi, lo, num_pivots

    def calculate_zone_strength(self, df: pd.DataFrame,
                               zone_high: float, zone_low: float,
                               lookback: int, num_pivots: int,
                               atr: pd.Series) -> Dict:
        """
        Calculate zone strength with multiple factors:
        - Number of pivots in zone
        - Number of touches
        - Recency of touches
        - Volume confirmation
        - Price close vs touches (closes > just touches)
        """
        touches = 0
        closes_in_zone = 0
        volume_weight = 0
        last_touch = -1

        current_atr = atr.iloc[-1]

        for i in range(max(0, len(df) - lookback), len(df)):
            # Check if price tested zone
            if zone_low <= df['high'].iloc[i] and df['low'].iloc[i] <= zone_high:
                touches += 1
                last_touch = i

                # Extra weight for close inside zone
                if zone_low <= df['close'].iloc[i] <= zone_high:
                    closes_in_zone += 1

                # Volume weight
                if 'volume' in df.columns:
                    volume_weight += (df['volume'].iloc[i] / df['volume'].tail(20).mean())

        # Base strength from pivots
        pivot_strength = num_pivots * 20

        # Touch strength (recent touches worth more)
        touch_strength = 0
        for i in range(max(0, len(df) - lookback), len(df)):
            if zone_low <= df['high'].iloc[i] and df['low'].iloc[i] <= zone_high:
                # Recent touches worth more (exponential decay)
                bars_ago = len(df) - 1 - i
                recency_factor = np.exp(-bars_ago / lookback)
                touch_strength += 10 * recency_factor

        # Close strength (very important - means rejection)
        close_strength = closes_in_zone * 15

        # Volume confirmation (0-20 points)
        if touches > 0:
            volume_score = min(20, (volume_weight / touches) * 10)
        else:
            volume_score = 0

        # Total strength (0-100 scale)
        total_strength = min(100, pivot_strength + touch_strength + close_strength + volume_score)

        return {
            'strength': total_strength,
            'touches': touches,
            'closes_in_zone': closes_in_zone,
            'last_touch': last_touch,
            'volume_weight': volume_weight / touches if touches > 0 else 0
        }

    # ==================== ZONE MERGING ====================

    def merge_overlapping_zones(self, zones: List[Dict]) -> List[Dict]:
        """
        Intelligently merge zones that overlap or are very close.
        Keep the one with higher strength, combine their stats.
        """
        if not self.merge_nearby_zones or len(zones) <= 1:
            return zones

        merged = []
        used = set()

        for i, zone1 in enumerate(zones):
            if i in used:
                continue

            current = zone1.copy()

            # Find overlapping/close zones
            for j, zone2 in enumerate(zones[i+1:], start=i+1):
                if j in used:
                    continue

                # Check if zones overlap or are within 2% of each other
                gap = max(0, zone2['low'] - current['high'])
                zone_size = current['high'] - current['low']

                if gap < zone_size * 0.02:  # Within 2% of zone
                    # Merge them
                    current['high'] = max(current['high'], zone2['high'])
                    current['low'] = min(current['low'], zone2['low'])
                    current['strength'] = (current['strength'] + zone2['strength']) / 2
                    current['touches'] += zone2['touches']
                    current['volume_weight'] = (current['volume_weight'] + zone2['volume_weight']) / 2
                    used.add(j)

            merged.append(current)

        return merged

    # ==================== TREND-AWARE ZONE CLASSIFICATION ====================

    def classify_zone(self, zone_high: float, zone_low: float,
                     current_price: float, trend: str) -> str:
        """
        Classify zone as support, resistance, or neutral based on price position.
        Takes trend into account.
        """
        zone_mid = (zone_high + zone_low) / 2

        if current_price > zone_high:
            return 'resistance'
        elif current_price < zone_low:
            return 'support'
        else:
            return 'in_zone'

    # ==================== MAIN CALCULATION ====================

    def calculate_zones(self, df: pd.DataFrame) -> List[SRZone]:
        """
        Main method to calculate all S/R zones with improvements.
        """
        # Ensure we have required columns
        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"DataFrame must contain columns: {required_cols}")

        # Calculate technical indicators
        atr = self.calculate_atr(df, self.atr_period)
        trend = self.calculate_trend(df, self.trend_period)

        # Get dynamic parameters based on trend
        pivot_period = self.get_dynamic_pivot_period(trend)
        adjusted_width_pct = self.get_adjusted_channel_width(df, atr)

        # Find pivots
        ph_list, pl_list = self.find_fractal_pivots(df, pivot_period)

        # Filter by volume
        ph_list = self.filter_pivots_by_volume(df, ph_list)
        pl_list = self.filter_pivots_by_volume(df, pl_list)

        all_pivots = ph_list + pl_list

        if not all_pivots:
            return []

        # Keep only recent pivots
        cutoff_idx = len(df) - self.loopback_period
        all_pivots = [(idx, val) for idx, val in all_pivots if idx >= cutoff_idx]

        if not all_pivots:
            return []

        # Calculate max channel width in price units
        highest = df['high'].tail(300).max()
        lowest = df['low'].tail(300).min()
        max_width = (highest - lowest) * adjusted_width_pct / 100

        # Calculate S/R zones
        zones_data = []
        for pivot_idx, (idx, pv) in enumerate(all_pivots):
            hi, lo, num_pp = self.get_sr_level(pivot_idx, pv, all_pivots, max_width)

            # Skip if zone is too small or pivots don't meet minimum
            if num_pp < self.min_strength:
                continue

            # Calculate comprehensive strength
            strength_info = self.calculate_zone_strength(
                df, hi, lo, self.loopback_period, num_pp, atr
            )

            current_price = df['close'].iloc[-1]
            zone_type = self.classify_zone(hi, lo, current_price, trend)

            zones_data.append({
                'high': hi,
                'low': lo,
                'mid': (hi + lo) / 2,
                'strength': strength_info['strength'],
                'touches': strength_info['touches'],
                'last_touch_idx': strength_info['last_touch'],
                'type': zone_type,
                'is_active': zone_type == 'in_zone',
                'volume_weight': strength_info['volume_weight'],
                'volatility_adjusted': True,
                'trend': trend,
                'atr_factor': atr.iloc[-1] / atr.tail(50).mean()
            })

        # Merge overlapping zones
        zones_data = self.merge_overlapping_zones(zones_data)

        # Sort by strength and get top N
        zones_data = sorted(zones_data, key=lambda x: x['strength'], reverse=True)
        zones_data = zones_data[:self.max_channels]

        # Convert to SRZone objects
        sr_zones = []
        for z in zones_data:
            sr_zones.append(SRZone(
                high=z['high'],
                low=z['low'],
                mid=z['mid'],
                strength=z['strength'],
                touches=z['touches'],
                last_touch_idx=z['last_touch_idx'],
                type=z['type'],
                is_active=z['is_active'],
                volatility_adjusted=z['volatility_adjusted'],
                volume_weighted=z['volume_weight']
            ))

        return sr_zones

    # ==================== BREAKOUT DETECTION ====================

    def check_breakouts(self, df: pd.DataFrame) -> Dict:
        """Detect if price has broken through zones with context"""
        zones = self.calculate_zones(df)

        current_price = df['close'].iloc[-1]
        previous_price = df['close'].iloc[-2]
        atr = self.calculate_atr(df, self.atr_period)
        current_atr = atr.iloc[-1]

        in_zone = False
        active_zone = None

        for zone in zones:
            if zone.low <= current_price <= zone.high:
                in_zone = True
                active_zone = zone
                break

        resistance_broken = False
        support_broken = False
        strong_breakout = False

        if not in_zone:
            for zone in zones:
                # Check resistance break
                if previous_price <= zone.high and current_price > zone.high:
                    resistance_broken = True
                    # Strong if breaks by more than 0.5 ATR
                    if current_price - zone.high > current_atr * 0.5:
                        strong_breakout = True

                # Check support break
                if previous_price >= zone.low and current_price < zone.low:
                    support_broken = True
                    # Strong if breaks by more than 0.5 ATR
                    if zone.low - current_price > current_atr * 0.5:
                        strong_breakout = True

        return {
            'resistance_broken': resistance_broken,
            'support_broken': support_broken,
            'strong_breakout': strong_breakout,
            'in_zone': in_zone,
            'active_zone': active_zone,
            'zones': zones,
            'current_price': current_price,
            'current_atr': current_atr
        }

    # ==================== VISUALIZATION & REPORTING ====================

    def print_zones(self, df: pd.DataFrame, include_stats: bool = True) -> None:
        """Pretty print zones with detailed information"""
        zones = self.calculate_zones(df)

        print(f"\n{'='*80}")
        print(f"SUPPORT/RESISTANCE ZONE ANALYSIS")
        print(f"{'='*80}")

        atr = self.calculate_atr(df, self.atr_period)
        trend = self.calculate_trend(df, self.trend_period)
        current_price = df['close'].iloc[-1]
        current_atr = atr.iloc[-1]

        print(f"\nCURRENT PRICE: {current_price:.4f}")
        print(f"ATR (14): {current_atr:.4f}")
        print(f"TREND: {trend.upper()}")
        print(f"Bars Analyzed: {len(df)}")

        if not zones:
            print("\n  No significant zones found")
            return

        print(f"\n{'-'*80}")
        print(f"{'#':<3} {'TYPE':<12} {'HIGH':<12} {'LOW':<12} {'WIDTH':<10} {'STR':<6} {'TOUCHES':<8}")
        print(f"{'-'*80}")

        for i, zone in enumerate(zones, 1):
            type_str = f"{zone.type.upper()[:3]}"
            if zone.is_active:
                type_str += " [ACTIVE]"

            print(f"{i:<3} {type_str:<12} {zone.high:<12.4f} {zone.low:<12.4f} "
                  f"{zone.width:<10.4f} {zone.strength:<6.1f} {zone.touches:<8}")

        if include_stats:
            print(f"\n{'-'*80}")
            print("ADDITIONAL METRICS:")
            print(f"{'-'*80}")

            for i, zone in enumerate(zones, 1):
                pct_to_high = ((zone.high - current_price) / current_price * 100) if current_price > 0 else 0
                pct_to_low = ((current_price - zone.low) / current_price * 100) if current_price > 0 else 0

                print(f"\nZone {i}:")
                print(f"  Distance to High: {abs(pct_to_high):.2f}% {'up' if pct_to_high > 0 else 'down'}")
                print(f"  Distance to Low:  {abs(pct_to_low):.2f}% {'up' if pct_to_low > 0 else 'down'}")
                print(f"  Zone Width: {zone.width:.4f} ({zone.width/current_price*100:.2f}% of price)")
                print(f"  Volume Weight: {zone.volume_weighted:.2f}")

        # Breakout info
        breakout = self.check_breakouts(df)
        print(f"\n{'-'*80}")
        print("BREAKOUT STATUS:")
        print(f"{'-'*80}")
        print(f"In Channel: {breakout['in_zone']}")
        print(f"Resistance Broken: {breakout['resistance_broken']} {'[STRONG]' if breakout['strong_breakout'] else ''}")
        print(f"Support Broken: {breakout['support_broken']} {'[STRONG]' if breakout['strong_breakout'] else ''}")

    def get_zones_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return zones as a pandas DataFrame for easy export"""
        zones = self.calculate_zones(df)

        data = []
        for i, zone in enumerate(zones, 1):
            data.append({
                'Rank': i,
                'Type': zone.type,
                'High': zone.high,
                'Low': zone.low,
                'Mid': zone.mid,
                'Width': zone.width,
                'Strength': zone.strength,
                'Touches': zone.touches,
                'Active': zone.is_active,
                'Volume_Weight': zone.volume_weighted
            })

        return pd.DataFrame(data)
