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

describe("POST /api/jobs/[jobId]/start — expired and unavailable cases", () => {
  it("returns 410 when the upload has been purged by retention", async () => {
    // Retention blanks inputFilePath and stamps filesPurgedAt. A job can still
    // be in a startable state at that point, and stat("") threw ENOENT -> 500.
    db.job.findFirst.mockResolvedValue({
      id: "j1",
      userId: TEST_USER.id,
      status: "previewed",
      inputFilePath: "",
      filesPurgedAt: new Date(),
    } as never);

    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(410);
    await expect(res.json()).resolves.toMatchObject({
      error: expect.stringContaining("expired"),
    });
    expect(statMock).not.toHaveBeenCalled();
    expect(db.job.updateMany).not.toHaveBeenCalled();
  });

  it("rolls the status back when the queue push fails", async () => {
    // The row is already "queued" by this point, so without a rollback a retry
    // hits the startable-status gate and 409s — the job sat wedged until the
    // reaper failed it a full deadline later, with no explanation.
    enqueue.mockRejectedValue(new Error("redis down"));

    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(503);

    const rollback = db.job.updateMany.mock.calls.at(-1)?.[0] as {
      where: Record<string, unknown>;
      data: Record<string, unknown>;
    };
    expect(rollback.where).toMatchObject({ id: "j1", status: "queued" });
    expect(rollback.data).toEqual({ status: "uploaded" });
  });

  it("does not roll back on a successful enqueue", async () => {
    const res = await POST(req(), jobParams("j1"));
    expect(res.status).toBe(202);
    expect(db.job.updateMany).toHaveBeenCalledTimes(1);
  });
});
