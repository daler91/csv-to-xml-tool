import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({
  prisma: { auditEntry: { create: vi.fn() } },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/worker-client", () => ({ workerFetch: vi.fn() }));
vi.mock("@/lib/rate-limit", () => ({ rateLimit: vi.fn() }));

import { POST } from "@/app/api/validate-xml/route";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";
import { rateLimit } from "@/lib/rate-limit";

const db = vi.mocked(prisma, true);
const auth = vi.mocked(getRequiredUser);
const worker = vi.mocked(workerFetch);
const limiter = vi.mocked(rateLimit);

function validateRequest(opts: {
  fileName?: string;
  content?: string;
  schemaType?: string;
  omitFile?: boolean;
}): Request {
  const form = new FormData();
  if (!opts.omitFile) {
    form.append(
      "file",
      new File([opts.content ?? "<xml/>"], opts.fileName ?? "report.xml", {
        type: "application/xml",
      })
    );
  }
  if (opts.schemaType !== undefined) form.append("schemaType", opts.schemaType);
  return new Request("http://localhost/api/validate-xml", {
    method: "POST",
    body: form,
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  auth.mockResolvedValue(TEST_USER as never);
  limiter.mockResolvedValue({ success: true, remaining: 9 } as never);
});

describe("POST /api/validate-xml", () => {
  it("rejects a non-XML file (400)", async () => {
    const res = await POST(
      validateRequest({ fileName: "data.csv", schemaType: "counseling" })
    );
    expect(res.status).toBe(400);
    expect(worker).not.toHaveBeenCalled();
  });

  it("rejects an unknown schema type (400)", async () => {
    const res = await POST(validateRequest({ schemaType: "bogus" }));
    expect(res.status).toBe(400);
  });

  it("rejects a missing file (400)", async () => {
    const res = await POST(
      validateRequest({ omitFile: true, schemaType: "counseling" })
    );
    expect(res.status).toBe(400);
  });

  it("returns 429 when rate limited", async () => {
    limiter.mockResolvedValue({ success: false, remaining: 0 } as never);
    const res = await POST(validateRequest({ schemaType: "counseling" }));
    expect(res.status).toBe(429);
  });

  it("proxies to the worker's content-based /validate-xsd and audits the check", async () => {
    worker.mockResolvedValue({
      is_valid: false,
      errors: ["Element 'X': bad"],
      error_count: 1,
    } as never);

    const res = await POST(
      validateRequest({ content: "<Doc/>", schemaType: "training" })
    );

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ is_valid: false, error_count: 1 });

    const [path, options] = worker.mock.calls[0];
    expect(path).toBe("/validate-xsd");
    const sent = JSON.parse(String(options?.body));
    expect(sent).toMatchObject({
      xml_content: "<Doc/>",
      schema_type: "training",
    });

    expect(db.auditEntry.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          action: "xml_validated",
          userId: TEST_USER.id,
        }),
      })
    );
  });

  it("returns 502 when the worker is unreachable", async () => {
    worker.mockRejectedValue(new Error("connect ECONNREFUSED"));
    const res = await POST(validateRequest({ schemaType: "counseling" }));
    expect(res.status).toBe(502);
  });

  it("passes a deterministic worker 400 through as a 400, not a 502", async () => {
    worker.mockRejectedValue(
      new Error('Worker error 400: {"detail":"xml_content must not be empty"}')
    );
    const res = await POST(validateRequest({ schemaType: "counseling" }));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("xml_content must not be empty");
  });

  it("decodes a UTF-16 upload instead of mangling it as UTF-8", async () => {
    worker.mockResolvedValue({
      is_valid: true,
      errors: [],
      error_count: 0,
    } as never);

    const xml = '<?xml version="1.0" encoding="UTF-16"?>\n<Doc>café</Doc>';
    // UTF-16LE with BOM — the classic legacy-Windows-tool export.
    const bytes = Buffer.concat([
      Buffer.from([0xff, 0xfe]),
      Buffer.from(xml, "utf16le"),
    ]);
    const form = new FormData();
    form.append(
      "file",
      new File([bytes], "legacy.xml", { type: "application/xml" })
    );
    form.append("schemaType", "counseling");
    const res = await POST(
      new Request("http://localhost/api/validate-xml", {
        method: "POST",
        body: form,
      })
    );

    expect(res.status).toBe(200);
    const sent = JSON.parse(String(worker.mock.calls[0]?.[1]?.body));
    // Correctly decoded (no replacement chars/NULs) and the declaration is
    // restated as UTF-8 since the content travels on as UTF-8 text.
    expect(sent.xml_content).toContain("<Doc>café</Doc>");
    expect(sent.xml_content).toContain('encoding="UTF-8"');
    expect(sent.xml_content).not.toContain("�");
  });
});
