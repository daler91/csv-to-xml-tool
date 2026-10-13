import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { isUnauthorized, routeError } from "@/lib/api-errors";
import { workerFetch, workerClientError } from "@/lib/worker-client";
import { MAX_UPLOAD_BYTES } from "@/lib/limits";
import { decodeCsvBuffer } from "@/lib/csv-decode";
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

    // Retention blanks inputFilePath on expiry; readFile("") threw ENOENT and
    // produced a generic 500 rather than telling the user the file was gone.
    if (job.filesPurgedAt || !job.inputFilePath) {
      return NextResponse.json(
        {
          error:
            "The uploaded file for this job has expired and been removed. Upload it again to preview.",
        },
        { status: 410 }
      );
    }

    // SEC-1: enforce the upload size cap server-side before sending to the worker.
    const bytes = await readFile(job.inputFilePath);
    if (bytes.byteLength > MAX_UPLOAD_BYTES) {
      return NextResponse.json(
        { error: "File size exceeds 50MB limit" },
        { status: 413 }
      );
    }
    // Same decoder as the conversion itself (job-runner.ts), so the preview
    // shows the names the filing will carry, cp1252 exports included.
    const { text: csvContent } = decodeCsvBuffer(bytes);

    // Web and worker are separate Railway services with no shared volume, so we
    // send the CSV content in the request body (job_id is for log correlation).
    let preview: PreviewResponse;
    try {
      preview = await workerFetch<PreviewResponse>("/preview", {
        method: "POST",
        body: JSON.stringify({
          job_id: jobId,
          csv_content: csvContent,
          converter_type: job.converterType,
        }),
      });
    } catch (error) {
      // The worker answers a malformed CSV with a specific 400; relaying it
      // as a 500 told the user the server "may be busy" for a file problem.
      const clientError = workerClientError(error);
      if (clientError) {
        return NextResponse.json({ error: clientError }, { status: 400 });
      }
      // Anything else is the deployment's problem, not the file's: the worker
      // is down or unreachable, refused WORKER_AUTH_TOKEN (401/503), or failed
      // (500). This used to rethrow into the generic 500 below, which logged
      // nothing, so a failing preview left no trace of which it was.
      console.error("Preview worker error:", jobId, error);
      return NextResponse.json(
        {
          error:
            "The conversion service couldn't generate a preview. Try again in a minute; if it keeps happening, the worker service needs checking.",
        },
        { status: 502 }
      );
    }

    // Update job with row count and advance status to "previewed",
    // but only from non-terminal states. A stale tab fetching the
    // preview of a cancelled/complete/error job would otherwise
    // revive it; conditional updateMany closes that loophole.
    //
    // We persist totalRows even on terminal jobs because the dashboard and
    // audit views want an accurate row count regardless of status — but NOT on
    // queued/converting ones. Any write bumps updatedAt, and the stuck-job
    // reaper (lib/job-reaper.ts) measures staleness from updatedAt on exactly
    // those two states; an unguarded write here silently reset that clock and
    // let a genuinely stuck job run past its deadline.
    await prisma.job.updateMany({
      where: { id: jobId, status: { notIn: ["queued", "converting"] } },
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
  } catch (error) {
    // Logged for the same reason: reading the upload or updating the job can
    // fail too, and a bare 500 said nothing about which.
    if (!isUnauthorized(error)) console.error("Preview error:", error);
    return routeError(error, "Failed to generate preview");
  }
}
