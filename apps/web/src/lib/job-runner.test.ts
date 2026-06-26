import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/prisma", () => ({
  prisma: {
    job: { findUnique: vi.fn(), updateMany: vi.fn() },
    auditEntry: { create: vi.fn() },
  },
}));
vi.mock("@/lib/worker-client", () => ({ workerFetch: vi.fn() }));
vi.mock("node:fs/promises", () => ({
  readFile: vi.fn(),
  mkdir: vi.fn(),
  writeFile: vi.fn(),
}));

import { runJob } from "@/lib/job-runner";
import { prisma } from "@/lib/prisma";
import { workerFetch } from "@/lib/worker-client";
import { readFile, writeFile } from "node:fs/promises";

const db = vi.mocked(prisma, true);
const worker = vi.mocked(workerFetch);
const read = vi.mocked(readFile);
const write = vi.mocked(writeFile);

const JOB = {
  id: "j1",
  userId: "u1",
  inputFileName: "in.csv",
  inputFilePath: "/data/uploads/j1/in.csv",
  converterType: "counseling",
  columnMapping: null,
};
const RESULT = {
  xml_content: '<?xml version="1.0"?><CounselingInformation/>',
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
  it("claims, sends CSV content, persists the returned XML, and completes", async () => {
    db.job.findUnique.mockResolvedValue(JOB as never);
    db.job.updateMany
      .mockResolvedValueOnce({ count: 1 } as never) // claim queued→converting
      .mockResolvedValueOnce({ count: 1 } as never); // converting→complete
    db.auditEntry.create.mockResolvedValue({} as never);
    read.mockResolvedValue("Contact ID\n003\n" as never);
    worker.mockResolvedValue(RESULT as never);

    await runJob("j1");

    // The CSV content is sent to the worker (no shared volume / file path).
    expect(read).toHaveBeenCalledWith("/data/uploads/j1/in.csv", "utf-8");
    expect(worker).toHaveBeenCalledWith(
      "/convert",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining("csv_content"),
      })
    );
    // The returned XML is written to our own disk at the deterministic path.
    expect(write).toHaveBeenCalledWith(
      "/data/output/j1/j1.xml",
      RESULT.xml_content,
      "utf-8"
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
    read.mockResolvedValue("Contact ID\n003\n" as never);
    worker.mockResolvedValue(RESULT as never);

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
    read.mockResolvedValue("Contact ID\n003\n" as never);
    worker.mockRejectedValue(new Error("Worker error 422: bad data"));

    await expect(runJob("j1")).rejects.toThrow(/Worker error 422/);
  });
});
