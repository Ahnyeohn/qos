import { spawn } from 'node:child_process';
import readline from 'node:readline';

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

const ROOM_ID = getArg('roomId');
if (!ROOM_ID) {
  console.error('usage: node viewer_master.mjs --roomId=test-room --chromiumPath=/path/to/chrome');
  process.exit(1);
}

const TOTAL_VIEWERS = toInt(getArg('totalViewers', '10000'), 'totalViewers');
const WORKER_COUNT = toInt(getArg('workerCount', '40'), 'workerCount');
if (WORKER_COUNT <= 0) throw new Error('--workerCount must be > 0');

const VIEWERS_PER_WORKER = Math.ceil(TOTAL_VIEWERS / WORKER_COUNT);
const CHROMIUM_PATH = getArg('chromiumPath', '');
const BASE_URL = getArg('baseUrl', 'https://10.20.13.186:5555');
const BATCH_SIZE = toInt(getArg('batchSize', '15'), 'batchSize');
const BATCH_DELAY_MS = toInt(getArg('batchDelayMs', '0'), 'batchDelayMs');
const WORKER_START_DELAY_MS = toInt(getArg('workerStartDelayMs', '1000'), 'workerStartDelayMs');
const RTP_CHECK_INTERVAL_MS = toInt(getArg('rtpCheckIntervalMs', '30000'), 'rtpCheckIntervalMs');
const RTP_WINDOW_MS = toInt(getArg('rtpWindowMs', '2000'), 'rtpWindowMs');
const STATS_CONCURRENCY = toInt(getArg('statsConcurrency', '25'), 'statsConcurrency');
const RETRY_DELAY_MS = toInt(getArg('retryDelayMs', '1000'), 'retryDelayMs');

const WORKER_SCRIPT = new URL('./test_viewer_flood.mjs', import.meta.url);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const workers = [];
const latestSummaries = new Map();
let shuttingDown = false;

function prefixStream(stream, prefix, isError = false) {
  const rl = readline.createInterface({ input: stream });
  rl.on('line', line => {
    if (line.startsWith('@@SUMMARY ')) {
      try {
        const summary = JSON.parse(line.slice('@@SUMMARY '.length));
        latestSummaries.set(summary.workerId, summary);
      } catch (error) {
        console.error(`${prefix} failed to parse summary: ${error.message}`);
      }
      return;
    }

    const output = `${prefix} ${line}\n`;
    if (isError) process.stderr.write(output);
    else process.stdout.write(output);
  });
}

function printAggregate() {
  let attempted = 0;
  let connected = 0;
  let receiving = 0;
  let failed = 0;
  let packetsDelta = 0;
  let bytesDelta = 0;

  for (const summary of latestSummaries.values()) {
    attempted += summary.attempted ?? 0;
    connected += summary.connected ?? 0;
    receiving += summary.receiving ?? 0;
    failed += summary.failed ?? 0;
    packetsDelta += summary.packetsDelta ?? 0;
    bytesDelta += summary.bytesDelta ?? 0;
  }

  console.log('');
  console.log('========== MASTER AGGREGATE ==========');
  console.log(`workers reporting : ${latestSummaries.size}/${workers.length}`);
  console.log(`target viewers    : ${TOTAL_VIEWERS}`);
  console.log(`attempted         : ${attempted}/${TOTAL_VIEWERS}`);
  console.log(`connected         : ${connected}`);
  console.log(`receiving RTP     : ${receiving}`);
  console.log(`failed attempts   : ${failed}`);
  console.log(`packetsDelta      : ${packetsDelta}`);
  console.log(`bytesDelta        : ${bytesDelta}`);
  console.log(`retryDelayMs      : ${RETRY_DELAY_MS}`);
  console.log('======================================');
}

async function spawnWorker(workerId) {
  const offset = workerId * VIEWERS_PER_WORKER;
  const remaining = TOTAL_VIEWERS - offset;
  if (remaining <= 0) return;

  const viewerCount = Math.min(VIEWERS_PER_WORKER, remaining);
  const args = [
    WORKER_SCRIPT.pathname,
    `--workerId=${workerId}`,
    `--roomId=${ROOM_ID}`,
    `--baseUrl=${BASE_URL}`,
    `--viewerCount=${viewerCount}`,
    `--viewerOffset=${offset}`,
    `--batchSize=${BATCH_SIZE}`,
    `--batchDelayMs=${BATCH_DELAY_MS}`,
    `--retryDelayMs=${RETRY_DELAY_MS}`,
    `--rtpCheckIntervalMs=${RTP_CHECK_INTERVAL_MS}`,
    `--rtpWindowMs=${RTP_WINDOW_MS}`,
    `--statsConcurrency=${STATS_CONCURRENCY}`
  ];

  if (CHROMIUM_PATH) args.push(`--chromiumPath=${CHROMIUM_PATH}`);

  console.log(`[master] spawn worker=${workerId} viewers=${viewerCount} range=${offset + 1}-${offset + viewerCount}`);

  const child = spawn(process.execPath, args, { stdio: ['ignore', 'pipe', 'pipe'] });
  child.workerId = workerId;
  workers.push(child);

  prefixStream(child.stdout, `[worker ${workerId}]`);
  prefixStream(child.stderr, `[worker ${workerId} ERROR]`, true);

  child.on('exit', (code, signal) => {
    console.log(`[master] worker=${workerId} exited code=${code} signal=${signal}`);
  });
}

async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;

  console.log('');
  console.log(`[master] ${signal}: stopping ${workers.length} workers`);

  for (const child of workers) {
    if (!child.killed) child.kill('SIGTERM');
  }

  await sleep(2000);

  for (const child of workers) {
    if (child.exitCode === null) child.kill('SIGKILL');
  }

  process.exit(0);
}

process.once('SIGINT', () => void shutdown('SIGINT'));
process.once('SIGTERM', () => void shutdown('SIGTERM'));

console.log('========== VIEWER FLOOD MASTER ==========');
console.log(`roomId               : ${ROOM_ID}`);
console.log(`baseUrl              : ${BASE_URL}`);
console.log(`totalViewers          : ${TOTAL_VIEWERS}`);
console.log(`workerCount           : ${WORKER_COUNT}`);
console.log(`viewersPerWorker      : ${VIEWERS_PER_WORKER}`);
console.log(`batchSize             : ${BATCH_SIZE}`);
console.log(`batchDelayMs          : ${BATCH_DELAY_MS}`);
console.log(`workerStartDelayMs    : ${WORKER_START_DELAY_MS}`);
console.log(`rtpCheckIntervalMs    : ${RTP_CHECK_INTERVAL_MS}`);
console.log(`rtpWindowMs           : ${RTP_WINDOW_MS}`);
console.log(`statsConcurrency      : ${STATS_CONCURRENCY}`);
console.log(`chromiumPath          : ${CHROMIUM_PATH || '(Playwright default)'}`);
console.log('=========================================');

for (let workerId = 0; workerId < WORKER_COUNT; workerId++) {
  await spawnWorker(workerId);
  if (workerId + 1 < WORKER_COUNT && WORKER_START_DELAY_MS > 0) {
    await sleep(WORKER_START_DELAY_MS);
  }
}

setInterval(printAggregate, 10_000).unref();

await new Promise(resolve => {
  const timer = setInterval(() => {
    if (workers.length > 0 && workers.every(child => child.exitCode !== null)) {
      clearInterval(timer);
      resolve();
    }
  }, 1000);
});

printAggregate();
