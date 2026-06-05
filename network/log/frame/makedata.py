import os
import argparse
import pandas as pd


def load_and_extract(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    required_cols = [
        "receiveTimeMs",
        "decodeStartMs",
        "decodeFinishMs",
        "desiredReceiveTimeMs",
        "desiredDecodeStartMs",
        "actualSlackMs",
        "receiveSlackMs",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["decodeSlackMs"] = df["desiredDecodeStartMs"] - df["receiveTimeMs"]

    out_cols = [
        "actualSlackMs",
        "receiveSlackMs",
        "decodeSlackMs",
        "receiveTimeMs",
        "decodeStartMs",
        "decodeFinishMs",
        "desiredReceiveTimeMs",
        "desiredDecodeStartMs",
    ]

    out_df = df[out_cols].copy()
    out_df = out_df.dropna().reset_index(drop=True)

    return out_df


def parse_args():
    parser = argparse.ArgumentParser(description="Extract timing/slack columns and save as spaced txt")
    parser.add_argument(
        "-pacing",
        type=int,
        default=0,
        help="Use pacing CSV if set to 1. Default: 0"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.pacing == 1:
        csv_path = "/home/n2sl/yeon/qos/network/log/frame/frame_records_pacing.csv"
        out_path = "/home/n2sl/yeon/qos/network/log/frame/slack_timing_values_pacing.txt"
    else:
        csv_path = "/home/n2sl/yeon/qos/network/log/frame/frame_records.csv"
        out_path = "/home/n2sl/yeon/qos/network/log/frame/slack_timing_values.txt"

    print(f"[INFO] csv_path: {csv_path}")
    print(f"[INFO] out_path: {out_path}")

    out_df = load_and_extract(csv_path)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        # 헤더
        f.write(", ".join(out_df.columns) + "\n")

        # 데이터
        for _, row in out_df.iterrows():
            values = [str(v) for v in row.tolist()]
            f.write(", ".join(values) + "\n")

    print(f"[INFO] saved {len(out_df)} rows to {out_path}")


if __name__ == "__main__":
    main()