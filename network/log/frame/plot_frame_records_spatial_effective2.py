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
        "frameBufferInsertTimeMs",
        "frameBufferExtractTimeMs",
        "latestDecodeTimeMs",
        "actualSlackMs",
        "actualSlackEffectiveMs",
        "decodeSlackEffectiveMs",
        "decodeQueueResidenceMs",
        "frameBufferResidenceMs",
        "currentSpatialLayer",
        "availableBitrateBps",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 수정된 정의
    df["preDecodeWaitingMs"] = df["frameBufferInsertTimeMs"] - df["receiveTimeMs"]

    # 새 지표
    df["actualSlackMinusPreDecodeWaitingMs"] = (
        df["actualSlackMs"] - df["preDecodeWaitingMs"]
    )

    # queueResidence 직접 계산
    df["queueResidenceMs"] = (
        df["decodeQueueResidenceMs"] + df["frameBufferResidenceMs"]
    )

    # 새 그래프용 지표 1
    df["frameBufferExtractMinusLatestDecodeMs"] = (
        df["frameBufferExtractTimeMs"] - df["latestDecodeTimeMs"]
    )

    # 새 그래프용 지표 2
    df["latestDecodeDeltaMs"] = df["latestDecodeTimeMs"].diff().fillna(0)

    df["availableBitrateMbps"] = df["availableBitrateBps"] / 1_000_000.0

    df = df.dropna(
        subset=[
            "frameId",
            "preDecodeWaitingMs",
            "actualSlackMs",
            "actualSlackMinusPreDecodeWaitingMs",
            "actualSlackEffectiveMs",
            "decodeSlackEffectiveMs",
            "decodeQueueResidenceMs",
            "frameBufferResidenceMs",
            "queueResidenceMs",
            "frameBufferExtractMinusLatestDecodeMs",
            "latestDecodeDeltaMs",
            "currentSpatialLayer",
            "availableBitrateMbps",
        ]
    ).copy()

    df["currentSpatialLayer"] = df["currentSpatialLayer"].astype(int)
    df = df.sort_values("frameId").reset_index(drop=True)

    return df


def plot_metrics_with_spatial_and_bitrate(df: pd.DataFrame, out_path: str) -> None:
    x = range(len(df))

    fig, (ax1, ax_mid, ax_res, ax_latest, ax2) = plt.subplots(
        5,
        1,
        figsize=(16, 14),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1.8, 1.6, 1.6, 1]},
    )

    # ===== Top plot =====
    ax1.plot(
        x,
        df["decodeSlackEffectiveMs"],
        label="decodeSlackEffectiveMs",
        linewidth=2.0,
        alpha=0.9,
        linestyle="-.",
    )

    ax1.plot(
        x,
        df["queueResidenceMs"],
        label="queueResidenceMs (= decodeQueueResidenceMs + frameBufferResidenceMs)",
        linewidth=2.0,
        alpha=0.9,
        linestyle=":",
    )

    ax1.set_ylabel("Milliseconds (ms)")
    ax1.set_title("Effective Slack / Queue / PreDecodeWaiting / Residences / LatestDecode / SpatialLayer / Bitrate")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="best")

    # ===== Middle plot =====
    ax_mid.plot(
        x,
        df["preDecodeWaitingMs"],
        label="preDecodeWaitingMs",
        linewidth=1.8,
        alpha=0.9,
        linestyle="-",
    )

    ax_mid.plot(
        x,
        df["actualSlackMinusPreDecodeWaitingMs"],
        label="actualSlackMs - preDecodeWaitingMs",
        linewidth=2.0,
        alpha=0.95,
        linestyle="--",
    )

    ax_mid.set_ylabel("Milliseconds (ms)")
    ax_mid.set_title("PreDecodeWaiting and Adjusted Actual Slack")
    ax_mid.grid(True, alpha=0.3)
    ax_mid.legend(loc="best")

    # ===== Residence detail plot =====
    ax_res.plot(
        x,
        df["decodeQueueResidenceMs"],
        label="decodeQueueResidenceMs",
        linewidth=2.0,
        alpha=0.9,
        linestyle="-",
    )

    ax_res.plot(
        x,
        df["frameBufferResidenceMs"],
        label="frameBufferResidenceMs",
        linewidth=2.0,
        alpha=0.9,
        linestyle="--",
    )

    ax_res.set_ylabel("Residence (ms)")
    ax_res.set_title("Decode Queue Residence and Frame Buffer Residence")
    ax_res.grid(True, alpha=0.3)
    ax_res.legend(loc="best")

    # ===== New latestDecode/frameBufferExtract plot =====
    ax_latest.plot(
        x,
        df["frameBufferExtractMinusLatestDecodeMs"],
        label="frameBufferExtractTimeMs - latestDecodeTimeMs",
        linewidth=2.0,
        alpha=0.9,
        linestyle="-",
    )

    # ax_latest.plot(
    #     x,
    #     df["latestDecodeDeltaMs"],
    #     label="latestDecodeTimeMs diff from previous frame",
    #     linewidth=2.0,
    #     alpha=0.9,
    #     linestyle="--",
    # )

    ax_latest.set_ylabel("Milliseconds (ms)")
    ax_latest.set_title("FrameBufferExtract - LatestDecode")
    ax_latest.grid(True, alpha=0.3)
    ax_latest.legend(loc="best")

    # ===== Bottom plot =====
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

    # spatial layer transition vertical lines
    prev_layer = df["currentSpatialLayer"].shift(1)
    transition_indices = df.index[df["currentSpatialLayer"] != prev_layer].tolist()

    for idx in transition_indices:
        if idx == 0:
            continue
        ax1.axvline(idx, linestyle=":", linewidth=1.0, alpha=0.5)
        ax_mid.axvline(idx, linestyle=":", linewidth=1.0, alpha=0.5)
        ax_res.axvline(idx, linestyle=":", linewidth=1.0, alpha=0.5)
        ax_latest.axvline(idx, linestyle=":", linewidth=1.0, alpha=0.5)
        ax2.axvline(idx, linestyle=":", linewidth=1.0, alpha=0.5)

    lines2, labels2 = ax2.get_legend_handles_labels()
    lines3, labels3 = ax3.get_legend_handles_labels()
    ax2.legend(lines2 + lines3, labels2 + labels3, loc="best")

    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()

    print(f"[INFO] Saved plot: {out_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot slack metrics, queue metrics, residence metrics, latestDecode metrics, spatial layer, and bitrate"
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
        out_path = "/home/n2sl/yeon/qos/network/log/frame/plots/effective_metrics_spatial_bitrate_pacing.png"
    else:
        csv_path = "/home/n2sl/yeon/qos/network/log/frame/frame_records.csv"
        out_path = "/home/n2sl/yeon/qos/network/log/frame/plots/effective_metrics_spatial_bitrate.png"

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print(f"[INFO] csv_path: {csv_path}")

    df = load_and_prepare_csv(csv_path)

    print(f"[INFO] loaded rows: {len(df)}")

    plot_metrics_with_spatial_and_bitrate(df, out_path)


if __name__ == "__main__":
    main()