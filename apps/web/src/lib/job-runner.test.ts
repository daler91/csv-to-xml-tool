import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/prisma", () => ({
  prisma: {
    job: { findUnique: vi.fn(), updateMany: vi.fn() },
    auditEntry: { create: vi.fn() },
  },
}));
vi.mock("@/lib/worker-client", () => ({ workerFetch: vi.fn() }));
vi.mock("@/lib/paths", () => ({ resolveWithinDataDir: vi.fn() }));

import { runJob } from "@/lib/job-runner";
import { prisma } from "@/lib/prisma";
import { workerFetch } from "@/lib/worker-client";
import { resolveWithinDataDir } from "@/lib/paths";

const db = vi.mocked(prisma, true);
const worker = vi.mocked(workerFetch);
const resolvePath = vi.mocked(resolveWithinDataDir);

const JOB = {
  id: "j1",
  userId: "u1",
  inputFileName: "in.csv",
  converterType: "counseling",
  columnMapping: null,
};
const RESULT = {
  stats: { total: 10 },
  issues: [],
  cleaning_diff: [],
  xsd_valid: true,
  xsd_errors: [],
};

beforeEach(() => {
  vi.resetAllMocks();
});

describe("runJob", () => {
  it("claims, calls the worker, and writes complete with the re-derived output path", async () => {
    db.job.findUnique.mockResolvedValue(JOB as never);
    db.job.updateMany
      .mockResolvedValueOnce({ count: 1 } as never) // claim queued→converting
      .mockResolvedValueOnce({ count: 1 } as never); // converting→complete
    db.auditEntry.create.mockResolvedValue({} as never);
    worker.mockResolvedValue(RESULT as never);
    resolvePath.mockResolvedValue("/data/output/j1/j1.xml");

    await runJob("j1");

    expect(worker).toHaveBeenCalledWith(
      "/convert",
      expect.objectContaining({ method: "POST" })
    );
    expect(db.job.updateMany).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        where: { id: "j1", status: "converting" },
        data: expect.objectContaining({
          status: "complete",
          outputFilePath: "/data/output/j1/j1.xml",
          totalRows: 10,
        }),
      })
    );
    expect(db.auditEntry.create).toHaveBeenCalledTimes(2); // started + complete
  });

  it("no-ops when the job was deleted", async () => {
    db.job.findUnique.mockResolvedValue(null as never);

    await runJob("j1");

    expect(db.job.updateMany).not.toHaveBeenCalled();
    expect(worker).not.toHaveBeenCalled();
  });

  it("no-ops when the claim is lost (job already terminal)", async () => {
    db.job.findUnique.mockResolvedValue(JOB as never);
    db.job.updateMany.mockResolvedValueOnce({ count: 0 } as never);

    await runJob("j1");

    expect(worker).not.toHaveBeenCalled();
    expect(db.auditEntry.create).not.toHaveBeenCalled();
  });

  it("discards the result when cancelled mid-flight (final update count 0)", async () => {
    db.job.findUnique.mockResolvedValue(JOB as never);
    db.job.updateMany
      .mockResolvedValueOnce({ count: 1 } as never) // claim
      .mockResolvedValueOnce({ count: 0 } as never); // cancelled before complete
    db.auditEntry.create.mockResolvedValue({} as never);
    worker.mockResolvedValue(RESULT as never);
    resolvePath.mockResolvedValue("/data/output/j1/j1.xml");

    await runJob("j1");

    // only the "started" audit — never "complete"
    expect(db.auditEntry.create).toHaveBeenCalledTimes(1);
    expect(db.auditEntry.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({ action: "conversion_started" }),
      })
    );
  });

  it("propagates worker errors so the consumer decides retry vs dead-letter", async () => {
    db.job.findUnique.mockResolvedValue(JOB as never);
    db.job.updateMany.mockResolvedValueOnce({ count: 1 } as never);
    worker.mockRejectedValue(new Error("Worker error 422: bad data"));

    await expect(runJob("j1")).rejects.toThrow(/Worker error 422/);
  });
});
