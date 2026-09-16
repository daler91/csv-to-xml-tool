import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { workerFetch } from "@/lib/worker-client";

// A Response whose body promise is controlled by the test, so the timeout
// behaviour *after* the headers arrive can be observed.
function responseWithBody(body: Promise<unknown>, init: { ok?: boolean; status?: number } = {}) {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: () => body,
    text: () => body.then((b) => JSON.stringify(b)),
  } as unknown as Response;
}

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.useFakeTimers();
  fetchMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("workerFetch", () => {
  it("returns the parsed body", async () => {
    fetchMock.mockResolvedValue(responseWithBody(Promise.resolve({ ok: 1 })));
    await expect(workerFetch("/x")).resolves.toEqual({ ok: 1 });
  });

  it("throws 'Worker error <status>: <body>' on a non-OK response", async () => {
    fetchMock.mockResolvedValue(
      responseWithBody(Promise.resolve({ detail: "nope" }), { ok: false, status: 422 })
    );
    await expect(workerFetch("/x")).rejects.toThrow('Worker error 422: {"detail":"nope"}');
  });

  it("keeps the timeout armed while the body is still downloading", async () => {
    // Headers arrive at once; the body never does. The abort must still fire.
    let abortSignal: AbortSignal | undefined;
    fetchMock.mockImplementation((_url: string, init: RequestInit) => {
      abortSignal = init.signal as AbortSignal;
      return Promise.resolve(
        responseWithBody(new Promise(() => {} /* never settles */))
      );
    });

    const pending = workerFetch("/convert", { timeoutMs: 5000 });
    await vi.advanceTimersByTimeAsync(4999);
    expect(abortSignal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(abortSignal?.aborted).toBe(true);
    // The promise itself stays pending until the aborted stream rejects,
    // which a real fetch does; the assertion above is the one that matters.
    void pending.catch(() => {});
  });

  it("surfaces a body-read failure through the same catch as a network error", async () => {
    fetchMock.mockResolvedValue(
      responseWithBody(Promise.reject(new SyntaxError("Unexpected end of JSON input")))
    );
    await expect(workerFetch("/x")).rejects.toThrow("Unexpected end of JSON input");
  });

  it("translates an abort into a 'timed out' error", async () => {
    fetchMock.mockImplementation((_url: string, init: RequestInit) => {
      const signal = init.signal as AbortSignal;
      return new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () =>
          reject(new DOMException("The operation was aborted.", "AbortError"))
        );
      });
    });

    // Attach the assertion before advancing the clock, or the rejection is
    // unhandled for a tick and vitest reports it as an error.
    const assertion = expect(workerFetch("/slow", { timeoutMs: 10 })).rejects.toThrow(
      "timed out after 10ms"
    );
    await vi.advanceTimersByTimeAsync(10);
    await assertion;
  });
});
