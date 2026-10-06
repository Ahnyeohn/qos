#!/bin/bash

IFACE="ens15f0"   # 실제 사용하는 NIC로 변경

set_rate() {
    RATE="$1"

    sudo tc qdisc replace dev "$IFACE" root tbf \
        rate "$RATE" \
        burst 64kb \
        latency 100ms

    echo "[$(date '+%H:%M:%S')] bandwidth = $RATE"
}

echo "=== bandwidth sweep start ==="

# L0 유도
set_rate "600kbit"
sleep 25

# L1 유도
set_rate "1800kbit"
sleep 25

# L2 유도
set_rate "7mbit"
sleep 25

echo "=== sweep finished ==="

# 마지막에는 제한 해제
sudo tc qdisc del dev "$IFACE" root 2>/dev/null

echo "[$(date '+%H:%M:%S')] bandwidth limit removed"