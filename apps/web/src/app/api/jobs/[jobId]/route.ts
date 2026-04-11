import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";

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
const TERMINAL_STATUSES = new Set(["cancelled", "complete", "error"]);

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
