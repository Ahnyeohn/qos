import matplotlib
matplotlib.use("Agg")

import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

NO_CSV = "/home/n2sl/yeon/qos/network/log/video_send_log_no_pacing.csv"
PACED_CSV = "/home/n2sl/yeon/qos/network/log/video_send_log_pacing.csv"
OUT_DIR = "/home/n2sl/yeon/qos/network/log/plots/pacing_compare_improved"

WARMUP_FRAMES = 1000
NUM_MATCHED_SAMPLES = 6          # 비교할 matched frame 수
MIN_PACKET_COUNT = 3             # 너무 작은 frame 제외
MAX_FRAME_TIME_MS = None         # 예: 20 으로 자를 수 있음. None이면 전체 표시


def load_packet_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    numeric_cols = ["send_time_us", "ssrc", "seq", "rtp_timestamp", "marker", "size"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=numeric_cols).copy()

    df["send_time_us"] = df["send_time_us"].astype("int64")
    df["ssrc"] = df["ssrc"].astype("int64")
    df["seq"] = df["seq"].astype("int64")
    df["rtp_timestamp"] = df["rtp_timestamp"].astype("int64")
    df["marker"] = df["marker"].astype("int64")
    df["size"] = df["size"].astype("int64")

    df = df.sort_values(["ssrc", "send_time_us", "seq"]).reset_index(drop=True)

    # 같은 ssrc 내에서 rtp_timestamp가 바뀌면 새 frame
    df["frame_index"] = (
        df.groupby("ssrc")["rtp_timestamp"]
          .transform(lambda s: (s != s.shift()).cumsum() - 1)
    )

    return df


def prepare_frame_packets(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["packet_order_in_frame"] = (
        df.groupby(["ssrc", "frame_index"]).cumcount()
    )

    first_send = (
        df.groupby(["ssrc", "frame_index"])["send_time_us"]
          .transform("min")
    )
    df["time_in_frame_ms"] = (df["send_time_us"] - first_send) / 1000.0

    return df


def get_frame_summary(df: pd.DataFrame) -> pd.DataFrame:
    summary = (
        df.groupby(["ssrc", "frame_index"], as_index=False)
          .agg(
              rtp_timestamp=("rtp_timestamp", "first"),
              packet_count=("seq", "count"),
              first_send_us=("send_time_us", "min"),
              last_send_us=("send_time_us", "max"),
              total_bytes=("size", "sum"),
          )
    )
    summary["spread_ms"] = (summary["last_send_us"] - summary["first_send_us"]) / 1000.0
    return summary


def select_single_ssrc_frames(summary: pd.DataFrame, warmup_frames: int) -> pd.DataFrame:
    ssrc = summary["ssrc"].iloc[0]
    s = summary[summary["ssrc"] == ssrc].sort_values("frame_index").reset_index(drop=True)
    s = s[s["frame_index"] >= warmup_frames].copy()
    s = s[s["packet_count"] >= MIN_PACKET_COUNT].copy()
    return s


def empirical_cdf(values):
    s = pd.Series(values).dropna().sort_values().to_numpy()
    if len(s) == 0:
        return s, s
    y = (pd.Series(range(1, len(s) + 1)) / len(s)).to_numpy()
    return s, y


def plot_spread_cdf(no_summary: pd.DataFrame, paced_summary: pd.DataFrame, out_path: str):
    fig, ax = plt.subplots(figsize=(8, 5))

    x1, y1 = empirical_cdf(no_summary["spread_ms"])
    x2, y2 = empirical_cdf(paced_summary["spread_ms"])

    ax.plot(x1, y1, label="No pacing")
    ax.plot(x2, y2, label="Pacing")

    ax.set_xlabel("Frame packet spread (ms)")
    ax.set_ylabel("CDF")
    ax.set_title("CDF of frame packet spread")
    ax.grid(True)
    ax.legend()

    plt.tight_layout()
    plt.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close()


def plot_spread_vs_bytes(no_summary: pd.DataFrame, paced_summary: pd.DataFrame, out_path: str):
    fig, ax = plt.subplots(figsize=(9, 6))

    ax.scatter(
        no_summary["total_bytes"],
        no_summary["spread_ms"],
        s=10,
        alpha=0.35,
        label="No pacing",
        marker="o"
    )

    ax.scatter(
        paced_summary["total_bytes"],
        paced_summary["spread_ms"],
        s=12,
        alpha=0.35,
        label="Pacing",
        marker="x"
    )

    ax.set_xlabel("Frame size (bytes)")
    ax.set_ylabel("Frame packet spread (ms)")
    ax.set_title("Frame size vs packet spread")
    ax.grid(True)
    ax.legend()

    plt.tight_layout()
    plt.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close()


def match_frames_by_size(no_summary: pd.DataFrame, paced_summary: pd.DataFrame, n_samples: int) -> pd.DataFrame:
    """
    no pacing 쪽 frame 몇 개를 고르고, pacing 쪽에서 total_bytes가 가장 가까운 frame을 매칭.
    """
    no_summary = no_summary.sort_values("frame_index").reset_index(drop=True)
    paced_summary = paced_summary.sort_values("frame_index").reset_index(drop=True)

    if len(no_summary) == 0 or len(paced_summary) == 0:
        raise ValueError("유효한 frame summary가 없습니다.")

    # no pacing에서 균등하게 샘플 선택
    step = max(1, len(no_summary) // n_samples)
    candidate_idx = list(range(0, len(no_summary), step))[:n_samples]

    matched_rows = []
    used_paced = set()

    for idx in candidate_idx:
        no_row = no_summary.iloc[idx]
        target_bytes = no_row["total_bytes"]

        paced_candidates = paced_summary.copy()
        paced_candidates = paced_candidates[~paced_candidates.index.isin(used_paced)].copy()
        if len(paced_candidates) == 0:
            break

        paced_candidates["abs_diff"] = (paced_candidates["total_bytes"] - target_bytes).abs()
        best_idx = paced_candidates["abs_diff"].idxmin()
        pa_row = paced_summary.loc[best_idx]

        used_paced.add(best_idx)

        matched_rows.append({
            "sample_id": len(matched_rows),
            "no_ssrc": int(no_row["ssrc"]),
            "no_frame_index": int(no_row["frame_index"]),
            "no_total_bytes": int(no_row["total_bytes"]),
            "no_packet_count": int(no_row["packet_count"]),
            "no_spread_ms": float(no_row["spread_ms"]),

            "pa_ssrc": int(pa_row["ssrc"]),
            "pa_frame_index": int(pa_row["frame_index"]),
            "pa_total_bytes": int(pa_row["total_bytes"]),
            "pa_packet_count": int(pa_row["packet_count"]),
            "pa_spread_ms": float(pa_row["spread_ms"]),
            "abs_size_diff": int(abs(int(no_row["total_bytes"]) - int(pa_row["total_bytes"]))),
        })

    matched = pd.DataFrame(matched_rows)
    if len(matched) == 0:
        raise ValueError("매칭된 frame이 없습니다.")
    return matched


def plot_matched_frame_samples(no_df, paced_df, matched_df, out_path):
    n = len(matched_df)
    fig, axes = plt.subplots(n, 2, figsize=(12, 3.2 * n), squeeze=False)

    for i, row in matched_df.iterrows():
        no_pkt = no_df[
            (no_df["ssrc"] == row["no_ssrc"]) &
            (no_df["frame_index"] == row["no_frame_index"])
        ].sort_values("send_time_us").copy()

        pa_pkt = paced_df[
            (paced_df["ssrc"] == row["pa_ssrc"]) &
            (paced_df["frame_index"] == row["pa_frame_index"])
        ].sort_values("send_time_us").copy()

        if MAX_FRAME_TIME_MS is not None:
            no_pkt = no_pkt[no_pkt["time_in_frame_ms"] <= MAX_FRAME_TIME_MS].copy()
            pa_pkt = pa_pkt[pa_pkt["time_in_frame_ms"] <= MAX_FRAME_TIME_MS].copy()

        ax1 = axes[i, 0]
        ax2 = axes[i, 1]

        ax1.scatter(
            no_pkt["time_in_frame_ms"],
            no_pkt["packet_order_in_frame"],
            s=28,
            alpha=0.85,
            marker="o"
        )
        ax1.set_title(
            f"No pacing | frame {row['no_frame_index']} | "
            f"bytes={row['no_total_bytes']} | spread={row['no_spread_ms']:.3f} ms"
        )
        ax1.set_xlabel("Time within frame (ms)")
        ax1.set_ylabel("Packet order in frame")
        ax1.grid(True)

        ax2.scatter(
            pa_pkt["time_in_frame_ms"],
            pa_pkt["packet_order_in_frame"],
            s=30,
            alpha=0.85,
            marker="x"
        )
        ax2.set_title(
            f"Pacing | frame {row['pa_frame_index']} | "
            f"bytes={row['pa_total_bytes']} | spread={row['pa_spread_ms']:.3f} ms"
        )
        ax2.set_xlabel("Time within frame (ms)")
        ax2.set_ylabel("Packet order in frame")
        ax2.grid(True)

    plt.tight_layout()
    plt.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close()


def print_basic_stats(no_summary: pd.DataFrame, paced_summary: pd.DataFrame):
    print("\n=== Spread statistics (ms) ===")
    print("[No pacing]")
    print(no_summary["spread_ms"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

    print("\n[Pacing]")
    print(paced_summary["spread_ms"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

    print("\n=== Frame size statistics (bytes) ===")
    print("[No pacing]")
    print(no_summary["total_bytes"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))

    print("\n[Pacing]")
    print(paced_summary["total_bytes"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]))


def main():
    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)

    no_df = prepare_frame_packets(load_packet_csv(NO_CSV))
    paced_df = prepare_frame_packets(load_packet_csv(PACED_CSV))

    no_summary_all = get_frame_summary(no_df)
    paced_summary_all = get_frame_summary(paced_df)

    no_summary = select_single_ssrc_frames(no_summary_all, WARMUP_FRAMES)
    paced_summary = select_single_ssrc_frames(paced_summary_all, WARMUP_FRAMES)

    print_basic_stats(no_summary, paced_summary)

    matched = match_frames_by_size(no_summary, paced_summary, NUM_MATCHED_SAMPLES)

    print("\n=== Matched frame samples ===")
    print(matched.to_string(index=False))

    plot_spread_cdf(
        no_summary,
        paced_summary,
        f"{OUT_DIR}/spread_cdf.png"
    )

    plot_spread_vs_bytes(
        no_summary,
        paced_summary,
        f"{OUT_DIR}/spread_vs_bytes.png"
    )

    plot_matched_frame_samples(
        no_df,
        paced_df,
        matched,
        f"{OUT_DIR}/matched_frame_samples.png"
    )

    matched.to_csv(f"{OUT_DIR}/matched_frame_samples.csv", index=False)

    print(f"\nsaved: {OUT_DIR}/spread_cdf.png")
    print(f"saved: {OUT_DIR}/spread_vs_bytes.png")
    print(f"saved: {OUT_DIR}/matched_frame_samples.png")
    print(f"saved: {OUT_DIR}/matched_frame_samples.csv")


if __name__ == "__main__":
    main()