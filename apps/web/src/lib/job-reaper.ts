import { prisma } from "@/lib/prisma";

// Backstop deadline: a job stuck in "queued" or "converting" past this is failed.
//
// With the durable queue (ARCH-1) the queue's sweep re-claims abandoned
// "converting" jobs (consumer died mid-run) within VISIBILITY_TIMEOUT_MS and
// retries them — and a re-claim resets `updatedAt` — so this reaper only fires on
// jobs the queue itself couldn't recover. It must therefore exceed both
// CONVERSION_TIMEOUT_MS and VISIBILITY_TIMEOUT_MS. It also covers "queued" jobs
// that were committed but never made it onto the Redis queue (the tiny
// enqueue-after-commit gap, or Redis down at enqueue) — the sweep can't see those,
// so the reaper is their only safety net.
//
// A queued/converting job's row isn't written until it terminalizes (progress is
// read live from the worker, never persisted), so `updatedAt` reliably marks when
// it entered that state and is a sound staleness baseline.
const REAP_DEADLINE_MS = Number(process.env.REAP_DEADLINE_MS) || 60 * 60 * 1000;

const STUCK_STATUSES = ["queued", "converting"];

/**
 * Fail jobs stuck in "queued"/"converting" past the deadline so they don't linger
 * forever. Scoped to a single user so it stays bounded and cheap enough to run on
 * the job-read paths (lazy reconciliation). Idempotent and race-safe: the guarded
 * updateMany only flips rows still in those states, so a job that just
 * completed/cancelled in a concurrent handler is left untouched (count === 0).
 *
 * Returns the number of jobs reaped.
 */
export async function reapStuckConvertingJobs(userId: string): Promise<number> {
  const deadline = new Date(Date.now() - REAP_DEADLINE_MS);

  const stuck = await prisma.job.findMany({
    where: { userId, status: { in: STUCK_STATUSES }, updatedAt: { lt: deadline } },
    select: { id: true },
  });

  let reaped = 0;
  for (const { id } of stuck) {
    const res = await prisma.job.updateMany({
      where: { id, status: { in: STUCK_STATUSES } },
      data: { status: "error", completedAt: new Date() },
    });
    if (res.count > 0) {
      reaped += 1;
      await prisma.auditEntry.create({
        data: {
          userId,
          jobId: id,
          action: "conversion_timeout",
          metadata: {
            reason: "Job stuck in queued/converting past the reaper deadline.",
          },
        },
      });
    }
  }

  return reaped;
}
