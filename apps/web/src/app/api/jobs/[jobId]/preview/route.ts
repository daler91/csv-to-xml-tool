import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";
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

    // Update job with row count
    await prisma.job.update({
      where: { id: jobId },
      data: {
        totalRows: preview.total_rows,
        status: "previewed",
      },
    });

    return NextResponse.json(preview);
  } catch {
    return NextResponse.json(
      { error: "Failed to generate preview" },
      { status: 500 }
    );
  }
}
