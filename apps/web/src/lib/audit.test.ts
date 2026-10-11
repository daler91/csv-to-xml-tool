import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/prisma", () => ({
  prisma: { auditEntry: { create: vi.fn() } },
}));

import { recordAudit } from "@/lib/audit";
import { prisma } from "@/lib/prisma";

const db = vi.mocked(prisma, true);

beforeEach(() => {
  vi.resetAllMocks();
});

describe("recordAudit", () => {
  it("writes the entry", async () => {
    db.auditEntry.create.mockResolvedValue({} as never);
    await recordAudit({ userId: "u1", action: "sign_in" });
    expect(db.auditEntry.create).toHaveBeenCalledWith({ data: { userId: "u1", action: "sign_in" } });
  });

  it("logs a failed write instead of failing the change it describes", async () => {
    db.auditEntry.create.mockRejectedValue(new Error("db down"));
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});

    await expect(recordAudit({ userId: "u1", action: "sign_in" })).resolves.toBeUndefined();

    expect(errorLog).toHaveBeenCalled();
    errorLog.mockRestore();
  });
});
