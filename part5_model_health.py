# -*- coding: utf-8 -*-
"""
PART 5: Model Health Dashboard
================================
Shows a 30-second health check: is the model safe to trade with right now?
Reads from prediction_log.csv (Part 7) if available, else uses stored accuracy.

HOW TO RUN:
  python part5_model_health.py

OUTPUT: model_health_report.txt  (also printed to console)

STREAMLIT INTEGRATION (add to dashboard.py):
  from part5_model_health import generate_health_report
  with st.expander("Model Health"):
      st.code(generate_health_report(), language=None)
"""

import sys
import pandas as pd
import numpy as np
import pickle
import json
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PIPELINE_DIR      = Path(__file__).parent
KIRAN_MODEL       = PIPELINE_DIR / "kiran_model.pkl"
DIRECTION_MODEL   = PIPELINE_DIR / "direction_model.pkl"
PRED_LOG          = PIPELINE_DIR / "prediction_log.csv"
RETRAIN_LOG       = PIPELINE_DIR / "retrain_log.json"
HEALTH_REPORT     = PIPELINE_DIR / "model_health_report.txt"

SEP  = "=" * 62
DASH = "-" * 62


# --- HELPERS -----------------------------------------------------------------

def load_prediction_log():
    if not PRED_LOG.exists():
        return None
    df = pd.read_csv(PRED_LOG, parse_dates=["log_date"])
    if "date" not in df.columns:
        df = df.rename(columns={"log_date": "date"})
    evaluated = df.dropna(subset=["was_correct"])
    return evaluated if len(evaluated) >= 5 else None


def window_accuracy(df, last_n):
    recent  = df.sort_values("date").tail(last_n)
    n       = len(recent)
    correct = int(recent["was_correct"].sum()) if n > 0 else 0
    acc     = correct / n if n > 0 else float("nan")
    return {"n": n, "correct": correct, "accuracy": acc}


def accuracy_bar(correct, total, width=20):
    if total == 0:
        return "No data"
    filled = int(round(correct / total * width))
    bar    = "#" * filled + "." * (width - filled)
    return "{}  ({}/{})".format(bar, correct, total)


def status_label(accuracy):
    if np.isnan(accuracy):
        return "[?] UNKNOWN  -- log predictions for 20+ days first"
    if accuracy > 0.55:
        return "[GREEN]  Use for trading  (accuracy {:.1%} > 55%)".format(accuracy)
    if accuracy >= 0.50:
        return "[YELLOW] Be cautious     (accuracy {:.1%}, 50-55%)".format(accuracy)
    return "[RED]    Stop trading    (accuracy {:.1%} < 50% -- retrain!)".format(accuracy)


def fmt(a):
    return "{:.1%}".format(a) if not np.isnan(a) else "N/A"


def compute_sharpe(df):
    if "actual_return" not in df.columns:
        return float("nan")
    traded = df[df["prediction"].isin(["BUY", "STRONG BUY"])] if "prediction" in df.columns else df
    if len(traded) < 20:
        return float("nan")
    rets = pd.to_numeric(traded["actual_return"], errors="coerce").dropna()
    if rets.std() == 0:
        return float("nan")
    return round((rets.mean() / rets.std()) * np.sqrt(250), 2)


def compute_max_drawdown(df):
    if "actual_return" not in df.columns:
        return float("nan")
    rets = pd.to_numeric(df.sort_values("date")["actual_return"], errors="coerce").fillna(0)
    cum  = (1 + rets).cumprod()
    dd   = (cum - cum.cummax()) / cum.cummax()
    return round(float(dd.min()) * 100, 2)


def calibration_check(df):
    if "ml_probability" not in df.columns:
        return []
    results = []
    for lo, hi in [(0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 1.01)]:
        sub = df[(df["ml_probability"] >= lo) & (df["ml_probability"] < hi)]
        if len(sub) < 5:
            continue
        results.append(("{}-{}%".format(int(lo*100), int(hi*100)),
                        (lo + hi) / 2, sub["was_correct"].mean(), len(sub)))
    return results


def last_retrain_info():
    if not RETRAIN_LOG.exists():
        return "Never retrained"
    try:
        log  = json.loads(RETRAIN_LOG.read_text(encoding="utf-8"))
        last = log[-1] if log else None
        if not last:
            return "Never retrained"
        return "{}  (direction acc {:.1%}, kept: {})".format(
            last["date"], last["new_acc"], last["kept"]
        )
    except Exception:
        return "Log unreadable"


def load_model_info(model_path):
    if not model_path.exists():
        return {}
    try:
        with open(model_path, "rb") as f:
            b = pickle.load(f)
        if isinstance(b, dict):
            return b
    except Exception:
        pass
    return {}


# --- REPORT BUILDER ----------------------------------------------------------

def generate_health_report():
    lines = [SEP, "  PSX MODEL HEALTH DASHBOARD",
             "  Generated: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M")), SEP]

    pred_df = load_prediction_log()

    if pred_df is not None and len(pred_df) >= 10:
        w20  = window_accuracy(pred_df, 20)
        w100 = window_accuracy(pred_df, 100)
        lines.append("  Based on {:,} logged & evaluated predictions".format(len(pred_df)))
        acc_20  = w20["accuracy"]
        acc_100 = w100["accuracy"]
        bar_20  = accuracy_bar(w20["correct"],  w20["n"])
        bar_100 = accuracy_bar(w100["correct"], w100["n"])
    else:
        # Fall back to stored test accuracy from direction_model.pkl
        dm = load_model_info(DIRECTION_MODEL)
        stored = dm.get("test_accuracy")
        acc_20  = stored if stored else float("nan")
        acc_100 = stored if stored else float("nan")
        filled  = int(acc_100 * 20) if not np.isnan(acc_100) else 10
        bar_20  = "#" * filled + "." * (20 - filled) + "  (estimated from test set)"
        bar_100 = bar_20
        lines.append("  NOTE: No prediction log yet -- showing stored test accuracy.")
        lines.append("        Run daily_morning.bat to start logging predictions.")

    # 30-second check
    lines += ["", DASH, "  30-SECOND HEALTH CHECK", DASH]
    lines.append("  Last 20  predictions:  {}".format(bar_20))
    lines.append("  Last 100 predictions:  {}".format(bar_100))

    # Status
    lines += ["", "  STATUS: {}".format(status_label(acc_100))]

    # Detailed metrics
    lines += ["", DASH, "  DETAILED METRICS", DASH]
    lines.append("  {:<38} {:>10}".format("Metric", "Value"))
    lines.append("  " + "-"*50)
    lines.append("  {:<38} {:>10}".format("Out-of-sample acc (last 20 preds)",  fmt(acc_20)))
    lines.append("  {:<38} {:>10}".format("Out-of-sample acc (last 100 preds)", fmt(acc_100)))
    lines.append("  {:<38} {:>10}".format("Benchmark (persistent forecast)",    "~50-52%"))
    beat = acc_100 - 0.51
    lines.append("  {:<38} {:>10}".format("Beat benchmark by",
                                          fmt(beat) if not np.isnan(acc_100) else "N/A"))

    if pred_df is not None:
        sharpe = compute_sharpe(pred_df)
        mdd    = compute_max_drawdown(pred_df)
        lines.append("  {:<38} {:>10}".format("Sharpe ratio (annualised)",
                                              str(sharpe) if not np.isnan(sharpe) else "N/A"))
        lines.append("  {:<38} {:>10}".format("Max drawdown",
                                              "{:.1f}%".format(mdd) if not np.isnan(mdd) else "N/A"))

    # Calibration
    if pred_df is not None:
        cal = calibration_check(pred_df)
        if cal:
            lines += ["", DASH, "  RELIABILITY: does 70% really mean 70%?", DASH]
            lines.append("  {:<12} {:>11} {:>11} {:>8}  {}".format(
                "Bucket", "Model says", "Actual", "Count", "Calibrated?"))
            lines.append("  " + "-"*55)
            for label, pred_p, actual_p, n in cal:
                ok = "[OK]" if abs(actual_p - pred_p) < 0.10 else "[OFF]"
                lines.append("  {:<12} {:>10.0%} {:>11.0%} {:>8}  {}".format(
                    label, pred_p, actual_p, n, ok))

    # Accuracy by score
    if pred_df is not None and "quality_score" in pred_df.columns:
        lines += ["", DASH, "  ACCURACY BY QUALITY SCORE", DASH]
        for qv in sorted(pred_df["quality_score"].dropna().unique()):
            sub = pred_df[pred_df["quality_score"] == qv]
            lines.append("  Score {}: {:.1%}  ({} trades)".format(
                int(qv), sub["was_correct"].mean(), len(sub)))

    # Model info -- both models
    lines += ["", DASH, "  MODEL INFO", DASH]
    lines.append("  Last direction retrain: {}".format(last_retrain_info()))

    km = load_model_info(KIRAN_MODEL)
    if km:
        lines.append("  Kiran setup model trained on: {} rows".format(
            "{:,}".format(km["train_rows"]) if km.get("train_rows") else "?"
        ))

    dm = load_model_info(DIRECTION_MODEL)
    if dm:
        lines.append("  Direction model trained on  : {} rows  (acc: {})".format(
            "{:,}".format(dm["train_rows"]) if dm.get("train_rows") else "?",
            fmt(dm["test_accuracy"]) if dm.get("test_accuracy") else "?"
        ))
    else:
        lines.append("  Direction model             : Not yet trained (run part3)")

    # Recommendation
    lines += ["", DASH, "  RECOMMENDATION", DASH]
    if np.isnan(acc_100):
        lines.append("  Start logging daily predictions (run daily_morning.bat).")
        lines.append("  After 20 trading days you will see real accuracy stats here.")
    elif acc_100 > 0.55:
        lines.append("  [OK] Model performing well. Normal position sizes.")
        lines.append("  Retrain monthly (1st Monday via retrain.bat).")
    elif acc_100 >= 0.50:
        lines.append("  [!] Model marginal. Reduce position size by 50%.")
        lines.append("  If below 55% for 2 more weeks: run part4_monthly_retrain.py --force")
    else:
        lines.append("  [!!] STOP TRADING with this model.")
        lines.append("  Run: python part4_monthly_retrain.py --force")
        lines.append("  Then re-run part3_train_test_split.py to diagnose.")

    lines.append(SEP)
    return "\n".join(lines)


def main():
    report = generate_health_report()
    print(report)
    HEALTH_REPORT.write_text(report, encoding="utf-8")
    print("\n  Report saved: {}".format(HEALTH_REPORT.name))
    print("  NEXT STEP: python part6_predictions.py")


if __name__ == "__main__":
    main()
