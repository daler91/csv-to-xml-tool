import Redis, { RedisOptions } from "ioredis";

/**
 * Lazy Redis client.
 *
 * Previously this module eagerly created an `ioredis` instance at
 * module-load time, which made two things unpleasant:
 *
 * 1. `next build` prerenders client pages and traces server routes
 *    by importing them, which transitively imported this module
 *    and tried to open a TCP connection to `redis://localhost:6379`.
 *    With no Redis running at build time, ioredis dumped screaming
 *    `ECONNREFUSED` errors across the build output.
 *
 * 2. Any tool that imported an API route for static analysis
 *    (tests, type generators, etc.) would spawn a live connection
 *    attempt as a side-effect.
 *
 * The fix is two-part:
 *   - `lazyConnect: true` so even after the client object exists,
 *     no socket is opened until the first command is issued.
 *   - A `getRedis()` getter instead of a top-level instance, so the
 *     client object itself isn't created until something actually
 *     needs it.
 *
 * In production the first rate-limit call wakes the connection and
 * every call after that reuses the same client. In dev/build, if
 * nothing ever calls a rate-limited endpoint, no connection is ever
 * attempted.
 */

const globalForRedis = globalThis as unknown as { redis?: Redis };

const DEFAULT_OPTIONS: RedisOptions = {
  lazyConnect: true,
  // Cap retry attempts per command so a dead Redis doesn't hang a
  // request for minutes. The rate-limit call path already handles
  // errors gracefully.
  maxRetriesPerRequest: 3,
  // Back off aggressively after the first failure so we don't spin.
  retryStrategy: (times) => {
    if (times > 3) return null; // stop retrying
    return Math.min(times * 200, 1000);
  },
};

export function getRedis(): Redis {
  if (!globalForRedis.redis) {
    globalForRedis.redis = new Redis(
      process.env.REDIS_URL || "redis://localhost:6379",
      DEFAULT_OPTIONS
    );
  }
  return globalForRedis.redis;
}
