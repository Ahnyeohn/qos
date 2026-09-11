# 10,000 viewer Playwright flood runner

## Files
- viewer\_master.mjs: launches multiple Node/Chromium worker processes.
- test\_viewer\_flood.mjs: each worker owns a subset of viewers and connects them in parallel batches.

## Install

```bash
npm install
```

If using Playwright Chromium:

```bash
npx playwright install chromium
```

If using your own Chromium build, pass --chromiumPath and browser download is not required.

## Example: 10,000 viewers with custom Chromium

```bash
node viewer_master.mjs \
  --roomId=test-room \
  --chromiumPath=/mnt/old/home/n2sl/chromium/src/out/Default/chrome \
  --totalViewers=10000 \
  --workerCount=40 \
  --batchSize=15 \
  --batchDelayMs=0 \
  --workerStartDelayMs=1000 \
  --rtpCheckIntervalMs=30000 \
  --rtpWindowMs=2000 \
  --statsConcurrency=25
```

Stop with Ctrl+C.
