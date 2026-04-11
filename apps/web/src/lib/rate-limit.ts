import { getRedis } from "./redis";

/**
 * Token-bucket-style rate limit backed by Redis.
 *
 * If Redis is unreachable (build-time prerender, dev without the
 * container running, transient outage), we fail **open** — the
 * caller is allowed through but gets an unknown ``remaining`` count.
 * The alternative (fail-closed on any Redis error) would brick the
 * entire app whenever Redis hiccups, which is worse than a brief
 * rate-limit gap.
 */
export async function rateLimit(
  key: string,
  limit: number,
  windowSeconds: number
): Promise<{ success: boolean; remaining: number }> {
  const redisKey = `rate-limit:${key}`;
  try {
    const redis = getRedis();
    const current = await redis.incr(redisKey);

    if (current === 1) {
      await redis.expire(redisKey, windowSeconds);
    }

    const remaining = Math.max(0, limit - current);
    return { success: current <= limit, remaining };
  } catch {
    // Redis is down or unreachable — fail open so a Redis outage
    // doesn't 429 every request.
    return { success: true, remaining: limit };
  }
}
