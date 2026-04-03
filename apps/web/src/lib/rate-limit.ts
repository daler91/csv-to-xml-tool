import { redis } from "./redis";

export async function rateLimit(
  key: string,
  limit: number,
  windowSeconds: number
): Promise<{ success: boolean; remaining: number }> {
  const redisKey = `rate-limit:${key}`;
  const current = await redis.incr(redisKey);

  if (current === 1) {
    await redis.expire(redisKey, windowSeconds);
  }

  const remaining = Math.max(0, limit - current);
  return { success: current <= limit, remaining };
}
