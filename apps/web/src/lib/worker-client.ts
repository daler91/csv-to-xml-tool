const WORKER_URL = process.env.WORKER_URL || "http://localhost:8000";
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
        ...fetchOptions?.headers,
      },
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Worker error ${res.status}: ${text}`);
    }

    return res.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`Worker request to ${path} timed out after ${timeoutMs}ms`);
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}
