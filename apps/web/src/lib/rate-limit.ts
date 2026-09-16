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
 *
 * The counter and its expiry are set in one MULTI. They used to be two
 * round trips — INCR, then EXPIRE only when the count had just become 1 —
 * so if the EXPIRE was lost (Redis blip between the two, process killed in
 * the gap) the key lived forever with no TTL and was never re-armed: after
 * `limit` more hits it answered 429 for good, and the shared
 * `signup:unknown` bucket or one user's `upload:<id>` stayed locked until
 * someone deleted the key by hand. `EXPIRE ... NX` (Redis 7) sets the TTL
 * only when the key has none, so it is idempotent across hits and also
 * heals a key that already lost its TTL.
 */
export async function rateLimit(
  key: string,
  limit: number,
  windowSeconds: number
): Promise<{ success: boolean; remaining: number }> {
  const redisKey = `rate-limit:${key}`;
  try {
    const redis = getRedis();
    const results = await redis
      .multi()
      .incr(redisKey)
      .expire(redisKey, windowSeconds, "NX")
      .exec();
    // exec() resolves to [[err, reply], ...] per command, or null if the
    // transaction was aborted; either way the counter is what matters.
    const incrResult = results?.[0];
    if (!incrResult || incrResult[0]) {
      throw incrResult?.[0] ?? new Error("rate-limit transaction aborted");
    }
    const current = Number(incrResult[1]);

    const remaining = Math.max(0, limit - current);
    return { success: current <= limit, remaining };
  } catch {
    // Redis is down or unreachable — fail open so a Redis outage
    // doesn't 429 every request.
    return { success: true, remaining: limit };
  }
}

/**
 * Clear a rate-limit counter.
 *
 * Used after a successful login so a user who mistypes their password a few
 * times and then gets it right isn't left throttled for the rest of the
 * window. Failures are swallowed for the same reason `rateLimit` fails open:
 * a Redis hiccup must not break sign-in.
 */
export async function resetRateLimit(key: string): Promise<void> {
  try {
    await getRedis().del(`rate-limit:${key}`);
  } catch {
    // Counter expires on its own; nothing to do.
  }
}
