import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/prisma", () => ({
  prisma: {
    job: { findMany: vi.fn(), updateMany: vi.fn() },
    auditEntry: { create: vi.fn() },
  },
}));
vi.mock("node:fs/promises", () => ({ rm: vi.fn() }));

import { rm } from "node:fs/promises";
import { purgeExpiredJobFiles } from "@/lib/retention";
import { prisma } from "@/lib/prisma";

const db = vi.mocked(prisma, true);
const fsRm = vi.mocked(rm);

beforeEach(() => {
  vi.resetAllMocks();
  fsRm.mockResolvedValue(undefined as never);
});

describe("purgeExpiredJobFiles", () => {
  it("removes files, marks the job purged, and audits", async () => {
    db.job.findMany.mockResolvedValue([
      { id: "old-1", inputFileName: "jan.csv" },
    ] as never);
    db.job.updateMany.mockResolvedValue({ count: 1 } as never);

    const purged = await purgeExpiredJobFiles("user-1");

    expect(purged).toBe(1);
    const rmPaths = fsRm.mock.calls.map((c) => String(c[0]));
    expect(rmPaths.some((p) => p.includes("uploads") && p.includes("old-1"))).toBe(true);
    expect(rmPaths.some((p) => p.includes("output") && p.includes("old-1"))).toBe(true);
    expect(db.job.updateMany.mock.calls[0][0].data).toMatchObject({
      inputFilePath: "",
      outputFilePath: null,
    });
    expect(db.auditEntry.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({ action: "files_purged", jobId: "old-1" }),
      })
    );
  });

  it("never selects jobs the queue may still be working on", async () => {
    db.job.findMany.mockResolvedValue([] as never);
    await purgeExpiredJobFiles("user-1");
    const where = db.job.findMany.mock.calls[0]?.[0]?.where;
    expect(where?.status).toEqual({
      notIn: expect.arrayContaining(["queued", "converting"]),
    });
    expect(where?.filesPurgedAt).toBeNull();
  });

  it("fails open when the sweep query throws (dashboard must not 500)", async () => {
    db.job.findMany.mockRejectedValue(
      new Error("column Job.filesPurgedAt does not exist")
    );
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    await expect(purgeExpiredJobFiles("user-1")).resolves.toBe(0);
    expect(errorSpy).toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  it("skips a job another sweep claimed first (count 0) without touching files", async () => {
    db.job.findMany.mockResolvedValue([
      { id: "old-1", inputFileName: "jan.csv" },
    ] as never);
    db.job.updateMany.mockResolvedValue({ count: 0 } as never);

    const purged = await purgeExpiredJobFiles("user-1");

    expect(purged).toBe(0);
    expect(fsRm).not.toHaveBeenCalled();
    expect(db.auditEntry.create).not.toHaveBeenCalled();
  });
});
