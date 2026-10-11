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

// Batches per scheduled run: up to 8 × 25 jobs an hour across all users.
const MAX_SWEEPS_PER_RUN = 8;

/**
 * The same purge for every user, run on a timer by the job consumer.
 *
 * The read-path sweep above only ever reached users who came back to the
 * dashboard, so a partner who uploaded client records (names, phones,
 * addresses) and never signed in again kept them on the volume indefinitely
 * -- while the upload form promised they "are automatically deleted after N
 * days". Safe to run on every web instance at once: each purge is claimed by
 * a guarded update first. Fail-open like the read-path sweep.
 */
export async function purgeAllExpiredJobFiles(): Promise<number> {
  let total = 0;
  try {
    for (let i = 0; i < MAX_SWEEPS_PER_RUN; i += 1) {
      const purged = await sweepExpiredJobFiles(null);
      total += purged;
      if (purged < MAX_PURGES_PER_SWEEP) break;
    }
  } catch (error) {
    console.error("[retention] scheduled purge failed:", error);
  }
  return total;
}

async function sweepExpiredJobFiles(userId: string | null): Promise<number> {
  const cutoff = new Date(
    Date.now() - RETENTION_DAYS * 24 * 60 * 60 * 1000
  );

  const expired = await prisma.job.findMany({
    where: {
      ...(userId ? { userId } : {}),
      createdAt: { lt: cutoff },
      filesPurgedAt: null,
      status: { notIn: ACTIVE_STATUSES },
    },
    select: { id: true, userId: true, inputFileName: true },
    take: MAX_PURGES_PER_SWEEP,
  });

  let purged = 0;
  for (const job of expired) {
    // Claim before deleting so two concurrent read paths can't both
    // purge (and double-write audit entries) for the same job. The status
    // predicate is repeated here, not only in the findMany above: a
    // POST /start landing between the two flips the job to queued, and
    // purging its input then would dead-letter the conversion with ENOENT.
    const claimed = await prisma.job.updateMany({
      where: {
        id: job.id,
        filesPurgedAt: null,
        status: { notIn: ACTIVE_STATUSES },
      },
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
        userId: job.userId,
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
