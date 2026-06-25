import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER, uploadRequest } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({
  prisma: {
    job: {
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
      findFirst: vi.fn(),
    },
    auditEntry: { create: vi.fn() },
  },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/rate-limit", () => ({ rateLimit: vi.fn() }));
vi.mock("@/lib/limits", () => ({ MAX_UPLOAD_BYTES: 1000 }));
vi.mock("node:fs/promises", () => ({
  writeFile: vi.fn(),
  mkdir: vi.fn(),
  rm: vi.fn(),
}));

import { POST } from "@/app/api/upload/route";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { rateLimit } from "@/lib/rate-limit";
import { writeFile, mkdir, rm } from "node:fs/promises";

const db = vi.mocked(prisma, true);
const auth = vi.mocked(getRequiredUser);
const limit = vi.mocked(rateLimit);
const write = vi.mocked(writeFile);

beforeEach(() => {
  vi.resetAllMocks();
  auth.mockResolvedValue(TEST_USER as never);
  limit.mockResolvedValue({ success: true, remaining: 9 });
  db.job.create.mockResolvedValue({ id: "job-1" } as never);
  db.job.update.mockResolvedValue({} as never);
  db.job.delete.mockResolvedValue({} as never);
  db.auditEntry.create.mockResolvedValue({} as never);
  write.mockResolvedValue(undefined as never);
  vi.mocked(mkdir).mockResolvedValue(undefined as never);
  vi.mocked(rm).mockResolvedValue(undefined as never);
});

describe("POST /api/upload", () => {
  it("rejects a non-CSV file with 400", async () => {
    const res = await POST(
      uploadRequest({ fileName: "data.txt", converterType: "counseling" })
    );
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "Only CSV files are accepted" });
    expect(db.job.create).not.toHaveBeenCalled();
  });

  it("rejects a file over the size cap with 413", async () => {
    const res = await POST(
      uploadRequest({
        fileName: "data.csv",
        content: "x".repeat(1001), // MAX_UPLOAD_BYTES mocked to 1000
        converterType: "counseling",
      })
    );
    expect(res.status).toBe(413);
  });

  it("rejects an unknown converterType with 400", async () => {
    const res = await POST(
      uploadRequest({ fileName: "data.csv", converterType: "bogus" })
    );
    expect(res.status).toBe(400);
  });

  it("rejects a previousJobId owned by another user (SEC-2 IDOR) with 400", async () => {
    db.job.findFirst.mockResolvedValue(null as never); // not found under this user
    const res = await POST(
      uploadRequest({
        fileName: "data.csv",
        converterType: "counseling",
        previousJobId: "other-users-job",
      })
    );
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "Invalid previousJobId" });
    expect(db.job.findFirst).toHaveBeenCalledWith({
      where: { id: "other-users-job", userId: TEST_USER.id },
      select: { id: true },
    });
    expect(db.job.create).not.toHaveBeenCalled();
  });

  it("cleans up the orphaned job when the file save fails (DATA-1) and returns 500", async () => {
    write.mockRejectedValue(new Error("ENOSPC"));
    const res = await POST(
      uploadRequest({ fileName: "data.csv", converterType: "counseling" })
    );
    expect(res.status).toBe(500);
    expect(db.job.delete).toHaveBeenCalledWith({ where: { id: "job-1" } });
    expect(db.auditEntry.create).not.toHaveBeenCalled();
  });

  it("creates the job, sanitizes the name, saves the file, audits, and returns 201", async () => {
    const res = await POST(
      uploadRequest({
        fileName: "My Data!.csv",
        content: "a,b\n1,2\n",
        converterType: "counseling",
      })
    );
    expect(res.status).toBe(201);
    expect(await res.json()).toEqual({ jobId: "job-1" });
    expect(db.job.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          userId: TEST_USER.id,
          converterType: "counseling",
          inputFileName: "My_Data_.csv",
        }),
      })
    );
    expect(write).toHaveBeenCalledOnce();
    expect(db.auditEntry.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({ action: "upload" }),
      })
    );
  });

  it("returns 401 when unauthorized", async () => {
    auth.mockRejectedValue(new Error("Unauthorized"));
    const res = await POST(
      uploadRequest({ fileName: "data.csv", converterType: "counseling" })
    );
    expect(res.status).toBe(401);
  });

  it("returns 429 when rate limited", async () => {
    limit.mockResolvedValue({ success: false, remaining: 0 });
    const res = await POST(
      uploadRequest({ fileName: "data.csv", converterType: "counseling" })
    );
    expect(res.status).toBe(429);
  });
});
