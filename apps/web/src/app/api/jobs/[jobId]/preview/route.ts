import { NextResponse } from "next/server";
import { readFile, stat } from "node:fs/promises";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";
import { MAX_UPLOAD_BYTES } from "@/lib/limits";
import type { PreviewResponse } from "@/types";

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

    // SEC-1: enforce the upload size cap server-side before streaming to the worker.
    const { size: inputSize } = await stat(job.inputFilePath);
    if (inputSize > MAX_UPLOAD_BYTES) {
      return NextResponse.json(
        { error: "File size exceeds 50MB limit" },
        { status: 413 }
      );
    }

    // Read file content and stream to worker
    const fileContent = await readFile(job.inputFilePath, "utf-8");

    const preview = await workerFetch<PreviewResponse>("/preview", {
      method: "POST",
      body: JSON.stringify({
        job_id: jobId,
        file_name: job.inputFileName,
        converter_type: job.converterType,
        file_content: fileContent,
      }),
    });

    // Update job with row count and advance status to "previewed",
    // but only from non-terminal states. A stale tab fetching the
    // preview of a cancelled/complete/error job would otherwise
    // revive it; conditional updateMany closes that loophole.
    //
    // We always persist totalRows (even on cancelled jobs) because
    // the dashboard and audit views want an accurate row count
    // regardless of status. Splitting into two updateMany calls
    // keeps the status transition tight.
    await prisma.job.updateMany({
      where: { id: jobId },
      data: { totalRows: preview.total_rows },
    });
    await prisma.job.updateMany({
      where: {
        id: jobId,
        status: { notIn: ["cancelled", "complete", "error", "converting", "queued"] },
      },
      data: { status: "previewed" },
    });

    return NextResponse.json(preview);
  } catch {
    return NextResponse.json(
      { error: "Failed to generate preview" },
      { status: 500 }
    );
  }
}
