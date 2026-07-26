import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER, jobParams } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({
  prisma: { job: { findFirst: vi.fn() }, auditEntry: { create: vi.fn() } },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/paths", () => ({ resolveWithinDataDir: vi.fn() }));
vi.mock("node:fs/promises", () => ({ readFile: vi.fn() }));

import { GET } from "@/app/api/jobs/[jobId]/download/route";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { resolveWithinDataDir } from "@/lib/paths";
import { readFile } from "node:fs/promises";

const db = vi.mocked(prisma, true);
const auth = vi.mocked(getRequiredUser);
const resolvePath = vi.mocked(resolveWithinDataDir);
const read = vi.mocked(readFile);

beforeEach(() => {
  vi.resetAllMocks();
  auth.mockResolvedValue(TEST_USER as never);
  db.job.findFirst.mockResolvedValue({
    outputFilePath: "/data/output/j1/j1.xml",
    inputFileName: "in.csv",
  } as never);
  resolvePath.mockResolvedValue("/data/output/j1/j1.xml");
  read.mockResolvedValue(Buffer.from("<xml/>") as never);
  db.auditEntry.create.mockResolvedValue({} as never);
});

describe("GET /api/jobs/[jobId]/download", () => {
  it("returns 404 when the job has no output file", async () => {
    db.job.findFirst.mockResolvedValue({ outputFilePath: null } as never);
    const res = await GET(new Request("http://localhost"), jobParams("j1"));
    expect(res.status).toBe(404);
  });

  it("returns 404 and reads nothing when the path escapes DATA_DIR (traversal)", async () => {
    db.job.findFirst.mockResolvedValue({
      outputFilePath: "/data/output/j1/../../../etc/passwd",
      inputFileName: "in.csv",
    } as never);
    resolvePath.mockRejectedValue(new Error("Path escapes DATA_DIR"));

    const res = await GET(new Request("http://localhost"), jobParams("j1"));

    expect(res.status).toBe(404);
    expect(read).not.toHaveBeenCalled();
    expect(db.auditEntry.create).not.toHaveBeenCalled();
  });

  it("streams the XML with download headers and writes an audit entry", async () => {
    const res = await GET(new Request("http://localhost"), jobParams("j1"));
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe("application/xml");
    expect(res.headers.get("Content-Disposition")).toContain("in.xml");
    expect(db.auditEntry.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({ action: "download" }),
      })
    );
  });
});

describe("GET /api/jobs/[jobId]/download — expired files", () => {
  it("returns 410 with an expired flag once retention has purged the output", async () => {
    // schema.prisma documents the intent -- "The row (and its audit trail)
    // survives; downloads show 'expired'" -- but this returned a flat 404, so
    // an aged-out file was indistinguishable from one that never existed.
    db.job.findFirst.mockResolvedValue({
      id: "j1",
      userId: TEST_USER.id,
      inputFileName: "in.csv",
      outputFilePath: null,
      filesPurgedAt: new Date(),
    } as never);

    const res = await GET(new Request("http://localhost"), jobParams("j1"));
    expect(res.status).toBe(410);
    await expect(res.json()).resolves.toMatchObject({ expired: true });
  });

  it("still returns 404 when there is simply no output yet", async () => {
    db.job.findFirst.mockResolvedValue({
      id: "j1",
      userId: TEST_USER.id,
      inputFileName: "in.csv",
      outputFilePath: null,
      filesPurgedAt: null,
    } as never);

    const res = await GET(new Request("http://localhost"), jobParams("j1"));
    expect(res.status).toBe(404);
  });
});
