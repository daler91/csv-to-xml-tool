import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { prisma } from "@/lib/prisma";
import { workerFetch } from "@/lib/worker-client";
import type { ConvertResponse } from "@/types";

const DATA_DIR = process.env.DATA_DIR || "/data";

// Per-conversion worker timeout. Raised from the worker-client 5-min default so
// long-but-valid conversions complete. The queue's VISIBILITY_TIMEOUT_MS and the
// reaper's REAP_DEADLINE_MS both exceed this (see job-queue.ts / job-reaper.ts).
const CONVERSION_TIMEOUT_MS =
  Number(process.env.CONVERSION_TIMEOUT_MS) || 30 * 60 * 1000;

/**
 * Run one conversion job to a terminal state. Called by the durable-queue
 * consumer (src/lib/job-consumer.ts). This is the conversion logic that used to
 * live inline in the start route's fire-and-forget `.then`.
 *
 * Idempotent and race-safe: a guarded `updateMany` only proceeds while the job
 * is still queued/converting, so a cancelled/complete/error job — or a re-claimed
 * job already finished by a prior attempt — is a no-op. On worker failure this
 * THROWS so the consumer can decide retry vs dead-letter; it does NOT write
 * "error" itself.
 */
export async function runJob(jobId: string): Promise<void> {
  const job = await prisma.job.findUnique({ where: { id: jobId } });
  if (!job) return; // job deleted — nothing to do

  // Claim the job: flip queued -> converting. If it's no longer queued/converting
  // (cancelled, already terminal, or finished by a prior claim), skip cleanly.
  const claimed = await prisma.job.updateMany({
    where: { id: jobId, status: { in: ["queued", "converting"] } },
    data: { status: "converting" },
  });
  if (claimed.count === 0) return;

  await prisma.auditEntry.create({
    data: { userId: job.userId, jobId, action: "conversion_started" },
  });

  // Web and worker are separate Railway services with no shared volume, so we
  // send the CSV content and persist the XML the worker returns on our own disk.
  const csvContent = await readFile(job.inputFilePath, "utf-8");
  const result = await workerFetch<ConvertResponse>("/convert", {
    method: "POST",
    body: JSON.stringify({
      job_id: jobId,
      csv_content: csvContent,
      converter_type: job.converterType,
      column_mapping: job.columnMapping,
    }),
    timeoutMs: CONVERSION_TIMEOUT_MS,
  });

  // Persist the returned XML on our own disk; the download route serves it from
  // job.outputFilePath. Keyed on jobId, confined to DATA_DIR.
  const outputDir = path.join(DATA_DIR, "output", jobId);
  await mkdir(outputDir, { recursive: true });
  const outputFilePath = path.join(outputDir, `${jobId}.xml`);
  await writeFile(outputFilePath, result.xml_content, "utf-8");

  // Conditional update: only write "complete" if the job is still converting.
  // If a cancel landed in the race window, updateMany returns count=0 and we
  // discard the result (the file on disk is orphaned but harmless).
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

  if (updated.count === 0) return; // cancelled mid-flight — discard

  await prisma.auditEntry.create({
    data: {
      userId: job.userId,
      jobId,
      action: "conversion_complete",
      metadata: result.stats,
    },
  });
}
