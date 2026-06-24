import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";

/**
 * Cancel a queued or in-flight conversion.
 *
 * The database is the authoritative source of state: we flip ``job.status`` to
 * ``"cancelled"`` immediately so the progress page, dashboard, and any future
 * reads see the cancellation even if the worker is still crunching. We then poke
 * the worker to drop the job at its next checkpoint (best-effort — we don't block
 * on the response).
 *
 * Only jobs that are ``"queued"`` or ``"converting"`` can be cancelled. Marking
 * an ``uploaded`` / ``previewed`` / ``mapping`` job as cancelled would create a
 * contradictory state that a later start or preview call could revive; for those
 * (and terminal states) we return the current status idempotently so repeat
 * clicks are safe.
 *
 * Race safety: the guarded ``updateMany`` against ``status in {queued,converting}``
 * means a late-arriving complete/error from the queue consumer cannot overwrite a
 * cancellation that landed in the race window — and the consumer's own guarded
 * update no-ops a job we cancelled while it was still queued, so it is never run.
 */
export async function POST(
  _req: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  try {
    const user = await getRequiredUser();
    const { jobId } = await params;

    const job = await prisma.job.findFirst({
      where: { id: jobId, userId: user.id },
    });

    if (!job) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }

    if (job.status !== "queued" && job.status !== "converting") {
      // Idempotent no-op for terminal states (complete, error, cancelled) and
      // pre-start states (uploaded, previewed, mapping). Repeat clicks from a
      // stale tab return the current status without modifying anything.
      return NextResponse.json({ status: job.status }, { status: 200 });
    }

    // Conditional update: only flip to cancelled if the job is still queued or
    // converting. If a completion lands in the narrow race window, updateMany
    // returns count=0 and we report the post-race status instead of reviving a
    // terminal job.
    const cancelled = await prisma.job.updateMany({
      where: { id: jobId, status: { in: ["queued", "converting"] } },
      data: { status: "cancelled", completedAt: new Date() },
    });

    if (cancelled.count === 0) {
      const current = await prisma.job.findUnique({ where: { id: jobId } });
      return NextResponse.json(
        { status: current?.status ?? "unknown" },
        { status: 200 }
      );
    }

    await prisma.auditEntry.create({
      data: {
        userId: user.id,
        jobId,
        action: "conversion_cancelled",
      },
    });

    // Tell the worker to drop the job at its next checkpoint. Fire-and-forget:
    // if the worker never receives it (or the job was still queued and never
    // reached the worker), the database state is still correct and the queue
    // consumer will discard any orphaned result.
    workerFetch(`/convert/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      body: "{}",
      timeoutMs: 5000,
    }).catch(() => {
      // Swallow worker errors — the DB is authoritative.
    });

    return NextResponse.json({ status: "cancelled" }, { status: 200 });
  } catch {
    return NextResponse.json(
      { error: "Failed to cancel conversion" },
      { status: 500 }
    );
  }
}
