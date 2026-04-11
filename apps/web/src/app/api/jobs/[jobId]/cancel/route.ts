import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";

/**
 * Cancel an in-flight conversion.
 *
 * The database is the authoritative source of state: we flip
 * ``job.status`` to ``"cancelled"`` immediately so the progress page,
 * dashboard, and any future reads see the cancellation even if the
 * worker is still crunching. We then poke the worker to drop the job at
 * its next checkpoint (best-effort — we don't block on the response).
 *
 * The ``start`` route's background handler checks the DB state before
 * writing any terminal status, so a cancelled job will not be
 * overwritten by a late-arriving ``complete`` or ``error`` from the
 * worker.
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

    // Only in-flight jobs can be cancelled. Terminal states (complete,
    // error, cancelled) are returned as-is so repeat clicks are idempotent.
    const cancellable = job.status === "converting" || job.status === "uploaded"
      || job.status === "previewed" || job.status === "mapping";

    if (!cancellable) {
      return NextResponse.json({ status: job.status }, { status: 200 });
    }

    await prisma.job.update({
      where: { id: jobId },
      data: { status: "cancelled", completedAt: new Date() },
    });

    await prisma.auditEntry.create({
      data: {
        userId: user.id,
        jobId,
        action: "conversion_cancelled",
      },
    });

    // Tell the worker to drop the job at its next checkpoint.
    // Fire-and-forget: if the worker never receives this, the database
    // state is still correct and the orphaned result will be discarded
    // by the start route's background handler.
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
