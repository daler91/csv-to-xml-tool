import { NextResponse } from "next/server";
import { Prisma } from "@prisma/client";
import { hash } from "bcryptjs";
import { prisma } from "@/lib/prisma";
import { rateLimit } from "@/lib/rate-limit";
import { normalizeEmail } from "@/lib/normalize";
import { clientIpFromHeaders } from "@/lib/client-ip";

function getClientIdentifier(req: Request): string {
  // The first X-Forwarded-For token, only when it is an IP address (see
  // lib/client-ip.ts); everything else shares the "unknown" bucket.
  return clientIpFromHeaders(req.headers) ?? "unknown";
}

// RFC 5321 caps an address at 254 characters; the shape check is deliberately
// loose (something@label.label) -- it exists to reject obvious garbage, not to
// validate deliverability. The domain is spelled as dot-separated labels that
// themselves exclude the dot: the earlier `[^\s@]+\.[^\s@]+` let the two
// classes overlap on ".", which backtracks super-linearly on a long, dotted,
// invalid input.
const MAX_EMAIL_LENGTH = 254;
const EMAIL_SHAPE = /^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+$/;
const MAX_NAME_LENGTH = 100;

function validatePasswordComplexity(password: string): string | null {
  if (password.length < 8) {
    return "Password must be at least 8 characters";
  }
  if (!/[A-Z]/.test(password)) {
    return "Password must contain at least one uppercase letter";
  }
  if (!/\d/.test(password)) {
    return "Password must contain at least one digit";
  }
  if (!/[^A-Za-z0-9]/.test(password)) {
    return "Password must contain at least one special character";
  }
  return null;
}

export async function POST(req: Request) {
  try {
    const ip = getClientIdentifier(req);
    const { success, remaining } = await rateLimit(`signup:${ip}`, 5, 60);
    if (!success) {
      return NextResponse.json(
        { error: "Too many requests" },
        { status: 429, headers: { "X-RateLimit-Remaining": String(remaining) } }
      );
    }

    // Malformed JSON is the caller's mistake (400), not a server error.
    const body: unknown = await req.json().catch(() => null);
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return NextResponse.json(
        { error: "Request body must be a JSON object" },
        { status: 400 }
      );
    }
    const { email: rawEmail, password, name } = body as Record<string, unknown>;
    const email = typeof rawEmail === "string" ? normalizeEmail(rawEmail) : "";

    if (!email || typeof password !== "string" || !password) {
      return NextResponse.json(
        { error: "Email and password are required" },
        { status: 400 }
      );
    }
    if (email.length > MAX_EMAIL_LENGTH || !EMAIL_SHAPE.test(email)) {
      return NextResponse.json(
        { error: "Enter a valid email address" },
        { status: 400 }
      );
    }
    // A non-string name reached Prisma's validation and came back as a 500.
    if (name !== undefined && name !== null && typeof name !== "string") {
      return NextResponse.json({ error: "Name must be text" }, { status: 400 });
    }
    const trimmedName = typeof name === "string" ? name.trim().slice(0, MAX_NAME_LENGTH) : "";

    const passwordError = validatePasswordComplexity(password);
    if (passwordError) {
      return NextResponse.json(
        { error: passwordError },
        { status: 400 }
      );
    }

    const existing = await prisma.user.findUnique({ where: { email } });
    if (existing) {
      return NextResponse.json(
        { error: "Email already registered" },
        { status: 409 }
      );
    }

    const passwordHash = await hash(password, 12);
    const user = await prisma.user.create({
      data: { email, passwordHash, name: trimmedName || null },
    });

    return NextResponse.json(
      { id: user.id, email: user.email },
      { status: 201 }
    );
  } catch (error) {
    // Two signups for the same address racing past the findUnique above:
    // the unique index rejects the second, which is the same 409 as the
    // check, not a 500.
    if (
      error instanceof Prisma.PrismaClientKnownRequestError &&
      error.code === "P2002"
    ) {
      return NextResponse.json(
        { error: "Email already registered" },
        { status: 409 }
      );
    }
    console.error("Signup error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
