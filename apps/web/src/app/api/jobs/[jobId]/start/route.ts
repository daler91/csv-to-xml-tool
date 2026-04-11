import { NextResponse } from "next/server";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";
import type { ConvertResponse } from "@/types";

const DATA_DIR = process.env.DATA_DIR || "/data";

// Statuses a job can transition *out of* into "converting".
// A cancelled/complete/error job can't be started — the user should
// re-upload instead. A job already in status=converting can't be
// started a second time.
const STARTABLE_STATUSES = ["uploaded", "previewed", "mapping"] as const;

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

    if (!STARTABLE_STATUSES.includes(job.status as typeof STARTABLE_STATUSES[number])) {
      return NextResponse.json(
        {
          error:
            `This job is ${job.status} and can't be started. Upload the file again if you want to re-convert.`,
        },
        { status: 409 }
      );
    }

    // Conditional transition to "converting". Using updateMany with a
    // status guard closes the read-then-write race: if the user
    // cancels (or the job otherwise transitions) between the findFirst
    // above and this update, updateMany returns count=0 and we bail
    // instead of reviving a terminal job.
    const started = await prisma.job.updateMany({
      where: {
        id: jobId,
        userId: user.id,
        status: { in: [...STARTABLE_STATUSES] },
      },
      data: { status: "converting" },
    });

    if (started.count === 0) {
      return NextResponse.json(
        {
          error:
            "This job's status changed before we could start it. Refresh the page and try again.",
        },
        { status: 409 }
      );
    }

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

        // Conditional update: only write "complete" if the job is still
        // converting. If the user cancelled between the worker finishing
        // and this update firing, updateMany returns count=0 and we
        // discard the result — the file on disk is orphaned but harmless.
        const updated = await prisma.job.updateMany({
          where: { id: jobId, status: "converting" },
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

        if (updated.count === 0) {
          // Job was cancelled (or otherwise terminal) before we could
          // write the result. Don't create a completion audit entry.
          return;
        }

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
        // If the failure is because the worker honoured a cancel request
        // or the user cancelled out-of-band, leave the job in its
        // "cancelled" state — only transition converting → error here.
        const updated = await prisma.job.updateMany({
          where: { id: jobId, status: "converting" },
          data: { status: "error" },
        });

        if (updated.count === 0) {
          return;
        }

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
