import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/redis", () => ({ getRedis: vi.fn() }));

import { rateLimit } from "@/lib/rate-limit";
import { getRedis } from "@/lib/redis";

const mockGetRedis = vi.mocked(getRedis);

/**
 * A Redis whose MULTI records the queued commands and answers INCR with
 * `incrValue`. `expireReply` lets a test simulate an EXPIRE that errored
 * inside the transaction.
 */
function fakeRedis(incrValue: number, expireReply: [Error | null, unknown] = [null, 1]) {
  const queued: unknown[][] = [];
  const multi = {
    incr: vi.fn((...args: unknown[]) => {
      queued.push(["incr", ...args]);
      return multi;
    }),
    expire: vi.fn((...args: unknown[]) => {
      queued.push(["expire", ...args]);
      return multi;
    }),
    exec: vi.fn().mockResolvedValue([[null, incrValue], expireReply]),
  };
  return {
    multi: vi.fn(() => multi),
    queued,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("rateLimit", () => {
  it("allows under the limit and arms the window expiry in the same transaction", async () => {
    const redis = fakeRedis(1);
    mockGetRedis.mockReturnValue(redis);

    const res = await rateLimit("k", 5, 60);

    expect(res).toEqual({ success: true, remaining: 4 });
    expect(redis.queued).toEqual([
      ["incr", "rate-limit:k"],
      ["expire", "rate-limit:k", 60, "NX"],
    ]);
  });

  it("re-issues EXPIRE NX on every hit, so a key that lost its TTL is healed rather than stuck", async () => {
    const redis = fakeRedis(3);
    mockGetRedis.mockReturnValue(redis);

    const res = await rateLimit("k", 5, 60);

    expect(res).toEqual({ success: true, remaining: 2 });
    // NX means an existing TTL is not reset, so the window is not extended.
    expect(redis.queued[1]).toEqual(["expire", "rate-limit:k", 60, "NX"]);
  });

  it("denies once the count exceeds the limit", async () => {
    mockGetRedis.mockReturnValue(fakeRedis(6));

    const res = await rateLimit("k", 5, 60);

    expect(res).toEqual({ success: false, remaining: 0 });
  });

  it("fails OPEN when Redis is unreachable", async () => {
    mockGetRedis.mockImplementation(() => {
      throw new Error("ECONNREFUSED");
    });

    const res = await rateLimit("k", 5, 60);

    expect(res).toEqual({ success: true, remaining: 5 });
  });

  it("fails OPEN when the transaction is aborted", async () => {
    const redis = fakeRedis(1);
    redis.multi().exec.mockResolvedValue(null);
    mockGetRedis.mockReturnValue(redis);

    const res = await rateLimit("k", 5, 60);

    expect(res).toEqual({ success: true, remaining: 5 });
  });
});
