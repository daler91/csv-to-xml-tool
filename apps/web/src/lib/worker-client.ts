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
