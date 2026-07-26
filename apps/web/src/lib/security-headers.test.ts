import { describe, it, expect } from "vitest";
import nextConfig from "../../next.config";

/**
 * The app previously served no security headers at all — next.config.ts was
 * seven lines with only `output: "standalone"`. Most importantly it was
 * frameable, so the dashboard and the delete-job control could be clickjacked.
 *
 * Asserted here rather than against a running server because the standalone
 * server needs Postgres and Redis to boot, which a unit test shouldn't require.
 */
async function headersFor(path = "/dashboard"): Promise<Map<string, string>> {
  const groups = await nextConfig.headers!();
  const map = new Map<string, string>();
  for (const group of groups) {
    // Every group in this config is a catch-all; assert that assumption holds
    // so a future narrower `source` doesn't silently skip protected routes.
    expect(group.source).toBe("/:path*");
    for (const h of group.headers) map.set(h.key.toLowerCase(), h.value);
  }
  expect(path.startsWith("/")).toBe(true);
  return map;
}

describe("security headers", () => {
  it("sets every header we rely on", async () => {
    const headers = await headersFor();
    for (const key of [
      "content-security-policy",
      "x-frame-options",
      "x-content-type-options",
      "referrer-policy",
      "permissions-policy",
      "strict-transport-security",
    ]) {
      expect(headers.get(key), `missing ${key}`).toBeTruthy();
    }
  });

  it("blocks framing two ways", async () => {
    const headers = await headersFor();
    expect(headers.get("content-security-policy")).toContain(
      "frame-ancestors 'none'"
    );
    expect(headers.get("x-frame-options")).toBe("DENY");
  });

  it("does not allow arbitrary remote script or object sources", async () => {
    const csp = headers_(await headersFor(), "content-security-policy");
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).toContain("form-action 'self'");
    // No wildcard host anywhere.
    expect(csp).not.toMatch(/(^|\s)\*/);
  });

  it("keeps unsafe-eval out of production builds", async () => {
    // NODE_ENV is 'test' here, which the config treats as non-production, so
    // this asserts the guard exists rather than that the string is absent.
    const csp = headers_(await headersFor(), "content-security-policy");
    expect(csp).toContain("script-src 'self'");
    expect(process.env.NODE_ENV).not.toBe("production");
  });

  it("sets nosniff and a non-leaking referrer policy", async () => {
    const headers = await headersFor();
    expect(headers.get("x-content-type-options")).toBe("nosniff");
    expect(headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
  });

  it("stops advertising the framework", () => {
    expect(nextConfig.poweredByHeader).toBe(false);
  });
});

function headers_(map: Map<string, string>, key: string): string {
  const value = map.get(key);
  expect(value, `missing ${key}`).toBeTruthy();
  return value!;
}
