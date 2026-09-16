import { describe, it, expect } from "vitest";

import { clientIpFromHeaders } from "@/lib/client-ip";

const headers = (xff?: string) =>
  new Headers(xff === undefined ? {} : { "x-forwarded-for": xff });

describe("clientIpFromHeaders", () => {
  it("takes the first token of X-Forwarded-For", () => {
    expect(clientIpFromHeaders(headers("203.0.113.7, 10.0.0.1"))).toBe("203.0.113.7");
  });

  it("accepts IPv6", () => {
    expect(clientIpFromHeaders(headers("2001:db8::1"))).toBe("2001:db8::1");
  });

  it("rejects anything that is not an address, so it never becomes a Redis key", () => {
    expect(clientIpFromHeaders(headers("unknown"))).toBeNull();
    expect(clientIpFromHeaders(headers("evil key; DROP"))).toBeNull();
    expect(clientIpFromHeaders(headers("203.0.113.7.8"))).toBeNull();
    expect(clientIpFromHeaders(headers("x".repeat(5000)))).toBeNull();
    expect(clientIpFromHeaders(headers(""))).toBeNull();
    expect(clientIpFromHeaders(headers())).toBeNull();
  });
});
