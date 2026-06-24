import { prisma } from "@/lib/prisma";

// How long a job may sit in "converting" before the reaper fails it.
//
// On a live process a conversion always leaves "converting" by
// CONVERSION_TIMEOUT_MS (worker success -> "complete", or the fetch abort in the
// start route's .catch -> "error"). This deadline therefore MUST exceed
// CONVERSION_TIMEOUT_MS so the reaper only ever acts on jobs whose Node process
// died before that .catch could run -- never on a job a live process will finish.
//
// A "converting" job is never written to the DB until it reaches a terminal state
// (progress is read live from the worker, not persisted), so `updatedAt` reliably
// marks when the job entered "converting" and is a sound staleness baseline.
const REAP_DEADLINE_MS = Number(process.env.REAP_DEADLINE_MS) || 45 * 60 * 1000;

/**
 * Fail jobs stuck in "converting" past the deadline (their process died before
 * the start route could mark them error/complete), so they don't linger forever.
 *
 * Scoped to a single user so it stays bounded and cheap enough to run on the
 * job-read paths (lazy reconciliation). Idempotent and race-safe: the guarded
 * updateMany only flips rows still in "converting", so a job that just
 * completed/cancelled in a concurrent handler is left untouched (count === 0).
 *
 * Returns the number of jobs reaped.
 */
export async function reapStuckConvertingJobs(userId: string): Promise<number> {
  const deadline = new Date(Date.now() - REAP_DEADLINE_MS);

  const stuck = await prisma.job.findMany({
    where: { userId, status: "converting", updatedAt: { lt: deadline } },
    select: { id: true },
  });

  let reaped = 0;
  for (const { id } of stuck) {
    const res = await prisma.job.updateMany({
      where: { id, status: "converting" },
      data: { status: "error", completedAt: new Date() },
    });
    if (res.count > 0) {
      reaped += 1;
      await prisma.auditEntry.create({
        data: {
          userId,
          jobId: id,
          action: "conversion_timeout",
          metadata: { reason: "Job stuck in converting past the reaper deadline." },
        },
      });
    }
  }

  return reaped;
}
