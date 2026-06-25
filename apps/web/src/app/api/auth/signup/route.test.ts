import { describe, it, expect, vi, beforeEach } from "vitest";
import { jsonRequest } from "@/test/helpers";

vi.mock("@/lib/prisma", () => ({
  prisma: { user: { findUnique: vi.fn(), create: vi.fn() } },
}));
vi.mock("@/lib/rate-limit", () => ({ rateLimit: vi.fn() }));
vi.mock("bcryptjs", () => ({ hash: vi.fn() }));

import { POST } from "@/app/api/auth/signup/route";
import { prisma } from "@/lib/prisma";
import { rateLimit } from "@/lib/rate-limit";
import { hash } from "bcryptjs";

const db = vi.mocked(prisma, true);
const limit = vi.mocked(rateLimit);
const hashMock = vi.mocked(hash);

const signup = (body: Record<string, unknown>) =>
  POST(jsonRequest("http://localhost/api/auth/signup", "POST", body));

beforeEach(() => {
  vi.resetAllMocks();
  limit.mockResolvedValue({ success: true, remaining: 4 });
  db.user.findUnique.mockResolvedValue(null as never);
  db.user.create.mockResolvedValue({ id: "u1", email: "new@example.com" } as never);
  hashMock.mockResolvedValue("hashed" as never);
});

describe("POST /api/auth/signup", () => {
  it.each([
    ["Pass1!", "at least 8 characters"],
    ["password123!", "uppercase"],
    ["Password!", "digit"],
    ["Password123", "special character"],
  ])("rejects a weak password %s", async (password, fragment) => {
    const res = await signup({ email: "new@example.com", password });
    expect(res.status).toBe(400);
    expect((await res.json()).error).toContain(fragment);
    expect(db.user.create).not.toHaveBeenCalled();
  });

  it("returns 409 for a duplicate email", async () => {
    db.user.findUnique.mockResolvedValue({ id: "existing" } as never);
    const res = await signup({ email: "taken@example.com", password: "ValidPass123!" });
    expect(res.status).toBe(409);
    expect(db.user.create).not.toHaveBeenCalled();
  });

  it("hashes the password and creates the user (201) without leaking the hash", async () => {
    const res = await signup({
      email: "new@example.com",
      password: "ValidPass123!",
      name: "New",
    });
    expect(res.status).toBe(201);
    expect(hashMock).toHaveBeenCalledWith("ValidPass123!", 12);
    const body = await res.json();
    expect(body).toEqual({ id: "u1", email: "new@example.com" });
    expect(body).not.toHaveProperty("passwordHash");
  });

  it("returns 429 when rate limited", async () => {
    limit.mockResolvedValue({ success: false, remaining: 0 });
    const res = await signup({ email: "new@example.com", password: "ValidPass123!" });
    expect(res.status).toBe(429);
  });

  it("normalizes the email (trim + lowercase) before lookup and creation", async () => {
    const res = await signup({ email: "  New@Example.COM  ", password: "ValidPass123!" });
    expect(res.status).toBe(201);
    expect(db.user.findUnique).toHaveBeenCalledWith({
      where: { email: "new@example.com" },
    });
    expect(db.user.create).toHaveBeenCalledWith({
      data: { email: "new@example.com", passwordHash: "hashed", name: null },
    });
  });

  it("detects a duplicate regardless of the submitted email's case", async () => {
    db.user.findUnique.mockResolvedValue({ id: "existing" } as never);
    const res = await signup({ email: "TAKEN@Example.com", password: "ValidPass123!" });
    expect(res.status).toBe(409);
    expect(db.user.findUnique).toHaveBeenCalledWith({
      where: { email: "taken@example.com" },
    });
    expect(db.user.create).not.toHaveBeenCalled();
  });

  it("rejects a whitespace-only email as missing", async () => {
    const res = await signup({ email: "   ", password: "ValidPass123!" });
    expect(res.status).toBe(400);
    expect(db.user.findUnique).not.toHaveBeenCalled();
    expect(db.user.create).not.toHaveBeenCalled();
  });
});
