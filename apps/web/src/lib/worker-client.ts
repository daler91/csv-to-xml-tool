const WORKER_URL = process.env.WORKER_URL || "http://localhost:8000";

export async function workerFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${WORKER_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Worker error ${res.status}: ${text}`);
  }

  return res.json();
}
