import {
  claimJob,
  ackJob,
  requeueJob,
  getAttempts,
  promoteDueJobs,
  sweepStaleClaims,
} from "@/lib/job-queue";
import { runJob } from "@/lib/job-runner";
import { purgeAllExpiredJobFiles } from "@/lib/retention";
import { prisma } from "@/lib/prisma";
import { assertTimeoutOrdering } from "@/lib/durability-timeouts";

// Max conversion attempts before a job is dead-lettered to "error".
const MAX_ATTEMPTS = Number(process.env.JOB_MAX_ATTEMPTS) || 3;
const SWEEP_INTERVAL_MS = 60 * 1000;
// File retention for every user, not only those who revisit the dashboard.
const RETENTION_INTERVAL_MS = 60 * 60 * 1000;
const CLAIM_TIMEOUT_SEC = 5;
// Pause after an unexpected failure inside the loop so a persistently broken
// dependency (Redis down, database gone) is retried, not hot-looped.
const FAILURE_BACKOFF_MS = 1000;
// Delay before retrying a transiently failed conversion, multiplied by 4 for
// each further attempt: 30 s, then 2 min with the default three attempts.
// Long enough to outlast a worker redeploy -- the old fixed 2 s pause spent
// all three attempts in about 4 s, so a restart failed every job in flight.
// The whole schedule is far inside REAP_DEADLINE_MS, which a delayed job
// (still "converting") is measured against.
const RETRY_BASE_MS = Number(process.env.JOB_RETRY_BASE_MS) || 30 * 1000;

/** Backoff before the retry that follows failed attempt `attempt` (1-based). */
export function retryDelayMs(attempt: number): number {
  return RETRY_BASE_MS * 4 ** Math.max(0, attempt - 1);
}

// Guard against Next.js dev-mode double registration / multiple register()
// calls in one process (mirrors the globalForRedis / globalForPrisma pattern).
const globalForConsumer = globalThis as unknown as {
  jobConsumerStarted?: boolean;
};

let running = true;

/**
 * Start the durable-queue consumer (called once from instrumentation.ts).
 * Kicks off a boot sweep to recover jobs abandoned by a previous process (the
 * durability win), schedules a periodic sweep, and enters the claim/run/ack
 * loop. Returns immediately — everything runs in the background.
 *
 * Nothing here awaits Redis. Next awaits `register()` before it starts
 * listening, and the queue client is configured to reconnect forever with an
 * offline command queue (see job-queue.ts), so an awaited command against an
 * unreachable Redis never settles — the boot sweep used to be awaited, and a
 * web deploy that raced a Redis restart therefore never came up at all: the
 * process listened on nothing, the platform healthcheck failed, and after
 * three restarts the service stayed down until a manual redeploy. Every other
 * Redis path in the app fails open; startup now does too.
 */
export async function startConsumer(): Promise<void> {
  if (globalForConsumer.jobConsumerStarted) return;
  globalForConsumer.jobConsumerStarted = true;

  // A misordered override would let the sweep re-queue jobs that are still
  // running; refuse to run the consumer on such a configuration.
  assertTimeoutOrdering();

  void sweepStaleClaims()
    .then((reclaimed) => {
      if (reclaimed.length) {
        console.log(
          `[job-consumer] boot sweep re-queued ${reclaimed.length} stale job(s)`
        );
      }
    })
    .catch((err) => {
      console.error("[job-consumer] boot sweep failed:", err);
    });

  setInterval(() => {
    sweepStaleClaims().catch((err) =>
      console.error("[job-consumer] periodic sweep failed:", err)
    );
  }, SWEEP_INTERVAL_MS);

  // Not awaited, like the boot sweep: retention fails open and must never
  // hold up startup. Then hourly.
  void purgeAllExpiredJobFiles();
  setInterval(() => {
    void purgeAllExpiredJobFiles();
  }, RETENTION_INTERVAL_MS);

  process.on("SIGTERM", stopConsumer);

  console.log("[job-consumer] started");
  void runLoop();
}

/** Stop claiming new jobs after the current one (SIGTERM, tests). */
export function stopConsumer(): void {
  running = false;
}

/**
 * The claim/run/ack loop. Exported for unit testing: `shouldRun` lets a test
 * drive a bounded number of iterations instead of the module's SIGTERM flag.
 *
 * Nothing inside the loop body is allowed to end it. It used to be
 * `void runLoop()` with `handleFailure` called bare inside the catch, so any
 * Redis or database error thrown *while handling* a failure rejected the
 * loop's promise — Next logs an unhandled rejection rather than exiting, so
 * the web kept serving while no job was ever claimed again, and the
 * started-flag above prevented a restart. One Redis restart during a
 * completing conversion was enough.
 */
export async function runLoop(
  shouldRun: () => boolean = () => running
): Promise<void> {
  while (shouldRun()) {
    let jobId: string | null = null;
    try {
      // Retries whose backoff has elapsed go back on the queue first. Checked
      // every iteration, so at most CLAIM_TIMEOUT_SEC late.
      await promoteDueJobs();
      jobId = await claimJob(CLAIM_TIMEOUT_SEC);
    } catch (err) {
      // Redis hiccup — pause briefly so we don't hot-loop, then retry.
      console.error("[job-consumer] claim failed:", err);
      await sleep(FAILURE_BACKOFF_MS);
      continue;
    }
    if (!jobId) continue; // claim timed out — loop (re-checks shouldRun)

    try {
      await processClaim(jobId);
    } catch (err) {
      console.error(
        `[job-consumer] failure handling for job ${jobId} threw; the job stays claimed for the sweep to retry:`,
        err
      );
      await sleep(FAILURE_BACKOFF_MS);
    }
  }
}

/**
 * Run one claimed job to a terminal queue state. Exported for unit testing.
 *
 * The attempts cap is enforced here, at claim time, and not only in
 * `handleFailure`: a job that kills the process instead of throwing (an
 * out-of-memory conversion, say) never reaches the failure handler, and the
 * sweep re-queues it every visibility window with no limit — while each
 * re-claim refreshes `updatedAt`, so the reaper never fires either. The
 * attempt counter is bumped by `claimJob`, so the first claim reads 1 and the
 * cap is `> MAX_ATTEMPTS`: exactly MAX_ATTEMPTS runs are allowed, the same
 * budget `handleFailure` applies to jobs that fail by throwing.
 */
export async function processClaim(jobId: string): Promise<void> {
  try {
    const attempt = await getAttempts(jobId);
    if (attempt > MAX_ATTEMPTS) {
      await deadLetter(
        jobId,
        `Attempts exhausted: claimed ${attempt} times without completing (limit ${MAX_ATTEMPTS}); a previous attempt probably crashed the consumer.`
      );
      await ackJob(jobId);
      return;
    }
    await runJob(jobId, attempt);
    await ackJob(jobId);
  } catch (err) {
    await handleFailure(jobId, err);
  }
}

// Exported for unit testing (the retry/dead-letter classification).
export async function handleFailure(jobId: string, err: unknown): Promise<void> {
  const message = err instanceof Error ? err.message : String(err);
  const status = workerErrorStatus(message);

  // Cancelled (worker 409): the DB is already "cancelled"; just drop the entry.
  if (status === 409) {
    await ackJob(jobId);
    return;
  }

  // Permanent input errors (400 / 422 from required-column validation) and
  // conversion timeouts aren't worth retrying — a 30-min timeout is unlikely
  // transient, and retrying it could blow past the reaper deadline. Dead-letter
  // immediately. Everything else (network, worker 5xx) is treated as transient.
  const isTimeout = /timed out/i.test(message);
  const permanent = status === 400 || status === 422 || isTimeout;

  const attempt = await getAttempts(jobId);
  if (!permanent && attempt < MAX_ATTEMPTS) {
    await requeueJob(jobId, retryDelayMs(attempt));
    return;
  }

  await deadLetter(jobId, message);
  await ackJob(jobId);
}

async function deadLetter(jobId: string, error: string): Promise<void> {
  // Guarded: only flip a job the queue still owns to error. If a cancel landed
  // first, count=0 and the "cancelled" status is preserved. "queued" is
  // included because a failure can come before the runner's queued ->
  // converting flip (the database briefly unreachable, say); guarding on
  // "converting" alone acked such a job while it stayed "queued", with no
  // audit row, until the reaper failed it as a timeout an hour later.
  const updated = await prisma.job.updateMany({
    where: { id: jobId, status: { in: ["queued", "converting"] } },
    data: { status: "error", completedAt: new Date() },
  });
  if (updated.count === 0) return;

  const job = await prisma.job.findUnique({
    where: { id: jobId },
    select: { userId: true },
  });
  if (job) {
    await prisma.auditEntry.create({
      data: {
        userId: job.userId,
        jobId,
        action: "conversion_deadlettered",
        metadata: { error },
      },
    });
  }
}

/** workerFetch throws Error("Worker error <status>: ...") on a non-OK response. */
export function workerErrorStatus(message: string): number | null {
  const m = message.match(/Worker error (\d+)/);
  return m ? Number(m[1]) : null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
