import { NextResponse } from "next/server";
import { readFile, writeFile, mkdir } from "fs/promises";
import path from "path";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";
import type { ConvertResponse } from "@/types";

const DATA_DIR = process.env.DATA_DIR || "/data";

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

    // Read file content to stream to worker
    const fileContent = await readFile(job.inputFilePath, "utf-8");

    // Fire-and-forget: start conversion in background, return immediately
    workerFetch<ConvertResponse & { xml_content?: string }>("/convert", {
      method: "POST",
      body: JSON.stringify({
        job_id: jobId,
        file_name: job.inputFileName,
        converter_type: job.converterType,
        column_mapping: job.columnMapping,
        file_content: fileContent,
      }),
    })
      .then(async (result) => {
        // Save XML content locally for download
        let outputFilePath = "";
        if (result.xml_content) {
          const outputDir = path.join(DATA_DIR, "output", jobId);
          await mkdir(outputDir, { recursive: true });
          outputFilePath = path.join(outputDir, `${jobId}.xml`);
          await writeFile(outputFilePath, result.xml_content, "utf-8");
        }

        await prisma.job.update({
          where: { id: jobId },
          data: {
            status: "complete",
            outputFilePath,
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
