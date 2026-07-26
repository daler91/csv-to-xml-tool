import { NextResponse } from "next/server";
import type { JobStatus } from "@prisma/client";
import { stat } from "node:fs/promises";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { routeError } from "@/lib/api-errors";
import { MAX_UPLOAD_BYTES } from "@/lib/limits";
import { enqueueJob } from "@/lib/job-queue";

// Statuses a job can transition *out of* into the queue.
// A cancelled/complete/error job can't be started — the user should re-upload
// instead. A job already queued/converting can't be started a second time.
const STARTABLE_STATUSES: ReadonlySet<JobStatus> = new Set<JobStatus>([
  "uploaded",
  "previewed",
  "mapping",
]);

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

    if (!STARTABLE_STATUSES.has(job.status)) {
      return NextResponse.json(
        {
          error:
            `This job is ${job.status} and can't be started. Upload the file again if you want to re-convert.`,
        },
        { status: 409 }
      );
    }

    // Retention blanks inputFilePath when it purges the upload, and a job can
    // still be in a startable state at that point (the sweep only excludes
    // queued/converting). Without this, stat("") threw ENOENT and the user got
    // an opaque 500 instead of being told the file had expired.
    if (job.filesPurgedAt || !job.inputFilePath) {
      return NextResponse.json(
        {
          error:
            "The uploaded file for this job has expired and been removed. Upload it again to convert.",
        },
        { status: 410 }
      );
    }

    // SEC-1: re-enforce the upload size cap server-side. The conversion itself
    // now happens later in the queue consumer, but the cap is cheap to check
    // here before we commit the job to the queue.
    const { size: inputSize } = await stat(job.inputFilePath);
    if (inputSize > MAX_UPLOAD_BYTES) {
      return NextResponse.json(
        { error: "File size exceeds 50MB limit" },
        { status: 413 }
      );
    }

    // ARCH-1: durable, web-owned queue. Guarded transition to "queued" closes the
    // read-then-write race (if the job is cancelled / otherwise transitions
    // between the findFirst above and here, updateMany returns count=0 and we
    // bail). The background consumer (src/lib/job-consumer.ts) then claims the
    // job, flips it to "converting", runs the conversion and persists the result,
    // re-claiming on restart — so a web crash/redeploy no longer strands the job.
    const started = await prisma.job.updateMany({
      where: {
        id: jobId,
        userId: user.id,
        status: { in: [...STARTABLE_STATUSES] },
      },
      data: { status: "queued" },
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

    // The job is durably "queued" in the DB; enqueue it for the consumer.
    //
    // If the push fails (Redis down) the row is already "queued", so a retry
    // hits the STARTABLE_STATUSES gate above and 409s — the job used to sit
    // wedged until the reaper failed it a full REAP_DEADLINE_MS later (1 hour
    // by default) with no explanation. Roll the status back so the user can
    // simply try again.
    try {
      await enqueueJob(jobId);
    } catch (enqueueError) {
      await prisma.job.updateMany({
        where: { id: jobId, userId: user.id, status: "queued" },
        data: { status: job.status },
      });
      console.error("Failed to enqueue job", jobId, enqueueError);
      return NextResponse.json(
        {
          error:
            "Couldn't queue the conversion just now. Please try again in a moment.",
        },
        { status: 503 }
      );
    }

    return NextResponse.json({ status: "queued" }, { status: 202 });
  } catch (error) {
    return routeError(error, "Failed to start conversion");
  }
}
