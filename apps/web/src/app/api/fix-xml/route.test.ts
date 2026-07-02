import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({
  prisma: { auditEntry: { create: vi.fn() } },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/worker-client", () => ({ workerFetch: vi.fn() }));
vi.mock("@/lib/rate-limit", () => ({ rateLimit: vi.fn() }));

import { POST } from "@/app/api/fix-xml/route";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { workerFetch } from "@/lib/worker-client";
import { rateLimit } from "@/lib/rate-limit";

const db = vi.mocked(prisma, true);
const auth = vi.mocked(getRequiredUser);
const worker = vi.mocked(workerFetch);
const limiter = vi.mocked(rateLimit);

const FIX_RESULT = {
  changed: true,
  fixed_xml_content: "<CounselingInformation/>",
  is_valid: true,
  errors: [],
  error_count: 0,
  error_details: [],
};

function fixRequest(opts: {
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
  return new Request("http://localhost/api/fix-xml", {
    method: "POST",
    body: form,
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  auth.mockResolvedValue(TEST_USER as never);
  limiter.mockResolvedValue({ success: true, remaining: 9 } as never);
});

describe("POST /api/fix-xml", () => {
  it("rejects a non-XML file (400)", async () => {
    const res = await POST(
      fixRequest({ fileName: "data.csv", schemaType: "counseling" })
    );
    expect(res.status).toBe(400);
    expect(worker).not.toHaveBeenCalled();
  });

  it("rejects an unknown schema type (400)", async () => {
    const res = await POST(fixRequest({ schemaType: "bogus" }));
    expect(res.status).toBe(400);
    expect(worker).not.toHaveBeenCalled();
  });

  it('rejects "training" — auto-fix is counseling-format only (400)', async () => {
    const res = await POST(fixRequest({ schemaType: "training" }));
    expect(res.status).toBe(400);
    expect(worker).not.toHaveBeenCalled();
  });

  it("rejects a missing file (400)", async () => {
    const res = await POST(
      fixRequest({ omitFile: true, schemaType: "counseling" })
    );
    expect(res.status).toBe(400);
  });

  it("returns 429 when rate limited", async () => {
    limiter.mockResolvedValue({ success: false, remaining: 0 } as never);
    const res = await POST(fixRequest({ schemaType: "counseling" }));
    expect(res.status).toBe(429);
    expect(worker).not.toHaveBeenCalled();
  });

  it("proxies to the worker's /fix-xml and audits the attempt", async () => {
    worker.mockResolvedValue(FIX_RESULT as never);

    const res = await POST(
      fixRequest({
        fileName: "broken.xml",
        content: "<Doc/>",
        schemaType: "counseling",
      })
    );

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ changed: true, is_valid: true });

    const [path, options] = worker.mock.calls[0];
    expect(path).toBe("/fix-xml");
    const sent = JSON.parse(String(options?.body));
    expect(sent).toMatchObject({
      xml_content: "<Doc/>",
      schema_type: "counseling",
    });
    expect(sent.job_id).toBeTruthy();

    expect(db.auditEntry.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          action: "xml_autofix",
          userId: TEST_USER.id,
          metadata: expect.objectContaining({
            fileName: "broken.xml",
            schemaType: "counseling",
            changed: true,
            isValid: true,
          }),
        }),
      })
    );
  });

  it("accepts training-client (shares the counseling XSD)", async () => {
    worker.mockResolvedValue(FIX_RESULT as never);
    const res = await POST(fixRequest({ schemaType: "training-client" }));
    expect(res.status).toBe(200);
  });

  it("returns 502 when the worker is unreachable", async () => {
    worker.mockRejectedValue(new Error("connect ECONNREFUSED"));
    const res = await POST(fixRequest({ schemaType: "counseling" }));
    expect(res.status).toBe(502);
  });
});
