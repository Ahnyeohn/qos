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

const BASE_URL =
  getArg(
    'baseUrl',
    'https://10.20.13.186:5555'
  );

const VIEWER_COUNT =
  toInt(
    getArg('viewerCount', '250'),
    'viewerCount'
  );

const VIEWER_OFFSET =
  toInt(
    getArg('viewerOffset', '0'),
    'viewerOffset'
  );

const BATCH_SIZE =
  Math.max(
    1,
    toInt(
      getArg('batchSize', '15'),
      'batchSize'
    )
  );

const BATCH_DELAY_MS =
  toInt(
    getArg('batchDelayMs', '0'),
    'batchDelayMs'
  );

const RTP_CHECK_INTERVAL_MS =
  toInt(
    getArg(
      'rtpCheckIntervalMs',
      '30000'
    ),
    'rtpCheckIntervalMs'
  );

const RTP_WINDOW_MS =
  toInt(
    getArg(
      'rtpWindowMs',
      '2000'
    ),
    'rtpWindowMs'
  );

const STATS_CONCURRENCY =
  Math.max(
    1,
    toInt(
      getArg(
        'statsConcurrency',
        '25'
      ),
      'statsConcurrency'
    )
  );

const CHROMIUM_PATH =
  getArg(
    'chromiumPath',
    ''
  );

const RETRY_DELAY_MS =
  toInt(
    getArg(
      'retryDelayMs',
      '1000'
    ),
    'retryDelayMs'
  );


const sleep =
  ms =>
    new Promise(
      resolve =>
        setTimeout(resolve, ms)
    );


const activeViewers = [];


let attemptedCount = 0;
let httpSuccessCount = 0;
let websocketCount = 0;
let peerConnectedCount = 0;
let failedCount = 0;

let latestRtpSummary = {
  receiving: 0,
  packetsDelta: 0,
  bytesDelta: 0
};

let checkingRtp = false;
let shuttingDown = false;


/*
 * ============================================================
 * Limited concurrency helper for stats
 * ============================================================
 */

async function mapLimit(
  items,
  limit,
  fn
) {
  const results =
    new Array(
      items.length
    );

  let nextIndex = 0;


  async function runner() {
    while (true) {
      const index =
        nextIndex++;

      if (
        index >=
        items.length
      ) {
        return;
      }


      try {
        results[index] =
          await fn(
            items[index],
            index
          );
      }
      catch (error) {
        results[index] = {
          error:
            error.message
        };
      }
    }
  }


  const runners = [];


  for (
    let i = 0;
    i <
    Math.min(
      limit,
      items.length
    );
    i++
  ) {
    runners.push(
      runner()
    );
  }


  await Promise.all(
    runners
  );


  return results;
}


/*
 * ============================================================
 * RTP stats from one Page
 *
 * Uses RTCPeerConnection objects captured by addInitScript().
 * ============================================================
 */

async function getInboundStats(
  page
) {
  return page.evaluate(
    async () => {
      const pcs =
        window.__peerConnections ??
        [];


      const result = {
        peerConnectionCount:
          pcs.length,

        connectedCount:
          0,

        connectionStates:
          [],

        packetsReceived:
          0,

        bytesReceived:
          0,

        videoPacketsReceived:
          0,

        videoBytesReceived:
          0,

        audioPacketsReceived:
          0,

        audioBytesReceived:
          0
      };


      for (
        const pc
        of pcs
      ) {
        result.connectionStates.push(
          pc.connectionState
        );


        if (
          pc.connectionState ===
          'connected'
        ) {
          result.connectedCount++;
        }


        const stats =
          await pc.getStats();


        stats.forEach(
          report => {
            if (
              report.type !==
                'inbound-rtp' ||
              report.isRemote
            ) {
              return;
            }


            const packets =
              report.packetsReceived ??
              0;

            const bytes =
              report.bytesReceived ??
              0;

            const kind =
              report.kind ??
              report.mediaType;


            result.packetsReceived +=
              packets;

            result.bytesReceived +=
              bytes;


            if (
              kind ===
              'video'
            ) {
              result.videoPacketsReceived +=
                packets;

              result.videoBytesReceived +=
                bytes;
            }
            else if (
              kind ===
              'audio'
            ) {
              result.audioPacketsReceived +=
                packets;

              result.audioBytesReceived +=
                bytes;
            }
          }
        );
      }


      return result;
    }
  );
}


/*
 * ============================================================
 * MASTER summary
 * ============================================================
 */

function emitSummary() {
  const summary = {
    workerId:
      WORKER_ID,

    attempted:
      attemptedCount,

    http:
      httpSuccessCount,

    websocket:
      websocketCount,

    connected:
      peerConnectedCount,

    receiving:
      latestRtpSummary.receiving,

    failed:
      failedCount,

    packetsDelta:
      latestRtpSummary.packetsDelta,

    bytesDelta:
      latestRtpSummary.bytesDelta,

    activeContexts:
      activeViewers.length
  };


  console.log(
    `@@SUMMARY ${JSON.stringify(summary)}`
  );
}


/*
 * ============================================================
 * RTP check across all viewer Pages
 * ============================================================
 */

async function checkAllRtp() {
  if (
    checkingRtp ||
    activeViewers.length === 0
  ) {
    return;
  }


  checkingRtp = true;


  try {
    const viewers =
      activeViewers.filter(
        viewer =>
          !viewer.page.isClosed()
      );


    const before =
      await mapLimit(
        viewers,

        STATS_CONCURRENCY,

        async viewer => ({
          viewerNumber:
            viewer.viewerNumber,

          stats:
            await getInboundStats(
              viewer.page
            )
        })
      );


    await sleep(
      RTP_WINDOW_MS
    );


    const after =
      await mapLimit(
        viewers,

        STATS_CONCURRENCY,

        async viewer => ({
          viewerNumber:
            viewer.viewerNumber,

          stats:
            await getInboundStats(
              viewer.page
            )
        })
      );


    let receiving = 0;
    let packetsDelta = 0;
    let bytesDelta = 0;


    for (
      let i = 0;
      i < viewers.length;
      i++
    ) {
      const beforeStats =
        before[i]?.stats;

      const afterStats =
        after[i]?.stats;


      if (
        !beforeStats ||
        !afterStats
      ) {
        continue;
      }


      const packetDelta =
        afterStats.packetsReceived -
        beforeStats.packetsReceived;


      const byteDelta =
        afterStats.bytesReceived -
        beforeStats.bytesReceived;


      if (
        packetDelta > 0 &&
        byteDelta > 0
      ) {
        receiving++;

        packetsDelta +=
          packetDelta;

        bytesDelta +=
          byteDelta;
      }
    }


    latestRtpSummary = {
      receiving,
      packetsDelta,
      bytesDelta
    };


    console.log(
      `[rtp] active=${viewers.length}` +
      ` receiving=${receiving}` +
      ` packetsDelta=${packetsDelta}` +
      ` bytesDelta=${bytesDelta}` +
      ` windowMs=${RTP_WINDOW_MS}`
    );


    emitSummary();
  }
  finally {
    checkingRtp = false;
  }
}


/*
 * ============================================================
 * Chromium
 * ============================================================
 */

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


if (CHROMIUM_PATH) {
  launchOptions.executablePath =
    CHROMIUM_PATH;
}


const browser =
  await chromium.launch(
    launchOptions
  );


console.log(
  `[worker ${WORKER_ID}] browser launched` +
  ` version=${browser.version()}` +
  ` executable=${CHROMIUM_PATH || 'Playwright default'}`
);


/*
 * ============================================================
 * ONE viewer
 *
 * ONE viewer
 *   -> ONE BrowserContext
 *   -> ONE Page
 *   -> ONE loadtest.js
 *   -> ONE RoomClientLoadTest
 * ============================================================
 */

async function connectViewer(
  viewerNumber
) {
  let context = null;
  let page = null;

  let stage =
    'INIT';


  const viewerStartedAt =
    Date.now();


  try {
    /*
     * ----------------------------------------------------------
     * Context
     * ----------------------------------------------------------
     */

    stage =
      'CREATE_CONTEXT';


    context =
      await browser.newContext({
        ignoreHTTPSErrors:
          true
      });


    /*
     * IMPORTANT:
     *
     * loadtest.js / mediasoup-client가
     * RTCPeerConnection을 생성하기 전에 Proxy 설치.
     */
    await context.addInitScript(
      () => {
        const NativeRTCPeerConnection =
          window.RTCPeerConnection;


        window.__peerConnections =
          [];


        window.RTCPeerConnection =
          new Proxy(
            NativeRTCPeerConnection,
            {
              construct(
                target,
                args
              ) {
                const pc =
                  new target(
                    ...args
                  );


                window.__peerConnections.push(
                  pc
                );


                return pc;
              }
            }
          );
      }
    );


    /*
     * ----------------------------------------------------------
     * Page
     * ----------------------------------------------------------
     */

    stage =
      'CREATE_PAGE';


    page =
      await context.newPage();


    /*
     * ----------------------------------------------------------
     * Debug handlers
     * ----------------------------------------------------------
     */

    page.on(
      'response',
      response => {
        if (
          response.status() >=
          400
        ) {
          console.error(
            `[viewer ${viewerNumber}] HTTP ${response.status()}` +
            ` type=${response.request().resourceType()}` +
            ` url=${response.url()}`
          );
        }
      }
    );


    page.on(
      'requestfailed',
      request => {
        console.error(
          `[viewer ${viewerNumber}] REQUEST FAILED` +
          ` type=${request.resourceType()}` +
          ` url=${request.url()}` +
          ` error=${request.failure()?.errorText}`
        );
      }
    );


    page.on(
      'console',
      message => {
        if (
          message.type() !==
          'error'
        ) {
          return;
        }


        const text =
          message.text();


        if (
          text.includes(
            'AudioContext encountered an error'
          ) ||
          text.includes(
            'audioElem.play() failed'
          )
        ) {
          return;
        }


        const location =
          message.location();


        console.error(
          `[viewer ${viewerNumber}] browser error:` +
          ` ${text}` +
          ` url=${location.url}` +
          ` line=${location.lineNumber ?? location.line}` +
          ` column=${location.columnNumber ?? location.column}`
        );
      }
    );


    page.on(
      'pageerror',
      error => {
        console.error(
          `[viewer ${viewerNumber}] page error:` +
          ` ${error.message}`
        );
      }
    );


    page.on(
      'websocket',
      () => {
        websocketCount++;
      }
    );


    /*
     * ----------------------------------------------------------
     * PAGE_GOTO
     * ----------------------------------------------------------
     */

    stage =
      'PAGE_GOTO';


    const url =
      `${BASE_URL}/loadtest.html` +
      `?roomId=${encodeURIComponent(ROOM_ID)}` +
      `&displayName=${encodeURIComponent(`viewer-${viewerNumber}`)}`;


    const gotoStartedAt =
      Date.now();


    const response =
      await page.goto(
        url,
        {
          waitUntil:
            'domcontentloaded',

          timeout:
            30_000
        }
      );


    const gotoElapsedMs =
      Date.now() -
      gotoStartedAt;


    if (!response) {
      throw new Error(
        'page.goto() returned no HTTP response'
      );
    }


    if (!response.ok()) {
      throw new Error(
        `HTTP ${response.status()}` +
        ` ${response.statusText()}`
      );
    }


    httpSuccessCount++;


    /*
     * ----------------------------------------------------------
     * WAIT_PC_CREATE
     * ----------------------------------------------------------
     */

    stage =
      'WAIT_PC_CREATE';


    const pcCreateStartedAt =
      Date.now();


    await page.waitForFunction(
      () =>
        (
          window.__peerConnections
            ?.length ??
          0
        ) > 0,

      undefined,

      {
        timeout:
          30_000
      }
    );


    const pcCreateElapsedMs =
      Date.now() -
      pcCreateStartedAt;


    /*
     * ----------------------------------------------------------
     * WAIT_PC_CONNECTED
     * ----------------------------------------------------------
     */

    stage =
      'WAIT_PC_CONNECTED';


    const pcConnectStartedAt =
      Date.now();


    await page.waitForFunction(
      () =>
        window.__peerConnections
          ?.some(
            pc =>
              pc.connectionState ===
              'connected'
          ),

      undefined,

      {
        timeout:
          30_000
      }
    );


    const pcConnectElapsedMs =
      Date.now() -
      pcConnectStartedAt;


    stage =
      'CONNECTED';


    peerConnectedCount++;


    activeViewers.push({
      viewerNumber,
      context,
      page
    });


    console.log(
      `[viewer ${viewerNumber}] CONNECTED` +
      ` total=${Date.now() - viewerStartedAt}ms` +
      ` goto=${gotoElapsedMs}ms` +
      ` pcCreate=${pcCreateElapsedMs}ms` +
      ` pcConnect=${pcConnectElapsedMs}ms`
    );


    return {
      viewerNumber,
      success: true
    };
  }
  catch (error) {
    failedCount++;


    let debug = null;


    if (
      page &&
      !page.isClosed()
    ) {
      try {
        debug =
          await page.evaluate(
            () => {
              const pcs =
                window.__peerConnections ??
                [];


              return {
                loadtestState:
                  window.__LOADTEST_STATE ??
                  null,

                pcCount:
                  pcs.length,

                pcs:
                  pcs.map(
                    pc => ({
                      connectionState:
                        pc.connectionState,

                      iceConnectionState:
                        pc.iceConnectionState,

                      iceGatheringState:
                        pc.iceGatheringState,

                      signalingState:
                        pc.signalingState
                    })
                  ),

                consumerCount:
                  window.CLIENT
                    ?._consumers
                    ?.size ??
                  null,

                videoConsumers:
                  window.CLIENT
                    ? Array.from(
                        window.CLIENT
                          ._consumers
                          ?.values?.() ??
                          []
                      ).filter(
                        consumer =>
                          consumer.kind ===
                          'video'
                      ).length
                    : null,

                recvTransportState:
                  window.CLIENT
                    ?._recvTransport
                    ?.connectionState ??
                  null
              };
            }
          );
      }
      catch {
        debug = null;
      }
    }


    console.error(
      `[viewer ${viewerNumber}] FAILED` +
      ` stage=${stage}` +
      ` totalElapsed=${Date.now() - viewerStartedAt}ms` +
      ` error=${error.message}` +
      ` debug=${JSON.stringify(debug)}`
    );


    if (context) {
      try {
        await context.close();
      }
      catch {}
    }


    return {
      viewerNumber,
      success: false,
      stage,
      error:
        error.message
    };
  }
}


/*
 * ============================================================
 * Batch/retry
 * ============================================================
 */

console.log(
  `[worker ${WORKER_ID}] start` +
  ` count=${VIEWER_COUNT}` +
  ` offset=${VIEWER_OFFSET}` +
  ` batchSize=${BATCH_SIZE}`
);


const pendingViewerNumbers =
  [];


for (
  let localIndex = 0;
  localIndex < VIEWER_COUNT;
  localIndex++
) {
  pendingViewerNumbers.push(
    VIEWER_OFFSET +
    localIndex +
    1
  );
}


let batchNumber = 0;


while (
  pendingViewerNumbers.length >
  0
) {
  batchNumber++;


  const viewerNumbers =
    pendingViewerNumbers.splice(
      0,
      Math.min(
        BATCH_SIZE,
        pendingViewerNumbers.length
      )
    );


  const startedAt =
    Date.now();


  const results =
    await Promise.all(
      viewerNumbers.map(
        connectViewer
      )
    );


  attemptedCount +=
    viewerNumbers.length;


  const succeededViewerNumbers =
    [];

  const failedViewerNumbers =
    [];


  for (
    const result
    of results
  ) {
    if (result.success) {
      succeededViewerNumbers.push(
        result.viewerNumber
      );
    }
    else {
      failedViewerNumbers.push(
        result.viewerNumber
      );
    }
  }


  /*
   * Failed logical viewer를 fresh Context/Page로 retry.
   */
  pendingViewerNumbers.push(
    ...failedViewerNumbers
  );


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


  if (
    failedViewerNumbers.length >
    0
  ) {
    console.log(
      `[retry] worker=${WORKER_ID}` +
      ` viewers=${failedViewerNumbers.join(',')}`
    );
  }


  emitSummary();


  if (
    pendingViewerNumbers.length >
    0
  ) {
    if (
      BATCH_DELAY_MS >
      0
    ) {
      await sleep(
        BATCH_DELAY_MS
      );
    }


    if (
      failedViewerNumbers.length >
        0 &&
      RETRY_DELAY_MS >
        0
    ) {
      await sleep(
        RETRY_DELAY_MS
      );
    }
  }
}


/*
 * ============================================================
 * Target reached
 * ============================================================
 */

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


/*
 * ============================================================
 * RTP monitoring
 * ============================================================
 */

await checkAllRtp();


const rtpTimer =
  setInterval(
    () =>
      void checkAllRtp(),

    RTP_CHECK_INTERVAL_MS
  );


/*
 * ============================================================
 * Shutdown
 * ============================================================
 */

async function shutdown(
  signal
) {
  if (shuttingDown)
    return;


  shuttingDown = true;


  clearInterval(
    rtpTimer
  );


  console.log(
    `[worker ${WORKER_ID}]` +
    ` ${signal}: closing browser`
  );


  try {
    await browser.close();
  }
  finally {
    process.exit(0);
  }
}


process.once(
  'SIGINT',
  () =>
    void shutdown(
      'SIGINT'
    )
);


process.once(
  'SIGTERM',
  () =>
    void shutdown(
      'SIGTERM'
    )
);


await new Promise(
  () => {}
);
