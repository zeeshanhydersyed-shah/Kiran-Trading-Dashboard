"""
boring_heterogeneity_analysis.py — tests whether the already-established
breakout edge (breakout outcome minus matched-control outcome) is
homogeneous or varies across Stock RS and Directional Volatility Ratio.

Primary panel: 20d lookback (78,393 breakout + 78,393 control rows).
Cross-definition check: 60d lookback panel, same workflow.
Negative control: liquidity, already rejected in an earlier round.

All variables (stock_rs, vol_ratio, liquidity) z-scored before entering
models so coefficients are directly comparable effect sizes. The
Breakout x variable INTERACTION term is the direct test of "does edge vary
with X" (H1) -- the main effect of X alone tests something different (does
X predict outcome regardless of breakout status). Both are reported.
"""

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

def load(path):
    df = pd.read_csv(path)
    return df


def zscore(s):
    return (s - s.mean()) / s.std()


def fit(y, X):
    Xc = sm.add_constant(X)
    return sm.OLS(y, Xc, missing="drop").fit()


def report_model(m, label, prev_r2=None):
    print(f"\n{'-'*90}\n{label}\n{'-'*90}")
    print(f"N={int(m.nobs):,}  R^2={m.rsquared:.5f}", end="")
    if prev_r2 is not None:
        print(f"   Delta R^2 vs previous={m.rsquared-prev_r2:+.5f}")
    else:
        print()
    ci = m.conf_int()
    for name in m.params.index:
        print(f"  {name:<28} coef={m.params[name]:+.5f}  95% CI=[{ci.loc[name,0]:+.5f},{ci.loc[name,1]:+.5f}]  p={m.pvalues[name]:.4g}")
    return m.rsquared


def run_workflow(panel_path, varname, label):
    print(f"\n{'#'*90}\n# WORKFLOW: {label}  (panel={panel_path})\n{'#'*90}")
    df = load(panel_path)
    df = df.dropna(subset=["outcome", "breakout", varname]).copy()
    print(f"N (complete case) = {len(df):,}   breakout={df['breakout'].sum():,}  control={(df['breakout']==0).sum():,}")

    df["z"] = zscore(df[varname])
    df["breakout_x_z"] = df["breakout"] * df["z"]

    # Model 1: outcome ~ breakout
    m1 = fit(df["outcome"], df[["breakout"]])
    r2_1 = report_model(m1, "MODEL 1: outcome ~ breakout")

    # Model 2: outcome ~ breakout + z + breakout*z
    m2 = fit(df["outcome"], df[["breakout", "z", "breakout_x_z"]])
    r2_2 = report_model(m2, f"MODEL 2: outcome ~ breakout + {varname}(z) + breakout*{varname}(z)", r2_1)

    return df, m1, m2


# ══════════════════════════════════════════════════════════════════════
# PRIMARY: 20d panel, Stock RS
# ══════════════════════════════════════════════════════════════════════
df20, m1_20, m2_rs_20 = run_workflow("boring_heterogeneity_panel_20d.csv", "stock_rs", "Primary — Stock RS, 20d lookback")

# ══════════════════════════════════════════════════════════════════════
# Analysis 1 — functional form: decile table, breakout vs control
# ══════════════════════════════════════════════════════════════════════
print(f"\n{'='*90}\nANALYSIS 1 — Functional form: E[outcome | Stock RS decile], breakout vs control\n{'='*90}")
df20["rs_decile"] = pd.qcut(df20["stock_rs"], 10, labels=False, duplicates="drop")
dec = df20.groupby(["rs_decile", "breakout"])["outcome"].mean().unstack()
dec.columns = ["control_mean", "breakout_mean"]
dec["edge"] = dec["breakout_mean"] - dec["control_mean"]
dec["rs_range"] = df20.groupby("rs_decile")["stock_rs"].apply(lambda s: f"{s.min():.1f} to {s.max():.1f}")
print(dec.round(3).to_string())
edge_vals = dec["edge"].to_numpy()
diffs = np.diff(edge_vals)
print(f"\nEdge deltas between consecutive deciles: {np.round(diffs,3)}")
print(f"Fraction of increasing steps: {(diffs>0).mean():.2f}")
mono_spearman, mono_p = stats.spearmanr(np.arange(len(edge_vals)), edge_vals)
print(f"Spearman rank correlation of decile index vs edge (monotonicity check): rho={mono_spearman:.3f}, p={mono_p:.4g}")

# ══════════════════════════════════════════════════════════════════════
# Analysis 2/3 — add Directional Vol Ratio, test independence from RS
# ══════════════════════════════════════════════════════════════════════
print(f"\n{'='*90}\nANALYSIS 2/3 — Model 3: add Directional Volatility Ratio; independence from RS\n{'='*90}")
df20v = df20.dropna(subset=["vol_ratio"]).copy()
df20v["z_rs"] = zscore(df20v["stock_rs"])
df20v["z_vr"] = zscore(df20v["vol_ratio"])
df20v["bo_x_rs"] = df20v["breakout"] * df20v["z_rs"]
df20v["bo_x_vr"] = df20v["breakout"] * df20v["z_vr"]

m2_same = fit(df20v["outcome"], df20v[["breakout", "z_rs", "bo_x_rs"]])
r2_m2 = report_model(m2_same, "MODEL 2 (refit on vol_ratio-complete subsample for fair comparison)")
m3 = fit(df20v["outcome"], df20v[["breakout", "z_rs", "bo_x_rs", "z_vr", "bo_x_vr"]])
r2_m3 = report_model(m3, "MODEL 3: + Directional Volatility Ratio (z) + breakout*ratio(z)", r2_m2)

print("\nPartial correlation check: vol_ratio vs outcome, WITHIN breakout rows only, controlling for stock_rs")
bo_only = df20v[df20v["breakout"] == 1]
def partial_corr(x, y, z):
    rxy,_ = stats.pearsonr(x,y); rxz,_ = stats.pearsonr(x,z); ryz,_ = stats.pearsonr(y,z)
    return (rxy - rxz*ryz) / np.sqrt((1-rxz**2)*(1-ryz**2))
pc = partial_corr(bo_only["vol_ratio"], bo_only["outcome"], bo_only["stock_rs"])
raw_r = stats.pearsonr(bo_only["vol_ratio"], bo_only["outcome"])[0]
print(f"  Raw corr(vol_ratio, outcome | breakout rows) = {raw_r:.4f}")
print(f"  Partial corr(vol_ratio, outcome | stock_rs, breakout rows only) = {pc:.4f}")

# ══════════════════════════════════════════════════════════════════════
# Analysis 4 — robustness: decile-based edge-vs-vol_ratio check
# ══════════════════════════════════════════════════════════════════════
print(f"\n{'='*90}\nANALYSIS 4 — Robustness: decile check for Directional Volatility Ratio\n{'='*90}")
df20v["vr_decile"] = pd.qcut(df20v["vol_ratio"], 10, labels=False, duplicates="drop")
decvr = df20v.groupby(["vr_decile", "breakout"])["outcome"].mean().unstack()
decvr.columns = ["control_mean", "breakout_mean"]
decvr["edge"] = decvr["breakout_mean"] - decvr["control_mean"]
print(decvr.round(3).to_string())
edge_vr = decvr["edge"].to_numpy()
mono_vr, mono_vr_p = stats.spearmanr(np.arange(len(edge_vr)), edge_vr)
print(f"Spearman rank correlation of vol_ratio decile vs edge: rho={mono_vr:.3f}, p={mono_vr_p:.4g}")

# ══════════════════════════════════════════════════════════════════════
# Analysis 5 — negative control: LIQUIDITY (already-rejected variable)
# ══════════════════════════════════════════════════════════════════════
df20_liq, m1_liq, m2_liq = run_workflow("boring_heterogeneity_panel_20d.csv", "liquidity", "NEGATIVE CONTROL — Liquidity (already rejected), 20d lookback")

# ══════════════════════════════════════════════════════════════════════
# Cross-definition check: 60d panel
# ══════════════════════════════════════════════════════════════════════
df60, m1_60, m2_rs_60 = run_workflow("boring_heterogeneity_panel_60d.csv", "stock_rs", "Cross-definition check — Stock RS, 60d lookback")
df60["rs_decile"] = pd.qcut(df60["stock_rs"], 10, labels=False, duplicates="drop")
dec60 = df60.groupby(["rs_decile", "breakout"])["outcome"].mean().unstack()
dec60.columns = ["control_mean", "breakout_mean"]
dec60["edge"] = dec60["breakout_mean"] - dec60["control_mean"]
print(f"\n{'='*90}\n60d panel — edge by RS decile\n{'='*90}")
print(dec60.round(3).to_string())
mono60, mono60_p = stats.spearmanr(np.arange(len(dec60)), dec60["edge"].to_numpy())
print(f"Spearman rank correlation (60d, monotonicity check): rho={mono60:.3f}, p={mono60_p:.4g}")

print("\n\nDone.")
