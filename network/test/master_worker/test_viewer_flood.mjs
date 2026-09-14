import { chromium } from 'playwright';

function getArg(name, defaultValue = undefined) {
  const prefix = `--${name}=`;
  const arg = process.argv.find(v => v.startsWith(prefix));
  return arg ? arg.slice(prefix.length) : defaultValue;
}

function toInt(value, name) {
  const n = Number(value);
  if (!Number.isInteger(n) || n < 0) {
    throw new Error(`invalid --${name}=${value}`);
  }
  return n;
}

const WORKER_ID = toInt(getArg('workerId', '0'), 'workerId');
const ROOM_ID = getArg('roomId');
if (!ROOM_ID) {
  console.error('missing --roomId');
  process.exit(1);
}

const BASE_URL = getArg('baseUrl', 'https://10.20.13.186:5555');
const VIEWER_COUNT = toInt(getArg('viewerCount', '250'), 'viewerCount');
const VIEWER_OFFSET = toInt(getArg('viewerOffset', '0'), 'viewerOffset');
const BATCH_SIZE = Math.max(1, toInt(getArg('batchSize', '15'), 'batchSize'));
const BATCH_DELAY_MS = toInt(getArg('batchDelayMs', '0'), 'batchDelayMs');
const RTP_CHECK_INTERVAL_MS = toInt(getArg('rtpCheckIntervalMs', '30000'), 'rtpCheckIntervalMs');
const RTP_WINDOW_MS = toInt(getArg('rtpWindowMs', '2000'), 'rtpWindowMs');
const STATS_CONCURRENCY = Math.max(1, toInt(getArg('statsConcurrency', '25'), 'statsConcurrency'));
const CHROMIUM_PATH = getArg('chromiumPath', '');
const RETRY_DELAY_MS = toInt(getArg('retryDelayMs', '1000'), 'retryDelayMs');

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const activeViewers = [];

let attemptedCount = 0;
let httpSuccessCount = 0;
let websocketCount = 0;
let peerConnectedCount = 0;
let failedCount = 0;
let latestRtpSummary = { receiving: 0, packetsDelta: 0, bytesDelta: 0 };
let checkingRtp = false;
let shuttingDown = false;

async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function runner() {
    while (true) {
      const index = nextIndex++;
      if (index >= items.length) return;

      try {
        results[index] = await fn(items[index], index);
      } catch (error) {
        results[index] = { error: error.message };
      }
    }
  }

  const runners = [];
  for (let i = 0; i < Math.min(limit, items.length); i++) runners.push(runner());
  await Promise.all(runners);
  return results;
}

async function getInboundStats(page) {
  return page.evaluate(async () => {
    const pcs = window.__peerConnections ?? [];
    const result = {
      peerConnectionCount: pcs.length,
      connectedCount: 0,
      connectionStates: [],
      packetsReceived: 0,
      bytesReceived: 0,
      videoPacketsReceived: 0,
      videoBytesReceived: 0,
      audioPacketsReceived: 0,
      audioBytesReceived: 0
    };

    for (const pc of pcs) {
      result.connectionStates.push(pc.connectionState);
      if (pc.connectionState === 'connected') result.connectedCount++;

      const stats = await pc.getStats();
      stats.forEach(report => {
        if (report.type !== 'inbound-rtp' || report.isRemote) return;

        const packets = report.packetsReceived ?? 0;
        const bytes = report.bytesReceived ?? 0;
        const kind = report.kind ?? report.mediaType;

        result.packetsReceived += packets;
        result.bytesReceived += bytes;

        if (kind === 'video') {
          result.videoPacketsReceived += packets;
          result.videoBytesReceived += bytes;
        } else if (kind === 'audio') {
          result.audioPacketsReceived += packets;
          result.audioBytesReceived += bytes;
        }
      });
    }

    return result;
  });
}

function emitSummary() {
  const summary = {
    workerId: WORKER_ID,
    attempted: attemptedCount,
    http: httpSuccessCount,
    websocket: websocketCount,
    connected: peerConnectedCount,
    receiving: latestRtpSummary.receiving,
    failed: failedCount,
    packetsDelta: latestRtpSummary.packetsDelta,
    bytesDelta: latestRtpSummary.bytesDelta,
    activeContexts: activeViewers.length
  };

  console.log(`@@SUMMARY ${JSON.stringify(summary)}`);
}

async function checkAllRtp() {
  if (checkingRtp || activeViewers.length === 0) return;
  checkingRtp = true;

  try {
    const viewers = activeViewers.filter(v => !v.page.isClosed());

    const before = await mapLimit(
      viewers,
      STATS_CONCURRENCY,
      async viewer => ({
        viewerNumber: viewer.viewerNumber,
        stats: await getInboundStats(viewer.page)
      })
    );

    await sleep(RTP_WINDOW_MS);

    const after = await mapLimit(
      viewers,
      STATS_CONCURRENCY,
      async viewer => ({
        viewerNumber: viewer.viewerNumber,
        stats: await getInboundStats(viewer.page)
      })
    );

    let receiving = 0;
    let packetsDelta = 0;
    let bytesDelta = 0;

    for (let i = 0; i < viewers.length; i++) {
      const b = before[i]?.stats;
      const a = after[i]?.stats;
      if (!b || !a) continue;

      const pDelta = a.packetsReceived - b.packetsReceived;
      const bDelta = a.bytesReceived - b.bytesReceived;

      if (pDelta > 0 && bDelta > 0) {
        receiving++;
        packetsDelta += pDelta;
        bytesDelta += bDelta;
      }
    }

    latestRtpSummary = { receiving, packetsDelta, bytesDelta };

    console.log(
      `[rtp] active=${viewers.length}` +
      ` receiving=${receiving}` +
      ` packetsDelta=${packetsDelta}` +
      ` bytesDelta=${bytesDelta}` +
      ` windowMs=${RTP_WINDOW_MS}`
    );

    emitSummary();
  } finally {
    checkingRtp = false;
  }
}

const launchOptions = {
  headless: true,
  args: [
    '--no-sandbox',

	'--no-first-run',
	'--disable-breakpad',

	'--use-fake-ui-for-media-stream',
	'--use-fake-device-for-media-stream',

    '--mute-audio'
  ]
};

if (CHROMIUM_PATH) launchOptions.executablePath = CHROMIUM_PATH;

const browser = await chromium.launch(launchOptions);

console.log(
  `[worker ${WORKER_ID}] browser launched` +
  ` version=${browser.version()}` +
  ` executable=${CHROMIUM_PATH || 'Playwright default'}`
);

async function connectViewer(viewerNumber) {
  let context = null;

  try {
    context = await browser.newContext({ ignoreHTTPSErrors: true });

    await context.addInitScript(() => {
      const NativeRTCPeerConnection = window.RTCPeerConnection;
      window.__peerConnections = [];
      window.RTCPeerConnection = new Proxy(NativeRTCPeerConnection, {
        construct(target, args) {
          const pc = new target(...args);
          window.__peerConnections.push(pc);
          return pc;
        }
      });
    });

    const page = await context.newPage();
	page.on('response', response => {
		if (response.status() >= 400) {
			console.error(
				`[viewer ${viewerNumber}] HTTP ${response.status()}` +
				` type=${response.request().resourceType()}` +
				` url=${response.url()}`
			);
		}
	});

	page.on('requestfailed', request => {
		console.error(
			`[viewer ${viewerNumber}] REQUEST FAILED` +
			` type=${request.resourceType()}` +
			` url=${request.url()}` +
			` error=${request.failure()?.errorText}`
		);
	});

    page.on('console', message => {
      if (message.type() !== 'error') return;
      const text = message.text();

      if (
        text.includes('AudioContext encountered an error') ||
        text.includes('audioElem.play() failed')
      ) {
        return;
      }

	  const location = message.location();

      console.error(
		`[viewer ${viewerNumber}] browser error:` +
		` ${text}` +
		` url=${location.url}` +
		` line=${location.line}` +
		` column=${location.column}`
		);
    });

    page.on('pageerror', error => {
      console.error(`[viewer ${viewerNumber}] page error: ${error.message}`);
    });

    page.on('websocket', () => {
      websocketCount++;
    });

    const url = `${BASE_URL}/loadtest.html?roomId=${encodeURIComponent(ROOM_ID)}`;
    const response = await page.goto(url, {
      waitUntil: 'domcontentloaded',
      timeout: 30_000
    });

    if (!response) throw new Error('page.goto() returned no HTTP response');
    if (!response.ok()) throw new Error(`HTTP ${response.status()} ${response.statusText()}`);
    httpSuccessCount++;

    await page.waitForFunction(
      () => (window.__peerConnections?.length ?? 0) > 0,
      undefined,
      { timeout: 30_000 }
    );

    await page.waitForFunction(
      () => window.__peerConnections?.some(pc => pc.connectionState === 'connected'),
      undefined,
      { timeout: 30_000 }
    );

    peerConnectedCount++;
    activeViewers.push({ viewerNumber, context, page });

    return { viewerNumber, success: true };
  } catch (error) {
    failedCount++;
    console.error(`[viewer ${viewerNumber}] FAILED: ${error.message}`);

    if (context) {
      try { await context.close(); } catch {}
    }

    return { viewerNumber, success: false, error: error.message };
  }
}

console.log(
  `[worker ${WORKER_ID}] start` +
  ` count=${VIEWER_COUNT}` +
  ` offset=${VIEWER_OFFSET}` +
  ` batchSize=${BATCH_SIZE}`
);

/*
 * Each worker has VIEWER_COUNT logical viewer slots.
 *
 * A slot is removed from the pending queue only after the viewer
 * successfully establishes a PeerConnection.
 *
 * Failed slots are appended to the queue and retried until this
 * worker has VIEWER_COUNT successful viewers.
 */
const pendingViewerNumbers = [];

for (let localIndex = 0; localIndex < VIEWER_COUNT; localIndex++) {
  pendingViewerNumbers.push(
    VIEWER_OFFSET + localIndex + 1
  );
}

let batchNumber = 0;

while (pendingViewerNumbers.length > 0) {
  batchNumber++;

  const viewerNumbers =
    pendingViewerNumbers.splice(
      0,
      Math.min(BATCH_SIZE, pendingViewerNumbers.length)
    );

  const startedAt = Date.now();

  const results = await Promise.all(
    viewerNumbers.map(connectViewer)
  );

  attemptedCount += viewerNumbers.length;

  const succeededViewerNumbers = [];
  const failedViewerNumbers = [];

  for (const result of results) {
    if (result.success) {
      succeededViewerNumbers.push(result.viewerNumber);
    } else {
      failedViewerNumbers.push(result.viewerNumber);
    }
  }

  /*
   * Failed logical viewers go back to the end of the queue.
   *
   * connectViewer() already closes the failed BrowserContext, so
   * retrying the same logical viewer number creates a fresh context
   * and a fresh peerId.
   */
  pendingViewerNumbers.push(...failedViewerNumbers);

  console.log(
    `[batch] worker=${WORKER_ID}` +
    ` batch=${batchNumber}` +
    ` attempted=${viewerNumbers.length}` +
    ` connected=${succeededViewerNumbers.length}` +
    ` retry=${failedViewerNumbers.length}` +
    ` elapsed=${((Date.now() - startedAt) / 1000).toFixed(2)}s` +
    ` totalConnected=${peerConnectedCount}/${VIEWER_COUNT}` +
    ` pending=${pendingViewerNumbers.length}` +
    ` totalAttempts=${attemptedCount}` +
    ` failedAttempts=${failedCount}`
  );

  if (failedViewerNumbers.length > 0) {
    console.log(
      `[retry] worker=${WORKER_ID}` +
      ` viewers=${failedViewerNumbers.join(',')}`
    );
  }

  emitSummary();

  if (pendingViewerNumbers.length > 0) {
    /*
     * Normal batch spacing.
     */
    if (BATCH_DELAY_MS > 0) {
      await sleep(BATCH_DELAY_MS);
    }

    /*
     * If this batch contained failures, avoid immediately hammering
     * the signaling/WebRTC setup path.
     */
    if (
      failedViewerNumbers.length > 0 &&
      RETRY_DELAY_MS > 0
    ) {
      await sleep(RETRY_DELAY_MS);
    }
  }
}

console.log(
  `[worker ${WORKER_ID}] target reached` +
  ` connected=${peerConnectedCount}/${VIEWER_COUNT}` +
  ` attempted=${attemptedCount}` +
  ` failedAttempts=${failedCount}`
);

console.log(
  `[worker ${WORKER_ID}] all join attempts finished` +
  ` attempted=${attemptedCount}` +
  ` connected=${peerConnectedCount}` +
  ` failed=${failedCount}`
);

await checkAllRtp();

const rtpTimer = setInterval(() => void checkAllRtp(), RTP_CHECK_INTERVAL_MS);

async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  clearInterval(rtpTimer);

  console.log(`[worker ${WORKER_ID}] ${signal}: closing browser`);

  try {
    await browser.close();
  } finally {
    process.exit(0);
  }
}

process.once('SIGINT', () => void shutdown('SIGINT'));
process.once('SIGTERM', () => void shutdown('SIGTERM'));

await new Promise(() => {});
