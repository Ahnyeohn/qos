import os
import re
import argparse
import pandas as pd
import matplotlib.pyplot as plt


DROP_PATTERN = re.compile(r"rtp_timestamp=(\d+)")


def load_frame_records(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    if "frameId" not in df.columns:
        raise ValueError("frame_records.csv must contain 'frameId' column")

    df["frameId"] = pd.to_numeric(df["frameId"], errors="coerce")
    df = df.dropna(subset=["frameId"]).copy()
    df["frameId"] = df["frameId"].astype("int64")

    df = df.drop_duplicates(subset=["frameId"], keep="first").copy()
    df["isRecorded"] = 1

    return df[["frameId", "isRecorded"]]


def load_frame_drop_log(log_path: str) -> pd.DataFrame:
    dropped_ids = []

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = DROP_PATTERN.search(line)
            if m:
                dropped_ids.append(int(m.group(1)))

    drop_df = pd.DataFrame({"frameId": sorted(set(dropped_ids))})
    drop_df["isDropped"] = 1

    return drop_df


def build_total_sequence(records_df: pd.DataFrame, drop_df: pd.DataFrame) -> pd.DataFrame:
    total_df = pd.merge(records_df, drop_df, on="frameId", how="outer")

    total_df["isRecorded"] = total_df["isRecorded"].fillna(0).astype(int)
    total_df["isDropped"] = total_df["isDropped"].fillna(0).astype(int)

    def classify(row):
        if row["isRecorded"] == 1 and row["isDropped"] == 0:
            return "recorded"
        elif row["isRecorded"] == 0 and row["isDropped"] == 1:
            return "dropped"
        elif row["isRecorded"] == 1 and row["isDropped"] == 1:
            return "both"
        else:
            return "unknown"

    total_df["frameStatus"] = total_df.apply(classify, axis=1)

    total_df = total_df.sort_values("frameId").reset_index(drop=True)
    total_df["frameIndex"] = total_df.index
    total_df["frameIdDiff"] = total_df["frameId"].diff().fillna(0)

    # 0/1 상태값:
    # recorded only -> 1
    # dropped or both -> 0
    total_df["recordedState01"] = (total_df["frameStatus"] == "recorded").astype(int)

    return total_df


def print_summary(total_df: pd.DataFrame) -> None:
    print("\n[INFO] frameStatus counts:")
    print(total_df["frameStatus"].value_counts().sort_index())

    print(f"\n[INFO] total frames in merged sequence: {len(total_df)}")
    print(f"[INFO] recorded only: {(total_df['frameStatus'] == 'recorded').sum()}")
    print(f"[INFO] dropped only : {(total_df['frameStatus'] == 'dropped').sum()}")
    print(f"[INFO] both         : {(total_df['frameStatus'] == 'both').sum()}")


def save_total_sequence_csv(total_df: pd.DataFrame, out_csv_path: str) -> None:
    total_df.to_csv(out_csv_path, index=False)
    print(f"[INFO] saved merged sequence csv: {out_csv_path}")


def plot_frame_timeline(total_df: pd.DataFrame, out_png_path: str) -> None:
    # 앞 500개 프레임만 보기
    plot_df = total_df.head(500).copy()

    fig, ax1 = plt.subplots(figsize=(16, 4))

    # ===== 0/1 state line only =====
    ax1.step(
        plot_df["frameIndex"],
        plot_df["recordedState01"],
        where="post",
        linewidth=1.8,
        label="recordedState01 (1=recorded, 0=dropped/both)",
    )

    ax1.set_title("Recorded(1) / Dropped(0) by merged frame index (first 500 frames)")
    ax1.set_xlabel("Merged frame index")
    ax1.set_ylabel("State")
    ax1.set_yticks([0, 1])
    ax1.set_yticklabels(["dropped", "recorded"])
    ax1.set_ylim(-0.2, 1.2)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="best")

    dropped_mask = plot_df["recordedState01"] == 0
    dropped_df = plot_df[dropped_mask]

    if not dropped_df.empty:
        ax1.scatter(
            dropped_df["frameIndex"],
            dropped_df["recordedState01"],
            s=18,
            marker="o",
            label="drop points",
        )

    plt.tight_layout()
    plt.savefig(out_png_path, dpi=200)
    plt.close()

    print(f"[INFO] saved plot: {out_png_path}")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot recorded/dropped frames as a 0/1 state line"
    )
    parser.add_argument(
        "--csv",
        type=str,
        default="/home/n2sl/yeon/qos/network/log/frame/frame_records.csv",
        help="Path to frame_records.csv",
    )
    parser.add_argument(
        "--log",
        type=str,
        default="/home/n2sl/yeon/qos/network/log/frame/frame_drop.log",
        help="Path to frame_drop.log",
    )
    parser.add_argument(
        "--out_csv",
        type=str,
        default="/home/n2sl/yeon/qos/network/log/frame/merged_frame_sequence.csv",
        help="Path to save merged sequence CSV",
    )
    parser.add_argument(
        "--out_plot",
        type=str,
        default="/home/n2sl/yeon/qos/network/log/frame/plots/merged_frame_timeline_01.png",
        help="Path to save timeline plot",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    os.makedirs(os.path.dirname(args.out_csv), exist_ok=True)
    os.makedirs(os.path.dirname(args.out_plot), exist_ok=True)

    print(f"[INFO] csv path: {args.csv}")
    print(f"[INFO] log path: {args.log}")

    records_df = load_frame_records(args.csv)
    drop_df = load_frame_drop_log(args.log)

    print(f"[INFO] recorded frames count: {len(records_df)}")
    print(f"[INFO] dropped frames(unique) count: {len(drop_df)}")

    total_df = build_total_sequence(records_df, drop_df)

    print_summary(total_df)
    save_total_sequence_csv(total_df, args.out_csv)
    plot_frame_timeline(total_df, args.out_plot)


if __name__ == "__main__":
    main()