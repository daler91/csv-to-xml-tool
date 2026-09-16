/**
 * Human-friendly error messages for /api/upload responses.
 *
 * Resolves docs/reviews/UX_REVIEW.md §4.1. The old client code flattened every
 * non-2xx response into ``data.error || "Upload failed"``, which
 * gave partners no diagnostic. This helper maps the known HTTP
 * status codes the upload route actually returns to concrete,
 * actionable messages.
 *
 * Keep the mapping in sync with ``apps/web/src/app/api/upload/route.ts``.
 */

import { formatMegabytes } from "@/lib/limits";

const DEFAULT_CAP_BYTES = 50 * 1024 * 1024;

export function uploadErrorMessage(
  status: number,
  serverError?: string,
  // The cap the server enforces, passed down from a server component so the
  // message matches a deployment that overrides MAX_UPLOAD_BYTES.
  maxUploadBytes: number = DEFAULT_CAP_BYTES
): string {
  switch (status) {
    case 413:
      return `This file is larger than ${formatMegabytes(maxUploadBytes)}. Split it into smaller batches or remove unused columns and try again.`;
    case 429:
      return "You've uploaded several files in a short window. Please wait about a minute and try again.";
    case 401:
    case 403:
      return "Your session expired. Please sign in again to continue.";
    case 400: {
      const msg = (serverError || "").toLowerCase();
      if (msg.includes("csv")) {
        return "That file isn't a CSV. Export it from Excel (or Salesforce) as a .csv file and try again.";
      }
      if (msg.includes("converter type")) {
        return "Please pick a converter type before uploading.";
      }
      if (msg.includes("required")) {
        return "Please select a file and a converter type before uploading.";
      }
      return (
        serverError ||
        "The upload was rejected. Check your file and converter type, then try again."
      );
    }
    case 500:
    case 502:
    case 503:
    case 504:
      return "Something went wrong on our side. Please try again in a minute. If it keeps happening, contact support.";
    default:
      return serverError || "Upload failed. Please try again.";
  }
}
