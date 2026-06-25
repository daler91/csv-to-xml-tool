import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("@/lib/job-queue", () => ({
  ackJob: vi.fn(),
  requeueJob: vi.fn(),
  getAttempts: vi.fn(),
  claimJob: vi.fn(),
  sweepStaleClaims: vi.fn(),
}));
vi.mock("@/lib/job-runner", () => ({ runJob: vi.fn() }));
vi.mock("@/lib/prisma", () => ({
  prisma: {
    job: { updateMany: vi.fn(), findUnique: vi.fn() },
    auditEntry: { create: vi.fn() },
  },
}));

import { handleFailure, workerErrorStatus } from "@/lib/job-consumer";
import { ackJob, requeueJob, getAttempts } from "@/lib/job-queue";
import { prisma } from "@/lib/prisma";

const ack = vi.mocked(ackJob);
const requeue = vi.mocked(requeueJob);
const attempts = vi.mocked(getAttempts);
const db = vi.mocked(prisma, true);

const workerError = (status: number) =>
  new Error(`Worker error ${status}: boom`);

beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  db.job.updateMany.mockResolvedValue({ count: 1 } as never);
  db.job.findUnique.mockResolvedValue({ userId: "u1" } as never);
  db.auditEntry.create.mockResolvedValue({} as never);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("workerErrorStatus", () => {
  it("parses the status code, or null when there is none", () => {
    expect(workerErrorStatus("Worker error 422: bad")).toBe(422);
    expect(workerErrorStatus("Worker request to /convert timed out after 5ms")).toBeNull();
    expect(workerErrorStatus("fetch failed")).toBeNull();
  });
});

describe("handleFailure", () => {
  it("409 cancelled → ack and drop (no requeue, no dead-letter)", async () => {
    await handleFailure("j1", workerError(409));

    expect(ack).toHaveBeenCalledWith("j1");
    expect(requeue).not.toHaveBeenCalled();
    expect(db.job.updateMany).not.toHaveBeenCalled();
  });

  it("400 → dead-letter immediately, no retry", async () => {
    await handleFailure("j1", workerError(400));

    expect(db.job.updateMany).toHaveBeenCalledWith(
      expect.objectContaining({
        where: { id: "j1", status: "converting" },
        data: expect.objectContaining({ status: "error" }),
      })
    );
    expect(ack).toHaveBeenCalledWith("j1");
    expect(requeue).not.toHaveBeenCalled();
  });

  it("422 → dead-letter immediately", async () => {
    await handleFailure("j1", workerError(422));
    expect(db.job.updateMany).toHaveBeenCalled();
    expect(requeue).not.toHaveBeenCalled();
  });

  it("timeout → dead-letter immediately (a 30-min timeout isn't transient)", async () => {
    await handleFailure(
      "j1",
      new Error("Worker request to /convert timed out after 1800000ms")
    );
    expect(db.job.updateMany).toHaveBeenCalled();
    expect(requeue).not.toHaveBeenCalled();
  });

  it("transient 5xx with attempts remaining → requeue", async () => {
    attempts.mockResolvedValue(1);

    const p = handleFailure("j1", workerError(500));
    await vi.advanceTimersByTimeAsync(2000); // skip the backoff sleep
    await p;

    expect(requeue).toHaveBeenCalledWith("j1");
    expect(db.job.updateMany).not.toHaveBeenCalled();
  });

  it("network error (no status) with attempts remaining → requeue", async () => {
    attempts.mockResolvedValue(0);

    const p = handleFailure("j1", new Error("fetch failed"));
    await vi.advanceTimersByTimeAsync(2000);
    await p;

    expect(requeue).toHaveBeenCalledWith("j1");
  });

  it("transient but attempts exhausted → dead-letter", async () => {
    attempts.mockResolvedValue(3); // == MAX_ATTEMPTS default

    await handleFailure("j1", workerError(500));

    expect(requeue).not.toHaveBeenCalled();
    expect(db.job.updateMany).toHaveBeenCalled();
    expect(ack).toHaveBeenCalledWith("j1");
  });
});
