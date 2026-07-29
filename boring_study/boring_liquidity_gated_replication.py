"""
boring_liquidity_gated_replication.py -- PRE-REGISTERED-STYLE REPLICATION

Question: does the Stock RS heterogeneity of the TP-before-stop breakout
edge survive when the liquidity gate (avg_vol_10d > 200,000, this
project's own standing threshold, reused from setup_log/config.py
convention) is applied FROM THE START, rather than computed on the
pooled/ungated population as every prior stage of this thread did?

Design, locked before inspecting output:
  1. Apply the liquidity gate to BOTH breakout and control rows (matched
     pairs must be judged on the same footing -- gating only one side
     would reintroduce exactly the kind of asymmetric selection bias
     this project's matched-control methodology exists to avoid).
  2. Recompute RS deciles via pd.qcut on the GATED population only (decile
     boundaries reflect the liquid universe's own RS distribution, not
     the pooled, contamination-inflated one).
  3. Reproduce the EXACT original methodology on this gated population:
     (a) decile table of control_rate / breakout_rate / edge,
     (b) Spearman rank correlation of decile vs EDGE (not raw breakout
         hit rate alone -- edge over matched control is the quantity
         this program has always used to characterize heterogeneity),
     (c) the regression hit_tp_10 ~ breakout + z(RS) + breakout*z(RS),
         directly comparable to the original ungated interaction terms
         (+0.03531 20d, +0.02887 60d).
  4. Both panels (20d, 60d) -- same cross-definition-consistency bar
     applied throughout this program. A result inconsistent in sign or
     significance across panels is flagged unreliable, not confirmed,
     per this project's own standing convention.
  5. Report the full 0-9 decile table so any single decile (not just the
     top) showing a clean, tradable edge is visible, not just decile 9.

Decision rule (stated before running): the RS effect modifier is judged
to SURVIVE only if the edge-vs-decile relationship is monotonic-ish,
carries a significant regression interaction term, AND replicates in
sign/significance across both panels. Anything weaker is a genuine,
reportable finding of its own (attenuation or evaporation), not something
to explain away.
"""

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

LIQ_THRESHOLD = 200000


def zscore(s):
    return (s - s.mean()) / s.std()


def fit(y, X):
    return sm.OLS(y, sm.add_constant(X), missing="drop").fit()


def report(m, label, prev=None):
    print(f"\n{'-'*90}\n{label}\n{'-'*90}")
    print(f"N={int(m.nobs):,}  R^2={m.rsquared:.5f}", end="")
    print(f"   Delta R^2 vs prior={m.rsquared-prev:+.5f}" if prev is not None else "")
    ci = m.conf_int()
    for name in m.params.index:
        print(f"  {name:<12} coef={m.params[name]:+.5f}  95% CI=[{ci.loc[name,0]:+.5f},{ci.loc[name,1]:+.5f}]  p={m.pvalues[name]:.4g}")
    return m.rsquared


def analyze(panel_path, label):
    print(f"\n{'#'*90}\n# {label}\n{'#'*90}")
    df = pd.read_csv(panel_path)
    print(f"Raw panel: {len(df):,} rows")

    d = df.dropna(subset=["hit_tp_10", "breakout", "stock_rs", "liquidity"]).copy()
    print(f"After dropping missing hit_tp_10/breakout/stock_rs/liquidity: {len(d):,} rows "
          f"(breakout={d['breakout'].sum():,}, control={(d['breakout']==0).sum():,})")

    liq_nonnull_by_type = df.groupby("breakout")["liquidity"].apply(lambda s: s.notna().mean())
    print(f"Liquidity field non-null rate by row type (0=control,1=breakout): {liq_nonnull_by_type.to_dict()}")

    dg = d[d["liquidity"] > LIQ_THRESHOLD].copy()
    print(f"\nAfter liquidity gate (>{LIQ_THRESHOLD:,}): {len(dg):,} rows "
          f"({len(dg)/len(d)*100:.1f}% retained) "
          f"(breakout={dg['breakout'].sum():,}, control={(dg['breakout']==0).sum():,})")

    dg["rs_decile"] = pd.qcut(dg["stock_rs"], 10, labels=False, duplicates="drop")

    print(f"\n--- Decile table (liquidity-gated, GATE APPLIED BEFORE DECILE COMPUTATION) ---")
    dec = dg.groupby(["rs_decile", "breakout"])["hit_tp_10"].agg(["size", "mean"]).unstack()
    n_tab = dec["size"]
    rate_tab = (dec["mean"] * 100).round(2)
    rate_tab.columns = ["control_rate", "breakout_rate"]
    rate_tab["edge"] = (rate_tab["breakout_rate"] - rate_tab["control_rate"]).round(2)
    rate_tab["n_control"] = n_tab[0].astype(int)
    rate_tab["n_breakout"] = n_tab[1].astype(int)
    print(rate_tab.to_string())

    rho, p = stats.spearmanr(rate_tab.index.to_numpy(), rate_tab["edge"].to_numpy())
    print(f"\nSpearman rank correlation (decile vs EDGE, liquidity-gated): rho={rho:.3f}, p={p:.4g}")
    best_decile = rate_tab["edge"].idxmax()
    print(f"Decile with the largest edge in the gated data: decile {best_decile} "
          f"(edge={rate_tab.loc[best_decile,'edge']:+.2f}pp, "
          f"breakout_rate={rate_tab.loc[best_decile,'breakout_rate']:.2f}%, "
          f"n_breakout={rate_tab.loc[best_decile,'n_breakout']:,})")

    print(f"\n--- Regression: hit_tp_10 ~ breakout + z(RS) + breakout*z(RS), liquidity-gated ---")
    dg["z_rs"] = zscore(dg["stock_rs"])
    dg["bo_x_rs"] = dg["breakout"] * dg["z_rs"]
    m1 = fit(dg["hit_tp_10"], dg[["breakout"]])
    r1 = report(m1, "MODEL 1: hit_tp_10 ~ breakout")
    m2 = fit(dg["hit_tp_10"], dg[["breakout", "z_rs", "bo_x_rs"]])
    report(m2, "MODEL 2: hit_tp_10 ~ breakout + z(RS) + breakout*z(RS)  [liquidity-gated]", r1)

    return rate_tab, m2


rate20, m20 = analyze("boring_heterogeneity_panel_20d_race.csv", "20d panel -- PRIMARY, liquidity-gated replication")
rate60, m60 = analyze("boring_heterogeneity_panel_60d_race.csv", "60d panel -- REPLICATION, liquidity-gated replication")

print(f"\n\n{'='*90}\nSUMMARY -- cross-panel comparison, ORIGINAL (ungated) vs THIS (gated) interaction term\n{'='*90}")
orig = {"20d": (0.03531, 4.257e-19), "60d": (0.02887, 6.231e-06)}
for label, m in [("20d", m20), ("60d", m60)]:
    gated_coef = m.params["bo_x_rs"]
    gated_p = m.pvalues["bo_x_rs"]
    o_coef, o_p = orig[label]
    print(f"{label}: ORIGINAL (ungated) bo_x_rs={o_coef:+.5f} (p={o_p:.3g})   "
          f"LIQUIDITY-GATED bo_x_rs={gated_coef:+.5f} (p={gated_p:.3g})   "
          f"retained {gated_coef/o_coef*100:.1f}% of original interaction magnitude")

print("\n\nDone.")
