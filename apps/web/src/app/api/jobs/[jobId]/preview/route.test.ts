import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER, jobParams } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({
  prisma: { job: { findFirst: vi.fn(), updateMany: vi.fn() } },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/worker-client", () => ({ workerFetch: vi.fn() }));
vi.mock("@/lib/limits", () => ({ MAX_UPLOAD_BYTES: 1000 }));
vi.mock("node:fs/promises", () => ({ stat: vi.fn() }));

import { GET } from "@/app/api/jobs/[jobId]/preview/route";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";
import { stat } from "node:fs/promises";

const db = vi.mocked(prisma, true);
const auth = vi.mocked(getRequiredUser);
const worker = vi.mocked(workerFetch);
const statMock = vi.mocked(stat);

beforeEach(() => {
  vi.resetAllMocks();
  auth.mockResolvedValue(TEST_USER as never);
  db.job.findFirst.mockResolvedValue({
    id: "j1",
    userId: TEST_USER.id,
    status: "uploaded",
    inputFilePath: "/data/uploads/j1/in.csv",
    inputFileName: "in.csv",
    converterType: "counseling",
  } as never);
  statMock.mockResolvedValue({ size: 100 } as never);
  worker.mockResolvedValue({ total_rows: 42 } as never);
  db.job.updateMany.mockResolvedValue({ count: 1 } as never);
});

describe("GET /api/jobs/[jobId]/preview", () => {
  it("returns 404 for a job the user does not own", async () => {
    db.job.findFirst.mockResolvedValue(null as never);
    const res = await GET(new Request("http://localhost"), jobParams("j1"));
    expect(res.status).toBe(404);
  });

  it("re-checks the size cap and returns 413 when too large", async () => {
    statMock.mockResolvedValue({ size: 5000 } as never);
    const res = await GET(new Request("http://localhost"), jobParams("j1"));
    expect(res.status).toBe(413);
    expect(worker).not.toHaveBeenCalled();
  });

  it("persists totalRows unconditionally and advances status only from non-terminal states", async () => {
    const res = await GET(new Request("http://localhost"), jobParams("j1"));
    expect(res.status).toBe(200);

    // 1st updateMany: unconditional row-count persist.
    expect(db.job.updateMany).toHaveBeenNthCalledWith(1, {
      where: { id: "j1" },
      data: { totalRows: 42 },
    });
    // 2nd updateMany: guarded status advance (won't revive terminal/queued/converting).
    expect(db.job.updateMany).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        where: expect.objectContaining({
          status: {
            notIn: ["cancelled", "complete", "error", "converting", "queued"],
          },
        }),
        data: { status: "previewed" },
      })
    );
  });
});
