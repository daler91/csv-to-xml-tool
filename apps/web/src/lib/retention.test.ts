import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/prisma", () => ({
  prisma: {
    job: { findMany: vi.fn(), updateMany: vi.fn() },
    auditEntry: { create: vi.fn() },
  },
}));
vi.mock("node:fs/promises", () => ({ rm: vi.fn() }));

import { rm } from "node:fs/promises";
import { purgeAllExpiredJobFiles, purgeExpiredJobFiles } from "@/lib/retention";
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
      { id: "old-1", userId: "user-1", inputFileName: "jan.csv" },
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
    // The claim repeats the status guard: a POST /start that flips the job to
    // queued between the select and the claim must not lose its input file.
    expect(db.job.updateMany.mock.calls[0][0].where).toMatchObject({
      filesPurgedAt: null,
      status: { notIn: expect.arrayContaining(["queued", "converting"]) },
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
      { id: "old-1", userId: "user-1", inputFileName: "jan.csv" },
    ] as never);
    db.job.updateMany.mockResolvedValue({ count: 0 } as never);

    const purged = await purgeExpiredJobFiles("user-1");

    expect(purged).toBe(0);
    expect(fsRm).not.toHaveBeenCalled();
    expect(db.auditEntry.create).not.toHaveBeenCalled();
  });
});

describe("purgeAllExpiredJobFiles", () => {
  it("covers every user, auditing each purge under the job's owner", async () => {
    // The read-path sweep only reached users who came back to the dashboard;
    // one who never signed in again kept client data on disk indefinitely.
    db.job.findMany.mockResolvedValueOnce([
      { id: "a", userId: "user-1", inputFileName: "a.csv" },
      { id: "b", userId: "user-2", inputFileName: "b.csv" },
    ] as never);
    db.job.updateMany.mockResolvedValue({ count: 1 } as never);

    const purged = await purgeAllExpiredJobFiles();

    expect(purged).toBe(2);
    expect(db.job.findMany.mock.calls[0]?.[0]?.where).not.toHaveProperty("userId");
    const owners = db.auditEntry.create.mock.calls.map((c) => c[0].data.userId);
    expect(owners).toEqual(["user-1", "user-2"]);
    // A short batch means the backlog is drained: no second query.
    expect(db.job.findMany).toHaveBeenCalledTimes(1);
  });

  it("keeps going while batches come back full, up to a bound", async () => {
    const full = Array.from({ length: 25 }, (_, i) => ({ id: `j${i}`, userId: "u", inputFileName: "x.csv" }));
    db.job.findMany.mockResolvedValue(full as never);
    db.job.updateMany.mockResolvedValue({ count: 1 } as never);

    const purged = await purgeAllExpiredJobFiles();

    expect(db.job.findMany).toHaveBeenCalledTimes(8);
    expect(purged).toBe(200);
  });

  it("fails open", async () => {
    db.job.findMany.mockRejectedValue(new Error("db down"));
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    await expect(purgeAllExpiredJobFiles()).resolves.toBe(0);
    log.mockRestore();
  });
});
