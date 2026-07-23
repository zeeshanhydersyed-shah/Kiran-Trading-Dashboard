"""
grand_test_run.py — Phase B/C: shared-capital portfolio + cost/CGT + reporting.
================================================================================
Consumes grand_test_candidates.pkl (produced by grand_test.py) and runs ONE
capital pool through all three edges, each traded by its own validated exit
(already baked into each candidate's pre-resolved exit_date/exit_price).

Cost model (real, from BMA statement + NCCPL CGT report):
  - per side: 0.15% brokerage + 15% FED on brokerage + 0.25% slippage
  - CGT: 15% on NET annual realized gain (losses offset), Pakistan FY Jul-Jun

Outputs: per-edge net EV, trades/year, net annual expectancy, by-market-stage,
combined equity curve + max drawdown, Monte-Carlo drawdown/ruin distribution,
capacity ceiling. Plus era-stratification and a sealed 2024-2026 holdout.

READ-ONLY on psx_data.db.
"""

import pickle
import numpy as np
import pandas as pd
from collections import defaultdict
from grand_test import (load_all, build_symbol_arrays, PER_SIDE_COST, CGT_RATE,
                        INITIAL_EQUITY, RISK_PER_TRADE, HOLDOUT_START)
from pakistan_rates import daily_interest


def fy_of(date_str):
    """Pakistan fiscal year label (Jul-Jun). '2020-08-x' -> FY2021; '2020-03' -> FY2020."""
    y, m = int(date_str[:4]), int(date_str[5:7])
    return y + 1 if m >= 7 else y


def run_portfolio(candidates, sym_data, regime_map=None, allowed_regimes=None,
                  start=None, end=None, edges=('Recovery', 'DC', 'Weinstein'),
                  apply_cgt=True, sleeves=None, apply_rfr=False):
    """Single shared-capital walk. Returns (trades_df, equity_df, summary).

    regime_map/allowed_regimes: if both given, an entry is only allowed when
      regime_map.get(entry_date) in allowed_regimes (market-regime gate).
    sleeves: optional dict edge->fraction; caps each edge's deployed capital to
      its fraction of current equity (structured contention instead of first-come)."""
    # Flatten candidates for selected edges, within [start,end] by entry_date
    cands = []
    for e in edges:
        for c in candidates.get(e, []):
            if start and c['entry_date'] < start:
                continue
            if end and c['entry_date'] > end:
                continue
            cands.append(c)
    cands.sort(key=lambda x: (x['entry_date'], x['signal_date']))
    by_entry = {}
    for c in cands:
        by_entry.setdefault(c['entry_date'], []).append(c)

    # Universe of trading dates
    all_dates = sorted({d for sd in sym_data.values() for d in sd['dates']})
    if start:
        all_dates = [d for d in all_dates if d >= start]
    if end:
        all_dates = [d for d in all_dates if d <= end]

    cash = equity = INITIAL_EQUITY
    peak = INITIAL_EQUITY
    max_dd = 0.0
    open_pos = {}            # symbol -> position
    deployed = defaultdict(float)   # edge -> currently deployed cost basis (sleeves)
    trades = []
    eq_curve = []
    fy_realized = {}         # fy -> net realized PKR (net of both-side costs, pre-CGT)
    loss_carry = 0.0
    cgt_paid_total = 0.0

    def price_on(sym, dt):
        sd = sym_data.get(sym)
        if not sd:
            return None
        i = sd['dti'].get(dt)
        return sd['close'][i] if i is not None else None

    prev_fy = None
    for dt in all_dates:
        cur_fy = fy_of(dt)

        # ── FY rollover: settle CGT on the FY that just ended ──
        if apply_cgt and prev_fy is not None and cur_fy != prev_fy:
            net = fy_realized.get(prev_fy, 0.0)
            taxable = net - loss_carry
            if taxable > 0:
                tax = CGT_RATE * taxable
                cash -= tax; equity -= tax; cgt_paid_total += tax
                loss_carry = 0.0
            else:
                loss_carry = -taxable            # carry the loss forward
        prev_fy = cur_fy

        # ── A. exits ──
        for sym in list(open_pos.keys()):
            pos = open_pos[sym]
            if pos['exit_date'] != dt:
                continue
            proceeds = pos['shares'] * pos['exit_price'] * (1 - PER_SIDE_COST)
            net_pl = proceeds - pos['cost_basis']
            cash += proceeds
            deployed[pos['edge']] -= pos['cost_basis']
            fy_realized[cur_fy] = fy_realized.get(cur_fy, 0.0) + net_pl
            trades.append(dict(
                edge=pos['edge'], symbol=sym, entry_date=pos['entry_date'],
                exit_date=dt, entry_price=pos['entry_price'],
                exit_price=pos['exit_price'], shares=pos['shares'],
                gross_ret_pct=(pos['exit_price']-pos['entry_price'])/pos['entry_price']*100,
                net_pl_pkr=net_pl,
                net_ret_pct=net_pl / pos['cost_basis'] * 100,
                eq_frac=net_pl / pos['equity_at_entry'],
                stage=pos.get('stage'), exit_reason=pos['exit_reason'],
                hold_days=pos['hold_days']))
            del open_pos[sym]

        # ── B. mark-to-market & earn RFR on idle cash ──
        pv = 0.0
        for sym, pos in open_pos.items():
            p = price_on(sym, dt)
            pv += (p if p is not None else pos['entry_price']) * pos['shares']
        if apply_rfr:
            cash += daily_interest(cash, dt)
        equity = cash + pv
        eq_curve.append((dt, equity))
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

        # ── C. entries ──
        regime_blocked = (regime_map is not None and allowed_regimes is not None
                          and regime_map.get(dt) not in allowed_regimes)
        for c in by_entry.get(dt, []):
            if regime_blocked:
                continue                          # market-regime gate: sit out
            sym = c['symbol']
            if sym in open_pos:
                continue                          # one position per symbol
            entry = c['entry_price']; stop = c['init_stop']
            risk_per_share = entry - stop
            if risk_per_share <= 0:
                continue
            shares = int((RISK_PER_TRADE * equity) / risk_per_share)
            if shares < 1:
                continue
            cost_basis = shares * entry * (1 + PER_SIDE_COST)
            if cost_basis > cash:
                continue                          # capital-constrained
            if sleeves is not None:
                budget = sleeves.get(c['edge'], 1.0) * equity
                if deployed[c['edge']] + cost_basis > budget:
                    continue                      # sleeve cap reached
                deployed[c['edge']] += cost_basis
            cash -= cost_basis
            open_pos[sym] = dict(
                edge=c['edge'], shares=shares, entry_price=entry,
                exit_date=c['exit_date'], exit_price=c['exit_price'],
                cost_basis=cost_basis, entry_date=c['entry_date'],
                exit_reason=c['exit_reason'], hold_days=c['hold_days'],
                equity_at_entry=equity, stage=c.get('stage'))

    # settle final FY CGT
    if apply_cgt and prev_fy is not None:
        net = fy_realized.get(prev_fy, 0.0)
        taxable = net - loss_carry
        if taxable > 0:
            tax = CGT_RATE * taxable
            cash -= tax; equity -= tax; cgt_paid_total += tax

    # force-close remaining at last price
    final_dt = all_dates[-1]
    for sym, pos in list(open_pos.items()):
        p = price_on(sym, final_dt) or pos['entry_price']
        proceeds = pos['shares'] * p * (1 - PER_SIDE_COST)
        net_pl = proceeds - pos['cost_basis']
        cash += proceeds
        trades.append(dict(
            edge=pos['edge'], symbol=sym, entry_date=pos['entry_date'],
            exit_date=final_dt, entry_price=pos['entry_price'], exit_price=p,
            shares=pos['shares'],
            gross_ret_pct=(p-pos['entry_price'])/pos['entry_price']*100,
            net_pl_pkr=net_pl, net_ret_pct=net_pl/pos['cost_basis']*100,
            eq_frac=net_pl/pos['equity_at_entry'],
            stage=pos.get('stage'), exit_reason='FORCE_CLOSE',
            hold_days=pos['hold_days']))
    equity = cash

    trades_df = pd.DataFrame(trades)
    eq_df = pd.DataFrame(eq_curve, columns=['date', 'equity'])
    years = (pd.to_datetime(all_dates[-1]) - pd.to_datetime(all_dates[0])).days / 365.25
    cagr = (equity / INITIAL_EQUITY) ** (1/years) - 1 if years > 0 else 0
    summary = dict(final_equity=equity, cagr=cagr, max_dd=max_dd,
                   years=years, cgt_paid=cgt_paid_total, n_trades=len(trades_df))
    return trades_df, eq_df, summary


def edge_table(trades_df, label=''):
    print(f"\n  {'Edge':<11} {'N':>5} {'WR':>6} {'avgW%':>7} {'avgL%':>7} "
          f"{'netEV%':>7} {'/yr':>5}  {label}")
    print("  " + "-"*62)
    for edge in ['Recovery', 'DC', 'Weinstein', 'ALL']:
        d = trades_df if edge == 'ALL' else trades_df[trades_df['edge'] == edge]
        if len(d) == 0:
            print(f"  {edge:<11} N=0"); continue
        w = d[d['net_ret_pct'] > 0]; l = d[d['net_ret_pct'] <= 0]
        wr = len(w)/len(d)*100
        aw = w['net_ret_pct'].mean() if len(w) else 0
        al = l['net_ret_pct'].mean() if len(l) else 0
        ev = wr/100*aw + (1-wr/100)*al
        yrs = ((pd.to_datetime(d['entry_date']).max()
                - pd.to_datetime(d['entry_date']).min()).days/365.25) or 1
        print(f"  {edge:<11} {len(d):>5} {wr:>5.1f}% {aw:>+7.2f} {al:>+7.2f} "
              f"{ev:>+7.2f} {len(d)/yrs:>5.0f}")


def monte_carlo(trades_df, n=5000, ruin_dd=0.40):
    """Bootstrap trade order using each trade's ACTUAL equity-fraction impact
    (net_pl / equity_at_entry). Reports max-DD distribution + prob of ruin."""
    fr = trades_df.sort_values('exit_date')['eq_frac'].to_numpy()
    if len(fr) < 5:
        return None
    dds, finals, ruined = [], [], 0
    rng = np.random.default_rng(42)
    for _ in range(n):
        order = rng.permutation(len(fr))
        eq = 1.0; peak = 1.0; mdd = 0.0
        for i in order:
            eq *= (1 + fr[i])
            peak = max(peak, eq)
            mdd = max(mdd, (peak - eq)/peak)
        dds.append(mdd); finals.append(eq)
        if mdd >= ruin_dd:
            ruined += 1
    dds = np.array(dds)
    return dict(dd_p50=np.percentile(dds, 50), dd_p95=np.percentile(dds, 95),
                dd_p99=np.percentile(dds, 99), ruin_prob=ruined/n,
                final_p50=np.percentile(finals, 50))


def load_regime_map():
    import sqlite3
    from grand_test import DB_PATH
    c = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT date, regime FROM market_regime", c)
    c.close()
    return dict(zip(df['date'].astype(str), df['regime']))


def scenario(candidates, sym_data, name, **kw):
    tdf, eqdf, summ = run_portfolio(candidates, sym_data, **kw)
    print(f"\n{'='*66}\n{name}\n{'='*66}")
    print(f"  Final equity PKR {summ['final_equity']:>12,.0f}   CAGR {summ['cagr']:>6.2%}   "
          f"maxDD {summ['max_dd']:>5.1%}   CGT PKR {summ['cgt_paid']:,.0f}   N={summ['n_trades']}")
    edge_table(tdf, name)
    return tdf, summ


def main():
    print("Loading candidates + prices + regime...")
    with open('grand_test_candidates.pkl', 'rb') as f:
        candidates = pickle.load(f)
    px, ss, kse, secstg = load_all()
    sym_data = build_symbol_arrays(px)
    regime = load_regime_map()
    BULL = ('TRENDING_UP',)
    BULL_VOL = ('TRENDING_UP', 'VOLATILE')
    SLEEVES = {'DC': 0.40, 'Weinstein': 0.40, 'Recovery': 0.20}

    # 1. Ungated (baseline) vs 2. regime-gated vs 3. gated+sleeved
    t1, s1 = scenario(candidates, sym_data, "[1] UNGATED shared pool (fires in every regime)")
    t2, s2 = scenario(candidates, sym_data, "[2] REGIME-GATED (longs only in TRENDING_UP)",
                      regime_map=regime, allowed_regimes=BULL)
    t3, s3 = scenario(candidates, sym_data, "[3] REGIME-GATED + VOLATILE allowed",
                      regime_map=regime, allowed_regimes=BULL_VOL)
    t4, s4 = scenario(candidates, sym_data, "[4] REGIME-GATED + CAPITAL SLEEVES (DC40/Wei40/Rec20)",
                      regime_map=regime, allowed_regimes=BULL, sleeves=SLEEVES)

    # RUN WITH RISK-FREE RATE (Pakistan T-bills/policy rates 2005-2026)
    print("\n" + "="*66)
    print("WITH RISK-FREE RATE (SBP policy rates on idle cash)")
    print("="*66)
    t2_rfr, s2_rfr = scenario(candidates, sym_data, "[2] REGIME-GATED + RFR",
                              regime_map=regime, allowed_regimes=BULL, apply_rfr=True)
    t4_rfr, s4_rfr = scenario(candidates, sym_data, "[4] REGIME-GATED + SLEEVES + RFR",
                              regime_map=regime, allowed_regimes=BULL, sleeves=SLEEVES, apply_rfr=True)

    print("\n--- RFR Impact Summary ---")
    print(f"  Regime-gated:       {s2['cagr']:>6.2%} → {s2_rfr['cagr']:>6.2%} (+{s2_rfr['cagr']-s2['cagr']:>6.2%})")
    print(f"  Gated+sleeves:      {s4['cagr']:>6.2%} → {s4_rfr['cagr']:>6.2%} (+{s4_rfr['cagr']-s4['cagr']:>6.2%})")

    # Holdout: gated, and gated+sleeved (the winner), in-sample vs sealed holdout
    print("\n--- In-sample (->2023) vs SEALED holdout (2024->) --- [WITHOUT RFR]")
    for tag, kw in [("gated", dict(regime_map=regime, allowed_regimes=BULL)),
                    ("gated+sleeves", dict(regime_map=regime, allowed_regimes=BULL, sleeves=SLEEVES))]:
        _, _, si = run_portfolio(candidates, sym_data, end='2023-12-31', **kw)
        _, _, so = run_portfolio(candidates, sym_data, start=HOLDOUT_START, **kw)
        print(f"  {tag:<14} IN-SAMPLE CAGR {si['cagr']:>6.2%} maxDD {si['max_dd']:>5.1%} N={si['n_trades']:<4} | "
              f"HOLDOUT CAGR {so['cagr']:>6.2%} maxDD {so['max_dd']:>5.1%} N={so['n_trades']}")

    print("\n--- In-sample (->2023) vs SEALED holdout (2024->) --- [WITH RFR]")
    for tag, kw in [("gated", dict(regime_map=regime, allowed_regimes=BULL, apply_rfr=True)),
                    ("gated+sleeves", dict(regime_map=regime, allowed_regimes=BULL, sleeves=SLEEVES, apply_rfr=True))]:
        _, _, si = run_portfolio(candidates, sym_data, end='2023-12-31', **kw)
        _, _, so = run_portfolio(candidates, sym_data, start=HOLDOUT_START, **kw)
        print(f"  {tag:<14} IN-SAMPLE CAGR {si['cagr']:>6.2%} maxDD {si['max_dd']:>5.1%} N={si['n_trades']:<4} | "
              f"HOLDOUT CAGR {so['cagr']:>6.2%} maxDD {so['max_dd']:>5.1%} N={so['n_trades']}")

    mc = monte_carlo(t2)
    if mc:
        print(f"\nMONTE-CARLO regime-gated (5000 paths): "
              f"maxDD p50={mc['dd_p50']:.1%} p95={mc['dd_p95']:.1%} p99={mc['dd_p99']:.1%} "
              f"Prob(DD>=40%)={mc['ruin_prob']:.1%}")

    t2.to_csv('grand_test_trades_gated.csv', index=False)
    print("\nGated trade ledger -> grand_test_trades_gated.csv")


if __name__ == '__main__':
    main()
