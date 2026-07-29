"""
boring_donchian_mechanism_models.py — Stage 2: sequential model building
on boring_donchian_mechanism_dataset.csv (produced by Stage 1).

Model 1: response ~ rarity (+ rarity^2)
Model 2: Model 1 + market/environment (breadth, dispersion, participation,
         avg_correlation, trend_persistence, volatility_level, sector_concentration)
Model 3: Model 2 + setup quality (base_duration, breakout_magnitude_pct)

Reports incremental R^2, AIC, BIC, nested F-test (likelihood improvement),
time-based 80/20 out-of-sample R^2, and a partial-dependence curve for
rarity (holding other Model-3 variables at their medians).

Robust check: OLS vs a rank-based (Spearman-transformed) regression, to see
if upside-outlier sensitivity changes the conclusions.
"""

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

df = pd.read_csv("boring_donchian_mechanism_dataset.csv")
print(f"Loaded dataset: {len(df):,} rows")

env_vars = ["breadth", "dispersion", "participation", "avg_correlation",
            "trend_persistence", "volatility_level", "sector_concentration"]
setup_vars = ["base_duration", "breakout_magnitude_pct"]

before = len(df)
df = df.dropna(subset=["response", "rarity"] + env_vars + setup_vars)
print(f"After dropping NaNs in any model variable: {len(df):,} / {before:,} "
      f"({len(df)/before*100:.1f}%)\n")

df["rarity_sq"] = df["rarity"] ** 2

print("=" * 90)
print("Pairwise correlation matrix — candidate variables (multicollinearity check)")
print("=" * 90)
corr_cols = ["rarity"] + env_vars + setup_vars
print(df[corr_cols].corr().round(2).to_string())
print()


def fit_ols(y, X_df):
    X = sm.add_constant(X_df)
    model = sm.OLS(y, X, missing="drop").fit()
    return model


def summarize(name, model, baseline_ll=None, baseline_df=None):
    print(f"\n{'-'*90}\n{name}\n{'-'*90}")
    print(f"N={int(model.nobs):,}  R^2={model.rsquared:.5f}  Adj R^2={model.rsquared_adj:.5f}  "
          f"AIC={model.aic:.1f}  BIC={model.bic:.1f}  LogLik={model.llf:.1f}")
    if baseline_ll is not None:
        lr_stat = 2 * (model.llf - baseline_ll)
        df_diff = model.df_model - baseline_df
        p_lr = stats.chi2.sf(lr_stat, df_diff) if df_diff > 0 else float("nan")
        print(f"LR test vs previous model: LR-stat={lr_stat:.2f}, df={df_diff:.0f}, p={p_lr:.6g}")
    print("\nCoefficients:")
    print(model.params.round(5).to_string())
    print("\nP-values:")
    print(model.pvalues.round(6).to_string())
    return model


# ── time-based 80/20 split ──
df_sorted = df.sort_values("date")
split_idx = int(len(df_sorted) * 0.8)
split_date = df_sorted["date"].iloc[split_idx]
train = df_sorted[df_sorted["date"] < split_date]
test = df_sorted[df_sorted["date"] >= split_date]
print(f"Time-based split at {split_date}: train N={len(train):,}, test N={len(test):,}\n")


def oos_r2(model, feature_cols, test_df):
    X_test = sm.add_constant(test_df[feature_cols], has_constant="add")
    X_test = X_test[model.params.index]  # align columns
    pred = model.predict(X_test)
    y_test = test_df["response"]
    ss_res = ((y_test - pred) ** 2).sum()
    ss_tot = ((y_test - y_test.mean()) ** 2).sum()
    return 1 - ss_res / ss_tot


results = {}

# Model 1
m1_features = ["rarity", "rarity_sq"]
m1 = fit_ols(train["response"], train[m1_features])
summarize("MODEL 1: response ~ rarity + rarity^2", m1)
m1_oos = oos_r2(m1, m1_features, test)
print(f"Out-of-sample R^2 (time-holdout): {m1_oos:.5f}")
results["model1"] = {"aic": m1.aic, "bic": m1.bic, "r2": m1.rsquared, "oos_r2": m1_oos, "ll": m1.llf, "df": m1.df_model}

# Model 2
m2_features = m1_features + env_vars
m2 = fit_ols(train["response"], train[m2_features])
summarize("MODEL 2: Model 1 + Market/Environment", m2, baseline_ll=m1.llf, baseline_df=m1.df_model)
m2_oos = oos_r2(m2, m2_features, test)
print(f"Out-of-sample R^2 (time-holdout): {m2_oos:.5f}")
results["model2"] = {"aic": m2.aic, "bic": m2.bic, "r2": m2.rsquared, "oos_r2": m2_oos, "ll": m2.llf, "df": m2.df_model}

# Model 3
m3_features = m2_features + setup_vars
m3 = fit_ols(train["response"], train[m3_features])
summarize("MODEL 3: Model 2 + Setup Quality", m3, baseline_ll=m2.llf, baseline_df=m2.df_model)
m3_oos = oos_r2(m3, m3_features, test)
print(f"Out-of-sample R^2 (time-holdout): {m3_oos:.5f}")
results["model3"] = {"aic": m3.aic, "bic": m3.bic, "r2": m3.rsquared, "oos_r2": m3_oos, "ll": m3.llf, "df": m3.df_model}

# ── incremental variable-by-variable, beyond rarity ──
print(f"\n{'='*90}\nEach candidate individually, beyond rarity alone (Model 1 baseline)\n{'='*90}")
individual_results = []
for v in env_vars + setup_vars:
    feats = m1_features + [v]
    m = fit_ols(train["response"], train[feats])
    d_r2 = m.rsquared - m1.rsquared
    print(f"  {v:<25} R^2={m.rsquared:.5f}  delta R^2 vs rarity-only={d_r2:+.5f}  "
          f"AIC={m.aic:.1f} (Model1 AIC={m1.aic:.1f})  coef={m.params.get(v, float('nan')):.5f}  "
          f"p={m.pvalues.get(v, float('nan')):.4g}")
    individual_results.append({"variable": v, "r2": m.rsquared, "delta_r2": d_r2,
                                "aic": m.aic, "coef": m.params.get(v), "pvalue": m.pvalues.get(v)})

pd.DataFrame(individual_results).to_csv("boring_donchian_individual_var_results.csv", index=False)

# ── regime dummies vs continuous environment vars ──
print(f"\n{'='*90}\nRegime dummies vs continuous environment variables (same rarity baseline)\n{'='*90}")
regime_dummies = pd.get_dummies(train["regime"], prefix="regime", drop_first=True).astype(float)
train_rd = pd.concat([train[m1_features], regime_dummies], axis=1)
m_regime = fit_ols(train["response"], train_rd)
summarize("Rarity + regime dummies (3 dummy vars)", m_regime, baseline_ll=m1.llf, baseline_df=m1.df_model)

m_env_only_features = m1_features + env_vars
m_env_only = fit_ols(train["response"], train[m_env_only_features])
print(f"\nRarity + continuous environment (7 vars), no regime dummies:")
print(f"  N={int(m_env_only.nobs):,}  R^2={m_env_only.rsquared:.5f}  AIC={m_env_only.aic:.1f}  BIC={m_env_only.bic:.1f}")
print(f"\nRarity + regime dummies (3 vars):")
print(f"  N={int(m_regime.nobs):,}  R^2={m_regime.rsquared:.5f}  AIC={m_regime.aic:.1f}  BIC={m_regime.bic:.1f}")
print(f"\nAIC difference (env - regime): {m_env_only.aic - m_regime.aic:+.2f} "
      f"({'continuous variables fit better' if m_env_only.aic < m_regime.aic else 'regime dummies fit better'})")

# ── robust check: rank-based regression ──
print(f"\n{'='*90}\nRobustness check: rank-transformed (Spearman-style) regression, Model 3 spec\n{'='*90}")
train_rank = train[["response"] + m3_features].rank()
m3_rank = fit_ols(train_rank["response"], train_rank[m3_features])
print(f"Rank-OLS  N={int(m3_rank.nobs):,}  R^2={m3_rank.rsquared:.5f}  (vs raw Model 3 R^2={m3.rsquared:.5f})")
print("Rank-OLS coefficients (sign check against raw Model 3):")
print(m3_rank.params.round(5).to_string())

# ── partial dependence: rarity, holding Model 3 vars at median ──
print(f"\n{'='*90}\nPartial dependence — predicted response vs rarity, other Model-3 vars at median\n{'='*90}")
medians = train[m3_features].median()
rarity_grid = np.linspace(train["rarity"].quantile(0.02), train["rarity"].quantile(0.98), 30)
pdp_rows = []
for r in rarity_grid:
    row = medians.copy()
    row["rarity"] = r
    row["rarity_sq"] = r ** 2
    x = sm.add_constant(pd.DataFrame([row]), has_constant="add")
    x = x[m3.params.index]
    pred = m3.predict(x).iloc[0]
    pdp_rows.append({"rarity": r, "predicted_response": pred})
pdp_df = pd.DataFrame(pdp_rows)
pdp_df.to_csv("boring_donchian_pdp_rarity.csv", index=False)
print(pdp_df.to_string(index=False))

print("\n\nStage 2 done. Summary of nested models:")
for k, v in results.items():
    print(f"  {k}: R^2={v['r2']:.5f}  AIC={v['aic']:.1f}  BIC={v['bic']:.1f}  OOS R^2={v['oos_r2']:.5f}")
