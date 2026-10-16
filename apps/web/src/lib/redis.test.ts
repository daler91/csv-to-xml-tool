import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { EventEmitter } from "node:events";
import type { RedisOptions } from "ioredis";

/** Every client the module has constructed, in order. */
const clients = vi.hoisted(
  () => [] as Array<EventEmitter & { url: string; options: RedisOptions }>
);

// ioredis is an EventEmitter, and so is this stand-in: emitting "error" with
// no listener throws, which is how a real connection error takes the process
// down. Nothing here opens a socket.
vi.mock("ioredis", async () => {
  const { EventEmitter } = await import("node:events");
  class FakeRedis extends EventEmitter {
    constructor(
      public url: string,
      public options: RedisOptions
    ) {
      super();
      clients.push(this);
    }
  }
  return { default: FakeRedis };
});

// The client is cached on globalThis so a dev-server hot reload, which
// re-evaluates the module, reuses it rather than opening another connection.
const globalForRedis = globalThis as unknown as { redis?: unknown };

async function loadModule() {
  vi.resetModules();
  return import("@/lib/redis");
}

beforeEach(() => {
  delete globalForRedis.redis;
  clients.length = 0;
});

afterEach(() => {
  delete globalForRedis.redis;
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("getRedis", () => {
  it("creates no client just by being imported", async () => {
    // `next build` imports every server route; an eager client tried to reach
    // Redis at build time and filled the output with ECONNREFUSED.
    await loadModule();
    expect(clients).toHaveLength(0);
  });

  it("creates the client on first use, connecting lazily to REDIS_URL", async () => {
    vi.stubEnv("REDIS_URL", "redis://cache:6380");
    const { getRedis } = await loadModule();
    getRedis();
    expect(clients).toHaveLength(1);
    expect(clients[0].url).toBe("redis://cache:6380");
    expect(clients[0].options.lazyConnect).toBe(true);
  });

  it.each([
    ["unset", undefined],
    ["blank", ""],
  ])("falls back to localhost:6379 when REDIS_URL is %s", async (_label, value) => {
    vi.stubEnv("REDIS_URL", value);
    const { getRedis } = await loadModule();
    getRedis();
    expect(clients[0].url).toBe("redis://localhost:6379");
  });

  it("reuses one client across calls and across a module reload", async () => {
    const first = (await loadModule()).getRedis();
    expect((await loadModule()).getRedis()).toBe(first);
    expect(clients).toHaveLength(1);
  });

  it("keeps a connection error from becoming an unhandled 'error' event", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const client = (await loadModule()).getRedis() as unknown as EventEmitter;

    expect(() => client.emit("error", new Error("connect ECONNREFUSED"))).not.toThrow();
    expect(log).toHaveBeenCalledWith("Redis client error:", "connect ECONNREFUSED");
  });

  it("fails a command after a few retries rather than hanging the request", async () => {
    (await loadModule()).getRedis();
    // null would mean "retry forever" to ioredis.
    const { maxRetriesPerRequest } = clients[0].options;
    expect(Number.isFinite(maxRetriesPerRequest)).toBe(true);
    expect(maxRetriesPerRequest).toBeGreaterThan(0);
  });

  it("never stops reconnecting, backing off to a 5s ceiling", async () => {
    // Returning anything but a number tells ioredis to give up for good. This
    // once returned null after 3 attempts, so any outage longer than ~2s left
    // the client dead until a restart: rate limiting failed open and every
    // enqueue threw.
    (await loadModule()).getRedis();
    const retry = clients[0].options.retryStrategy!;

    let previous = 0;
    for (const attempt of [1, 2, 3, 4, 5, 10, 25, 100, 10_000]) {
      const delay = retry(attempt);
      expect(typeof delay, `attempt ${attempt}`).toBe("number");
      expect(delay as number).toBeGreaterThanOrEqual(previous);
      expect(delay as number).toBeLessThanOrEqual(5000);
      previous = delay as number;
    }
    expect(previous).toBe(5000);
  });
});
