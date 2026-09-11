#!/bin/bash

echo "======= START ======"

#timeout --signal=INT 300s \
node viewer_master.mjs \
  --roomId=test-room \
  --chromiumPath=/home/n2sl/chromium/src/out/VideoNoPresent/chrome \
  --totalViewers=200 \
  --workerCount=1 \
  --batchSize=25 \
  --batchDelayMs=0 \
  --retryDelayMs=0 \
  --workerStartDelayMs=1000 \
  --rtpCheckIntervalMs=30000 \
  --rtpWindowMs=2000 \
  --statsConcurrency=25
