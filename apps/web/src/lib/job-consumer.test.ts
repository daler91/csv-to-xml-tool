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

import {
  handleFailure,
  processClaim,
  runLoop,
  startConsumer,
  stopConsumer,
  workerErrorStatus,
} from "@/lib/job-consumer";
import {
  ackJob,
  requeueJob,
  getAttempts,
  claimJob,
  sweepStaleClaims,
} from "@/lib/job-queue";
import { runJob } from "@/lib/job-runner";
import { prisma } from "@/lib/prisma";

const ack = vi.mocked(ackJob);
const requeue = vi.mocked(requeueJob);
const attempts = vi.mocked(getAttempts);
const claim = vi.mocked(claimJob);
const sweep = vi.mocked(sweepStaleClaims);
const run = vi.mocked(runJob);
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


describe("processClaim", () => {
  it("runs the job with its attempt number and acks it", async () => {
    attempts.mockResolvedValue(2);
    run.mockResolvedValue(undefined);

    await processClaim("j1");

    expect(run).toHaveBeenCalledWith("j1", 2);
    expect(ack).toHaveBeenCalledWith("j1");
    expect(db.job.updateMany).not.toHaveBeenCalled();
  });

  it("dead-letters a job claimed more than MAX_ATTEMPTS times without running it", async () => {
    // A job that crashes the process never reaches handleFailure; the sweep
    // re-queues it every visibility window. The cap has to bite at claim time.
    attempts.mockResolvedValue(4); // MAX_ATTEMPTS default is 3

    await processClaim("j1");

    expect(run).not.toHaveBeenCalled();
    expect(db.job.updateMany).toHaveBeenCalledWith(
      expect.objectContaining({
        where: { id: "j1", status: "converting" },
        data: expect.objectContaining({ status: "error" }),
      })
    );
    expect(db.auditEntry.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          action: "conversion_deadlettered",
          metadata: { error: expect.stringMatching(/claimed 4 times/) },
        }),
      })
    );
    expect(ack).toHaveBeenCalledWith("j1");
  });

  it("allows exactly MAX_ATTEMPTS runs", async () => {
    attempts.mockResolvedValue(3);
    run.mockResolvedValue(undefined);

    await processClaim("j1");

    expect(run).toHaveBeenCalledWith("j1", 3);
  });

  it("routes a failing run through handleFailure", async () => {
    attempts.mockResolvedValue(1);
    run.mockRejectedValue(workerError(422));

    await processClaim("j1");

    expect(db.job.updateMany).toHaveBeenCalled(); // dead-lettered (permanent)
    expect(requeue).not.toHaveBeenCalled();
  });
});

describe("runLoop", () => {
  it("survives a failure handler that itself throws", async () => {
    // Claim j1, whose run fails; handling that failure hits Redis (getAttempts)
    // which throws too. The loop must log, back off, and claim again rather
    // than reject and never claim another job.
    let calls = 0;
    claim.mockImplementation(async () => (++calls === 1 ? "j1" : null));
    attempts.mockRejectedValue(new Error("ECONNRESET"));
    run.mockRejectedValue(new Error("fetch failed"));
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});

    const loop = runLoop(() => calls < 3);
    await vi.advanceTimersByTimeAsync(5000);
    await loop;

    expect(calls).toBe(3);
    expect(errorLog).toHaveBeenCalledWith(
      expect.stringMatching(/failure handling for job j1 threw/),
      expect.any(Error)
    );
    errorLog.mockRestore();
  });

  it("backs off and keeps going when a claim throws", async () => {
    let calls = 0;
    claim.mockImplementation(async () => {
      calls += 1;
      if (calls === 1) throw new Error("Redis down");
      return null;
    });
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});

    const loop = runLoop(() => calls < 2);
    await vi.advanceTimersByTimeAsync(2000);
    await loop;

    expect(calls).toBe(2);
    errorLog.mockRestore();
  });
});

describe("startConsumer", () => {
  it("does not wait for the boot sweep, so an unreachable Redis cannot block startup", async () => {
    // A sweep whose promise never settles is what an unreachable Redis looks
    // like under maxRetriesPerRequest: null. register() awaits startConsumer,
    // so startConsumer must resolve regardless.
    sweep.mockReturnValue(new Promise(() => {}));
    // Park the loop on a claim that never returns (what BLMOVE against an
    // unreachable Redis looks like) so it does not spin for the rest of the run.
    claim.mockReturnValue(new Promise(() => {}));
    const log = vi.spyOn(console, "log").mockImplementation(() => {});

    let started = false;
    const p = startConsumer().then(() => {
      started = true;
    });
    await vi.advanceTimersByTimeAsync(0);
    await p;
    stopConsumer();

    expect(started).toBe(true);
    expect(sweep).toHaveBeenCalledTimes(1);
    expect(claim).toHaveBeenCalledTimes(1);
    log.mockRestore();
  });
});
