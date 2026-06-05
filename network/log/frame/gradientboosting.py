import os
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


CSV_PATH = "/home/n2sl/yeon/qos/network/log/frame/frame_records.csv"
OUT_DIR = "/home/n2sl/yeon/qos/network/log/frame/gbr_results"
TRAIN_RATIO = 0.7


def load_and_prepare_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()
    
    required_cols = [
        "frameId",
        "actualSlackMs",
        "rttMs",
        "lossRate",
        "aceQueueBytes",
        "pacingBacklogBytes",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[required_cols].dropna().copy()
    df = df.sort_values("frameId").reset_index(drop=True)
    return df


def time_order_train_test_split(df: pd.DataFrame, train_ratio: float = 0.7):
    n = len(df)
    split_idx = int(n * train_ratio)
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()
    return train_df, test_df


def evaluate_predictions(y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = math.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)
    return mae, rmse, r2


def save_prediction_plot(test_df: pd.DataFrame, out_path: str):
    x = np.arange(len(test_df))

    plt.figure(figsize=(14, 7))
    plt.plot(x, test_df["actualSlackMs"], label="actualSlackMs", linewidth=2.0, alpha=0.7)
    plt.plot(x, test_df["gbrPredictedSlackMs"], label="gbrPredictedSlackMs", linewidth=2.0, linestyle="--")
    plt.xlabel("Test frame index")
    plt.ylabel("Slack (ms)")
    plt.title("GradientBoosting: Actual vs Predicted Slack")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"[INFO] csv: {CSV_PATH}")
    print(f"[INFO] outdir: {OUT_DIR}")
    print(f"[INFO] train_ratio: {TRAIN_RATIO}")

    df = load_and_prepare_csv(CSV_PATH)

    print(f"[INFO] total valid rows: {len(df)}")

    feature_cols = [
        "rttMs",
        "lossRate",
        "aceQueueBytes",
        "pacingBacklogBytes",
    ]
    target_col = "actualSlackMs"

    train_df, test_df = time_order_train_test_split(df, train_ratio=TRAIN_RATIO)

    print(f"[INFO] train rows: {len(train_df)}")
    print(f"[INFO] test rows : {len(test_df)}")

    X_train = train_df[feature_cols]
    y_train = train_df[target_col]

    X_test = test_df[feature_cols]
    y_test = test_df[target_col]

    model = GradientBoostingRegressor(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=3,
        random_state=42,
    )

    model.fit(X_train, y_train)
    pred = model.predict(X_test)

    mae, rmse, r2 = evaluate_predictions(y_test, pred)

    print("\n[RESULT] GradientBoostingRegressor")
    print(f"  MAE : {mae:.4f}")
    print(f"  RMSE: {rmse:.4f}")
    print(f"  R^2 : {r2:.4f}")

    result_df = test_df.copy()
    result_df["gbrPredictedSlackMs"] = pred
    result_df["gbrErrorMs"] = result_df["gbrPredictedSlackMs"] - result_df["actualSlackMs"]

    result_csv_path = os.path.join(OUT_DIR, "gbr_slack_prediction_results.csv")
    result_df.to_csv(result_csv_path, index=False)
    print(f"[INFO] Saved result CSV: {result_csv_path}")

    summary_df = pd.DataFrame([
        {
            "model": "GradientBoostingRegressor",
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "train_rows": len(train_df),
            "test_rows": len(test_df),
        }
    ])

    summary_csv_path = os.path.join(OUT_DIR, "gbr_slack_prediction_summary.csv")
    summary_df.to_csv(summary_csv_path, index=False)
    print(f"[INFO] Saved summary CSV: {summary_csv_path}")

    plot_path = os.path.join(OUT_DIR, "gbr_actual_vs_predicted_slack.png")
    save_prediction_plot(result_df, plot_path)
    print(f"[INFO] Saved plot: {plot_path}")


if __name__ == "__main__":
    main()