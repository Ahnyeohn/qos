import os
import math
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


CSV_PATH = "/home/n2sl/yeon/qos/network/log/frame/frame_records_pacing.csv"
OUT_DIR = "/home/n2sl/yeon/qos/network/log/frame/knn_result"
TEST_RATIO = 0.3


def load_and_prepare_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    df.columns = df.columns.str.strip()

    required_cols = [
        "frameId",
        "predictedSlackMs",
        "actualSlackMs",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # predicted/actual 둘 다 있는 행만 사용
    df = df.dropna(subset=["frameId", "predictedSlackMs", "actualSlackMs"]).copy()

    # 시간 순서 유지
    df = df.sort_values("frameId").reset_index(drop=True)

    return df


def split_test_portion(df: pd.DataFrame, test_ratio: float = 0.3) -> pd.DataFrame:
    n = len(df)
    test_start = int(n * (1.0 - test_ratio))
    return df.iloc[test_start:].copy()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"[INFO] csv: {CSV_PATH}")
    print(f"[INFO] outdir: {OUT_DIR}")
    print(f"[INFO] test_ratio: {TEST_RATIO}")

    df = load_and_prepare_csv(CSV_PATH)

    print(f"[INFO] total valid rows: {len(df)}")

    test_df = split_test_portion(df, TEST_RATIO)

    print(f"[INFO] test rows: {len(test_df)}")

    y_true = test_df["actualSlackMs"]
    y_pred = test_df["predictedSlackMs"]

    mae = mean_absolute_error(y_true, y_pred)
    rmse = math.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)

    # errorMs 컬럼이 이미 있으면 그대로 쓰고, 없으면 새로 계산
    if "errorMs" in test_df.columns:
        test_df["errorMs_from_csv"] = pd.to_numeric(test_df["errorMs"], errors="coerce")
    test_df["errorMs_recomputed"] = test_df["predictedSlackMs"] - test_df["actualSlackMs"]

    print("\n[RESULT] Existing CSV predictedSlackMs on last 30%")
    print(f"  MAE : {mae:.6f}")
    print(f"  RMSE: {rmse:.6f}")
    print(f"  R^2 : {r2:.6f}")

    summary_df = pd.DataFrame([
        {
            "model": "ExistingCsvPredictedSlack",
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "total_valid_rows": len(df),
            "test_rows": len(test_df),
            "test_ratio": TEST_RATIO,
        }
    ])

    summary_csv_path = os.path.join(OUT_DIR, "existing_csv_prediction_summary.csv")
    summary_df.to_csv(summary_csv_path, index=False)

    result_csv_path = os.path.join(OUT_DIR, "existing_csv_test_portion_results.csv")
    test_df.to_csv(result_csv_path, index=False)

    print(f"[INFO] Saved summary CSV: {summary_csv_path}")
    print(f"[INFO] Saved test portion CSV: {result_csv_path}")


if __name__ == "__main__":
    main()