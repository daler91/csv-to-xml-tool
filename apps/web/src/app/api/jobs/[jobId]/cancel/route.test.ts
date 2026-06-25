import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER, jobParams } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({
  prisma: {
    job: { findFirst: vi.fn(), updateMany: vi.fn(), findUnique: vi.fn() },
    auditEntry: { create: vi.fn() },
  },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/worker-client", () => ({ workerFetch: vi.fn() }));

import { POST } from "@/app/api/jobs/[jobId]/cancel/route";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";

const db = vi.mocked(prisma, true);
const auth = vi.mocked(getRequiredUser);
const worker = vi.mocked(workerFetch);

const req = () => new Request("http://localhost/api/jobs/j1/cancel", { method: "POST" });

beforeEach(() => {
  vi.resetAllMocks();
  auth.mockResolvedValue(TEST_USER as never);
  db.job.updateMany.mockResolvedValue({ count: 1 } as never);
  db.auditEntry.create.mockResolvedValue({} as never);
  worker.mockResolvedValue(undefined as never); // fire-and-forget poke
});

describe("POST /api/jobs/[jobId]/cancel", () => {
  it("returns 404 for a job the user does not own", async () => {
    db.job.findFirst.mockResolvedValue(null as never);
    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(404);
  });

  it("is an idempotent no-op for a non-cancellable state", async () => {
    db.job.findFirst.mockResolvedValue({ status: "uploaded" } as never);
    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "uploaded" });
    expect(db.job.updateMany).not.toHaveBeenCalled();
  });

  it("cancels a queued job, audits, and pokes the worker (200)", async () => {
    db.job.findFirst.mockResolvedValue({ status: "queued" } as never);
    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "cancelled" });
    expect(db.auditEntry.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({ action: "conversion_cancelled" }),
      })
    );
    expect(worker).toHaveBeenCalledWith(
      "/convert/j1/cancel",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("reports the post-race status without auditing when the guard loses (count 0)", async () => {
    db.job.findFirst.mockResolvedValue({ status: "converting" } as never);
    db.job.updateMany.mockResolvedValue({ count: 0 } as never);
    db.job.findUnique.mockResolvedValue({ status: "complete" } as never);
    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "complete" });
    expect(db.auditEntry.create).not.toHaveBeenCalled();
  });

  it("still returns 200 when the best-effort worker poke rejects", async () => {
    db.job.findFirst.mockResolvedValue({ status: "converting" } as never);
    worker.mockRejectedValue(new Error("worker down"));
    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(200);
  });
});
