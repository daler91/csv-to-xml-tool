/**
 * Shared helpers for the QUAL-1 web test suite.
 *
 * Note: the Prisma / session / worker mocks are declared per-file with
 * `vi.mock(...)` (their factories must be hoisted, so they can't live here).
 * This module only provides plain data + Request builders used in test bodies.
 */

export const TEST_USER = {
  id: "user-1",
  email: "test@example.com",
  name: "Test User",
} as const;

export const OTHER_USER = {
  id: "user-2",
  email: "other@example.com",
  name: "Other User",
} as const;

/** The `{ params }` context Next passes to a dynamic `[jobId]` route handler. */
export function jobParams(jobId: string): {
  params: Promise<{ jobId: string }>;
} {
  return { params: Promise.resolve({ jobId }) };
}

/** A JSON Request for routes that read `req.json()`. */
export function jsonRequest(
  url: string,
  method: string,
  body?: unknown
): Request {
  return new Request(url, {
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/** A multipart upload Request for the /api/upload route. */
export function uploadRequest(opts: {
  fileName?: string;
  content?: string;
  converterType?: string;
  previousJobId?: string;
  omitFile?: boolean;
}): Request {
  const form = new FormData();
  if (!opts.omitFile) {
    form.append(
      "file",
      new File([opts.content ?? "a,b\n1,2\n"], opts.fileName ?? "data.csv", {
        type: "text/csv",
      })
    );
  }
  if (opts.converterType !== undefined)
    form.append("converterType", opts.converterType);
  if (opts.previousJobId !== undefined)
    form.append("previousJobId", opts.previousJobId);
  return new Request("http://localhost/api/upload", {
    method: "POST",
    body: form,
  });
}
