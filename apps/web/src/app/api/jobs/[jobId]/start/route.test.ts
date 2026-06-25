import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER, jobParams } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({
  prisma: { job: { findFirst: vi.fn(), updateMany: vi.fn() } },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/limits", () => ({ MAX_UPLOAD_BYTES: 1000 }));
vi.mock("@/lib/job-queue", () => ({ enqueueJob: vi.fn() }));
vi.mock("node:fs/promises", () => ({ stat: vi.fn() }));

import { POST } from "@/app/api/jobs/[jobId]/start/route";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { enqueueJob } from "@/lib/job-queue";
import { stat } from "node:fs/promises";

const db = vi.mocked(prisma, true);
const auth = vi.mocked(getRequiredUser);
const enqueue = vi.mocked(enqueueJob);
const statMock = vi.mocked(stat);

const req = () => new Request("http://localhost/api/jobs/j1/start", { method: "POST" });

beforeEach(() => {
  vi.resetAllMocks();
  auth.mockResolvedValue(TEST_USER as never);
  db.job.findFirst.mockResolvedValue({
    id: "j1",
    userId: TEST_USER.id,
    status: "uploaded",
    inputFilePath: "/data/uploads/j1/in.csv",
  } as never);
  statMock.mockResolvedValue({ size: 100 } as never);
  db.job.updateMany.mockResolvedValue({ count: 1 } as never);
  enqueue.mockResolvedValue(undefined);
});

describe("POST /api/jobs/[jobId]/start", () => {
  it("returns 404 for a job the user does not own", async () => {
    db.job.findFirst.mockResolvedValue(null as never);
    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(404);
    expect(enqueue).not.toHaveBeenCalled();
  });

  it("returns 409 when the job is not in a startable state", async () => {
    db.job.findFirst.mockResolvedValue({
      id: "j1",
      userId: TEST_USER.id,
      status: "converting",
      inputFilePath: "/data/uploads/j1/in.csv",
    } as never);
    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(409);
    expect(db.job.updateMany).not.toHaveBeenCalled();
  });

  it("re-checks the file size server-side and returns 413 when it grew past the cap", async () => {
    statMock.mockResolvedValue({ size: 5000 } as never); // > mocked cap 1000
    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(413);
    expect(db.job.updateMany).not.toHaveBeenCalled();
  });

  it("returns 409 when the guarded transition loses the race (count 0)", async () => {
    db.job.updateMany.mockResolvedValue({ count: 0 } as never);
    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(409);
    expect(enqueue).not.toHaveBeenCalled();
  });

  it("transitions to queued and enqueues on success (202)", async () => {
    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({ status: "queued" });
    expect(db.job.updateMany).toHaveBeenCalledWith(
      expect.objectContaining({
        where: expect.objectContaining({ id: "j1", userId: TEST_USER.id }),
        data: { status: "queued" },
      })
    );
    expect(enqueue).toHaveBeenCalledWith("j1");
  });
});
