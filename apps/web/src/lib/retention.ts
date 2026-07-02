import { rm } from "node:fs/promises";
import path from "node:path";
import type { JobStatus } from "@prisma/client";
import { prisma } from "@/lib/prisma";
import { RETENTION_DAYS } from "@/lib/limits";

const DATA_DIR = process.env.DATA_DIR || "/data";

// Never purge a job the queue may still be working on — the runner
// needs the input file and is about to write the output file.
const ACTIVE_STATUSES: JobStatus[] = ["queued", "converting"];

// Bound per invocation so the sweep stays cheap on the read paths it
// piggybacks on (dashboard, /api/jobs) — the same lazy-reconciliation
// pattern as reapStuckConvertingJobs. A backlog drains across visits.
const MAX_PURGES_PER_SWEEP = 25;

/**
 * Deletes the on-disk files (uploaded CSV, generated XML) of this
 * user's jobs older than RETENTION_DAYS. The job row, its results
 * summary, and the audit trail are all kept — only the files go, and
 * `filesPurgedAt` records that they did so the UI can say "expired"
 * instead of failing a download.
 *
 * Returns the number of jobs whose files were purged.
 */
export async function purgeExpiredJobFiles(userId: string): Promise<number> {
  // Fail-open: this is background maintenance piggybacking on read paths —
  // a sweep failure (e.g. a schema mismatch) must never take the dashboard
  // down with it. Log and move on; the next read retries.
  try {
    return await sweepExpiredJobFiles(userId);
  } catch (error) {
    console.error("[retention] purge sweep failed:", error);
    return 0;
  }
}

async function sweepExpiredJobFiles(userId: string): Promise<number> {
  const cutoff = new Date(
    Date.now() - RETENTION_DAYS * 24 * 60 * 60 * 1000
  );

  const expired = await prisma.job.findMany({
    where: {
      userId,
      createdAt: { lt: cutoff },
      filesPurgedAt: null,
      status: { notIn: ACTIVE_STATUSES },
    },
    select: { id: true, inputFileName: true },
    take: MAX_PURGES_PER_SWEEP,
  });

  let purged = 0;
  for (const job of expired) {
    // Claim before deleting so two concurrent read paths can't both
    // purge (and double-write audit entries) for the same job.
    const claimed = await prisma.job.updateMany({
      where: { id: job.id, filesPurgedAt: null },
      data: {
        filesPurgedAt: new Date(),
        inputFilePath: "",
        outputFilePath: null,
      },
    });
    if (claimed.count === 0) continue;

    // Paths are built from the DB-issued job id (cuid), not user input.
    await rm(path.join(DATA_DIR, "uploads", job.id), {
      recursive: true,
      force: true,
    }).catch(() => {});
    await rm(path.join(DATA_DIR, "output", job.id), {
      recursive: true,
      force: true,
    }).catch(() => {});

    purged += 1;
    await prisma.auditEntry.create({
      data: {
        userId,
        jobId: job.id,
        action: "files_purged",
        metadata: {
          fileName: job.inputFileName,
          retentionDays: RETENTION_DAYS,
        },
      },
    });
  }

  return purged;
}
