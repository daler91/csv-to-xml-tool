import { describe, it, expect, vi, beforeEach } from "vitest";

// One fake Redis client shared by both the dedicated queue connection
// (`new Redis()` inside getQueueRedis) and the shared `getRedis()`.
const client = vi.hoisted(() => ({
  blmove: vi.fn(),
  zadd: vi.fn(),
  hincrby: vi.fn(),
  hget: vi.fn(),
  lrem: vi.fn(),
  zrem: vi.fn(),
  hdel: vi.fn(),
  lpush: vi.fn(),
  zrangebyscore: vi.fn(),
  on: vi.fn(),
}));

// getQueueRedis does `new Redis(...)`, so the mock default must be constructable
// (an arrow isn't); the constructor returns the shared fake client.
vi.mock("ioredis", () => ({
  default: class {
    constructor() {
      return client;
    }
  },
}));
vi.mock("@/lib/redis", () => ({ getRedis: vi.fn(() => client) }));

import {
  enqueueJob,
  claimJob,
  ackJob,
  requeueJob,
  getAttempts,
  promoteDueJobs,
  sweepStaleClaims,
} from "@/lib/job-queue";

const PENDING = "csvxml:jobs:pending";
const PROCESSING = "csvxml:jobs:processing";
const CLAIMS = "csvxml:jobs:claims";
const ATTEMPTS = "csvxml:jobs:attempts";
const DELAYED = "csvxml:jobs:delayed";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("enqueueJob", () => {
  it("LPUSHes the job id onto pending", async () => {
    await enqueueJob("j1");
    expect(client.lpush).toHaveBeenCalledWith(PENDING, "j1");
  });
});

describe("claimJob", () => {
  it("BLMOVEs pending→processing, records the claim time, and bumps attempts", async () => {
    client.blmove.mockResolvedValue("j1");

    const id = await claimJob(5);

    expect(id).toBe("j1");
    expect(client.blmove).toHaveBeenCalledWith(
      PENDING,
      PROCESSING,
      "RIGHT",
      "LEFT",
      5
    );
    expect(client.zadd).toHaveBeenCalledWith(CLAIMS, expect.any(Number), "j1");
    expect(client.hincrby).toHaveBeenCalledWith(ATTEMPTS, "j1", 1);
  });

  it("returns null on timeout without recording a claim", async () => {
    client.blmove.mockResolvedValue(null);

    const id = await claimJob(5);

    expect(id).toBeNull();
    expect(client.zadd).not.toHaveBeenCalled();
    expect(client.hincrby).not.toHaveBeenCalled();
  });
});

describe("ackJob", () => {
  it("removes the job from processing, claims, and attempts", async () => {
    await ackJob("j1");
    expect(client.lrem).toHaveBeenCalledWith(PROCESSING, 0, "j1");
    expect(client.zrem).toHaveBeenCalledWith(CLAIMS, "j1");
    expect(client.hdel).toHaveBeenCalledWith(ATTEMPTS, "j1");
  });
});

describe("requeueJob", () => {
  it("moves the job back to pending and keeps the attempt count", async () => {
    await requeueJob("j1");
    expect(client.lrem).toHaveBeenCalledWith(PROCESSING, 0, "j1");
    expect(client.zrem).toHaveBeenCalledWith(CLAIMS, "j1");
    expect(client.lpush).toHaveBeenCalledWith(PENDING, "j1");
    expect(client.hdel).not.toHaveBeenCalled(); // attempts preserved
  });
});

describe("requeueJob with a delay", () => {
  it("parks the job in delayed instead of pending", async () => {
    vi.spyOn(Date, "now").mockReturnValue(1_000);

    await requeueJob("j1", 30_000);

    expect(client.lrem).toHaveBeenCalledWith(PROCESSING, 0, "j1");
    expect(client.zrem).toHaveBeenCalledWith(CLAIMS, "j1");
    expect(client.zadd).toHaveBeenCalledWith(DELAYED, 31_000, "j1");
    expect(client.lpush).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});

describe("promoteDueJobs", () => {
  it("moves due retries to pending, only those it actually removes", async () => {
    client.zrangebyscore.mockResolvedValue(["j1", "j2"]);
    // j2 was promoted by a competing consumer first.
    client.zrem.mockResolvedValueOnce(1).mockResolvedValueOnce(0);

    const promoted = await promoteDueJobs(5_000);

    expect(client.zrangebyscore).toHaveBeenCalledWith(DELAYED, 0, 5_000);
    expect(promoted).toEqual(["j1"]);
    expect(client.lpush).toHaveBeenCalledTimes(1);
    expect(client.lpush).toHaveBeenCalledWith(PENDING, "j1");
  });

  it("does nothing when no retry is due", async () => {
    client.zrangebyscore.mockResolvedValue([]);
    expect(await promoteDueJobs()).toEqual([]);
    expect(client.lpush).not.toHaveBeenCalled();
  });
});

describe("getAttempts", () => {
  it("parses the stored count and defaults to 0", async () => {
    client.hget.mockResolvedValueOnce("3");
    expect(await getAttempts("j1")).toBe(3);
    client.hget.mockResolvedValueOnce(null);
    expect(await getAttempts("j1")).toBe(0);
  });
});

describe("sweepStaleClaims", () => {
  it("re-queues ONLY the stale claims it actually removes from processing", async () => {
    client.zrangebyscore.mockResolvedValue(["stale1", "stale2"]);
    // stale1 still in processing (LREM→1); stale2 already gone (LREM→0).
    client.lrem.mockResolvedValueOnce(1).mockResolvedValueOnce(0);

    const reclaimed = await sweepStaleClaims();

    expect(reclaimed).toEqual(["stale1"]);
    expect(client.lpush).toHaveBeenCalledTimes(1);
    expect(client.lpush).toHaveBeenCalledWith(PENDING, "stale1");
    // both claims are cleared from the ZSET regardless of the LREM result
    expect(client.zrem).toHaveBeenCalledWith(CLAIMS, "stale1");
    expect(client.zrem).toHaveBeenCalledWith(CLAIMS, "stale2");
  });

  it("returns an empty list when nothing is stale", async () => {
    client.zrangebyscore.mockResolvedValue([]);
    expect(await sweepStaleClaims()).toEqual([]);
    expect(client.lpush).not.toHaveBeenCalled();
  });
});
