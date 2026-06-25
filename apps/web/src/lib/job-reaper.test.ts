import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/prisma", () => ({
  prisma: {
    job: { findMany: vi.fn(), updateMany: vi.fn() },
    auditEntry: { create: vi.fn() },
  },
}));

import { reapStuckConvertingJobs } from "@/lib/job-reaper";
import { prisma } from "@/lib/prisma";

const db = vi.mocked(prisma, true);

beforeEach(() => {
  vi.resetAllMocks();
});

describe("reapStuckConvertingJobs", () => {
  it("flips each stale job to error (guarded) and writes a timeout audit entry", async () => {
    db.job.findMany.mockResolvedValue([{ id: "j1" }, { id: "j2" }] as never);
    db.job.updateMany.mockResolvedValue({ count: 1 } as never);
    db.auditEntry.create.mockResolvedValue({} as never);

    const reaped = await reapStuckConvertingJobs("user-1");

    expect(reaped).toBe(2);
    expect(db.job.updateMany).toHaveBeenCalledWith({
      where: { id: "j1", status: { in: ["queued", "converting"] } },
      data: { status: "error", completedAt: expect.any(Date) },
    });
    expect(db.auditEntry.create).toHaveBeenCalledTimes(2);
  });

  it("does not audit a job whose guarded update loses the race (count 0)", async () => {
    db.job.findMany.mockResolvedValue([{ id: "j1" }] as never);
    db.job.updateMany.mockResolvedValue({ count: 0 } as never);

    const reaped = await reapStuckConvertingJobs("user-1");

    expect(reaped).toBe(0);
    expect(db.auditEntry.create).not.toHaveBeenCalled();
  });

  it("does nothing when no jobs are stuck", async () => {
    db.job.findMany.mockResolvedValue([] as never);

    const reaped = await reapStuckConvertingJobs("user-1");

    expect(reaped).toBe(0);
    expect(db.job.updateMany).not.toHaveBeenCalled();
  });
});
