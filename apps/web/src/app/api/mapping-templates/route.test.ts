import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER, jsonRequest } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({
  prisma: {
    mappingTemplate: {
      findMany: vi.fn(),
      upsert: vi.fn(),
      deleteMany: vi.fn(),
    },
    job: { findFirst: vi.fn() },
  },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));

import { GET, POST } from "@/app/api/mapping-templates/route";
import { DELETE } from "@/app/api/mapping-templates/[templateId]/route";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";

const db = vi.mocked(prisma, true);
const auth = vi.mocked(getRequiredUser);

function templateParams(templateId: string): {
  params: Promise<{ templateId: string }>;
} {
  return { params: Promise.resolve({ templateId }) };
}

beforeEach(() => {
  vi.resetAllMocks();
  auth.mockResolvedValue(TEST_USER as never);
});

describe("GET /api/mapping-templates", () => {
  it("returns the user's templates", async () => {
    db.mappingTemplate.findMany.mockResolvedValue([
      { id: "t1", name: "Monthly", converterType: "counseling", mapping: { A: "B" } },
    ] as never);
    const res = await GET(new Request("http://localhost/api/mapping-templates"));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.templates).toHaveLength(1);
    expect(body.lastJobMapping).toBeNull();
    expect(db.mappingTemplate.findMany.mock.calls[0]?.[0]?.where).toMatchObject(
      { userId: TEST_USER.id }
    );
  });

  it("rejects an unknown converter type (400)", async () => {
    const res = await GET(
      new Request("http://localhost/api/mapping-templates?converterType=nope")
    );
    expect(res.status).toBe(400);
  });

  it("includes the last completed job's mapping for the requested type", async () => {
    db.mappingTemplate.findMany.mockResolvedValue([] as never);
    db.job.findFirst.mockResolvedValue({
      columnMapping: { "My Col": "Contact ID" },
    } as never);
    const res = await GET(
      new Request(
        "http://localhost/api/mapping-templates?converterType=counseling"
      )
    );
    const body = await res.json();
    expect(body.lastJobMapping).toEqual({ "My Col": "Contact ID" });
    expect(db.job.findFirst.mock.calls[0]?.[0]?.where).toMatchObject({
      userId: TEST_USER.id,
      converterType: "counseling",
      status: "complete",
    });
  });

  it("drops a malformed stored mapping instead of returning it", async () => {
    db.mappingTemplate.findMany.mockResolvedValue([] as never);
    db.job.findFirst.mockResolvedValue({
      columnMapping: { "My Col": 42 },
    } as never);
    const res = await GET(
      new Request(
        "http://localhost/api/mapping-templates?converterType=counseling"
      )
    );
    const body = await res.json();
    expect(body.lastJobMapping).toBeNull();
  });
});

describe("POST /api/mapping-templates", () => {
  it("saves a template scoped to the user (upsert by name)", async () => {
    db.mappingTemplate.upsert.mockResolvedValue({
      id: "t1",
      name: "Monthly",
      converterType: "counseling",
      mapping: { A: "B" },
    } as never);
    const res = await POST(
      jsonRequest("http://localhost", "POST", {
        name: "  Monthly ",
        converterType: "counseling",
        mapping: { A: "B" },
      })
    );
    expect(res.status).toBe(201);
    const upsertArg = db.mappingTemplate.upsert.mock.calls[0][0];
    expect(upsertArg.create).toMatchObject({
      userId: TEST_USER.id,
      name: "Monthly",
    });
  });

  it("rejects a missing name (400)", async () => {
    const res = await POST(
      jsonRequest("http://localhost", "POST", {
        converterType: "counseling",
        mapping: { A: "B" },
      })
    );
    expect(res.status).toBe(400);
  });

  it("rejects an unknown converter type (400)", async () => {
    const res = await POST(
      jsonRequest("http://localhost", "POST", {
        name: "x",
        converterType: "bogus",
        mapping: { A: "B" },
      })
    );
    expect(res.status).toBe(400);
  });

  it("rejects an empty or non-string mapping (400)", async () => {
    for (const mapping of [{}, { A: 42 }, "not-an-object", null]) {
      const res = await POST(
        jsonRequest("http://localhost", "POST", {
          name: "x",
          converterType: "counseling",
          mapping,
        })
      );
      expect(res.status).toBe(400);
    }
    expect(db.mappingTemplate.upsert).not.toHaveBeenCalled();
  });
});

describe("DELETE /api/mapping-templates/[templateId]", () => {
  it("deletes only within the user's scope", async () => {
    db.mappingTemplate.deleteMany.mockResolvedValue({ count: 1 } as never);
    const res = await DELETE(
      new Request("http://localhost"),
      templateParams("t1")
    );
    expect(res.status).toBe(200);
    expect(db.mappingTemplate.deleteMany).toHaveBeenCalledWith({
      where: { id: "t1", userId: TEST_USER.id },
    });
  });

  it("returns 404 for a foreign or missing template", async () => {
    db.mappingTemplate.deleteMany.mockResolvedValue({ count: 0 } as never);
    const res = await DELETE(
      new Request("http://localhost"),
      templateParams("t-other")
    );
    expect(res.status).toBe(404);
  });
});
