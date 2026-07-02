import { NextResponse } from "next/server";
import { rm } from "node:fs/promises";
import path from "node:path";
import type { JobStatus } from "@prisma/client";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";
import { reapStuckConvertingJobs } from "@/lib/job-reaper";

const DATA_DIR = process.env.DATA_DIR || "/data";

interface ProgressSnapshot {
  processed: number;
  total: number;
  updated_at: number;
}

async function fetchWorkerProgress(
  jobId: string
): Promise<ProgressSnapshot | null> {
  try {
    return await workerFetch<ProgressSnapshot>(
      `/convert/${encodeURIComponent(jobId)}/progress`,
      { method: "GET", timeoutMs: 3000 }
    );
  } catch {
    // 404 (no snapshot yet / already cleared) or transient network
    // error — treat as "no progress yet" so the UI falls back to
    // its elapsed-time counter.
    return null;
  }
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  try {
    const user = await getRequiredUser();
    const { jobId } = await params;

    // ARCH-1: reconcile stuck "converting" jobs before reading, so a job whose
    // process died is shown as "error" instead of a perpetual converting state.
    await reapStuckConvertingJobs(user.id);

    const job = await prisma.job.findFirst({
      where: { id: jobId, userId: user.id },
    });

    if (!job) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }

    // For in-flight conversions, also fetch the worker's in-memory
    // progress snapshot so the progress page can show row-level
    // progress instead of a dead 0% bar. UX_REVIEW.md §3.6.
    if (job.status === "converting") {
      const progress = await fetchWorkerProgress(jobId);
      if (progress) {
        return NextResponse.json({
          ...job,
          processedRows: progress.processed,
          totalRows: progress.total,
          progressUpdatedAt: progress.updated_at,
        });
      }
    }

    return NextResponse.json(job);
  } catch {
    return NextResponse.json({ error: "Failed to fetch job" }, { status: 500 });
  }
}

// A job in any of these states is terminal from the user's
// perspective: the flow is over, and PATCH requests from stale
// tabs should not be able to revive it. Matches the set enforced
// in the /cancel, /start, and /preview routes.
const TERMINAL_STATUSES = new Set<JobStatus>(["cancelled", "complete", "error"]);

export async function PATCH(
  req: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  try {
    const user = await getRequiredUser();
    const { jobId } = await params;
    const data = await req.json();

    const job = await prisma.job.findFirst({
      where: { id: jobId, userId: user.id },
    });

    if (!job) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }

    if (TERMINAL_STATUSES.has(job.status)) {
      return NextResponse.json(
        {
          error:
            `This job is ${job.status} and can't be modified. Re-upload if you want to work on it again.`,
        },
        { status: 409 }
      );
    }

    // Whitelist fields that clients are allowed to update
    const allowedFields = ["columnMapping", "status"] as const;
    const sanitizedData: Record<string, unknown> = {};
    for (const key of allowedFields) {
      if (key in data) {
        sanitizedData[key] = data[key];
      }
    }

    if (Object.keys(sanitizedData).length === 0) {
      return NextResponse.json({ error: "No valid fields to update" }, { status: 400 });
    }

    // Conditional update to close the read-then-write race: if the
    // user cancels between the findFirst above and this update, the
    // NOT IN guard ensures the PATCH doesn't revive the cancelled
    // job. Count is 0 when the race loses; we read back the current
    // status and report it.
    const updated = await prisma.job.updateMany({
      where: {
        id: jobId,
        userId: user.id,
        status: { notIn: Array.from(TERMINAL_STATUSES) },
      },
      data: sanitizedData,
    });

    if (updated.count === 0) {
      const current = await prisma.job.findUnique({ where: { id: jobId } });
      return NextResponse.json(
        {
          error:
            `This job is ${current?.status ?? "in a terminal state"} and can't be modified.`,
        },
        { status: 409 }
      );
    }

    const fresh = await prisma.job.findUnique({ where: { id: jobId } });
    return NextResponse.json(fresh);
  } catch {
    return NextResponse.json({ error: "Failed to update job" }, { status: 500 });
  }
}

// A job the queue may still be working on can't be deleted out from
// under the runner — cancel it first, then delete.
const ACTIVE_STATUSES = new Set<JobStatus>(["queued", "converting"]);

export async function DELETE(
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

    if (ACTIVE_STATUSES.has(job.status)) {
      return NextResponse.json(
        {
          error:
            "This job is still running. Cancel it first, then delete it.",
        },
        { status: 409 }
      );
    }

    // Files first, row second: if the row delete fails the job still
    // renders (downloads 404), which is recoverable by retrying —
    // whereas deleting the row first could orphan files no sweep can
    // find. Paths are built from the DB-issued id, not the URL param.
    await rm(path.join(DATA_DIR, "uploads", job.id), {
      recursive: true,
      force: true,
    }).catch(() => {});
    await rm(path.join(DATA_DIR, "output", job.id), {
      recursive: true,
      force: true,
    }).catch(() => {});

    // Guarded delete: a job that raced into queued/converting since the
    // read above is left alone. Postgres nulls auditEntry.jobId and any
    // child job's previousJobId (optional relations -> SET NULL), so the
    // audit trail and re-upload rows survive.
    const deleted = await prisma.job.deleteMany({
      where: {
        id: jobId,
        userId: user.id,
        status: { notIn: Array.from(ACTIVE_STATUSES) },
      },
    });

    if (deleted.count === 0) {
      return NextResponse.json(
        { error: "This job is still running and can't be deleted." },
        { status: 409 }
      );
    }

    await prisma.auditEntry.create({
      data: {
        userId: user.id,
        action: "job_deleted",
        metadata: {
          deletedJobId: job.id,
          fileName: job.inputFileName,
          converterType: job.converterType,
          status: job.status,
        },
      },
    });

    return NextResponse.json({ deleted: true });
  } catch (error) {
    if (error instanceof Error && error.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    console.error("Delete job error:", error);
    return NextResponse.json(
      { error: "Failed to delete job" },
      { status: 500 }
    );
  }
}
