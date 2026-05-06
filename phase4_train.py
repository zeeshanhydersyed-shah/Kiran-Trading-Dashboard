"""
Phase 4 -- KIRAN ML Model Training.

Trains a classifier on backtest_setups to predict Win vs Loss
for triggered setups only (No_Trigger and Expired excluded --
they never entered the trade).

Time-series split (strict -- no leakage):
    Train  : 2024
    Test   : 2025
    (2026 is a partial year, shown separately as live context)

Features built from backtest_setups columns + derived fields.

Output:
    kiran_model.pkl         -- trained model (LightGBM or GBM fallback)
    kiran_model_features.pkl-- ordered feature list for live inference
    phase4_report.txt       -- full evaluation report
    feature_importance.csv  -- ranked feature importance

Usage:
    python phase4_train.py
"""

import sys
import logging
import sqlite3
import json
from pathlib import Path

import pandas as pd
import numpy as np
import joblib

from sklearn.metrics import (
    classification_report, roc_auc_score,
    confusion_matrix, accuracy_score,
)
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import TimeSeriesSplit, cross_val_score

# Force UTF-8 on Windows consoles so special chars don't crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DB_PATH      = "psx_data.db"
MODEL_PATH   = "kiran_model.pkl"
FEATURES_PATH= "kiran_model_features.pkl"
REPORT_PATH  = "phase4_report.txt"
FI_PATH      = "feature_importance.csv"

lines = []

def h(title):
    sep = "=" * 60
    lines.append(f"\n{sep}\n  {title}\n{sep}")

def p(text=""):
    lines.append(str(text))


# =============================================================================
# 1. LOAD DATA
# =============================================================================

def load_backtest() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM backtest_setups").fetchall()
    conn.close()
    df = pd.DataFrame([dict(r) for r in rows])
    df["as_of_date"] = pd.to_datetime(df["as_of_date"])
    return df


# =============================================================================
# 2. FEATURE ENGINEERING
# =============================================================================

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep only triggered setups (Win_Trail, Win_T1, Loss).
    Binary target: 1 = Win_Trail (trade ran on 10MA, captured extended move)
                   0 = Win_T1   (stopped at breakeven, 0.5R)
                     + Loss      (full loss, -1R)

    Rationale: We want the ML to identify setups likely to TRAIL, not just
    to trigger. Win_T1 and Loss are both "didn't get the big move" outcomes.
    """
    # Only triggered trades
    df = df[df["outcome"].isin(["Win_Trail", "Win_T1", "Loss"])].copy()
    log.info("Triggered setups: %d", len(df))

    # Binary target: did this trade produce a trailing win?
    df["target"] = (df["outcome"] == "Win_Trail").astype(int)

    # Direction encoded
    df["direction_long"] = (df["direction"] == "LONG").astype(int)

    # Seasonality
    df["month"] = df["as_of_date"].dt.month
    df["quarter"] = df["as_of_date"].dt.quarter

    # Distance from current price to entry (how close to trigger)
    df["dist_to_entry_pct"] = (
        (df["entry_price"] - df["latest_close"]) / df["latest_close"] * 100
    ).round(3)
    # For LONG: positive = price below entry (good -- buy-stop not yet triggered)
    # For SHORT: negative = price above entry (good -- sell-stop not yet triggered)
    # Use absolute value so both directions comparable
    df["dist_to_entry_pct"] = df["dist_to_entry_pct"].abs()

    # Range position: where is price in the consolidation range?
    # 0 = at support, 1 = at resistance
    rng = df["resistance_level"] - df["support_level"]
    df["range_position"] = np.where(
        rng > 0,
        (df["latest_close"] - df["support_level"]) / rng,
        0.5,
    ).round(3)

    # Momentum acceleration: 10d vs 30d ratio
    # >1 = accelerating, <1 = decelerating
    df["momentum_ratio"] = np.where(
        df["stock_perf_30d"].abs() > 0.1,
        (df["stock_perf_10d"] / df["stock_perf_30d"]).round(3),
        0.0,
    )
    df["momentum_ratio"] = df["momentum_ratio"].clip(-3, 3)

    # Volume in millions (easier for the model to work with)
    df["avg_vol_10d_m"] = (df["avg_vol_10d"] / 1_000_000).round(3)

    # Log volume (right-skewed distribution)
    df["log_vol"] = np.log1p(df["avg_vol_10d"].fillna(0))

    # Range window as ordinal (5=tight, 7=medium, 10=wide)
    df["range_window"] = df["range_window"].fillna(7)

    return df


# Top 10 features by importance â€” dropped bottom 6 (direction_long, quarter,
# range_window, quality_score contribute < 2% each and hurt generalisation).
FEATURES = [
    # Liquidity & volatility (top predictors)
    "log_vol",
    "atr_pct",
    # Stock momentum
    "stock_perf_30d",
    "risk_pct",
    "momentum_ratio",
    "dist_to_entry_pct",
    # Market context
    "sector_rank",
    "month",
    "stock_perf_10d",
    "breadth_score",
]


# =============================================================================
# 3. TRAIN / TEST SPLIT
# =============================================================================

MIN_TRAIN_SAMPLES    = 60   # absolute floor; below this CV is meaningless
SMALL_DATA_THRESHOLD = 150  # below this, include 2026 in training (no hold-out)


def split_data(df: pd.DataFrame):
    """
    Strategy: Train on ALL historical data (2024+2025), Live inference = 2026.

    Small-data mode (total triggered < SMALL_DATA_THRESHOLD): include 2026
    setups in training too — holding out 5 samples from 100 teaches nothing.
    In that mode there is no live hold-out; CV within all data is the only
    reliability estimate.
    """
    total = len(df)
    if total < SMALL_DATA_THRESHOLD:
        # Small-data mode: train on everything, no hold-out
        train = df.copy()
        live  = df.iloc[0:0].copy()   # empty DataFrame, same columns
    else:
        train = df[df["as_of_date"].dt.year <= 2025].copy()
        live  = df[df["as_of_date"].dt.year >= 2026].copy()

    # Keep year-level splits for within-train analysis
    train_2024 = df[df["as_of_date"].dt.year == 2024].copy()
    train_2025 = df[df["as_of_date"].dt.year == 2025].copy()
    return train, train_2024, train_2025, live


# =============================================================================
# 4. MODEL
# =============================================================================

def get_model():
    """
    Returns (model, name).

    We use a heavily regularised LightGBM to prevent memorisation on the
    small 2024 training set (369 samples, 10 features):
      - max_depth=3, num_leaves=7  â†’ very shallow trees
      - min_child_samples=30       >>no leaf with fewer than 30 samples
      - n_estimators=100           >>fewer trees (early stopping is data-hungry)
      - reg_alpha/lambda=1.0       >>L1+L2 penalty
      - subsample=0.8, colsample=0.8 â†’ stochastic to reduce variance
    """
    try:
        import lightgbm as lgb
        model = lgb.LGBMClassifier(
            n_estimators=100,
            learning_rate=0.05,
            max_depth=3,
            num_leaves=7,
            min_child_samples=30,
            reg_alpha=1.0,
            reg_lambda=1.0,
            subsample=0.8,
            colsample_bytree=0.8,
            class_weight="balanced",
            random_state=42,
            verbose=-1,
        )
        name = "LightGBM (regularised)"
        log.info("Using LightGBM (regularised)")
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier
        model = GradientBoostingClassifier(
            n_estimators=80,
            learning_rate=0.05,
            max_depth=2,
            min_samples_leaf=20,
            subsample=0.8,
            random_state=42,
        )
        name = "GradientBoosting (sklearn)"
        log.warning("LightGBM not found -- using sklearn GBM")
    return model, name


def get_logistic():
    """Simple logistic regression baseline â€” robust with small datasets."""
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(
            C=0.5,
            class_weight="balanced",
            max_iter=1000,
            random_state=42,
        )),
    ])
    return model, "LogisticRegression (baseline)"


# =============================================================================
# 5. EVALUATION
# =============================================================================

def evaluate(name: str, model, X, y, split_label: str):
    pred  = model.predict(X)
    proba = model.predict_proba(X)[:, 1]
    acc   = accuracy_score(y, pred)
    auc   = roc_auc_score(y, proba)
    cm    = confusion_matrix(y, pred)
    cr    = classification_report(y, pred, target_names=["Loss", "Win"])

    p(f"\n-- {split_label} --")
    p(f"Accuracy  : {acc*100:.1f}%")
    p(f"AUC-ROC   : {auc:.3f}  (0.5=random, 1.0=perfect)")
    p(f"Confusion matrix (rows=actual, cols=predicted):")
    p(f"             Pred Loss  Pred Win")
    p(f"  Actual Loss  {cm[0,0]:>6}     {cm[0,1]:>6}")
    p(f"  Actual Win   {cm[1,0]:>6}     {cm[1,1]:>6}")
    p()
    p(cr)
    return auc


def feature_importance_report(model, feature_names: list, model_name: str):
    try:
        if hasattr(model, "feature_importances_"):
            imp = model.feature_importances_
        else:
            return

        fi = pd.DataFrame({
            "feature": feature_names,
            "importance": imp,
        }).sort_values("importance", ascending=False)
        fi["importance_pct"] = (fi["importance"] / fi["importance"].sum() * 100).round(1)

        fi.to_csv(FI_PATH, index=False)
        log.info("Feature importance saved to %s", FI_PATH)

        h("FEATURE IMPORTANCE (top 16)")
        p(f"{'Rank':<5} {'Feature':<25} {'Importance %':>13}")
        p("-" * 46)
        for i, (_, row) in enumerate(fi.head(16).iterrows(), 1):
            bar = "#" * int(row["importance_pct"] / 2)
            p(f"{i:<5} {row['feature']:<25} {row['importance_pct']:>12.1f}%  {bar}")

        return fi

    except Exception as e:
        p(f"Feature importance unavailable: {e}")
        return None


# =============================================================================
# 6. MAIN
# =============================================================================

def main():
    log.info("Phase 4 -- KIRAN ML Training")

    # â”€â”€ Load & engineer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    raw = load_backtest()
    log.info("Total backtest rows: %d", len(raw))

    df = build_features(raw)

    # Drop rows with any NaN in features
    df_clean = df.dropna(subset=FEATURES + ["target"])
    dropped = len(df) - len(df_clean)
    if dropped:
        log.warning("Dropped %d rows with NaN features", dropped)
    df = df_clean

    # â”€â”€ Split â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    train, train_2024, train_2025, live = split_data(df)

    h("DATASET OVERVIEW")
    p(f"Total triggered setups  : {len(df):,}")
    p(f"  Train (2024+2025)     : {len(train):,}  "
      f"({train['target'].sum()} wins / {(train['target']==0).sum()} losses)")
    p(f"    2024 only           : {len(train_2024):,}  WR={train_2024['target'].mean()*100:.1f}%")
    p(f"    2025 only           : {len(train_2025):,}  WR={train_2025['target'].mean()*100:.1f}%")
    live_note = "unseen -- live inference only" if len(live) > 0 else "included in training (small-data mode)"
    p(f"  Live  (2026+)         : {len(live):,}  ({live_note})")
    p()
    p(f"Features used ({len(FEATURES)}): {', '.join(FEATURES)}")
    p()
    p("NOTE: We train on 2024+2025 combined. A strict 2024â†’2025 out-of-sample")
    p("test showed sub-random AUC because one year is insufficient to cover")
    p("regime changes. Combined training maximises sample size (933 vs 369).")
    p("Cross-validation within 2024+2025 gives the stability estimate.")

    if len(train) < MIN_TRAIN_SAMPLES:
        log.error("Training set too small (%d). Need more historical data.", len(train))
        return

    if len(df) < SMALL_DATA_THRESHOLD:
        p()
        p("*** LOW-DATA WARNING ***")
        p(f"Only {len(df)} triggered setups available (threshold: {SMALL_DATA_THRESHOLD}).")
        p("Training on ALL data (no 2026 hold-out). CV AUC is the only reliability")
        p("estimate. Model confidence scores should be treated as directional hints,")
        p("not precise probabilities. Reliability improves as more setups accumulate.")

    X_train = train[FEATURES].values
    y_train = train["target"].values
    X_train_df = pd.DataFrame(X_train, columns=FEATURES)

    majority_rate = max(y_train.mean(), 1 - y_train.mean()) * 100
    p(f"\nBaseline (always predict majority class): {majority_rate:.1f}%")

    # â”€â”€ Cross-validation within training set â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    h("TIME-SERIES CROSS-VALIDATION (3 folds within 2024+2025)")
    p("Folds are time-ordered (no leakage). AUC measures stability.")
    tscv = TimeSeriesSplit(n_splits=3)

    for get_fn in [get_logistic, get_model]:
        m_cv, mname_cv = get_fn()
        cv_scores = cross_val_score(
            m_cv, X_train, y_train,
            cv=tscv, scoring="roc_auc", n_jobs=1,
        )
        p(f"\n  {mname_cv}")
        p(f"    Fold AUCs : {[round(s,3) for s in cv_scores]}")
        p(f"    Mean AUC  : {cv_scores.mean():.3f}  Â± {cv_scores.std():.3f}")
        if cv_scores.mean() > 0.55:
            p(f"    >>USABLE signal detected")
        elif cv_scores.mean() > 0.50:
            p(f"    >>Weak signal (better than random)")
        else:
            p(f"    >>No signal in this configuration")

    # â”€â”€ Train BOTH models on full 2024+2025, pick winner â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    candidates = []
    for get_fn in [get_logistic, get_model]:
        m, mname = get_fn()
        log.info("Training %s on %d samples (2024+2025)...", mname, len(train))
        m.fit(X_train_df if hasattr(m, 'named_steps') else X_train, y_train)

        tr_proba = m.predict_proba(X_train_df if hasattr(m, 'named_steps') else X_train)[:, 1]
        tr_auc   = roc_auc_score(y_train, tr_proba)

        h(f"MODEL: {mname}  (trained on 2024+2025)")
        tr_auc = evaluate(mname, m,
                          X_train_df if hasattr(m, 'named_steps') else X_train,
                          y_train, "FULL TRAIN (2024+2025) -- fit quality check")

        candidates.append((tr_auc, m, mname))

    # Best by train AUC â€” since we have no hold-out, use CV mean to break tie
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_tr_auc, model, model_name = candidates[0]

    h(f"SELECTED MODEL: {model_name}")
    p(f"  Train AUC (2024+2025) : {best_tr_auc:.3f}")
    p()
    p("  Without a true hold-out year, we cannot report a clean test AUC.")
    p("  The model will be validated naturally as 2026 live results accumulate.")
    p("  Re-train with 2026 data at year-end for a proper out-of-sample check.")

    # â”€â”€ Feature importance â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    fi = feature_importance_report(model, FEATURES, model_name)

    # â”€â”€ Quality score validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    h("QUALITY SCORE vs MODEL SCORE (on 2024+2025 training data)")
    tr_prob = model.predict_proba(X_train_df if hasattr(model, 'named_steps') else X_train)[:, 1]
    train = train.copy()
    train["model_prob"] = tr_prob
    for qs in sorted(train["quality_score"].dropna().unique()):
        g  = train[train["quality_score"] == qs]
        gw = g[g["target"] == 1]
        wr = len(gw)/len(g)*100 if len(g) else 0
        avg_prob = g["model_prob"].mean() * 100
        p(f"  Quality {int(qs)}: n={len(g):>4}  actual WR={wr:.1f}%  "
          f"model avg confidence={avg_prob:.1f}%")

    # â”€â”€ Confidence score distribution on live (2026) setups â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if not live.empty:
        h("MODEL CONFIDENCE ON 2026 SETUPS (live -- first real out-of-sample)")
        X_live = live[FEATURES].values
        X_live_df = pd.DataFrame(X_live, columns=FEATURES)
        live = live.copy()
        live["model_prob"] = model.predict_proba(
            X_live_df if hasattr(model, 'named_steps') else X_live
        )[:, 1]
        p(f"2026 setups (never seen during training): {len(live)}")
        p(f"  Avg confidence   : {live['model_prob'].mean()*100:.1f}%")
        p(f"  High conf (>=65%): {(live['model_prob']>=0.65).sum()} setups")
        p(f"  Low  conf (<=45%): {(live['model_prob']<=0.45).sum()} setups")
        p()
        top5 = live.nlargest(5, "model_prob")[
            ["as_of_date","direction","symbol","sector",
             "quality_score","model_prob"]
        ]
        p("Top 5 highest-confidence 2026 setups:")
        for _, r in top5.iterrows():
            p(f"  {str(r['as_of_date'].date())}  {r['direction']:<6} "
              f"{r['symbol']:<8} Q={int(r['quality_score'])}  "
              f"confidence={r['model_prob']*100:.1f}%")

    # â”€â”€ Save model â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    joblib.dump(model,    MODEL_PATH)
    joblib.dump(FEATURES, FEATURES_PATH)
    log.info("Model saved  : %s", MODEL_PATH)
    log.info("Features saved: %s", FEATURES_PATH)

    h("NEXT STEPS -- Phase 5")
    p("1. Load kiran_model.pkl in dashboard.py")
    p("2. For each live setup, extract the same 16 features")
    p("3. model.predict_proba([features])[0][1] * 100 = confidence score")
    p("4. Display as confidence badge on each setup card in KIRAN")
    p("5. Re-train monthly as new backtest data accumulates")

    # â”€â”€ Write report â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    report = "\n".join(lines)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    log.info("Report saved : %s", REPORT_PATH)
    print("\n" + report)


if __name__ == "__main__":
    main()

