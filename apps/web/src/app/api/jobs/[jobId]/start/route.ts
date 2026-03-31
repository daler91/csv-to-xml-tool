import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";
import type { ConvertResponse } from "@/types";

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

    // Update status to converting
    await prisma.job.update({
      where: { id: jobId },
      data: { status: "converting" },
    });

    await prisma.auditEntry.create({
      data: {
        userId: user.id,
        jobId,
        action: "conversion_started",
      },
    });

    // Fire-and-forget: start conversion in background, return immediately
    workerFetch<ConvertResponse>("/convert", {
      method: "POST",
      body: JSON.stringify({
        job_id: jobId,
        file_name: job.inputFileName,
        converter_type: job.converterType,
        column_mapping: job.columnMapping,
      }),
    })
      .then(async (result) => {
        await prisma.job.update({
          where: { id: jobId },
          data: {
            status: "complete",
            outputFilePath: result.xml_path,
            totalRows: result.stats.total,
            summary: result.stats as object,
            issues: result.issues as object[],
            cleaningDiffs: result.cleaning_diff as object[],
            xsdValid: result.xsd_valid,
            xsdErrors: result.xsd_errors,
            completedAt: new Date(),
          },
        });

        await prisma.auditEntry.create({
          data: {
            userId: user.id,
            jobId,
            action: "conversion_complete",
            metadata: result.stats,
          },
        });
      })
      .catch(async (workerError) => {
        await prisma.job.update({
          where: { id: jobId },
          data: { status: "error" },
        });

        await prisma.auditEntry.create({
          data: {
            userId: user.id,
            jobId,
            action: "conversion_failed",
            metadata: {
              error:
                workerError instanceof Error
                  ? workerError.message
                  : "Unknown error",
            },
          },
        });
      });

    return NextResponse.json({ status: "converting" }, { status: 202 });
  } catch {
    return NextResponse.json(
      { error: "Failed to start conversion" },
      { status: 500 }
    );
  }
}
