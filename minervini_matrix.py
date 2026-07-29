"""
Minervini Scenario Matrix — PSX
================================
RS ≥ 95 fixed filter.

Exit logic (hybrid):
  - Hard initial SL  = -4% from entry (always active)
  - Trailing ATR stop activates ONLY once close > entry price
    trail = SMA(n) - atr_mult × ATR14
    Once active: stop = max(trail_stop, initial_sl_price)  → never goes below -4%

Matrix dimensions:
  sma_n     : 10, 20
  atr_mult  : 0.5, 1.0, 1.5, 2.0
  hold_max  : 20, 40, 60

All permutations = 2 × 4 × 3 = 24 scenarios.

Usage:
    python minervini_matrix.py
    python minervini_matrix.py --rs_min 95 --initial_sl 0.04
"""

import argparse, json, warnings, itertools
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

BASE       = Path(__file__).parent
STOCK_CSV  = BASE / "merged_psx_data.csv"
INDEX_CSV  = BASE / "merged_index_data.csv"
OUTPUT_DIR = BASE / "backtest_results"
OUTPUT_DIR.mkdir(exist_ok=True)

DEFAULTS = dict(
    rs_min      = 95,
    initial_sl  = 0.04,   # hard floor SL from entry
    atr_period  = 14,
    sma_trend   = 50,
    sma_regime  = 50,
    resist_window = 60,
    pp_vol_window = 10,
    min_avg_vol = 100_000, # 20-day avg daily volume floor
)

MATRIX = dict(
    sma_n    = [10, 20],
    atr_mult = [0.5, 1.0, 1.5, 2.0],
    hold_max = [20, 40, 60],
)


# ══════════════════════════════════════════════════════════════════════════════
#  LOAD
# ══════════════════════════════════════════════════════════════════════════════

def load_data():
    print("Loading data …")
    stocks = pd.read_csv(STOCK_CSV, parse_dates=["date"])
    stocks = stocks.sort_values(["symbol","date"]).reset_index(drop=True)

    index = pd.read_csv(INDEX_CSV, parse_dates=["date"])
    index = index[index["symbol"]=="KSE-100"][["date","close"]].copy()
    index = index.sort_values("date").reset_index(drop=True)
    index.rename(columns={"close":"idx_close"}, inplace=True)

    print(f"  {stocks['symbol'].nunique()} symbols  "
          f"{stocks['date'].min().date()} → {stocks['date'].max().date()}")
    return stocks, index


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURES  (computed once, shared across all scenarios)
# ══════════════════════════════════════════════════════════════════════════════

def build_features(stocks: pd.DataFrame, index: pd.DataFrame, p: dict) -> pd.DataFrame:
    print("Computing features …")
    df = stocks.copy()
    g  = df.groupby("symbol", sort=False)

    # SMA 10, 20, 50
    for n in [10, 20, p["sma_trend"]]:
        df[f"sma{n}"] = g["close"].transform(
            lambda s, n=n: s.rolling(n, min_periods=n).mean()
        )
    df["trend_up"] = df["close"] > df[f"sma{p['sma_trend']}"]

    # ATR14
    pc = g["close"].transform(lambda s: s.shift(1))
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"]  - pc).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = g["close"].transform(
        lambda s: tr.loc[s.index].rolling(p["atr_period"], min_periods=p["atr_period"]).mean()
    )

    # Pre-compute trail stop columns for all sma_n values
    for n in MATRIX["sma_n"]:
        for m in MATRIX["atr_mult"]:
            col = f"ts_{n}_{str(m).replace('.','p')}"
            df[col] = df[f"sma{n}"] - m * df["atr14"]

    # RS rating
    for w, col in [(21,"r21"),(63,"r63"),(126,"r126"),(252,"r252")]:
        df[col] = g["close"].transform(lambda s, w=w: s / s.shift(w) - 1)
    df["rs_raw"] = 0.4*df["r252"] + 0.3*df["r126"] + 0.2*df["r63"] + 0.1*df["r21"]
    df["rs_rating"] = df.groupby("date")["rs_raw"].rank(pct=True, method="average") * 100

    # Index regime + RS score
    idx = index.copy()
    idx["idx_sma50"] = idx["idx_close"].rolling(p["sma_regime"], min_periods=p["sma_regime"]).mean()
    idx["market_up"] = idx["idx_close"] > idx["idx_sma50"]
    for w,c in [(21,"ir21"),(63,"ir63"),(126,"ir126"),(252,"ir252")]:
        idx[c] = idx["idx_close"] / idx["idx_close"].shift(w) - 1
    df = df.merge(idx[["date","market_up","ir21","ir63","ir126","ir252"]], on="date", how="left")
    df["rs_score"] = df["rs_raw"] - (0.4*df["ir252"]+0.3*df["ir126"]+0.2*df["ir63"]+0.1*df["ir21"])

    # Pocket pivot
    df["prev_close"] = g["close"].transform(lambda s: s.shift(1))
    df["down_day"]   = df["close"] < df["prev_close"]
    w = p["pp_vol_window"]
    dv = df["volume"].where(df["down_day"], 0)
    df["max_down_vol"] = (
        df.groupby("symbol", sort=False)
          .apply(lambda grp: dv.loc[grp.index].rolling(w, min_periods=1).max())
          .reset_index(level=0, drop=True)
    )
    df["close_pos"]    = (df["close"] - df["low"]) / (df["high"] - df["low"] + 1e-9)
    df["pocket_pivot"] = (
        df["trend_up"] &
        (df["close_pos"] > 0.70) &
        (df["volume"] > df["max_down_vol"])
    )

    # Overhead resistance
    rw = p["resist_window"]
    df["resist_60"]   = g["close"].transform(lambda s: s.rolling(rw, min_periods=rw).max().shift(1))
    df["no_overhead"] = df["close"] >= 0.95 * df["resist_60"]

    # Volume liquidity filter — 20-day avg volume >= min_avg_vol
    df["avg_vol20"] = g["volume"].transform(lambda s: s.rolling(20, min_periods=20).mean().shift(1))
    df["liquid"]    = df["avg_vol20"] >= p["min_avg_vol"]

    # Entry signal
    df["signal"] = (
        df["market_up"]    &
        df["trend_up"]     &
        df["pocket_pivot"] &
        (df["rs_score"] > 0) &
        df["no_overhead"]  &
        df["liquid"]       &
        (df["rs_rating"] >= p["rs_min"])
    )

    print(f"  Signals: {df['signal'].sum():,}")
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  STEP A — Pre-extract signal windows (done ONCE for all scenarios)
# ══════════════════════════════════════════════════════════════════════════════

MAX_HOLD = max(MATRIX["hold_max"])   # 60 bars — biggest window we'll ever need

def extract_signal_windows(df: pd.DataFrame) -> list:
    """
    For each valid signal, extract up to MAX_HOLD forward bars of prices and
    all trail-stop columns. Returns a list of dicts, one per accepted signal.
    Enforces one-trade-at-a-time per symbol (no overlap at signal-extraction time
    using the longest possible hold window — conservative).
    """
    print("Extracting signal windows …")
    ts_cols = [c for c in df.columns if c.startswith("ts_")]
    windows = []

    for sym, grp in df.groupby("symbol"):
        grp   = grp.sort_values("date").reset_index(drop=True)
        n     = len(grp)
        dates = grp["date"].values
        opens = grp["open"].values
        closes= grp["close"].values
        highs = grp["high"].values
        lows  = grp["low"].values
        sigs  = grp["signal"].values
        rs_r  = grp["rs_rating"].values

        # Pre-extract all trail-stop arrays
        ts_arrays = {c: grp[c].values for c in ts_cols}

        in_trade_until = -1

        for i in range(n):
            if not sigs[i] or i <= in_trade_until:
                continue
            ei = i + 1
            if ei >= n:
                continue

            ep = float(opens[ei]) if not np.isnan(opens[ei]) and opens[ei] > 0 else float(closes[ei])
            if ep <= 0:
                continue

            # Slice forward MAX_HOLD bars
            end = min(ei + MAX_HOLD + 1, n)
            fw = dict(
                sym        = sym,
                signal_idx = i,
                entry_idx  = ei,
                entry_date = pd.Timestamp(dates[ei]),
                entry_price= ep,
                rs_rating  = float(rs_r[i]),
                dates      = dates[ei:end],
                opens      = opens[ei:end],
                highs      = highs[ei:end],
                lows       = lows[ei:end],
                closes     = closes[ei:end],
            )
            for c in ts_cols:
                fw[c] = ts_arrays[c][ei:end]

            windows.append(fw)
            # Block out MAX_HOLD bars for this symbol (worst-case hold)
            in_trade_until = min(ei + MAX_HOLD - 1, n - 1)

    print(f"  Signal windows: {len(windows):,}")
    return windows


# ══════════════════════════════════════════════════════════════════════════════
#  STEP B — Simulate one scenario over pre-extracted windows (fast)
# ══════════════════════════════════════════════════════════════════════════════

def simulate(windows: list, sma_n: int, atr_mult: float,
             hold_max: int, initial_sl: float) -> pd.DataFrame:
    ts_col = f"ts_{sma_n}_{str(atr_mult).replace('.','p')}"
    trades = []

    for fw in windows:
        ep       = fw["entry_price"]
        hard_sl  = ep * (1 - initial_sl)
        lows_arr = fw["lows"]
        closes_arr = fw["closes"]
        ts_arr   = fw[ts_col]
        n_fw     = min(hold_max + 1, len(lows_arr))

        current_stop = hard_sl
        trail_active = False
        outcome      = "time"
        exit_price   = float(closes_arr[min(hold_max - 1, len(closes_arr)-1)])
        exit_offset  = min(hold_max - 1, len(closes_arr)-1)

        for j in range(1, n_fw):
            close_j = float(closes_arr[j])
            low_j   = float(lows_arr[j])

            if close_j > ep:
                trail_active = True

            if trail_active:
                ts_j = float(ts_arr[j]) if not np.isnan(ts_arr[j]) else current_stop
                current_stop = max(current_stop, ts_j, hard_sl)

            if low_j <= current_stop:
                outcome     = "sl"
                exit_price  = current_stop
                exit_offset = j
                break

        entry_date = fw["entry_date"]
        exit_date  = pd.Timestamp(fw["dates"][exit_offset])
        ret        = exit_price / ep - 1

        trades.append({
            "symbol"      : fw["sym"],
            "entry_date"  : entry_date,
            "exit_date"   : exit_date,
            "entry_price" : round(ep, 4),
            "exit_price"  : round(exit_price, 4),
            "outcome"     : outcome,
            "return_pct"  : round(ret * 100, 4),
            "holding_days": (exit_date - entry_date).days,
            "rs_rating"   : fw["rs_rating"],
        })

    return pd.DataFrame(trades)


# ══════════════════════════════════════════════════════════════════════════════
#  METRICS
# ══════════════════════════════════════════════════════════════════════════════

def metrics(t: pd.DataFrame) -> dict:
    if t.empty:
        return dict(n=0)
    wins   = t[t["return_pct"] > 0]
    losses = t[t["return_pct"] <= 0]
    n      = len(t)
    gp     = wins["return_pct"].sum()
    gl     = abs(losses["return_pct"].sum())
    return dict(
        n        = n,
        win_rate = round(len(wins)/n*100, 1),
        avg_ret  = round(t["return_pct"].mean(), 2),
        avg_win  = round(wins["return_pct"].mean(), 2)   if not wins.empty   else 0.0,
        avg_loss = round(losses["return_pct"].mean(), 2) if not losses.empty else 0.0,
        pf       = round(gp/gl, 2) if gl > 0 else float("inf"),
        sl_exits = int((t["outcome"]=="sl").sum()),
        time_exits=int((t["outcome"]=="time").sum()),
        avg_hold = round(t["holding_days"].mean(), 1),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  PRINT MATRIX
# ══════════════════════════════════════════════════════════════════════════════

def print_matrix(rows: list):
    df = pd.DataFrame(rows)
    df = df.sort_values(["sma_n","atr_mult","hold_max"]).reset_index(drop=True)

    # ── Full table ────────────────────────────────────────────────────────────
    print("\n" + "═"*110)
    print("  SCENARIO MATRIX  |  RS≥95  |  Hard SL -4%  +  Trailing ATR (activates above entry)")
    print("  sma_n=SMA period for trail  |  mult=ATR multiplier  |  hold=max bars")
    print("═"*110)
    hdr = (f"  {'SMA':>5} {'Mult':>6} {'Hold':>6}"
           f" {'Trades':>7} {'WinR%':>7} {'AvgRet%':>8} {'AvgWin%':>8}"
           f" {'AvgLoss%':>9} {'PF':>6} {'SL_ex':>7} {'Tm_ex':>7} {'AvgHold':>8}")
    print(hdr)
    print("─"*110)

    for _, r in df.iterrows():
        print(f"  {int(r.sma_n):>5} {r.atr_mult:>6.1f} {int(r.hold_max):>6}"
              f" {int(r.n):>7} {r.win_rate:>7.1f} {r.avg_ret:>8.2f} {r.avg_win:>8.2f}"
              f" {r.avg_loss:>9.2f} {r.pf:>6.2f} {int(r.sl_exits):>7} {int(r.time_exits):>7}"
              f" {r.avg_hold:>8.1f}")
        if r.atr_mult == MATRIX["atr_mult"][-1]:
            print("─"*110)

    print()

    # ── Best scenarios ranked by profit factor ────────────────────────────────
    top = df.nlargest(5, "pf")
    print("  TOP 5 by Profit Factor:")
    print(f"  {'SMA':>5} {'Mult':>6} {'Hold':>6} {'Trades':>7} {'WinR%':>7}"
          f" {'AvgRet%':>8} {'PF':>6}")
    for _, r in top.iterrows():
        print(f"  {int(r.sma_n):>5} {r.atr_mult:>6.1f} {int(r.hold_max):>6}"
              f" {int(r.n):>7} {r.win_rate:>7.1f} {r.avg_ret:>8.2f} {r.pf:>6.2f}")

    print()
    top_ret = df.nlargest(5, "avg_ret")
    print("  TOP 5 by Avg Return/Trade:")
    print(f"  {'SMA':>5} {'Mult':>6} {'Hold':>6} {'Trades':>7} {'WinR%':>7}"
          f" {'AvgRet%':>8} {'PF':>6}")
    for _, r in top_ret.iterrows():
        print(f"  {int(r.sma_n):>5} {r.atr_mult:>6.1f} {int(r.hold_max):>6}"
              f" {int(r.n):>7} {r.win_rate:>7.1f} {r.avg_ret:>8.2f} {r.pf:>6.2f}")

    print("=" *110)
    return df


# =============================================================================
#  MAIN
# =============================================================================

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rs_min",     type=float, default=DEFAULTS["rs_min"])
    ap.add_argument("--min_avg_vol", type=int,   default=DEFAULTS["min_avg_vol"])
    ap.add_argument("--initial_sl", type=float, default=DEFAULTS["initial_sl"])
    ap.add_argument("--no_save",    action="store_true")
    return vars(ap.parse_args())


def main():
    p = {**DEFAULTS, **parse_args()}
    print(f"RS>={p['rs_min']}  |  Hard SL -{p['initial_sl']*100:.0f}%  |  Trailing ATR activates above entry")

    stocks, index = load_data()
    df = build_features(stocks, index, p)
    windows = extract_signal_windows(df)

    total = len(MATRIX["sma_n"]) * len(MATRIX["atr_mult"]) * len(MATRIX["hold_max"])
    print(f"\nRunning {total} scenarios ...\n")

    rows = []
    done = 0
    for sma_n, atr_mult, hold_max in itertools.product(
        MATRIX["sma_n"], MATRIX["atr_mult"], MATRIX["hold_max"]
    ):
        t = simulate(windows, sma_n=sma_n, atr_mult=atr_mult,
                     hold_max=hold_max, initial_sl=p["initial_sl"])
        m = metrics(t)
        done += 1
        print(f"  [{done:>2}/{total}] SMA{sma_n} x{atr_mult} H{hold_max}d -> {m.get('n',0)} trades  WR={m.get('win_rate',0)}%  AvgRet={m.get('avg_ret',0)}%  PF={m.get('pf',0)}")
        rows.append({"sma_n": sma_n, "atr_mult": atr_mult, "hold_max": hold_max, **m})