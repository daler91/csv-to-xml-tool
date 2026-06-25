import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/redis", () => ({ getRedis: vi.fn() }));

import { rateLimit } from "@/lib/rate-limit";
import { getRedis } from "@/lib/redis";

const mockGetRedis = vi.mocked(getRedis);

function fakeRedis(incrValue: number) {
  return {
    incr: vi.fn().mockResolvedValue(incrValue),
    expire: vi.fn().mockResolvedValue(1),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("rateLimit", () => {
  it("allows under the limit and sets the window expiry on the first hit", async () => {
    const redis = fakeRedis(1);
    mockGetRedis.mockReturnValue(redis);

    const res = await rateLimit("k", 5, 60);

    expect(res).toEqual({ success: true, remaining: 4 });
    expect(redis.expire).toHaveBeenCalledWith("rate-limit:k", 60);
  });

  it("does not reset the expiry on subsequent hits", async () => {
    const redis = fakeRedis(3);
    mockGetRedis.mockReturnValue(redis);

    const res = await rateLimit("k", 5, 60);

    expect(res).toEqual({ success: true, remaining: 2 });
    expect(redis.expire).not.toHaveBeenCalled();
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
});
