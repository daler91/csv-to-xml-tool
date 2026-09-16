/**
 * The user-facing reason a job ended in `error`.
 *
 * A failed conversion has no column of its own: `deadLetter`
 * (job-consumer.ts) and the reaper (job-reaper.ts) flip the status and put
 * the reason in the audit trail only, so the results page rendered an
 * `error` job as an empty "Conversion Results" with no summary and no
 * message. This turns that audit metadata into a sentence the page can show.
 */

export const FAILURE_ACTIONS = ["conversion_deadlettered", "conversion_timeout"] as const;

export interface FailureAuditEntry {
  action: string;
  metadata: unknown;
}

const WORKER_ERROR = /^Worker error (\d+): ([\s\S]*)$/;

/** The worker's `detail` string from a "Worker error NNN: {json}" message. */
function workerDetail(message: string): { status: number; detail: string | null } | null {
  const match = WORKER_ERROR.exec(message);
  if (!match) return null;
  let detail: string | null = null;
  try {
    const parsed = JSON.parse(match[2])?.detail;
    if (typeof parsed === "string" && parsed) detail = parsed;
  } catch {
    // Non-JSON body — no detail to show.
  }
  return { status: Number(match[1]), detail };
}

export function describeJobFailure(entry: FailureAuditEntry | null): string {
  if (!entry) {
    return "The conversion failed, but no reason was recorded. Try re-uploading the file.";
  }
  const metadata =
    entry.metadata && typeof entry.metadata === "object"
      ? (entry.metadata as Record<string, unknown>)
      : {};

  if (entry.action === "conversion_timeout") {
    return "The conversion did not finish within the time limit and was stopped. Try again; if it keeps happening, split the file into smaller batches.";
  }

  const raw = typeof metadata.error === "string" ? metadata.error : "";
  if (/timed out/i.test(raw)) {
    return "The worker did not respond within the conversion time limit. Try again; if it keeps happening, split the file into smaller batches.";
  }
  if (/attempts exhausted/i.test(raw)) {
    return "The conversion was retried and crashed each time. The file may be too large for the service; try a smaller batch or contact support.";
  }
  const worker = workerDetail(raw);
  if (worker) {
    if (worker.status === 422 || worker.status === 400) {
      return worker.detail
        ? `The file could not be converted: ${worker.detail}`
        : "The file could not be converted because the worker rejected its content.";
    }
    return "The conversion service failed while processing this file. Try again in a few minutes; if it keeps happening, contact support.";
  }
  if (raw) {
    return "The conversion could not be completed after several attempts. Try again in a few minutes; if it keeps happening, contact support.";
  }
  return "The conversion failed, but no reason was recorded. Try re-uploading the file.";
}
