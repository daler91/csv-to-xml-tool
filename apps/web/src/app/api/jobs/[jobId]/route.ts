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

    const updated = await prisma.job.update({
      where: { id: jobId },
      data: sanitizedData,
    });

    return NextResponse.json(updated);
  } catch {
    return NextResponse.json({ error: "Failed to update job" }, { status: 500 });
  }
}
