import { afterEach, describe, it, expect, vi } from "vitest";

import { clientIpFromHeaders } from "@/lib/client-ip";

const headers = (xff?: string) =>
  new Headers(xff === undefined ? {} : { "x-forwarded-for": xff });

describe("clientIpFromHeaders", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("takes the entry our proxy appended, not the one the client wrote", () => {
    // The client sent "X-Forwarded-For: 198.51.100.1"; the edge proxy
    // appended the address it actually saw.
    expect(clientIpFromHeaders(headers("198.51.100.1, 203.0.113.7"))).toBe("203.0.113.7");
    expect(clientIpFromHeaders(headers("203.0.113.7"))).toBe("203.0.113.7");
  });

  it("counts TRUSTED_PROXY_HOPS from the right", () => {
    vi.stubEnv("TRUSTED_PROXY_HOPS", "2");
    expect(clientIpFromHeaders(headers("198.51.100.1, 203.0.113.7, 10.0.0.1"))).toBe("203.0.113.7");
    // Fewer entries than proxies: it did not come through them all.
    expect(clientIpFromHeaders(headers("203.0.113.7"))).toBeNull();

    vi.stubEnv("TRUSTED_PROXY_HOPS", "0");
    expect(clientIpFromHeaders(headers("203.0.113.7"))).toBeNull();
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
