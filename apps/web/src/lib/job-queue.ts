import Redis from "ioredis";

import { getRedis } from "@/lib/redis";

/**
 * Durable, web-owned job queue (ARCH-1) built on Redis.
 *
 * The web enqueues a job id when a conversion is started; a background consumer
 * (src/lib/job-consumer.ts) claims it, runs the conversion, and persists the
 * result. A claimed job that isn't acked within the visibility timeout is
 * treated as abandoned (its consumer died) and re-queued by the sweep — that is
 * the durability win over the old fire-and-forget call.
 *
 * Keys (all string-only ops so the existing Redis works):
 *   pending     LIST  — job ids awaiting a consumer (LPUSH on, BLMOVE off the right)
 *   processing  LIST  — job ids currently claimed (BLMOVE target; crash-visible)
 *   claims      ZSET  — jobId -> claim epoch-ms, so the sweep can find stale claims
 *   attempts    HASH  — jobId -> attempt count, for retry / dead-letter
 */

const PREFIX = "csvxml:jobs:";
const PENDING = `${PREFIX}pending`;
const PROCESSING = `${PREFIX}processing`;
const CLAIMS = `${PREFIX}claims`;
const ATTEMPTS = `${PREFIX}attempts`;

// A job claimed (in PROCESSING) longer than this is treated as abandoned and
// re-queued by the sweep. MUST exceed CONVERSION_TIMEOUT_MS (the per-attempt
// worker timeout) so the sweep never reclaims a job a live consumer is still
// legitimately running, and SHOULD be below the reaper deadline so the sweep's
// retry gets first crack before the reaper backstops the job to "error".
const VISIBILITY_TIMEOUT_MS =
  Number(process.env.VISIBILITY_TIMEOUT_MS) || 40 * 60 * 1000;

/**
 * Dedicated Redis connection for the blocking consumer.
 *
 * `BLMOVE` blocks the socket for its whole timeout, so it must NOT run on the
 * shared `getRedis()` client (that would stall every rate-limit INCR sharing it).
 * `maxRetriesPerRequest: null` is required for blocking commands (the shared
 * client's retry cap throws on them); instead we keep reconnecting so a transient
 * Redis blip doesn't kill the consumer loop.
 */
const globalForQueue = globalThis as unknown as { queueRedis?: Redis };

export function getQueueRedis(): Redis {
  if (!globalForQueue.queueRedis) {
    const client = new Redis(process.env.REDIS_URL || "redis://localhost:6379", {
      lazyConnect: true,
      maxRetriesPerRequest: null,
      retryStrategy: (times) => Math.min(times * 200, 2000),
    });
    // Without a listener, ioredis re-emits connection errors as an unhandled
    // 'error' event, which would crash the process. Log and let it reconnect.
    client.on("error", (err) => {
      console.error("[job-queue] redis connection error:", err.message);
    });
    globalForQueue.queueRedis = client;
  }
  return globalForQueue.queueRedis;
}

/** Enqueue a job id for the consumer. Uses the shared client (a quick LPUSH). */
export async function enqueueJob(jobId: string): Promise<void> {
  await getRedis().lpush(PENDING, jobId);
}

/**
 * Block up to `timeoutSec` for the next job, atomically moving it from PENDING
 * to PROCESSING; record the claim time and bump the attempt count. Returns the
 * job id, or null on timeout.
 */
export async function claimJob(timeoutSec: number): Promise<string | null> {
  const redis = getQueueRedis();
  const jobId = await redis.blmove(
    PENDING,
    PROCESSING,
    "RIGHT",
    "LEFT",
    timeoutSec
  );
  if (jobId === null) return null;
  await redis.zadd(CLAIMS, Date.now(), jobId);
  await redis.hincrby(ATTEMPTS, jobId, 1);
  return jobId;
}

/** Current attempt count for a job (incremented at each claim). */
export async function getAttempts(jobId: string): Promise<number> {
  const v = await getQueueRedis().hget(ATTEMPTS, jobId);
  return v ? Number(v) : 0;
}

/** Remove a finished job from every queue structure. */
export async function ackJob(jobId: string): Promise<void> {
  const redis = getQueueRedis();
  await redis.lrem(PROCESSING, 0, jobId);
  await redis.zrem(CLAIMS, jobId);
  await redis.hdel(ATTEMPTS, jobId);
}

/** Put a job back on PENDING for another attempt (keeps the attempt count). */
export async function requeueJob(jobId: string): Promise<void> {
  const redis = getQueueRedis();
  await redis.lrem(PROCESSING, 0, jobId);
  await redis.zrem(CLAIMS, jobId);
  await redis.lpush(PENDING, jobId);
}

/**
 * Re-queue any claims older than the visibility timeout — jobs whose consumer
 * died mid-run. The `LREM`-returns-1 gate makes this safe under competing
 * consumers: only the instance that actually removes the PROCESSING entry
 * re-queues it. Returns the ids re-queued.
 */
export async function sweepStaleClaims(): Promise<string[]> {
  const redis = getQueueRedis();
  const cutoff = Date.now() - VISIBILITY_TIMEOUT_MS;
  const stale = await redis.zrangebyscore(CLAIMS, 0, cutoff);
  const reclaimed: string[] = [];
  for (const jobId of stale) {
    const removed = await redis.lrem(PROCESSING, 1, jobId);
    await redis.zrem(CLAIMS, jobId);
    if (removed > 0) {
      await redis.lpush(PENDING, jobId);
      reclaimed.push(jobId);
    }
  }
  return reclaimed;
}
