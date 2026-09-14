#!/bin/bash

echo "======= DELETE LOG FILE ======"
rm -rf /mnt/old/home/n2sl/chromium/src/telemetry_all.log
rm -rf /mnt/old/home/n2sl/qos/network/log/frame/csv/frame_packets.csv
rm -rf /mnt/old/home/n2sl/qos/network/log/frame/csv/frame_records.csv
echo ""

echo "======= START ======"

#timeout --signal=INT 300s \
node viewer_master.mjs \
  --roomId=test-room \
  --chromiumPath=/mnt/old/home/n2sl/chromium/src/out/VideoNoPresent/chrome \
  --totalViewers=1000 \
  --workerCount=5 \
  --batchSize=25 \
  --batchDelayMs=0 \
  --retryDelayMs=0 \
  --workerStartDelayMs=1000 \
  --rtpCheckIntervalMs=30000 \
  --rtpWindowMs=2000 \
  --statsConcurrency=25
