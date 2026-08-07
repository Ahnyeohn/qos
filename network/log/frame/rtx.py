#!/usr/bin/env python3

import csv
from collections import Counter, defaultdict
from pathlib import Path


BASE_DIR = Path("/home/n2sl/yeon/qos/network/log/frame")

LATE_DROP_CSV = BASE_DIR / "csv" / "late_drop_cause_analysis.csv"
RTP_CSV = BASE_DIR / "tshark" / "rtp_packets.csv"
OUTPUT_CSV = BASE_DIR / "csv" / "late_drop_rtp_analysis.csv"

MEDIA_PT = 101
RTX_PT = 102
FLEXFEC_PT = 118


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    """
    tshark CSV의 헤더/값에 따옴표나 공백이 남아 있는 경우를 처리한다.
    """
    normalized = {}

    for key, value in row.items():
        if key is None:
            continue

        clean_key = key.strip().strip('"')
        clean_value = value.strip().strip('"') if value is not None else ""

        normalized[clean_key] = clean_value

    return normalized


def parse_int(value: str) -> int | None:
    try:
        return int(value, 0)
    except (TypeError, ValueError):
        return None


def parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_ms(value: float | None) -> str:
    if value is None:
        return ""

    return f"{value:.3f}"


def load_late_drop_frames(
    csv_path: Path,
) -> tuple[list[int], dict[int, dict[str, str]]]:
    """
    late_drop_cause_analysis.csv에 존재하는 모든 frameId를 읽는다.
    원래 행 정보도 frameId별로 보관한다.
    """
    frame_ids: list[int] = []
    frame_records: dict[int, dict[str, str]] = {}

    with csv_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for raw_row in reader:
            row = normalize_row(raw_row)
            frame_id = parse_int(row.get("frameId", ""))

            if frame_id is None:
                continue

            if frame_id not in frame_records:
                frame_ids.append(frame_id)

            frame_records[frame_id] = row

    return frame_ids, frame_records


def load_target_rtp_packets(
    csv_path: Path,
    target_frame_ids: set[int],
) -> dict[int, list[dict[str, object]]]:
    """
    late/drop CSV에 포함된 frameId에 해당하는 RTP 패킷만 읽는다.
    frameId는 RTP timestamp와 대응한다고 가정한다.
    """
    packets_by_timestamp: dict[int, list[dict[str, object]]] = defaultdict(list)

    with csv_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for raw_row in reader:
            row = normalize_row(raw_row)

            timestamp = parse_int(row.get("rtp.timestamp", ""))
            payload_type = parse_int(row.get("rtp.p_type", ""))
            epoch = parse_float(row.get("frame.time_epoch", ""))

            if (
                timestamp is None
                or payload_type is None
                or epoch is None
                or timestamp not in target_frame_ids
            ):
                continue

            packets_by_timestamp[timestamp].append(
                {
                    "frame_number": parse_int(row.get("frame.number", "")),
                    "time": epoch,
                    "pt": payload_type,
                    "ssrc": row.get("rtp.ssrc", ""),
                    "seq": parse_int(row.get("rtp.seq", "")),
                    "marker": parse_int(row.get("rtp.marker", "")),
                    "src": row.get("ip.src", ""),
                    "dst": row.get("ip.dst", ""),
                    "src_port": row.get("udp.srcport", ""),
                    "dst_port": row.get("udp.dstport", ""),
                    "frame_len": parse_int(row.get("frame.len", "")),
                    "udp_length": parse_int(row.get("udp.length", "")),
                }
            )

    return packets_by_timestamp


def packet_time(packet: dict[str, object]) -> float:
    return float(packet["time"])


def elapsed_ms(
    packet: dict[str, object] | None,
    base_time: float | None,
) -> float | None:
    if packet is None or base_time is None:
        return None

    return (packet_time(packet) - base_time) * 1000.0


def analyze_frame(
    frame_id: int,
    frame_record: dict[str, str],
    packets: list[dict[str, object]],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    packets = sorted(packets, key=packet_time)

    media_packets = [
        packet for packet in packets
        if packet["pt"] == MEDIA_PT
    ]
    rtx_packets = [
        packet for packet in packets
        if packet["pt"] == RTX_PT
    ]
    fec_packets = [
        packet for packet in packets
        if packet["pt"] == FLEXFEC_PT
    ]

    relevant_packets = [
        packet for packet in packets
        if packet["pt"] in {MEDIA_PT, RTX_PT, FLEXFEC_PT}
    ]

    first_media = media_packets[0] if media_packets else None
    last_media = media_packets[-1] if media_packets else None
    first_rtx = rtx_packets[0] if rtx_packets else None
    last_rtx = rtx_packets[-1] if rtx_packets else None
    first_fec = fec_packets[0] if fec_packets else None
    last_fec = fec_packets[-1] if fec_packets else None
    last_relevant = relevant_packets[-1] if relevant_packets else None

    first_media_time = packet_time(first_media) if first_media else None
    last_media_time = packet_time(last_media) if last_media else None
    last_rtx_time = packet_time(last_rtx) if last_rtx else None
    last_fec_time = packet_time(last_fec) if last_fec else None

    rtx_after_last_media_ms = None

    if last_rtx_time is not None and last_media_time is not None:
        rtx_after_last_media_ms = (
            last_rtx_time - last_media_time
        ) * 1000.0

    fec_after_last_media_ms = None

    if last_fec_time is not None and last_media_time is not None:
        fec_after_last_media_ms = (
            last_fec_time - last_media_time
        ) * 1000.0

    last_packet_pt = (
        int(last_relevant["pt"])
        if last_relevant is not None
        else None
    )

    if last_packet_pt == RTX_PT:
        final_packet_type = "RTX"
    elif last_packet_pt == FLEXFEC_PT:
        final_packet_type = "FLEXFEC"
    elif last_packet_pt == MEDIA_PT:
        final_packet_type = "MEDIA"
    else:
        final_packet_type = "NO_RTP_MATCH"

    result: dict[str, object] = {
        "frameId": frame_id,
        "frameClass": frame_record.get("frameClass", ""),
        "primaryCause_reference_only": frame_record.get(
            "primaryCause",
            "",
        ),
        "max_wait": frame_record.get("max_wait", ""),
        "preDecodeWaitingMs": frame_record.get(
            "preDecodeWaitingMs",
            "",
        ),
        "pcap_packet_span_ms": frame_record.get(
            "pcap_packet_span_ms",
            "",
        ),
        "receiver_packet_span_ms": frame_record.get(
            "receiver_packet_span_ms",
            "",
        ),
        "pcap_matched": frame_record.get("pcap_matched", ""),
        "media_packet_count": len(media_packets),
        "rtx_packet_count": len(rtx_packets),
        "flexfec_packet_count": len(fec_packets),
        "first_media_epoch": (
            f"{first_media_time:.6f}"
            if first_media_time is not None
            else ""
        ),
        "last_media_epoch": (
            f"{last_media_time:.6f}"
            if last_media_time is not None
            else ""
        ),
        "first_rtx_epoch": (
            f"{packet_time(first_rtx):.6f}"
            if first_rtx is not None
            else ""
        ),
        "last_rtx_epoch": (
            f"{last_rtx_time:.6f}"
            if last_rtx_time is not None
            else ""
        ),
        "first_flexfec_epoch": (
            f"{packet_time(first_fec):.6f}"
            if first_fec is not None
            else ""
        ),
        "last_flexfec_epoch": (
            f"{last_fec_time:.6f}"
            if last_fec_time is not None
            else ""
        ),
        "last_packet_epoch": (
            f"{packet_time(last_relevant):.6f}"
            if last_relevant is not None
            else ""
        ),
        "last_packet_pt": (
            last_packet_pt
            if last_packet_pt is not None
            else ""
        ),
        "last_packet_type": final_packet_type,
        "first_rtx_from_first_media_ms": format_ms(
            elapsed_ms(first_rtx, first_media_time)
        ),
        "last_rtx_from_first_media_ms": format_ms(
            elapsed_ms(last_rtx, first_media_time)
        ),
        "last_flexfec_from_first_media_ms": format_ms(
            elapsed_ms(last_fec, first_media_time)
        ),
        "last_packet_from_first_media_ms": format_ms(
            elapsed_ms(last_relevant, first_media_time)
        ),
        "rtx_after_last_media_ms": format_ms(
            rtx_after_last_media_ms
        ),
        "flexfec_after_last_media_ms": format_ms(
            fec_after_last_media_ms
        ),
        "last_packet_is_rtx": (
            "True" if last_packet_pt == RTX_PT else "False"
        ),
    }

    return result, rtx_packets


def print_frame_analysis(
    result: dict[str, object],
    rtx_packets: list[dict[str, object]],
) -> None:
    print("=" * 100)
    print(
        f"RTP timestamp/frameId: {result['frameId']} "
        f"[{result['frameClass']}]"
    )

    print(
        f"PT 101 media: {result['media_packet_count']}, "
        f"PT 102 RTX: {result['rtx_packet_count']}, "
        f"PT 118 FlexFEC: {result['flexfec_packet_count']}"
    )

    print(
        f"receiver span: "
        f"{result['receiver_packet_span_ms']} ms, "
        f"pcap span: {result['pcap_packet_span_ms']} ms, "
        f"max_wait: {result['max_wait']} ms"
    )

    print(
        f"마지막 RTP 종류: {result['last_packet_type']} "
        f"(PT={result['last_packet_pt']}), "
        f"첫 media 이후 "
        f"{result['last_packet_from_first_media_ms']} ms"
    )

    if not rtx_packets:
        print("RTX packet: 없음")
        return

    print("RTX packets:")

    first_media_epoch = parse_float(
        str(result["first_media_epoch"])
    )

    for packet in rtx_packets:
        time_epoch = packet_time(packet)

        relative_ms = (
            (time_epoch - first_media_epoch) * 1000.0
            if first_media_epoch is not None
            else None
        )

        relative_text = (
            f"{relative_ms:.3f}ms"
            if relative_ms is not None
            else "N/A"
        )

        print(
            f"  time={time_epoch:.6f}, "
            f"fromFirstMedia={relative_text}, "
            f"ssrc={packet['ssrc']}, "
            f"rtxSeq={packet['seq']}, "
            f"{packet['src']}:{packet['src_port']} -> "
            f"{packet['dst']}:{packet['dst_port']}"
        )


def save_results(
    output_path: Path,
    results: list[dict[str, object]],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not results:
        raise RuntimeError("분석 결과가 없습니다.")

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(results[0].keys()),
        )

        writer.writeheader()
        writer.writerows(results)


def print_summary(results: list[dict[str, object]]) -> None:
    total = len(results)

    with_rtx = [
        row for row in results
        if int(row["rtx_packet_count"]) > 0
    ]

    last_is_rtx = [
        row for row in results
        if row["last_packet_is_rtx"] == "True"
    ]

    no_rtp_match = [
        row for row in results
        if row["last_packet_type"] == "NO_RTP_MATCH"
    ]

    final_type_counts = Counter(
        str(row["last_packet_type"])
        for row in results
    )

    print()
    print("#" * 100)
    print("[SUMMARY]")
    print(f"late/drop CSV frame 수         : {total}")
    print(f"RTX가 존재한 frame 수         : {len(with_rtx)}")
    print(f"마지막 패킷이 RTX인 frame 수  : {len(last_is_rtx)}")
    print(f"PCAP RTP 미매칭 frame 수       : {len(no_rtp_match)}")

    print("마지막 패킷 종류별 수:")

    for packet_type, count in sorted(final_type_counts.items()):
        print(f"  {packet_type}: {count}")

    print()
    print("마지막 패킷이 RTX인 frameId:")

    for row in last_is_rtx:
        print(
            f"  {row['frameId']} "
            f"[{row['frameClass']}], "
            f"RTX count={row['rtx_packet_count']}, "
            f"last RTX delay="
            f"{row['last_rtx_from_first_media_ms']}ms, "
            f"receiver span="
            f"{row['receiver_packet_span_ms']}ms"
        )


def main() -> None:
    if not LATE_DROP_CSV.exists():
        raise FileNotFoundError(
            f"late/drop CSV가 없습니다: {LATE_DROP_CSV}"
        )

    if not RTP_CSV.exists():
        raise FileNotFoundError(
            f"RTP CSV가 없습니다: {RTP_CSV}"
        )

    frame_ids, frame_records = load_late_drop_frames(
        LATE_DROP_CSV
    )

    if not frame_ids:
        raise RuntimeError(
            "late_drop_cause_analysis.csv에서 "
            "frameId를 읽지 못했습니다."
        )

    print(f"[INFO] late/drop frame 수: {len(frame_ids)}")
    print(f"[INFO] RTP CSV 읽는 중: {RTP_CSV}")

    packets_by_timestamp = load_target_rtp_packets(
        RTP_CSV,
        set(frame_ids),
    )

    results: list[dict[str, object]] = []

    for frame_id in frame_ids:
        packets = packets_by_timestamp.get(frame_id, [])

        result, rtx_packets = analyze_frame(
            frame_id,
            frame_records[frame_id],
            packets,
        )

        results.append(result)

        print_frame_analysis(
            result,
            rtx_packets,
        )

    save_results(
        OUTPUT_CSV,
        results,
    )

    print_summary(results)

    print()
    print(f"[INFO] 분석 결과 저장: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()