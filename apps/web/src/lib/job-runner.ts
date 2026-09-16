import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { prisma } from "@/lib/prisma";
import { workerFetch } from "@/lib/worker-client";
import { CONVERSION_TIMEOUT_MS } from "@/lib/durability-timeouts";
import { decodeCsvBuffer } from "@/lib/csv-decode";
import type { ConvertResponse } from "@/types";

const DATA_DIR = process.env.DATA_DIR || "/data";

// Per-conversion worker timeout: CONVERSION_TIMEOUT_MS, raised from the
// worker-client 5-min default so long-but-valid conversions complete. The
// queue's VISIBILITY_TIMEOUT_MS and the reaper's REAP_DEADLINE_MS both exceed it
// (durability-timeouts.ts asserts the ordering at consumer startup).

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
export async function runJob(jobId: string, attempt = 1): Promise<void> {
  const job = await prisma.job.findUnique({ where: { id: jobId } });
  if (!job) return; // job deleted — nothing to do

  // Claim the job: flip queued -> converting. If it's no longer queued/converting
  // (cancelled, already terminal, or finished by a prior claim), skip cleanly.
  const claimed = await prisma.job.updateMany({
    where: { id: jobId, status: { in: ["queued", "converting"] } },
    data: { status: "converting" },
  });
  if (claimed.count === 0) return;

  // One "conversion_started" per job. A sweep re-claim or a requeue runs this
  // function again with a higher attempt number, and each run used to write
  // another "started" row, so a job retried three times showed three starts
  // in the audit trail; later attempts are recorded as retries instead.
  await prisma.auditEntry.create({
    data: {
      userId: job.userId,
      jobId,
      action: attempt > 1 ? "conversion_retried" : "conversion_started",
      metadata: { attempt },
    },
  });

  // Web and worker are separate Railway services with no shared volume, so we
  // send the CSV content and persist the XML the worker returns on our own disk.
  // Decoded with a cp1252 fallback rather than as bare UTF-8: an Excel
  // "CSV (Comma delimited)" export is the system code page, and a plain
  // utf-8 read turned every accented name into U+FFFD before the worker saw
  // it -- silently, since what the worker received was valid UTF-8.
  const { text: csvContent, encoding } = decodeCsvBuffer(
    await readFile(job.inputFilePath)
  );
  if (encoding !== "utf-8") {
    console.warn(`[job-runner] job ${jobId}: input decoded as ${encoding}, not UTF-8`);
  }
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

  // Prefer the worker's structured per-error details (line/row/field —
  // Contract B) when validation failed and they're present; fall back to the
  // raw string list for older workers. Both shapes share the Job.xsdErrors
  // Json column, so the results page branches on entry type when rendering.
  const xsdErrors =
    !result.xsd_valid && result.xsd_error_details?.length
      ? (result.xsd_error_details as object[])
      : result.xsd_errors;

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
      xsdErrors,
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
