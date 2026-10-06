#!/bin/bash

echo "======= START ======"

#timeout --signal=INT 300s \
taskset -c 1-11 \
node viewer_master.mjs \
  --roomId=test-room \
  --baseUrl=https://10.1.2.3:5555 \
  --chromiumPath=/home/n2sl/chromium/src/out/VideoNoPresent/chrome \
  --totalViewers=10 \
  --workerCount=5 \
  --batchSize=25 \
  --batchDelayMs=0 \
  --retryDelayMs=0 \
  --workerStartDelayMs=1000 \
  --rtpCheckIntervalMs=30000 \
  --rtpWindowMs=2000 \
  --statsConcurrency=25
