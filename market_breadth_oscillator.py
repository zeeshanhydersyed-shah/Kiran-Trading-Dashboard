"""
Market Breadth Oscillator Chart
Calculates 20/50/200 EMA conditions for all PSX stocks and plots long/short counts.
"""

import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
from pathlib import Path


def load_price_data() -> pd.DataFrame:
    """Load historical price data from SQLite database (or CSV fallback)."""
    try:
        from database import get_prices_for_breadth
        raw = get_prices_for_breadth()
        if not raw:
            raise ValueError("No price data from database")

        df = pd.DataFrame(raw)
        df['date'] = pd.to_datetime(df['date'])
        df['symbol'] = df['symbol'].astype(str)
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        return df.dropna(subset=['close'])
    except Exception as e:
        print(f"Database load failed ({e}), falling back to CSV...")
        csv_path = Path(__file__).parent / 'merged_psx_data.csv'
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")
        df = pd.read_csv(csv_path)
        df['date'] = pd.to_datetime(df['date'])
        return df


def calculate_emas(group: pd.DataFrame) -> pd.DataFrame:
    """Calculate 20, 50, 200 EMAs for a stock."""
    group = group.sort_values('date').reset_index(drop=True)
    group['ema_20'] = group['close'].ewm(span=20, adjust=False).mean()
    group['ema_50'] = group['close'].ewm(span=50, adjust=False).mean()
    group['ema_200'] = group['close'].ewm(span=200, adjust=False).mean()
    return group


def apply_ema_conditions(df: pd.DataFrame) -> pd.DataFrame:
    """Apply LONG and SHORT conditions to each row."""
    df['long_condition'] = (
        (df['close'] > df['ema_20']) &
        (df['ema_20'] > df['ema_50']) &
        (df['ema_50'] > df['ema_200'])
    ).astype(int)

    df['short_condition'] = (
        (df['close'] < df['ema_20']) &
        (df['ema_20'] < df['ema_50']) &
        (df['ema_50'] < df['ema_200'])
    ).astype(int)

    return df


def compute_breadth_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily counts of stocks meeting LONG/SHORT conditions."""
    breadth = df.groupby('date').agg({
        'long_condition': 'sum',
        'short_condition': 'sum'
    }).reset_index()

    breadth.columns = ['Date', 'Long_Count', 'Short_Count']
    breadth = breadth.sort_values('Date').reset_index(drop=True)

    return breadth


def plot_breadth_oscillator(breadth: pd.DataFrame, output_path: str = None):
    """Plot the market breadth oscillator chart."""
    fig, ax = plt.subplots(figsize=(14, 7))

    ax.plot(breadth['Date'], breadth['Long_Count'], color='#00E676', linewidth=2, label='Long Count')
    ax.plot(breadth['Date'], breadth['Short_Count'], color='#FF5252', linewidth=2, label='Short Count')

    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(loc='upper left', fontsize=11)

    ax.set_xlabel('Date', fontsize=11)
    ax.set_ylabel('Stock Count', fontsize=11)
    ax.set_title('Market Breadth Oscillator (PSX)', fontsize=13, fontweight='bold')

    fig.autofmt_xdate(rotation=45, ha='right')
    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Chart saved to {output_path}")
    else:
        plt.show()


def main():
    """Main execution pipeline."""
    print("Loading price data from database...")
    df = load_price_data()

    print("Calculating EMAs by stock...")
    df = df.groupby('symbol', group_keys=False).apply(calculate_emas, include_groups=False)

    print("Applying LONG/SHORT conditions...")
    df = apply_ema_conditions(df)

    print("Computing daily breadth counts...")
    breadth = compute_breadth_counts(df)

    print(f"\nBreadth data summary:")
    print(f"Date range: {breadth['Date'].min().date()} to {breadth['Date'].max().date()}")
    print(f"Long Count - Min: {breadth['Long_Count'].min()}, Max: {breadth['Long_Count'].max()}, Mean: {breadth['Long_Count'].mean():.1f}")
    print(f"Short Count - Min: {breadth['Short_Count'].min()}, Max: {breadth['Short_Count'].max()}, Mean: {breadth['Short_Count'].mean():.1f}")

    print("\nPlotting chart...")
    output_path = Path(__file__).parent / 'market_breadth_oscillator.png'
    plot_breadth_oscillator(breadth, str(output_path))

    # Save breadth data to CSV
    breadth_csv_path = Path(__file__).parent / 'breadth_data.csv'
    breadth.to_csv(breadth_csv_path, index=False)
    print(f"Breadth data saved to {breadth_csv_path}")


if __name__ == '__main__':
    main()
