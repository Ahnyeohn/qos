import os
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


INVALID_BIG_THRESHOLD = 1e18
DEFAULT_LATE_THRESHOLD_MS = -5.0

OUTCOME_NORMAL = "NORMAL"
OUTCOME_LATE = "LATE"
OUTCOME_DROP = "DROP"


def to_numeric_clean(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    s = s.mask(np.isinf(s), np.nan)
    s = s.mask(s.abs() > INVALID_BIG_THRESHOLD, np.nan)
    return s


def first_existing_column(df: pd.DataFrame, candidates, required=True):
    """Return the first column name that exists among candidates."""
    for col in candidates:
        if col in df.columns:
            return col

    if required:
        raise ValueError(
            "Missing required column. Expected one of: " + ", ".join(candidates)
        )

    return None


def classify_dropped_frame(df: pd.DataFrame) -> pd.Series:
    """
    dropped frame 판정.

    정상 decode된 frame이라면 최소한 아래 단계들이 있어야 함.
      - frameBufferInsertTimeMs
      - frameBufferExtractTimeMs
      - decodeQueueInsertTimeMs
      - decodeQueueExtractTimeMs
      - decodeStartMs
      - decodeFinishMs

    이 중 핵심 단계가 0/NaN이면 dropped로 본다.
    """
    required_pipeline_cols = [
        "frameBufferInsertTimeMs",
        "frameBufferExtractTimeMs",
        "decodeQueueInsertTimeMs",
        "decodeQueueExtractTimeMs",
        "decodeStartMs",
        "decodeFinishMs",
    ]

    dropped = pd.Series(False, index=df.index)

    for col in required_pipeline_cols:
        if col in df.columns:
            dropped = dropped | df[col].isna() | (df[col] <= 0)

    return dropped


def classify_frame_class(df: pd.DataFrame, late_threshold_ms: float) -> pd.Series:
    """
    SAFE_NORMAL:
        isDropped == False and max_wait > late_threshold_ms

    LATE_NORMAL:
        isDropped == False and max_wait <= late_threshold_ms

    DROPPED:
        isDropped == True
    """
    frame_class = pd.Series(CLASS_SAFE_NORMAL, index=df.index, dtype="object")

    dropped_mask = df["isDropped"] == True
    late_normal_mask = (
        (df["isDropped"] == False)
        & (df["max_wait"] <= late_threshold_ms)
    )

    frame_class.loc[late_normal_mask] = CLASS_LATE_NORMAL
    frame_class.loc[dropped_mask] = CLASS_DROPPED

    return frame_class


def load_and_prepare_csv(csv_path: str, late_threshold_ms: float) -> pd.DataFrame:
    df = pd.read_csv(csv_path, skipinitialspace=True)
    df.columns = df.columns.str.strip()

    # ============================================================
    # 2026-09-03 직전 CSV writer의 header comma 누락 호환.
    #
    # 잘못된 header:
    #   decodeSlackEffectiveMsactualDeadlineMiss,frameOutcome,<unnamed>
    # 실제 row 값:
    #   decodeSlackEffectiveMs,actualDeadlineMiss,frameOutcome
    #
    # writer를 수정한 새 CSV에서는 이 블록이 아무 일도 하지 않는다.
    # ============================================================
    malformed_col = "decodeSlackEffectiveMsactualDeadlineMiss"
    if malformed_col in df.columns:
        unnamed_cols = [c for c in df.columns if str(c).startswith("Unnamed:")]
        if "frameOutcome" in df.columns and unnamed_cols:
            actual_deadline_values = df["frameOutcome"].copy()
            outcome_values = df[unnamed_cols[0]].copy()

            df = df.rename(columns={malformed_col: "decodeSlackEffectiveMs"})
            df["actualDeadlineMiss"] = actual_deadline_values
            df["frameOutcome"] = outcome_values
            df = df.drop(columns=unnamed_cols[0])

            print(
                "[WARN] Repaired legacy malformed CSV header: "
                "decodeSlackEffectiveMs / actualDeadlineMiss / frameOutcome"
            )

    # ============================================================
    # 새 CSV schema에서 실제 전송 시점의 bitrate column은 send* 이름을 사용한다.
    # 이전 CSV도 사용할 수 있도록 legacy 이름을 fallback으로 지원한다.
    # ============================================================
    available_bitrate_col = first_existing_column(
        df,
        ["sendAvailableBitrateBps", "availableBitrateBps"],
    )
    gcc_bitrate_col = first_existing_column(
        df,
        ["sendGccAvailableBitrateBps", "gccAvailableBitrateBps"],
    )
    camel_bitrate_col = first_existing_column(
        df,
        ["sendCamelAvailableBitrateBps", "camelAvailableBitrateBps"],
    )

    # KNN decision / actual action columns.
    decision_mode_col = first_existing_column(df, ["decisionMode"])
    decision_layer_col = first_existing_column(df, ["decisionSpatialLayer"])
    decision_pacing_col = first_existing_column(df, ["decisionPacing"])
    decision_fec_col = first_existing_column(df, ["decisionFecRedundancyPercent"],)

    # ============================================================
    # Prediction columns.
    # 새 이름을 우선 사용하고 legacy 이름을 fallback으로 둔다.
    # ============================================================
    predicted_decode_slack_col = first_existing_column(
        df,
        ["decisionPredictedDecodeSlackMs", "decisionPredictedSlackMs"],
    )
    predicted_deadline_miss_col = first_existing_column(
        df,
        ["decisionPredictedDeadlineMissProbability"],
        required=False,
    )
    prediction_error_col = first_existing_column(
        df,
        ["predictionErrorMs"],
    )

    actual_layer_col = first_existing_column(
        df,
        ["actualSpatialLayer", "currentSpatialLayer"],
    )
    actual_pacing_col = first_existing_column(df, ["actualPacing"])
    actual_fec_col = first_existing_column(
        df,
        ["actualFecRedundancyPercent", "fecRedundancyPercent"],
    )

    # ============================================================
    # SFU가 직접 판정해서 CSV에 기록한 실제 outcome.
    # 새 CSV에서는 반드시 이 값을 분석 기준으로 사용한다.
    # ============================================================
    actual_deadline_miss_col = first_existing_column(
        df,
        ["actualDeadlineMiss"],
        required=False,
    )
    frame_outcome_col = first_existing_column(
        df,
        ["frameOutcome"],
        required=False,
    )

    required_numeric_cols = [
        "frameId",
        "receiveTimeMs",
        "render_time",
        "frameBufferInsertTimeMs",
        "frameBufferExtractTimeMs",
        "decodeSlackNominalMs",
        "currentSpatialLayer",
        "decodeStartMs",
        "decodeFinishMs",
        "max_wait",
        available_bitrate_col,
        gcc_bitrate_col,
        camel_bitrate_col,
        decision_layer_col,
        decision_pacing_col,
        decision_fec_col,
        predicted_decode_slack_col,
        prediction_error_col,
        actual_layer_col,
        actual_pacing_col,
        actual_fec_col,
    ]

    if predicted_deadline_miss_col is not None:
        required_numeric_cols.append(predicted_deadline_miss_col)

    if actual_deadline_miss_col is not None:
        required_numeric_cols.append(actual_deadline_miss_col)

    for col in dict.fromkeys(required_numeric_cols):
        df[col] = to_numeric_clean(df[col])

    # ============================================================
    # 기존 Slack 관련 계산은 그대로 유지.
    # ============================================================
    df["renderMinusReceiveMs"] = np.nan

    valid_render_receive = (
        df["render_time"].notna()
        & (df["render_time"] > 0)
        & df["receiveTimeMs"].notna()
        & (df["receiveTimeMs"] > 0)
    )

    df.loc[valid_render_receive, "renderMinusReceiveMs"] = (
        df.loc[valid_render_receive, "render_time"]
        - df.loc[valid_render_receive, "receiveTimeMs"]
    )

    # preDecodeWaitingMs = frameBufferInsertTimeMs - receiveTimeMs
    df["preDecodeWaitingMs"] = np.nan

    valid_receive = (
        df["receiveTimeMs"].notna()
        & (df["receiveTimeMs"] > 0)
    )

    valid_fb_insert = (
        df["frameBufferInsertTimeMs"].notna()
        & (df["frameBufferInsertTimeMs"] > 0)
    )

    valid_predecode_mask = valid_receive & valid_fb_insert

    df.loc[valid_predecode_mask, "preDecodeWaitingMs"] = (
        df.loc[valid_predecode_mask, "frameBufferInsertTimeMs"]
        - df.loc[valid_predecode_mask, "receiveTimeMs"]
    )

    no_frame_buffer_insert_mask = valid_receive & (~valid_fb_insert)
    df.loc[no_frame_buffer_insert_mask, "preDecodeWaitingMs"] = 0.0
    df.loc[df["preDecodeWaitingMs"] < 0, "preDecodeWaitingMs"] = 0.0

    # bitrate
    df["availableBitrateMbps"] = df[available_bitrate_col] / 1_000_000.0
    df["gccAvailableBitrateMbps"] = df[gcc_bitrate_col] / 1_000_000.0
    df["camelAvailableBitrateMbps"] = df[camel_bitrate_col] / 1_000_000.0

    # ============================================================
    # Actual outcome.
    # 새 CSV에서는 SFU 판정 결과(frameOutcome / actualDeadlineMiss)를 그대로 사용.
    # 이전 CSV만 legacy 재판정을 fallback으로 사용한다.
    # ============================================================
    if frame_outcome_col is not None:
        outcome = df[frame_outcome_col].astype("string").str.strip().str.upper()
        outcome = outcome.replace(
            {
                "SAFE_NORMAL": OUTCOME_NORMAL,
                "LATE_NORMAL": OUTCOME_LATE,
                "DROPPED": OUTCOME_DROP,
                "PRE_DECODE_DROP": OUTCOME_DROP,
            }
        )
        df["frameOutcomePlot"] = outcome
        df["isDropped"] = df["frameOutcomePlot"].eq(OUTCOME_DROP).fillna(False)
    else:
        df["isDropped"] = classify_dropped_frame(df)
        legacy_class = classify_frame_class(df, late_threshold_ms)
        df["frameOutcomePlot"] = legacy_class.replace(
            {
                "SAFE_NORMAL": OUTCOME_NORMAL,
                "LATE_NORMAL": OUTCOME_LATE,
                "DROPPED": OUTCOME_DROP,
            }
        )

    if actual_deadline_miss_col is not None:
        df["actualDeadlineMissPlot"] = df[actual_deadline_miss_col]
    else:
        df["actualDeadlineMissPlot"] = (
            df["frameOutcomePlot"].isin([OUTCOME_LATE, OUTCOME_DROP]).astype(float)
        )

    df["frameOutcomePlot"] = df["frameOutcomePlot"].fillna("UNKNOWN")

    # dropped frame에서도 그래프에 유지하되 frameId는 반드시 있어야 함.
    df = df.dropna(subset=["frameId"]).copy()

    df["currentSpatialLayer"] = pd.to_numeric(
        df["currentSpatialLayer"],
        errors="coerce",
    ).fillna(-1).astype(int)

    # ============================================================
    # Plot 전용 canonical column.
    # ============================================================
    df["decisionModePlot"] = df[decision_mode_col].astype("string")
    df["decisionSpatialLayerPlot"] = df[decision_layer_col]
    df["decisionPacingPlot"] = df[decision_pacing_col]
    df["decisionFecPercentPlot"] = df[decision_fec_col]

    df["predictedDecodeSlackMsPlot"] = df[predicted_decode_slack_col]
    df["predictionErrorMsPlot"] = df[prediction_error_col]

    if predicted_deadline_miss_col is not None:
        df["predictedDeadlineMissProbabilityPlot"] = df[predicted_deadline_miss_col]
    else:
        df["predictedDeadlineMissProbabilityPlot"] = np.nan

    df["actualSpatialLayerPlot"] = df[actual_layer_col]
    df["actualPacingPlot"] = df[actual_pacing_col]
    df["actualFecPercentPlot"] = df[actual_fec_col]

    df = df.sort_values("frameId").reset_index(drop=True)
    return df


def add_late_drop_circles(
    ax,
    x,
    df: pd.DataFrame,
    y_col: str,
    late_label: str = "LATE",
    drop_label: str = "DROP",
) -> None:
    """Slack 그래프 위에 SFU 판정 LATE / DROP frame만 circle로 표시."""
    valid = df[y_col].notna()

    late_mask = valid & (df["frameOutcomePlot"] == OUTCOME_LATE)
    drop_mask = valid & (df["frameOutcomePlot"] == OUTCOME_DROP)

    if late_mask.sum() > 0:
        ax.scatter(
            np.asarray(x)[late_mask],
            df.loc[late_mask, y_col],
            facecolors="none",
            edgecolors="tab:orange",
            marker="o",
            s=75,
            linewidths=1.9,
            label=late_label,
            zorder=8,
        )

    if drop_mask.sum() > 0:
        ax.scatter(
            np.asarray(x)[drop_mask],
            df.loc[drop_mask, y_col],
            facecolors="none",
            edgecolors="tab:red",
            marker="o",
            s=90,
            linewidths=2.1,
            label=drop_label,
            zorder=9,
        )


def print_summary(df: pd.DataFrame) -> None:
    print(f"\n[INFO] loaded rows: {len(df)}")

    print("\n[INFO] SFU frame outcome counts:")
    print(
        df["frameOutcomePlot"].value_counts().reindex(
            [OUTCOME_NORMAL, OUTCOME_LATE, OUTCOME_DROP, "UNKNOWN"],
            fill_value=0,
        )
    )

    print("\n[INFO] actual deadline miss summary:")
    valid_actual = df["actualDeadlineMissPlot"].dropna()
    if len(valid_actual) > 0:
        print(f"count     : {len(valid_actual)}")
        print(f"miss count: {int((valid_actual > 0.5).sum())}")
        print(f"miss rate : {(valid_actual > 0.5).mean():.6f}")
    else:
        print("no valid actualDeadlineMiss rows")

    print("\n[INFO] decision mode counts:")
    print(df["decisionModePlot"].value_counts(dropna=False))

    print("\n[INFO] actual deadline miss rate by decision mode:")
    miss_by_mode = (
        df.dropna(subset=["actualDeadlineMissPlot"])
        .groupby("decisionModePlot", dropna=False)["actualDeadlineMissPlot"]
        .agg(["count", "mean"])
        .rename(columns={"mean": "actualMissRate"})
    )
    print(miss_by_mode)

    knn_mask = df["decisionModePlot"].eq("KNN").fillna(False)

    print("\n[INFO] KNN predicted decode Slack summary:")
    print(df.loc[knn_mask, "predictedDecodeSlackMsPlot"].describe())

    print("\n[INFO] KNN predicted deadline miss probability summary:")
    print(df.loc[knn_mask, "predictedDeadlineMissProbabilityPlot"].describe())

    print("\n[INFO] prediction error summary (only rows where error exists):")
    print(df["predictionErrorMsPlot"].dropna().describe())

    calibration_df = df.loc[
        knn_mask
        & df["predictedDeadlineMissProbabilityPlot"].notna()
        & df["actualDeadlineMissPlot"].notna()
    ].copy()

    if not calibration_df.empty:
        calibration_df["missProbLevel"] = calibration_df[
            "predictedDeadlineMissProbabilityPlot"
        ].round(6)

        grouped = calibration_df.groupby("missProbLevel", sort=True)
        calibration = grouped["actualDeadlineMissPlot"].agg(
            frameCount="count",
            actualMissRate="mean",
        )

        outcome_counts = pd.crosstab(
            calibration_df["missProbLevel"],
            calibration_df["frameOutcomePlot"],
        ).reindex(
            columns=[OUTCOME_NORMAL, OUTCOME_LATE, OUTCOME_DROP],
            fill_value=0,
        )

        calibration = calibration.join(outcome_counts, how="left")
        calibration.insert(0, "predictedMissProbability", calibration.index)

        print("\n[INFO] KNN deadline miss probability calibration table:")
        print(calibration.to_string(index=False))

    print("\n[INFO] KNN decision layer counts:")
    print(df.loc[knn_mask, "decisionSpatialLayerPlot"].value_counts(dropna=False).sort_index())

    print("\n[INFO] KNN decision pacing counts:")
    print(df.loc[knn_mask, "decisionPacingPlot"].value_counts(dropna=False).sort_index())

    print("\n[INFO] KNN decision FEC redundancy counts:")
    print(df.loc[knn_mask, "decisionFecPercentPlot"].value_counts(dropna=False).sort_index())

    print("\n[INFO] actual layer counts:")
    print(df["actualSpatialLayerPlot"].value_counts(dropna=False).sort_index())

    print("\n[INFO] actual pacing counts:")
    print(df["actualPacingPlot"].value_counts(dropna=False).sort_index())

    print("\n[INFO] actual FEC redundancy counts:")
    print(df["actualFecPercentPlot"].value_counts(dropna=False).sort_index())

    comparable_layer = (
        knn_mask
        & df["decisionSpatialLayerPlot"].notna()
        & df["actualSpatialLayerPlot"].notna()
    )
    if comparable_layer.any():
        layer_mismatch = (
            df.loc[comparable_layer, "decisionSpatialLayerPlot"]
            != df.loc[comparable_layer, "actualSpatialLayerPlot"]
        )
        print("\n[INFO] KNN decision/actual layer mismatch:")
        print(f"comparable frames: {int(comparable_layer.sum())}")
        print(f"mismatch frames  : {int(layer_mismatch.sum())}")
        print(f"mismatch rate    : {layer_mismatch.mean():.6f}")


def plot_action_panel(
    ax,
    x,
    layer,
    pacing,
    fec_percent,
    title: str,
    layer_label: str,
    pacing_label: str,
    fec_label: str,
    show_fec: bool = True,
):
    """
    Layer / Pacing / FEC를 한 칸에 표시.

    left y-axis:
      Pacing OFF -> -1.0
      Pacing ON  -> -0.5
      Layer L0   ->  0
      Layer L1   ->  1
      Layer L2   ->  2

    right y-axis:
      FEC redundancy percent
    """
    layer = pd.to_numeric(layer, errors="coerce")
    pacing = pd.to_numeric(pacing, errors="coerce")
    fec_percent = pd.to_numeric(fec_percent, errors="coerce")

    # Layer는 원래 0/1/2 위치에 표시.
    ax.step(
        x,
        layer,
        where="post",
        linewidth=2.0,
        label=layer_label,
    )

    # Pacing은 layer와 겹치지 않도록 아래쪽 전용 위치로 mapping.
    pacing_y = pacing.map({0.0: -1.0, 1.0: -0.5})

    ax.step(
        x,
        pacing_y,
        where="post",
        linewidth=1.8,
        linestyle="--",
        label=pacing_label,
    )

    ax.set_yticks([-1.0, -0.5, 0.0, 1.0, 2.0])
    ax.set_yticklabels(["Pacing OFF", "Pacing ON", "L0", "L1", "L2"])
    ax.set_ylim(-1.2, 2.2)
    ax.set_ylabel("Layer / Pacing")
    ax.grid(True, alpha=0.3)
    ax.set_title(title)

    # ============================================================
    # FEC는 필요한 panel에서만 표시.
    # ============================================================
    if show_fec:
        ax_fec = ax.twinx()

        ax_fec.step(
            x,
            fec_percent,
            where="post",
            linewidth=1.8,
            linestyle=":",
            label=fec_label,
        )

        ax_fec.set_ylabel("FEC redundancy (%)")

        fec_values = np.sort(
            pd.Series(fec_percent).dropna().unique()
        )

        if 0 < len(fec_values) <= 10:
            ax_fec.set_yticks(fec_values)

        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax_fec.get_legend_handles_labels()

        ax.legend(
            lines1 + lines2,
            labels1 + labels2,
            loc="best",
        )

        return ax_fec

    # FEC를 표시하지 않는 경우.
    ax.legend(loc="best")

    return None

def plot_metrics(
    df: pd.DataFrame,
    out_path: str,
    late_threshold_ms: float,
) -> None:
    x = np.arange(len(df))

    # ============================================================
    # 최종 8개 칸:
    # 1) renderMinusReceiveMs
    # 2) decodeSlackNominalMs
    # 3) preDecodeWaitingMs
    # 4) KNN predicted decode Slack + predictionError
    # 5) KNN predicted deadline miss probability + actual outcome
    # 6) Spatial Layer + Available Bitrate
    # 7) KNN Decision Action (L/P/F)
    # 8) Actual Executed Action (L/P/F)
    # ============================================================
    fig, (
        ax_effective,
        ax_nominal,
        ax_predecode,
        ax_prediction,
        ax_deadline_miss,
        ax_layer,
        ax_knn_action,
        ax_actual_action,
    ) = plt.subplots(
        8,
        1,
        figsize=(17, 24),
        sharex=True,
        gridspec_kw={
            "height_ratios": [2.1, 2.1, 1.7, 2.1, 2.0, 1.5, 1.7, 1.7]
        },
    )

    ax_effective.plot(
        x,
        df["renderMinusReceiveMs"],
        label="renderMinusReceiveMs (= render_time - receiveTimeMs)",
        linewidth=2.0,
        alpha=0.9,
        linestyle="-.",
    )
    add_late_drop_circles(ax_effective, x, df, "renderMinusReceiveMs")
    ax_effective.axhline(0, color="black", linewidth=1.0, alpha=0.45)
    ax_effective.set_ylabel("Milliseconds (ms)")
    ax_effective.set_title("renderMinusReceiveMs (SFU LATE / DROP frames circled)")
    ax_effective.grid(True, alpha=0.3)
    ax_effective.legend(loc="best")

    ax_nominal.plot(
        x,
        df["decodeSlackNominalMs"],
        label="decodeSlackNominalMs",
        linewidth=2.0,
        alpha=0.9,
    )
    add_late_drop_circles(ax_nominal, x, df, "decodeSlackNominalMs")
    ax_nominal.axhline(0, color="black", linewidth=1.0, alpha=0.45)
    ax_nominal.set_ylabel("Milliseconds (ms)")
    ax_nominal.set_title("decodeSlackNominalMs (SFU LATE / DROP frames circled)")
    ax_nominal.grid(True, alpha=0.3)
    ax_nominal.legend(loc="best")

    ax_predecode.plot(
        x,
        df["preDecodeWaitingMs"],
        label="preDecodeWaitingMs (= frameBufferInsertTimeMs - receiveTimeMs)",
        linewidth=2.0,
        alpha=0.9,
    )
    add_late_drop_circles(ax_predecode, x, df, "preDecodeWaitingMs")
    ax_predecode.axhline(0, color="black", linewidth=1.0, alpha=0.45)
    ax_predecode.set_ylabel("Milliseconds (ms)")
    ax_predecode.set_title("preDecodeWaitingMs (SFU LATE / DROP frames circled)")
    ax_predecode.grid(True, alpha=0.3)
    ax_predecode.legend(loc="best")

    knn_mask = df["decisionModePlot"].eq("KNN").fillna(False)

    predicted_decode_slack = df["predictedDecodeSlackMsPlot"].where(knn_mask)
    prediction_error = df["predictionErrorMsPlot"].where(knn_mask)

    # ax_prediction.plot(
    #     x,
    #     predicted_decode_slack,
    #     label="decisionPredictedDecodeSlackMs (KNN)",
    #     linewidth=2.0,
    #     alpha=0.9,
    # )

    error_mask = prediction_error.notna()
    if error_mask.any():
        ax_prediction.scatter(
            x[error_mask],
            prediction_error.loc[error_mask],
            label="predictionErrorMs (= decodeSlackNominal - predictedDecodeSlack)",
            s=24,
            alpha=0.9,
        )

    ax_prediction.axhline(0, color="black", linewidth=1.0, alpha=0.45)
    ax_prediction.set_ylabel("Milliseconds (ms)")
    ax_prediction.set_title("KNN Predicted Decode Slack and Prediction Error")
    ax_prediction.grid(True, alpha=0.3)
    ax_prediction.legend(loc="best")

    predicted_miss = df["predictedDeadlineMissProbabilityPlot"].where(knn_mask)
    actual_miss = df["actualDeadlineMissPlot"].where(knn_mask)

    ax_deadline_miss.plot(
        x,
        predicted_miss,
        label="decisionPredictedDeadlineMissProbability",
        linewidth=2.0,
        alpha=0.9,
    )
    ax_deadline_miss.step(
        x,
        actual_miss,
        where="post",
        label="actualDeadlineMiss (SFU)",
        linewidth=1.2,
        alpha=0.55,
    )

    late_mask = knn_mask & df["frameOutcomePlot"].eq(OUTCOME_LATE)
    drop_mask = knn_mask & df["frameOutcomePlot"].eq(OUTCOME_DROP)

    if late_mask.any():
        ax_deadline_miss.scatter(
            x[late_mask],
            np.full(int(late_mask.sum()), 1.02),
            facecolors="none",
            marker="o",
            s=42,
            linewidths=1.5,
            label="actual LATE",
            zorder=8,
        )

    if drop_mask.any():
        ax_deadline_miss.scatter(
            x[drop_mask],
            np.full(int(drop_mask.sum()), 0.96),
            marker="x",
            s=42,
            linewidths=1.5,
            label="actual DROP",
            zorder=9,
        )

    ax_deadline_miss.set_ylim(-0.05, 1.10)
    ax_deadline_miss.set_yticks(np.arange(0.0, 1.01, 0.2))
    ax_deadline_miss.set_ylabel("Probability / Miss")
    ax_deadline_miss.set_title("KNN Deadline Miss Probability vs Actual SFU Outcome")
    ax_deadline_miss.grid(True, alpha=0.3)
    ax_deadline_miss.legend(loc="best")

    ax_layer.step(
        x,
        df["currentSpatialLayer"],
        label="currentSpatialLayer",
        linewidth=2.0,
        where="post",
    )
    ax_layer.set_ylabel("Spatial Layer")
    ax_layer.set_yticks([-1, 0, 1, 2])
    ax_layer.set_ylim(-1.2, 2.2)
    ax_layer.grid(True, alpha=0.3)

    ax_bitrate = ax_layer.twinx()
    ax_bitrate.plot(x, df["availableBitrateMbps"], label="selected available bitrate", linewidth=1.8, alpha=0.9, linestyle="--")
    ax_bitrate.plot(x, df["gccAvailableBitrateMbps"], label="GCC bitrate", linewidth=1.4, alpha=0.8, linestyle="-.")
    ax_bitrate.plot(x, df["camelAvailableBitrateMbps"], label="Camel bitrate", linewidth=1.8, alpha=0.9, linestyle=":")
    ax_bitrate.set_ylabel("Available Bitrate (Mbps)")
    lines1, labels1 = ax_layer.get_legend_handles_labels()
    lines2, labels2 = ax_bitrate.get_legend_handles_labels()
    ax_layer.legend(lines1 + lines2, labels1 + labels2, loc="best")
    ax_layer.set_title("Current Spatial Layer and Available Bitrate")

    decision_layer = df["decisionSpatialLayerPlot"].where(knn_mask)
    decision_pacing = df["decisionPacingPlot"].where(knn_mask)
    decision_fec = df["decisionFecPercentPlot"].where(knn_mask)
    
    plot_action_panel(
        ax=ax_knn_action,
        x=x,
        layer=decision_layer,
        pacing=decision_pacing,
        fec_percent=decision_fec,
        title="KNN Decision Action (Layer / Pacing)",
        layer_label="decisionSpatialLayer",
        pacing_label="decisionPacing",
        fec_label="decisionFecRedundancyPercent",
        show_fec=False,
    )
    plot_action_panel(
        ax_actual_action,
        x,
        df["actualSpatialLayerPlot"],
        df["actualPacingPlot"],
        df["actualFecPercentPlot"],
        "Actual Executed Action (Layer / Pacing / FEC)",
        "actualSpatialLayer",
        "actualPacing",
        "actualFecRedundancyPercent",
    )
    ax_actual_action.set_xlabel("Frame index")

    prev_layer = df["currentSpatialLayer"].shift(1)
    transition_indices = df.index[df["currentSpatialLayer"] != prev_layer].tolist()

    transition_axes = [
        ax_effective,
        ax_nominal,
        ax_predecode,
        ax_prediction,
        ax_deadline_miss,
        ax_layer,
        ax_knn_action,
        ax_actual_action,
    ]

    for idx in transition_indices:
        if idx == 0:
            continue
        for ax in transition_axes:
            ax.axvline(idx, linestyle=":", linewidth=1.0, alpha=0.35)

    knn_indices = np.flatnonzero(knn_mask.to_numpy())
    if len(knn_indices) > 0:
        first_knn_idx = int(knn_indices[0])
        for ax in transition_axes:
            ax.axvline(first_knn_idx, linestyle="--", linewidth=1.4, alpha=0.7)
        print(f"[INFO] first KNN frame index: {first_knn_idx}")

    ax_effective.text(
        0.01,
        0.03,
        "Outcome source: SFU frameOutcome / actualDeadlineMiss\n"
        f"Legacy fallback LATE threshold: max_wait <= {late_threshold_ms} ms",
        transform=ax_effective.transAxes,
        fontsize=9,
        family="monospace",
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": "white",
            "edgecolor": "gray",
            "alpha": 0.8,
        },
    )

    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"[INFO] Saved plot: {out_path}")


def plot_deadline_miss_calibration(df: pd.DataFrame, out_path: str) -> None:
    """Predicted miss probability와 실제 miss rate의 calibration을 확인."""
    knn_mask = df["decisionModePlot"].eq("KNN").fillna(False)
    calib = df.loc[
        knn_mask
        & df["predictedDeadlineMissProbabilityPlot"].notna()
        & df["actualDeadlineMissPlot"].notna()
    ].copy()

    if calib.empty:
        print("[WARN] No valid KNN rows for deadline miss calibration plot.")
        return

    calib["missProbLevel"] = calib["predictedDeadlineMissProbabilityPlot"].round(6)
    grouped = (
        calib.groupby("missProbLevel", sort=True)["actualDeadlineMissPlot"]
        .agg(frameCount="count", actualMissRate="mean")
        .reset_index()
    )

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot([0.0, 1.0], [0.0, 1.0], linestyle="--", linewidth=1.4, alpha=0.7, label="ideal calibration")
    ax.plot(grouped["missProbLevel"], grouped["actualMissRate"], marker="o", linewidth=2.0, label="observed actual miss rate")
    ax.set_xlim(-0.03, 1.03)
    ax.set_ylim(-0.03, 1.03)
    ax.set_xticks(np.arange(0.0, 1.01, 0.2))
    ax.set_yticks(np.arange(0.0, 1.01, 0.2))
    ax.set_xlabel("Predicted deadline miss probability")
    ax.set_ylabel("Observed actual deadline miss rate")
    ax.set_title("Deadline Miss Probability Calibration")
    ax.grid(True, alpha=0.3)

    ax_count = ax.twinx()
    ax_count.bar(grouped["missProbLevel"], grouped["frameCount"], width=0.07, alpha=0.18, label="frame count")
    ax_count.set_ylabel("Frame count")

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax_count.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="best")

    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"[INFO] Saved deadline miss calibration plot: {out_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Plot Slack metrics, KNN predicted decode Slack / prediction error, "
            "deadline miss probability / actual SFU outcome, current layer / bitrate, "
            "KNN decision action, and actual executed action. "
            "Packet loss, queue residence, and ACE-specific panels are intentionally omitted."
        )
    )

    parser.add_argument(
        "-pacing",
        type=int,
        default=0,
        help="Use pacing CSV if set to 1. Default: 0",
    )

    parser.add_argument(
        "--late-threshold-ms",
        type=float,
        default=DEFAULT_LATE_THRESHOLD_MS,
        help="Threshold for LATE_NORMAL classification. Default: -5 ms",
    )

    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Optional custom input CSV path",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional custom output plot path",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    if args.input is not None:
        csv_path = args.input
    else:
        if args.pacing == 1:
            csv_path = "csv/frame_records_pacing.csv"
        else:
            csv_path = "csv/frame_records.csv"

    if args.output is not None:
        out_path = args.output
    else:
        if args.pacing == 1:
            out_path = "plots/knn_slack_actions_pacing.png"
        else:
            out_path = "plots/knn_slack_actions.png"

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    print(f"[INFO] csv_path          : {csv_path}")
    print(f"[INFO] out_path          : {out_path}")
    print(f"[INFO] late_threshold_ms : {args.late_threshold_ms}")

    df = load_and_prepare_csv(
        csv_path=csv_path,
        late_threshold_ms=args.late_threshold_ms,
    )

    print_summary(df)

    plot_metrics(
        df=df,
        out_path=out_path,
        late_threshold_ms=args.late_threshold_ms,
    )

    root, ext = os.path.splitext(out_path)
    if not ext:
        ext = ".png"
    calibration_out_path = root + "_deadline_miss_calibration" + ext

    plot_deadline_miss_calibration(
        df=df,
        out_path=calibration_out_path,
    )


if __name__ == "__main__":
    main()
