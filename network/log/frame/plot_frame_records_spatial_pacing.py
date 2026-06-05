import os
import argparse
import pandas as pd
import matplotlib.pyplot as plt


def load_and_prepare_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    required_cols = [
        "frameId",
        "receiveTimeMs",
        "desiredDecodeStartMs",
        "actualSlackMs",
        "receiveSlackMs",
        "currentSpatialLayer",
        "availableBitrateBps",
        "pacing",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # decodeSlackMs 새로 계산
    df["decodeSlackMs"] = df["desiredDecodeStartMs"] - df["receiveTimeMs"]

    # 보기 편하게 Mbps 단위 추가
    df["availableBitrateMbps"] = df["availableBitrateBps"] / 1_000_000.0

    df = df.dropna(
        subset=[
            "frameId",
            "actualSlackMs",
            "receiveSlackMs",
            "decodeSlackMs",
            "currentSpatialLayer",
            "availableBitrateMbps",
            "pacing",
        ]
    ).copy()

    df["currentSpatialLayer"] = df["currentSpatialLayer"].astype(int)
    df["pacing"] = df["pacing"].astype(int)

    df = df.sort_values("frameId").reset_index(drop=True)

    return df


def print_layer_summary(df: pd.DataFrame) -> None:
    print("\n[INFO] currentSpatialLayer counts:")
    print(df["currentSpatialLayer"].value_counts().sort_index())

    print("\n[INFO] pacing counts:")
    print(df["pacing"].value_counts().sort_index())

    print("\n[INFO] Slack summary by currentSpatialLayer:")
    summary = df.groupby("currentSpatialLayer")[
        ["actualSlackMs", "receiveSlackMs", "decodeSlackMs", "availableBitrateMbps"]
    ].agg(["count", "mean", "median", "std", "min", "max"])
    print(summary)

    print("\n[INFO] Slack summary by pacing:")
    pacing_summary = df.groupby("pacing")[
        ["actualSlackMs", "receiveSlackMs", "decodeSlackMs", "availableBitrateMbps"]
    ].agg(["count", "mean", "median", "std", "min", "max"])
    print(pacing_summary)

    # spatial layer transition 위치 확인
    df_tmp = df.copy()
    df_tmp["prevSpatialLayer"] = df_tmp["currentSpatialLayer"].shift(1)
    spatial_transitions = df_tmp[df_tmp["currentSpatialLayer"] != df_tmp["prevSpatialLayer"]]

    print("\n[INFO] Spatial layer transitions:")
    print(
        spatial_transitions[
            [
                "frameId",
                "prevSpatialLayer",
                "currentSpatialLayer",
                "availableBitrateMbps",
                "actualSlackMs",
                "receiveSlackMs",
                "decodeSlackMs",
            ]
        ].head(20)
    )

    # pacing transition 위치 확인
    df_tmp["prevpacing"] = df_tmp["pacing"].shift(1)
    pacing_transitions = df_tmp[df_tmp["pacing"] != df_tmp["prevpacing"]]

    print("\n[INFO] Pacing transitions:")
    print(
        pacing_transitions[
            [
                "frameId",
                "prevpacing",
                "pacing",
                "currentSpatialLayer",
                "availableBitrateMbps",
                "actualSlackMs",
                "receiveSlackMs",
                "decodeSlackMs",
            ]
        ].head(20)
    )


def plot_slacks_with_spatial_and_bitrate(df: pd.DataFrame, out_path: str) -> None:
    x = range(len(df))

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(14, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    # Slack metrics
    ax1.plot(
        x,
        df["actualSlackMs"],
        label="actualSlackMs",
        linewidth=1.3,
        alpha=0.65,
        linestyle="-",
    )

    ax1.plot(
        x,
        df["receiveSlackMs"],
        label="receiveSlackMs",
        linewidth=2.2,
        alpha=0.95,
        linestyle="--",
    )

    ax1.plot(
        x,
        df["decodeSlackMs"],
        label="decodeSlackMs",
        linewidth=2.0,
        alpha=0.95,
        linestyle="-.",
    )

    ax1.set_ylabel("Slack (ms)")
    ax1.set_title("Slack metrics with currentSpatialLayer, availableBitrate, and pacing")
    ax1.grid(True, alpha=0.3)

    # Bottom plot: currentSpatialLayer + availableBitrateMbps
    ax2.step(
        x,
        df["currentSpatialLayer"],
        label="currentSpatialLayer",
        linewidth=2.0,
        where="post",
        color="red",
    )

    ax2.set_xlabel("Frame index")
    ax2.set_ylabel("Spatial Layer", color="red")
    ax2.tick_params(axis="y", labelcolor="red")
    ax2.set_yticks([0, 1, 2])
    ax2.set_ylim(-0.2, 2.2)
    ax2.grid(True, alpha=0.3)

    ax3 = ax2.twinx()
    ax3.plot(
        x,
        df["availableBitrateMbps"],
        label="availableBitrateMbps",
        linewidth=1.8,
        alpha=0.85,
        linestyle="--",
        color="blue",
    )
    ax3.set_ylabel("Available Bitrate (Mbps)", color="blue")
    ax3.tick_params(axis="y", labelcolor="blue")

    # pacing transition vertical lines
    prev_pacing = df["pacing"].shift(1)
    pacing_transition_indices = df.index[df["pacing"] != prev_pacing].tolist()

    pacing_label_used = False

    for idx in pacing_transition_indices:
        if idx == 0:
            continue

        old_value = int(df.loc[idx - 1, "pacing"])
        new_value = int(df.loc[idx, "pacing"])

        if old_value == 0 and new_value == 1:
            label = "pacing OFF → ON"
        elif old_value == 1 and new_value == 0:
            label = "pacing ON → OFF"
        else:
            label = "pacing change"

        ax1.axvline(
            idx,
            color="black",
            linestyle=":",
            linewidth=2.0,
            alpha=0.9,
            label=label if not pacing_label_used else None,
        )

        ax2.axvline(
            idx,
            color="black",
            linestyle=":",
            linewidth=2.0,
            alpha=0.9,
        )

        pacing_label_used = True

    # legends
    lines1, labels1 = ax1.get_legend_handles_labels()
    ax1.legend(lines1, labels1, loc="best")

    lines2, labels2 = ax2.get_legend_handles_labels()
    lines3, labels3 = ax3.get_legend_handles_labels()
    ax2.legend(lines2 + lines3, labels2 + labels3, loc="best")

    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()

    print(f"[INFO] Saved plot: {out_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot slack metrics with currentSpatialLayer, availableBitrateMbps, and pacing"
    )
    parser.add_argument(
        "-pacing",
        type=int,
        default=0,
        help="Use pacing CSV if set to 1. Default: 0",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.pacing == 1:
        csv_path = "/home/n2sl/yeon/qos/network/log/frame/frame_records_pacing.csv"
        out_path = "/home/n2sl/yeon/qos/network/log/frame/plots/slacks_spatial_bitrate_pacing_switch.png"
    else:
        csv_path = "/home/n2sl/yeon/qos/network/log/frame/frame_records.csv"
        out_path = "/home/n2sl/yeon/qos/network/log/frame/plots/slacks_spatial_bitrate_pacing_switch.png"

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print(f"[INFO] csv_path: {csv_path}")

    df = load_and_prepare_csv(csv_path)

    print(f"[INFO] loaded rows: {len(df)}")

    print_layer_summary(df)

    plot_slacks_with_spatial_and_bitrate(df, out_path)


if __name__ == "__main__":
    main()