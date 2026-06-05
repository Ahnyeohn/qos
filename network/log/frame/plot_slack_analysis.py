import os
import argparse
import pandas as pd
import matplotlib.pyplot as plt


def load_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    required_cols = ["frameId", "receiveSlackMs", "actualSlackMs"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required_cols).copy()
    df = df.sort_values("frameId").reset_index(drop=True)
    return df


def plot_receive_vs_actual_slack(df: pd.DataFrame, out_path: str) -> None:
    x = range(len(df))

    plt.figure(figsize=(14, 7))

    # actual slack
    plt.plot(
        x,
        df["actualSlackMs"],
        label="actualSlackMs",
        linewidth=1.5,
        alpha=0.65,
        linestyle="-",
        zorder=1
    )

    # receive slack
    plt.plot(
        x,
        df["receiveSlackMs"],
        label="receiveSlackMs",
        linewidth=2.3,
        alpha=0.95,
        linestyle="--",
        marker="o",
        markersize=3,
        markevery=20,
        zorder=2
    )

    plt.xlabel("Frame index")
    plt.ylabel("Milliseconds (ms)")
    plt.title("receiveSlackMs vs actualSlackMs")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    plt.savefig(out_path, dpi=200)
    plt.close()

    print(f"[INFO] Saved: {out_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="Plot receiveSlackMs and actualSlackMs in one graph")
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
        out_path = "/home/n2sl/yeon/qos/network/log/frame/plots/receive_vs_actual_slack_pacing.png"
    else:
        csv_path = "/home/n2sl/yeon/qos/network/log/frame/frame_records.csv"
        out_path = "/home/n2sl/yeon/qos/network/log/frame/plots/receive_vs_actual_slack.png"

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print(f"[INFO] csv_path: {csv_path}")
    df = load_csv(csv_path)
    print(f"[INFO] loaded rows: {len(df)}")

    plot_receive_vs_actual_slack(df, out_path)


if __name__ == "__main__":
    main()