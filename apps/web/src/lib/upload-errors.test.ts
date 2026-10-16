import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER, uploadRequest } from "@/test/helpers";

// The sync check at the bottom drives the real /api/upload route; these are
// the same boundary mocks that route's own test uses.
vi.mock("@/lib/prisma", () => ({
  prisma: {
    job: { create: vi.fn(), update: vi.fn(), delete: vi.fn(), findFirst: vi.fn() },
    auditEntry: { create: vi.fn() },
  },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/rate-limit", () => ({ rateLimit: vi.fn() }));
vi.mock("node:fs/promises", () => ({ writeFile: vi.fn(), mkdir: vi.fn(), rm: vi.fn() }));

import { uploadErrorMessage } from "@/lib/upload-errors";
import { POST as upload } from "@/app/api/upload/route";
import { getRequiredUser } from "@/lib/session";
import { rateLimit } from "@/lib/rate-limit";

const MB = 1024 * 1024;

// Distinctive fragments of each friendly message, so a copy edit doesn't break
// the tests but landing in the wrong branch does.
const NOT_A_CSV = /isn't a CSV/;
const PICK_A_TYPE = /pick a converter type/;
const FILE_AND_TYPE = /select a file and a converter type/;
const OUR_SIDE = /on our side/;

describe("uploadErrorMessage", () => {
  describe("413", () => {
    it("names the cap it is given, not the 50MB the server's own text hardcodes", () => {
      const message = uploadErrorMessage(413, "File size exceeds 50MB limit", 10 * MB);
      expect(message).toContain("10MB");
      expect(message).not.toContain("50MB");
    });

    it("falls back to the 50MB default cap", () => {
      expect(uploadErrorMessage(413)).toContain("50MB");
    });
  });

  it("asks the user to wait out a rate limit (429)", () => {
    expect(uploadErrorMessage(429, "Too many requests")).toMatch(/wait about a minute/);
  });

  it.each([401, 403])("reports an expired session for %i", (status) => {
    expect(uploadErrorMessage(status, "Unauthorized")).toMatch(/session expired/);
  });

  describe("400", () => {
    it.each([
      ["Only CSV files are accepted", NOT_A_CSV],
      ["ONLY CSV FILES ARE ACCEPTED", NOT_A_CSV],
      ["Converter type must be 'counseling', 'training', or 'training-client'", PICK_A_TYPE],
      ["File and converter type are required", FILE_AND_TYPE],
    ])("maps %j to its own message", (serverError, expected) => {
      expect(uploadErrorMessage(400, serverError)).toMatch(expected);
    });

    it("tells a user missing the file to select one, not only to pick a type", () => {
      // The route sends this one string whether the file or the type is
      // missing. It also contains "converter type", so checking for that
      // phrase first sent a user who forgot the file to the type picker.
      const message = uploadErrorMessage(400, "File and converter type are required");
      expect(message).not.toMatch(PICK_A_TYPE);
      expect(message).toMatch(FILE_AND_TYPE);
    });

    it("passes an unrecognized server message through verbatim", () => {
      expect(uploadErrorMessage(400, "Invalid previousJobId")).toBe("Invalid previousJobId");
    });

    it("has a generic message when the server gave none", () => {
      expect(uploadErrorMessage(400)).toMatch(/upload was rejected/);
    });
  });

  it.each([500, 502, 503, 504])(
    "reports a server failure (%i) without echoing the server's text",
    (status) => {
      const message = uploadErrorMessage(status, "PrismaClientKnownRequestError P2022");
      expect(message).toMatch(OUR_SIDE);
      expect(message).not.toContain("P2022");
    }
  );

  it("passes any other status's server message through, with a fallback", () => {
    expect(uploadErrorMessage(409, "Job already exists")).toBe("Job already exists");
    expect(uploadErrorMessage(418)).toBe("Upload failed. Please try again.");
  });
});

/**
 * upload-errors.ts maps the upload route's 400s by matching words in their
 * text, and its header asks for the two to be kept in sync. Nothing enforced
 * that: reword a route message and the user silently gets the raw server text
 * — or, as happened, a different branch's advice. These drive the real route
 * into each 400 it can send and check the message the user would see.
 */
describe("stays in sync with the /api/upload route's 400s", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(getRequiredUser).mockResolvedValue(TEST_USER as never);
    vi.mocked(rateLimit).mockResolvedValue({ success: true, remaining: 9 });
  });

  it.each([
    ["no file", { omitFile: true, converterType: "counseling" }, FILE_AND_TYPE],
    ["no converter type", {}, FILE_AND_TYPE],
    ["a file that is not a CSV", { fileName: "export.xlsx", converterType: "counseling" }, NOT_A_CSV],
    ["an unknown converter type", { converterType: "bogus" }, PICK_A_TYPE],
  ] as const)("an upload with %s", async (_label, opts, expected) => {
    const res = await upload(uploadRequest(opts));
    expect(res.status).toBe(400);
    const { error } = await res.json();
    expect(uploadErrorMessage(res.status, error)).toMatch(expected);
  });
});
