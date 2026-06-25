import {
  claimJob,
  ackJob,
  requeueJob,
  getAttempts,
  sweepStaleClaims,
} from "@/lib/job-queue";
import { runJob } from "@/lib/job-runner";
import { prisma } from "@/lib/prisma";

// Max conversion attempts before a job is dead-lettered to "error".
const MAX_ATTEMPTS = Number(process.env.JOB_MAX_ATTEMPTS) || 3;
const SWEEP_INTERVAL_MS = 60 * 1000;
const CLAIM_TIMEOUT_SEC = 5;

// Guard against Next.js dev-mode double registration / multiple register()
// calls in one process (mirrors the globalForRedis / globalForPrisma pattern).
const globalForConsumer = globalThis as unknown as {
  jobConsumerStarted?: boolean;
};

let running = true;

/**
 * Start the durable-queue consumer (called once from instrumentation.ts).
 * Runs a boot sweep to recover jobs abandoned by a previous process (the
 * durability win), schedules a periodic sweep, then enters the claim/run/ack
 * loop. Returns immediately — the loop runs in the background.
 */
export async function startConsumer(): Promise<void> {
  if (globalForConsumer.jobConsumerStarted) return;
  globalForConsumer.jobConsumerStarted = true;

  try {
    const reclaimed = await sweepStaleClaims();
    if (reclaimed.length) {
      console.log(
        `[job-consumer] boot sweep re-queued ${reclaimed.length} stale job(s)`
      );
    }
  } catch (err) {
    console.error("[job-consumer] boot sweep failed:", err);
  }

  setInterval(() => {
    sweepStaleClaims().catch((err) =>
      console.error("[job-consumer] periodic sweep failed:", err)
    );
  }, SWEEP_INTERVAL_MS);

  process.on("SIGTERM", () => {
    running = false;
  });

  console.log("[job-consumer] started");
  void runLoop();
}

async function runLoop(): Promise<void> {
  while (running) {
    let jobId: string | null = null;
    try {
      jobId = await claimJob(CLAIM_TIMEOUT_SEC);
    } catch (err) {
      // Redis hiccup — pause briefly so we don't hot-loop, then retry.
      console.error("[job-consumer] claim failed:", err);
      await sleep(1000);
      continue;
    }
    if (!jobId) continue; // claim timed out — loop (re-checks `running`)

    try {
      await runJob(jobId);
      await ackJob(jobId);
    } catch (err) {
      await handleFailure(jobId, err);
    }
  }
}

// Exported for unit testing (the retry/dead-letter classification); the runLoop
// that calls it isn't directly testable.
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

  if (!permanent && (await getAttempts(jobId)) < MAX_ATTEMPTS) {
    await sleep(2000); // brief best-effort backoff
    await requeueJob(jobId);
    return;
  }

  await deadLetter(jobId, message);
  await ackJob(jobId);
}

async function deadLetter(jobId: string, error: string): Promise<void> {
  // Guarded: only flip a still-"converting" job to error. If a cancel landed
  // first, count=0 and the "cancelled" status is preserved.
  const updated = await prisma.job.updateMany({
    where: { id: jobId, status: "converting" },
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
