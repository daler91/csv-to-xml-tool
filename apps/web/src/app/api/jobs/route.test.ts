import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({ prisma: { job: { findMany: vi.fn() } } }));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/job-reaper", () => ({ reapStuckConvertingJobs: vi.fn() }));
vi.mock("@/lib/retention", () => ({ purgeExpiredJobFiles: vi.fn() }));

import { GET } from "@/app/api/jobs/route";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { reapStuckConvertingJobs } from "@/lib/job-reaper";
import { purgeExpiredJobFiles } from "@/lib/retention";

const db = vi.mocked(prisma, true);
const auth = vi.mocked(getRequiredUser);
const reap = vi.mocked(reapStuckConvertingJobs);
const purge = vi.mocked(purgeExpiredJobFiles);

beforeEach(() => {
  vi.resetAllMocks();
  auth.mockResolvedValue(TEST_USER as never);
  reap.mockResolvedValue(0);
  purge.mockResolvedValue(0);
  db.job.findMany.mockResolvedValue([] as never);
});

/** The arguments of the one findMany the route made. */
function listQuery() {
  expect(db.job.findMany).toHaveBeenCalledTimes(1);
  return db.job.findMany.mock.calls[0]?.[0];
}

describe("GET /api/jobs", () => {
  it("returns the user's jobs", async () => {
    const jobs = [
      { id: "job-2", status: "complete" },
      { id: "job-1", status: "error" },
    ];
    db.job.findMany.mockResolvedValue(jobs as never);

    const res = await GET();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(jobs);
  });

  it("lists only the signed-in user's jobs, newest first", async () => {
    await GET();
    expect(listQuery()?.where).toEqual({ userId: TEST_USER.id });
    expect(listQuery()?.orderBy).toEqual({ createdAt: "desc" });
  });

  it("leaves server file paths and the bulky per-row JSON out of the list", async () => {
    // Paths are server internals. Issues, cleaning diffs and XSD errors can run
    // to thousands of entries per job; they belong to that job's own page, not
    // to every row of the dashboard.
    await GET();
    const select = listQuery()?.select;
    expect(select).toBeDefined();
    for (const field of [
      "inputFilePath",
      "outputFilePath",
      "userId",
      "columnMapping",
      "issues",
      "cleaningDiffs",
      "xsdErrors",
    ]) {
      expect(select, field).not.toHaveProperty(field);
    }
  });

  it("reaps stuck jobs and purges expired files for this user before reading", async () => {
    // Before, not after: a job the reaper just failed must show as failed in
    // this same response, not as "converting" until the next refresh.
    await GET();
    expect(reap).toHaveBeenCalledWith(TEST_USER.id);
    expect(purge).toHaveBeenCalledWith(TEST_USER.id);

    const read = db.job.findMany.mock.invocationCallOrder[0];
    expect(reap.mock.invocationCallOrder[0]).toBeLessThan(read);
    expect(purge.mock.invocationCallOrder[0]).toBeLessThan(read);
  });

  it("still lists the jobs when the stuck-job reaper's own query fails", async () => {
    // The real reaper, against the same database mock: its query fails, the
    // list query after it succeeds. It used to fail the whole list with a 500.
    const actual = await vi.importActual<typeof import("@/lib/job-reaper")>("@/lib/job-reaper");
    reap.mockImplementation(actual.reapStuckConvertingJobs);
    const jobs = [{ id: "job-1", status: "complete" }];
    db.job.findMany
      .mockRejectedValueOnce(new Error("Can't reach database server"))
      .mockResolvedValueOnce(jobs as never);
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});

    const res = await GET();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(jobs);
    expect(errorLog).toHaveBeenCalledWith(expect.stringContaining("[job-reaper]"), expect.any(Error));
    errorLog.mockRestore();
  });

  it("does no housekeeping and reads nothing without a session", async () => {
    auth.mockRejectedValue(new Error("Unauthorized"));

    const res = await GET();
    expect(res.status).toBe(401);
    expect(reap).not.toHaveBeenCalled();
    expect(purge).not.toHaveBeenCalled();
    expect(db.job.findMany).not.toHaveBeenCalled();
  });
});
