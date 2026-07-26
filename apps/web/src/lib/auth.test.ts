import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/prisma", () => ({
  prisma: { user: { findUnique: vi.fn() } },
}));
vi.mock("@/lib/rate-limit", () => ({
  rateLimit: vi.fn(),
  resetRateLimit: vi.fn(),
}));
vi.mock("bcryptjs", () => ({ compare: vi.fn() }));
// vi.mock factories are hoisted above ordinary declarations, so the capture
// slot has to be hoisted with them.
const captured = vi.hoisted(() => ({ config: undefined as unknown }));

// NextAuth's factory runs at import time; stub it so importing the module under
// test doesn't try to build a real auth handler.
vi.mock("next-auth", () => ({
  default: (config: unknown) => {
    captured.config = config;
    return { handlers: {}, auth: vi.fn(), signIn: vi.fn(), signOut: vi.fn() };
  },
}));
vi.mock("next-auth/providers/credentials", () => ({
  default: (options: unknown) => options,
}));

import "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { rateLimit, resetRateLimit } from "@/lib/rate-limit";
import { compare } from "bcryptjs";

const db = vi.mocked(prisma, true);
const limiter = vi.mocked(rateLimit);
const resetLimiter = vi.mocked(resetRateLimit);
const bcryptCompare = vi.mocked(compare);

type AuthorizeFn = (
  credentials: Record<string, unknown>,
  request?: Request
) => Promise<unknown>;

function authorize(): AuthorizeFn {
  const config = captured.config as { providers: { authorize: AuthorizeFn }[] };
  return config.providers[0].authorize;
}

const CREDS = { email: "User@Example.com ", password: "hunter2" };
const USER = {
  id: "u1",
  email: "user@example.com",
  name: "User",
  passwordHash: "hash",
};

beforeEach(() => {
  vi.clearAllMocks();
  limiter.mockResolvedValue({ success: true, remaining: 9 });
  db.user.findUnique.mockResolvedValue(USER as never);
  bcryptCompare.mockResolvedValue(true as never);
});

describe("credentials authorize — throttling", () => {
  it("throttles by normalized email, so case variants share a bucket", async () => {
    await authorize()(CREDS);
    expect(limiter).toHaveBeenCalledWith(
      "login:email:user@example.com",
      expect.any(Number),
      expect.any(Number)
    );
  });

  it("rejects without ever hashing once the email limit is hit", async () => {
    limiter.mockResolvedValue({ success: false, remaining: 0 });
    const result = await authorize()(CREDS);
    expect(result).toBeNull();
    // The point of throttling: no bcrypt work, no user lookup.
    expect(bcryptCompare).not.toHaveBeenCalled();
    expect(db.user.findUnique).not.toHaveBeenCalled();
  });

  it("also throttles by forwarded IP when one is present", async () => {
    const request = new Request("http://localhost/api/auth/callback/credentials", {
      headers: { "x-forwarded-for": "203.0.113.9, 10.0.0.1" },
    });
    await authorize()(CREDS, request);
    expect(limiter).toHaveBeenCalledWith(
      "login:ip:203.0.113.9",
      expect.any(Number),
      expect.any(Number)
    );
  });

  it("does not require a forwarded IP", async () => {
    await expect(authorize()(CREDS)).resolves.toMatchObject({ id: "u1" });
    expect(limiter).toHaveBeenCalledTimes(1);
  });

  it("clears the counter after a successful sign-in", async () => {
    await authorize()(CREDS);
    expect(resetLimiter).toHaveBeenCalledWith("login:email:user@example.com");
  });

  it("leaves the counter alone when the password is wrong", async () => {
    bcryptCompare.mockResolvedValue(false as never);
    expect(await authorize()(CREDS)).toBeNull();
    expect(resetLimiter).not.toHaveBeenCalled();
  });
});

describe("credentials authorize — enumeration resistance", () => {
  it("returns null identically for unknown user, bad password and throttled", async () => {
    db.user.findUnique.mockResolvedValue(null as never);
    expect(await authorize()(CREDS)).toBeNull();

    db.user.findUnique.mockResolvedValue(USER as never);
    bcryptCompare.mockResolvedValue(false as never);
    expect(await authorize()(CREDS)).toBeNull();

    limiter.mockResolvedValue({ success: false, remaining: 0 });
    expect(await authorize()(CREDS)).toBeNull();
  });

  it("rejects missing credentials without touching the limiter", async () => {
    expect(await authorize()({ email: "", password: "" })).toBeNull();
    expect(limiter).not.toHaveBeenCalled();
  });
});
