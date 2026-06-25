import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER, jobParams, jsonRequest } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({
  prisma: {
    job: { findFirst: vi.fn(), updateMany: vi.fn(), findUnique: vi.fn() },
  },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/worker-client", () => ({ workerFetch: vi.fn() }));
vi.mock("@/lib/job-reaper", () => ({ reapStuckConvertingJobs: vi.fn() }));

import { GET, PATCH } from "@/app/api/jobs/[jobId]/route";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";
import { reapStuckConvertingJobs } from "@/lib/job-reaper";

const db = vi.mocked(prisma, true);
const auth = vi.mocked(getRequiredUser);
const worker = vi.mocked(workerFetch);
const reaper = vi.mocked(reapStuckConvertingJobs);

beforeEach(() => {
  vi.resetAllMocks();
  auth.mockResolvedValue(TEST_USER as never);
  reaper.mockResolvedValue(0);
});

describe("GET /api/jobs/[jobId]", () => {
  it("returns 404 for a job the user does not own", async () => {
    db.job.findFirst.mockResolvedValue(null as never);
    const res = await GET(new Request("http://localhost"), jobParams("j1"));
    expect(res.status).toBe(404);
  });

  it("reconciles stuck jobs (reaper) before reading", async () => {
    db.job.findFirst.mockResolvedValue({ id: "j1", status: "uploaded" } as never);
    await GET(new Request("http://localhost"), jobParams("j1"));
    expect(reaper).toHaveBeenCalledWith(TEST_USER.id);
  });

  it("merges live worker progress for a converting job", async () => {
    db.job.findFirst.mockResolvedValue({ id: "j1", status: "converting" } as never);
    worker.mockResolvedValue({ processed: 5, total: 10, updated_at: 123 } as never);
    const res = await GET(new Request("http://localhost"), jobParams("j1"));
    const body = await res.json();
    expect(body).toMatchObject({
      processedRows: 5,
      totalRows: 10,
      progressUpdatedAt: 123,
    });
  });

  it("returns the job without progress when the worker snapshot fails", async () => {
    db.job.findFirst.mockResolvedValue({ id: "j1", status: "converting" } as never);
    worker.mockRejectedValue(new Error("no snapshot"));
    const res = await GET(new Request("http://localhost"), jobParams("j1"));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).not.toHaveProperty("processedRows");
  });
});

describe("PATCH /api/jobs/[jobId]", () => {
  it("refuses to modify a terminal job (409)", async () => {
    db.job.findFirst.mockResolvedValue({ id: "j1", status: "complete" } as never);
    const res = await PATCH(
      jsonRequest("http://localhost", "PATCH", { columnMapping: { a: 1 } }),
      jobParams("j1")
    );
    expect(res.status).toBe(409);
    expect(db.job.updateMany).not.toHaveBeenCalled();
  });

  it("strips non-whitelisted fields before updating", async () => {
    db.job.findFirst.mockResolvedValue({ id: "j1", status: "uploaded" } as never);
    db.job.updateMany.mockResolvedValue({ count: 1 } as never);
    db.job.findUnique.mockResolvedValue({ id: "j1" } as never);

    await PATCH(
      jsonRequest("http://localhost", "PATCH", {
        columnMapping: { a: 1 },
        userId: "attacker",
        inputFilePath: "/etc/passwd",
      }),
      jobParams("j1")
    );

    const dataArg = db.job.updateMany.mock.calls[0][0].data;
    expect(dataArg).toEqual({ columnMapping: { a: 1 } });
  });

  it("returns 400 when no whitelisted fields are present", async () => {
    db.job.findFirst.mockResolvedValue({ id: "j1", status: "uploaded" } as never);
    const res = await PATCH(
      jsonRequest("http://localhost", "PATCH", { nope: 1 }),
      jobParams("j1")
    );
    expect(res.status).toBe(400);
  });

  it("returns 409 when the guarded update loses the race (count 0)", async () => {
    db.job.findFirst.mockResolvedValue({ id: "j1", status: "uploaded" } as never);
    db.job.updateMany.mockResolvedValue({ count: 0 } as never);
    db.job.findUnique.mockResolvedValue({ status: "cancelled" } as never);
    const res = await PATCH(
      jsonRequest("http://localhost", "PATCH", { columnMapping: { a: 1 } }),
      jobParams("j1")
    );
    expect(res.status).toBe(409);
  });
});
