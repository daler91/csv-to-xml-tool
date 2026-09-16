const WORKER_URL = process.env.WORKER_URL || "http://localhost:8000";
const WORKER_AUTH_TOKEN = process.env.WORKER_AUTH_TOKEN || "";
const DEFAULT_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

export async function workerFetch<T>(
  path: string,
  options?: RequestInit & { timeoutMs?: number }
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchOptions } = options ?? {};
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${WORKER_URL}${path}`, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        // SEC-1: authenticate every worker call with the shared bearer token.
        ...(WORKER_AUTH_TOKEN
          ? { Authorization: `Bearer ${WORKER_AUTH_TOKEN}` }
          : {}),
        ...fetchOptions?.headers,
      },
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Worker error ${res.status}: ${text}`);
    }

    // `await`, not a bare `return res.json()`: without it the `finally` ran
    // (and cleared the timeout) as soon as the headers arrived, so a stalled
    // body download -- and for /convert the body is the payload -- was never
    // aborted, and a body-read failure bypassed the `catch` and surfaced as a
    // raw SyntaxError instead of the "Worker error" shapes the consumer's
    // retry classification keys on.
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`Worker request to ${path} timed out after ${timeoutMs}ms`);
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * The worker's own detail message when it rejected the *request content*
 * with a deterministic 400 or 422 (malformed CSV, unsupported schema type,
 * empty content) — the caller's problem, to surface as a 400. Returns null
 * for everything else, including the other 4xx codes that are the
 * deployment's problem and must not be relabelled as a bad file: 401/403 is a
 * wrong WORKER_AUTH_TOKEN, 413 is the worker's MAX_REQUEST_BYTES, 429 is
 * throttling. Those fall through to the route's 502 path and its log line.
 */
export function workerClientError(error: unknown): string | null {
  if (!(error instanceof Error)) return null;
  const match = /^Worker error (400|422): ([\s\S]*)$/.exec(error.message);
  if (!match) return null;
  try {
    const detail = JSON.parse(match[2])?.detail;
    if (typeof detail === "string" && detail) return detail;
  } catch {
    // Non-JSON body — use a generic message below.
  }
  return "The file could not be processed";
}
