#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
KNN sample-space visualization for frame_records.csv

Generates:
  1) global_knn_feature_map.png
     - PCA projection of normalized KNN sample space
     - color: experiment phase/network group
     - marker: actual spatial layer

  2) slack_colored_knn_feature_map.png
     - same PCA coordinates
     - color: actual decode slack
     - marker: actual spatial layer

Important:
- Only knnTrainingEligible == 1 rows are used.
- Pause rows are automatically excluded.
- By default, only rows where decision action == actual executed action are used,
  so the decision-time feature vector corresponds to the action whose actual
  decode slack became the historical KNN label.
- PCA is fitted on the same normalization scales used by SlackPredictor.
- With --include-action-distance, the legacy action-distance terms are embedded
  into Euclidean coordinates before PCA. Use this mainly when
  ActionConditionedPredictionEnabled=false.
"""

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.colors import TwoSlopeNorm, Normalize


# ============================================================
# Current SlackPredictor::Config normalization scales.
# Keep synchronized with SlackPredictor.hpp.
# ============================================================
RTT_SCALE_MS = 100.0
LOSS_SCALE = 0.05
BANDWIDTH_SCALE_BPS = 5_000_000.0
CONGESTION_SCALE = 1.0
FRAME_SIZE_SCALE_BYTES = 20_000.0
PACING_DELAY_SCALE_MS = 50.0

# Legacy action-distance terms.
SPATIAL_LAYER_MISMATCH_DISTANCE = 1.0
FEC_PROTECTION_SCALE = 128.0
PACING_MISMATCH_DISTANCE = 1.0

FEATURE_COLUMNS = [
    "decisionRttMs",
    "decisionLossRate",
    "decisionAvailableBitrateBps",
    "decisionCongestion",
    "decisionFrameSizeBytes",
    "decisionPacingDelayMs",
]

ACTION_COLUMNS = [
    "decisionSpatialLayer",
    "decisionFecProtectionFactor",
    "decisionPacing",
    "actualSpatialLayer",
    "actualFecProtectionFactor",
    "actualPacing",
]

REQUIRED_COLUMNS = [
    "decisionMode",
    "coldStartPhase",
    "coldStartNetworkProfile",
    "knnEvaluationPhase",
    "knnEvaluationNetworkProfile",
    "knnTrainingEligible",
    "decodeSlackNominalMs",
    *FEATURE_COLUMNS,
    *ACTION_COLUMNS,
]


def parse_args():
    p = argparse.ArgumentParser(
        description="Plot 2D PCA maps of historical KNN training samples."
    )
    p.add_argument("--input", required=True, help="frame_records.csv path")
    p.add_argument(
        "--output-dir",
        default="knn_cluster_plots",
        help="Directory for generated PNG files",
    )
    p.add_argument(
        "--include-action-distance",
        action="store_true",
        help=(
            "Include legacy action-distance terms in the PCA input space. "
            "Useful when ActionConditionedPredictionEnabled=false."
        ),
    )
    p.add_argument(
        "--keep-action-mismatch",
        action="store_true",
        help=(
            "Keep rows where model decision action and actual executed action differ. "
            "Default is to remove them so feature/label correspondence is exact."
        ),
    )
    p.add_argument(
        "--layer",
        type=int,
        choices=[0, 1, 2],
        default=None,
        help="Optional: visualize only one actual spatial layer",
    )
    p.add_argument(
        "--fec-pf",
        type=int,
        choices=[0, 26, 64, 102, 128],
        default=None,
        help="Optional: visualize only one actual FEC protection factor",
    )
    p.add_argument(
        "--pacing",
        type=int,
        choices=[0, 1],
        default=None,
        help="Optional: visualize only actual pacing OFF(0) or ON(1)",
    )
    p.add_argument("--dpi", type=int, default=180, help="Output image DPI")
    return p.parse_args()


def require_columns(df):
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise RuntimeError(
            "Required columns are missing from frame_records.csv:\n  "
            + "\n  ".join(missing)
        )


def numericize(df, columns):
    for c in columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")


def make_experiment_group(row):
    mode = str(row["decisionMode"]).strip().upper()

    if mode == "COLD":
        profile = str(row["coldStartNetworkProfile"]).strip().upper()
        return f"Cold / {profile}"

    if mode == "KNN":
        phase = str(row["knnEvaluationPhase"]).strip().upper()
        if phase == "COLLECT_NORMAL":
            return "KNN / NORMAL"
        if phase == "COLLECT_2MBIT":
            return "KNN / 2MBIT"

        profile = str(row["knnEvaluationNetworkProfile"]).strip().upper()
        return f"KNN / {profile}"

    return f"{mode} / UNKNOWN"


def load_training_samples(args):
    df = pd.read_csv(args.input, low_memory=False)
    require_columns(df)

    numeric_cols = [
        "knnTrainingEligible",
        "decodeSlackNominalMs",
        *FEATURE_COLUMNS,
        *ACTION_COLUMNS,
    ]
    numericize(df, numeric_cols)

    before = len(df)

    # Predictor training samples only. Pause rows have 0 here.
    df = df[df["knnTrainingEligible"] == 1].copy()

    # Need actual Slack label.
    df = df[np.isfinite(df["decodeSlackNominalMs"])].copy()

    # Need finite feature vector.
    finite_feature_mask = np.ones(len(df), dtype=bool)
    for c in FEATURE_COLUMNS:
        finite_feature_mask &= np.isfinite(df[c].to_numpy(dtype=float))
    df = df.loc[finite_feature_mask].copy()

    # Exact historical-sample geometry by default.
    if not args.keep_action_mismatch:
        action_match = (
            (df["decisionSpatialLayer"] == df["actualSpatialLayer"])
            & (
                df["decisionFecProtectionFactor"]
                == df["actualFecProtectionFactor"]
            )
            & (df["decisionPacing"] == df["actualPacing"])
        )
        df = df[action_match].copy()

    if args.layer is not None:
        df = df[df["actualSpatialLayer"] == args.layer].copy()
    if args.fec_pf is not None:
        df = df[df["actualFecProtectionFactor"] == args.fec_pf].copy()
    if args.pacing is not None:
        df = df[df["actualPacing"] == args.pacing].copy()

    df["experimentGroup"] = df.apply(make_experiment_group, axis=1)

    valid_groups = {
        "Cold / NORMAL",
        "Cold / 2MBIT",
        "KNN / NORMAL",
        "KNN / 2MBIT",
    }
    df = df[df["experimentGroup"].isin(valid_groups)].copy()

    if len(df) < 3:
        raise RuntimeError(
            f"Too few valid training rows after filtering: {len(df)}"
        )

    print(f"[INFO] input rows: {before}")
    print(f"[INFO] KNN training rows used: {len(df)}")
    print("[INFO] group counts:")
    print(df["experimentGroup"].value_counts().sort_index().to_string())
    print("[INFO] actual layer counts:")
    print(df["actualSpatialLayer"].value_counts().sort_index().to_string())

    return df


def build_knn_space(df, include_action_distance):
    """
    Base normalized feature space:
      RTT / 100
      Loss / 0.05
      BW / 5e6
      Congestion / 1
      FrameSize / 20000
      PacingDelay / 50

    If include_action_distance=True, append coordinates reproducing the legacy
    action terms used when ActionConditionedPredictionEnabled=false.
    """
    X_feature = np.column_stack(
        [
            df["decisionRttMs"].to_numpy(float) / RTT_SCALE_MS,
            df["decisionLossRate"].to_numpy(float) / LOSS_SCALE,
            df["decisionAvailableBitrateBps"].to_numpy(float)
            / BANDWIDTH_SCALE_BPS,
            df["decisionCongestion"].to_numpy(float) / CONGESTION_SCALE,
            df["decisionFrameSizeBytes"].to_numpy(float)
            / FRAME_SIZE_SCALE_BYTES,
            df["decisionPacingDelayMs"].to_numpy(float)
            / PACING_DELAY_SCALE_MS,
        ]
    )

    names = ["RTT", "Loss", "BW", "Congestion", "FrameSize", "PacingDelay"]

    if not include_action_distance:
        return X_feature, names

    # Any two different spatial layers should have Euclidean distance 1.0.
    # 3-D one-hot scaled by 1/sqrt(2) gives exactly that.
    layer = df["actualSpatialLayer"].to_numpy(int)
    layer_one_hot = np.zeros((len(df), 3), dtype=float)
    valid_layer = (layer >= 0) & (layer <= 2)
    layer_one_hot[np.arange(len(df))[valid_layer], layer[valid_layer]] = (
        SPATIAL_LAYER_MISMATCH_DISTANCE / math.sqrt(2.0)
    )

    fec_coord = (
        df["actualFecProtectionFactor"].to_numpy(float) / FEC_PROTECTION_SCALE
    )[:, None]

    pacing_coord = (
        df["actualPacing"].to_numpy(float) * PACING_MISMATCH_DISTANCE
    )[:, None]

    X = np.column_stack([X_feature, layer_one_hot, fec_coord, pacing_coord])
    names += ["LayerOneHot0", "LayerOneHot1", "LayerOneHot2", "FEC", "Pacing"]
    return X, names


def pca_2d(X):
    """PCA with NumPy SVD; no scikit-learn dependency."""
    mean = np.mean(X, axis=0)
    X_centered = X - mean

    _, singular_values, vt = np.linalg.svd(X_centered, full_matrices=False)
    components = vt[:2]
    coordinates = X_centered @ components.T

    if len(X) > 1:
        eigenvalues = (singular_values ** 2) / (len(X) - 1)
    else:
        eigenvalues = singular_values ** 2

    total = np.sum(eigenvalues)
    explained = eigenvalues / total if total > 0 else np.zeros_like(eigenvalues)
    return coordinates, explained[:2], components


def default_group_colors(groups):
    cycle = plt.rcParams["axes.prop_cycle"].by_key().get("color", [])
    if not cycle:
        cycle = [None] * len(groups)
    return {g: cycle[i % len(cycle)] for i, g in enumerate(groups)}


def plot_global_feature_map(df, xy, explained, output_path, include_action_distance, dpi):
    groups = [
        "Cold / NORMAL",
        "Cold / 2MBIT",
        "KNN / NORMAL",
        "KNN / 2MBIT",
    ]
    layer_markers = {0: "o", 1: "^", 2: "s"}
    group_colors = default_group_colors(groups)

    fig, ax = plt.subplots(figsize=(12, 8))

    for group in groups:
        for layer in [0, 1, 2]:
            mask = (
                (df["experimentGroup"].to_numpy() == group)
                & (df["actualSpatialLayer"].to_numpy(float) == layer)
            )
            if not np.any(mask):
                continue

            ax.scatter(
                xy[mask, 0],
                xy[mask, 1],
                s=13,
                alpha=0.45,
                marker=layer_markers[layer],
                c=group_colors[group],
                edgecolors="none",
            )

    ax.set_xlabel(f"PC1 ({explained[0] * 100:.1f}% variance)")
    ax.set_ylabel(f"PC2 ({explained[1] * 100:.1f}% variance)")

    metric_text = (
        "normalized feature + legacy action distance"
        if include_action_distance
        else "normalized 6-D KNN feature"
    )
    ax.set_title("Global KNN Sample Feature Map\n" f"PCA of {metric_text}")
    ax.grid(alpha=0.2)

    group_handles = []
    for group in groups:
        if not np.any(df["experimentGroup"].to_numpy() == group):
            continue
        group_handles.append(
            Line2D(
                [0], [0], marker="o", linestyle="None", markersize=7,
                markerfacecolor=group_colors[group], markeredgecolor="none",
                label=group,
            )
        )

    legend1 = ax.legend(
        handles=group_handles,
        title="Experiment group",
        loc="upper right",
    )
    ax.add_artist(legend1)

    layer_handles = []
    for layer in [0, 1, 2]:
        if not np.any(df["actualSpatialLayer"].to_numpy(float) == layer):
            continue
        layer_handles.append(
            Line2D(
                [0], [0], marker=layer_markers[layer], linestyle="None",
                markersize=7, markerfacecolor="none", markeredgecolor="black",
                label=f"L{layer}",
            )
        )

    ax.legend(handles=layer_handles, title="Actual spatial layer", loc="lower right")
    ax.text(0.01, 0.01, f"N = {len(df):,}", transform=ax.transAxes,
            ha="left", va="bottom")

    fig.tight_layout()
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {output_path}")


def make_slack_norm(slack):
    finite = slack[np.isfinite(slack)]
    low = float(np.percentile(finite, 2.0))
    high = float(np.percentile(finite, 98.0))

    if low < 0.0 < high:
        return TwoSlopeNorm(vmin=low, vcenter=0.0, vmax=high)

    if math.isclose(low, high):
        low -= 1.0
        high += 1.0

    return Normalize(vmin=low, vmax=high)


def plot_slack_colored_map(df, xy, explained, output_path, include_action_distance, dpi):
    layer_markers = {0: "o", 1: "^", 2: "s"}

    slack = df["decodeSlackNominalMs"].to_numpy(float)

    norm = make_slack_norm(slack)

    # ========================================================
    # Slack이 낮은 sample부터 먼저 그리고,
    # Slack이 높은 sample을 마지막에 그린다.
    #
    # 이유:
    # 같은 PCA 위치에 여러 점이 겹쳐 있을 때
    # positive/high Slack sample이 가장 위에 보이도록 하기 위함.
    # ========================================================
    order = np.argsort(slack)

    xy_sorted = xy[order]
    slack_sorted = slack[order]

    layer_sorted = (
        df["actualSpatialLayer"]
        .to_numpy(float)[order]
    )

    fig, ax = plt.subplots(figsize=(12, 8))

    last_scatter = None

    layers = df["actualSpatialLayer"].to_numpy(float)

    # ============================================================
    # 1단계:
    # 전체 점을 Slack 낮은 순서 -> 높은 순서로 그림.
    #
    # 이렇게 하면 positive Slack이 무조건 위쪽에 위치한다.
    # ============================================================

    order = np.argsort(slack)

    for idx in order:
        layer = int(layers[idx])

        if layer not in layer_markers:
            continue

        last_scatter = ax.scatter(
            xy[idx, 0],
            xy[idx, 1],
            c=[slack[idx]],
            cmap="coolwarm",
            norm=norm,
            s=18,
            alpha=0.65,
            marker=layer_markers[layer],
            edgecolors="none",
        )

    ax.set_xlabel(f"PC1 ({explained[0] * 100:.1f}% variance)")
    ax.set_ylabel(f"PC2 ({explained[1] * 100:.1f}% variance)")

    metric_text = (
        "normalized feature + legacy action distance"
        if include_action_distance
        else "normalized 6-D KNN feature"
    )
    ax.set_title(
        "KNN Feature Map Colored by Actual Decode Slack\n"
        f"PCA of {metric_text}"
    )
    ax.grid(alpha=0.2)

    if last_scatter is not None:
        cbar = fig.colorbar(last_scatter, ax=ax, pad=0.02)
        cbar.set_label("Actual decode slack [ms]")

    layer_handles = []
    for layer in [0, 1, 2]:
        if not np.any(df["actualSpatialLayer"].to_numpy(float) == layer):
            continue
        layer_handles.append(
            Line2D(
                [0], [0], marker=layer_markers[layer], linestyle="None",
                markersize=7, markerfacecolor="none", markeredgecolor="black",
                label=f"L{layer}",
            )
        )

    ax.legend(handles=layer_handles, title="Actual spatial layer", loc="upper right")
    ax.text(0.01, 0.01, f"N = {len(df):,}", transform=ax.transAxes,
            ha="left", va="bottom")

    fig.tight_layout()
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {output_path}")


def print_pca_summary(explained, components, feature_names):
    print(
        "[INFO] PCA explained variance: "
        f"PC1={explained[0] * 100:.2f}% "
        f"PC2={explained[1] * 100:.2f}% "
        f"sum={(explained[0] + explained[1]) * 100:.2f}%"
    )

    loading_df = pd.DataFrame(
        {
            "feature": feature_names,
            "PC1_loading": components[0],
            "PC2_loading": components[1],
        }
    )
    loading_df["PC1_abs"] = np.abs(loading_df["PC1_loading"])
    loading_df["PC2_abs"] = np.abs(loading_df["PC2_loading"])

    print("\n[INFO] strongest PC1 loadings:")
    print(
        loading_df.sort_values("PC1_abs", ascending=False)[
            ["feature", "PC1_loading"]
        ].head(6).to_string(index=False)
    )

    print("\n[INFO] strongest PC2 loadings:")
    print(
        loading_df.sort_values("PC2_abs", ascending=False)[
            ["feature", "PC2_loading"]
        ].head(6).to_string(index=False)
    )


def main():
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_training_samples(args)
    X, feature_names = build_knn_space(df, args.include_action_distance)
    xy, explained, components = pca_2d(X)

    print_pca_summary(explained, components, feature_names)

    plot_global_feature_map(
        df,
        xy,
        explained,
        output_dir / "global_knn_feature_map.png",
        args.include_action_distance,
        args.dpi,
    )

    plot_slack_colored_map(
        df,
        xy,
        explained,
        output_dir / "slack_colored_knn_feature_map.png",
        args.include_action_distance,
        args.dpi,
    )


if __name__ == "__main__":
    main()
