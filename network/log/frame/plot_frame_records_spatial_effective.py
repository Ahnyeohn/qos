import os
import argparse
import pandas as pd
import matplotlib.pyplot as plt


def load_and_prepare_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    required_cols = [
        "frameId",
        "actualSlackMs",
        "actualSlackEffectiveMs",
        "receiveSlackMs",
        "decodeSlackNominalMs",
        "queueResidenceMs",
        "decodeSlackEffectiveMs",
        "currentSpatialLayer",
        "availableBitrateBps",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 보기 편하게 Mbps 단위 추가
    df["availableBitrateMbps"] = df["availableBitrateBps"] / 1_000_000.0

    df = df.dropna(
        subset=[
            "frameId",
            "actualSlackMs",
            "actualSlackEffectiveMs",
            "receiveSlackMs",
            "decodeSlackNominalMs",
            "queueResidenceMs",
            "decodeSlackEffectiveMs",
            "currentSpatialLayer",
            "availableBitrateMbps",
        ]
    ).copy()

    df["currentSpatialLayer"] = df["currentSpatialLayer"].astype(int)
    df = df.sort_values("frameId").reset_index(drop=True)

    return df


def print_layer_summary(df: pd.DataFrame) -> None:
    print("\n[INFO] currentSpatialLayer counts:")
    print(df["currentSpatialLayer"].value_counts().sort_index())

    print("\n[INFO] Slack summary by currentSpatialLayer:")
    summary = df.groupby("currentSpatialLayer")[
        [
            "actualSlackMs",
            "actualSlackEffectiveMs",
            "receiveSlackMs",
            "decodeSlackNominalMs",
            "queueResidenceMs",
            "decodeSlackEffectiveMs",
            "availableBitrateMbps",
        ]
    ].agg(["count", "mean", "median", "std", "min", "max"])

    print(summary)

    df_tmp = df.copy()
    df_tmp["prevSpatialLayer"] = df_tmp["currentSpatialLayer"].shift(1)
    transitions = df_tmp[df_tmp["currentSpatialLayer"] != df_tmp["prevSpatialLayer"]]

    print("\n[INFO] Spatial layer transitions:")
    print(
        transitions[
            [
                "frameId",
                "prevSpatialLayer",
                "currentSpatialLayer",
                "availableBitrateMbps",
                "actualSlackMs",
                "actualSlackEffectiveMs",
                "receiveSlackMs",
                "decodeSlackNominalMs",
                "queueResidenceMs",
                "decodeSlackEffectiveMs",
            ]
        ].head(20)
    )


def plot_slacks_with_spatial_and_bitrate(df: pd.DataFrame, out_path: str) -> None:
    x = range(len(df))

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(16, 9),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    # ===== Top plot: slack-related metrics =====
    ax1.plot(
        x,
        df["actualSlackMs"],
        label="actualSlackMs",
        linewidth=1.2,
        alpha=0.65,
        linestyle="-",
    )

    ax1.plot(
        x,
        df["actualSlackEffectiveMs"],
        label="actualSlackEffectiveMs",
        linewidth=2.0,
        alpha=0.95,
        linestyle="--",
    )

    ax1.plot(
        x,
        df["receiveSlackMs"],
        label="receiveSlackMs",
        linewidth=1.8,
        alpha=0.9,
        linestyle="-.",
    )

    ax1.plot(
        x,
        df["decodeSlackNominalMs"],
        label="decodeSlackNominalMs",
        linewidth=2.0,
        alpha=0.9,
        linestyle=":",
    )

    ax1.plot(
        x,
        df["queueResidenceMs"],
        label="queueResidenceMs",
        linewidth=1.8,
        alpha=0.85,
        linestyle="-",
    )

    ax1.plot(
        x,
        df["decodeSlackEffectiveMs"],
        label="decodeSlackEffectiveMs",
        linewidth=2.2,
        alpha=0.95,
        linestyle="--",
        marker="o",
        markersize=2,
        markevery=30,
    )

    ax1.set_ylabel("Milliseconds (ms)")
    ax1.set_title("Slack-related metrics with currentSpatialLayer and availableBitrate")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="best", ncol=2)

    # ===== Bottom plot: layer + bitrate =====
    ax2.step(
        x,
        df["currentSpatialLayer"],
        label="currentSpatialLayer",
        linewidth=2.0,
        where="post",
        color="red",
    )

    ax2.set_xlabel("Frame index")
    ax2.set_ylabel("Spatial Layer")
    ax2.set_yticks([0, 1, 2])
    ax2.set_ylim(-0.2, 2.2)
    ax2.grid(True, alpha=0.3)

    ax3 = ax2.twinx()
    ax3.plot(
        x,
        df["availableBitrateMbps"],
        label="availableBitrateMbps",
        linewidth=1.5,
        alpha=0.8,
        linestyle="-",
        color="blue",
    )
    ax3.set_ylabel("Available Bitrate (Mbps)")

    # layer transition vertical lines
    prev_layer = df["currentSpatialLayer"].shift(1)
    transition_indices = df.index[df["currentSpatialLayer"] != prev_layer].tolist()

    for idx in transition_indices:
        if idx == 0:
            continue
        ax1.axvline(idx, linestyle=":", linewidth=1.0, alpha=0.45)
        ax2.axvline(idx, linestyle=":", linewidth=1.0, alpha=0.45)

    lines2, labels2 = ax2.get_legend_handles_labels()
    lines3, labels3 = ax3.get_legend_handles_labels()
    ax2.legend(lines2 + lines3, labels2 + labels3, loc="best")

    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()

    print(f"[INFO] Saved plot: {out_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot slack-related metrics with currentSpatialLayer and availableBitrateMbps"
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
        out_path = "/home/n2sl/yeon/qos/network/log/frame/plots/slacks_spatial_bitrate_pacing.png"
    else:
        csv_path = "/home/n2sl/yeon/qos/network/log/frame/frame_records.csv"
        out_path = "/home/n2sl/yeon/qos/network/log/frame/plots/slacks_spatial_bitrate.png"

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print(f"[INFO] csv_path: {csv_path}")

    df = load_and_prepare_csv(csv_path)

    print(f"[INFO] loaded rows: {len(df)}")

    print_layer_summary(df)

    plot_slacks_with_spatial_and_bitrate(df, out_path)


if __name__ == "__main__":
    main()