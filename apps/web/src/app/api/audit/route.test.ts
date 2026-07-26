import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({
  prisma: {
    auditEntry: {
      findMany: vi.fn(),
      count: vi.fn(),
    },
  },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));

import {
  GET,
  escapeCsvValue,
  MAX_PAGE_SIZE,
  MAX_EXPORT_ROWS,
  DEFAULT_PAGE_SIZE,
} from "@/app/api/audit/route";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";

const db = vi.mocked(prisma, true);
const auth = vi.mocked(getRequiredUser);

function auditRequest(query = ""): Request {
  return new Request(`http://localhost/api/audit${query}`);
}

beforeEach(() => {
  vi.resetAllMocks();
  auth.mockResolvedValue(TEST_USER as never);
  db.auditEntry.findMany.mockResolvedValue([] as never);
  db.auditEntry.count.mockResolvedValue(0 as never);
});

describe("GET /api/audit — authorization", () => {
  it("scopes every query to the calling user", async () => {
    await GET(auditRequest());
    expect(db.auditEntry.findMany).toHaveBeenCalledWith(
      expect.objectContaining({ where: { userId: TEST_USER.id } })
    );
    expect(db.auditEntry.count).toHaveBeenCalledWith({
      where: { userId: TEST_USER.id },
    });
  });

  it("returns 401 rather than 500 when the session is missing", async () => {
    auth.mockRejectedValue(new Error("Unauthorized"));
    const res = await GET(auditRequest());
    expect(res.status).toBe(401);
  });
});

describe("GET /api/audit — pagination bounds", () => {
  // These params flowed straight into Prisma's skip/take. Non-numeric input
  // produced NaN and page=0 produced a negative skip -- both 500s -- while a
  // huge pageSize was accepted as-is.
  it.each([
    ["?pageSize=abc", DEFAULT_PAGE_SIZE],
    ["?pageSize=", DEFAULT_PAGE_SIZE],
    ["?pageSize=0", 1],
    ["?pageSize=-10", 1],
    ["?pageSize=100000000", MAX_PAGE_SIZE],
    ["?pageSize=NaN", DEFAULT_PAGE_SIZE],
    ["?pageSize=1e9", 1], // parseInt("1e9") === 1
  ])("clamps %s to take=%i", async (query, expected) => {
    const res = await GET(auditRequest(query));
    expect(res.status).toBe(200);
    expect(db.auditEntry.findMany).toHaveBeenCalledWith(
      expect.objectContaining({ take: expected })
    );
  });

  it.each([
    ["?page=0", 0],
    ["?page=-5", 0],
    ["?page=abc", 0],
    ["?page=3&pageSize=10", 20],
  ])("never produces a negative skip for %s", async (query, expectedSkip) => {
    const res = await GET(auditRequest(query));
    expect(res.status).toBe(200);
    const call = db.auditEntry.findMany.mock.calls[0][0] as { skip: number };
    expect(call.skip).toBe(expectedSkip);
    expect(call.skip).toBeGreaterThanOrEqual(0);
  });

  it("reports the clamped page size back to the client", async () => {
    const res = await GET(auditRequest("?pageSize=100000000"));
    const body = await res.json();
    expect(body.pageSize).toBe(MAX_PAGE_SIZE);
  });
});

describe("GET /api/audit — CSV export", () => {
  it("bounds the export instead of fetching every row", async () => {
    await GET(auditRequest("?format=csv"));
    // Second call is the export query; it previously had no `take` at all.
    const exportCall = db.auditEntry.findMany.mock.calls.at(-1)?.[0] as {
      take: number;
      where: unknown;
    };
    expect(exportCall.take).toBe(MAX_EXPORT_ROWS);
    expect(exportCall.where).toEqual({ userId: TEST_USER.id });
  });

  it("returns CSV with the expected headers", async () => {
    const res = await GET(auditRequest("?format=csv"));
    expect(res.headers.get("Content-Type")).toBe("text/csv");
    expect(await res.text()).toContain("Date,Action,File,Type,Details");
  });
});

describe("escapeCsvValue", () => {
  it("doubles embedded quotes", () => {
    expect(escapeCsvValue('say "hi"')).toBe('say ""hi""');
  });

  // A filename like =cmd|'/c calc'!A1 executes on open in Excel/Sheets.
  it.each(["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"])(
    "prefixes %j so it can't be read as a formula",
    (value) => {
      expect(escapeCsvValue(value).startsWith("'")).toBe(true);
    }
  );

  it("leaves ordinary values untouched", () => {
    expect(escapeCsvValue("report.csv")).toBe("report.csv");
    expect(escapeCsvValue("2026-07-26T00:00:00.000Z")).toBe(
      "2026-07-26T00:00:00.000Z"
    );
  });

  it("renders null and undefined as empty", () => {
    expect(escapeCsvValue(null)).toBe("");
    expect(escapeCsvValue(undefined)).toBe("");
  });
});
