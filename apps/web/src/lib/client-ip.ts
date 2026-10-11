import { isIP } from "node:net";

/**
 * The client IP for rate-limit keys, or null when none can be trusted.
 *
 * Each proxy appends the address it received the request from, so only the
 * entries our own proxies added can be trusted, counted from the right; the
 * client can write anything to the left of them. This used to take the first
 * (leftmost) entry, which the client chooses, so rotating a fake address
 * escaped the signup and per-IP login limits. `TRUSTED_PROXY_HOPS` is how many
 * proxies sit in front of the app (default 1, e.g. Railway's edge; 2 with a CDN
 * in front of that; 0 to ignore the header). The chosen entry must parse as an
 * IPv4 or IPv6 address, so arbitrary header text never becomes a Redis key.
 */
export function clientIpFromHeaders(headers: Headers): string | null {
  const hops = trustedProxyHops();
  const forwarded = headers.get("x-forwarded-for");
  if (!forwarded || hops === 0) return null;
  const entries = forwarded.split(",").map((entry) => entry.trim());
  // Fewer entries than proxies: the request did not come through all of them.
  if (entries.length < hops) return null;
  const client = entries[entries.length - hops];
  // 45 is the longest textual IPv6 form; anything longer is not an address.
  if (!client || client.length > 45 || isIP(client) === 0) return null;
  return client;
}

function trustedProxyHops(): number {
  const raw = process.env.TRUSTED_PROXY_HOPS;
  const value = raw === undefined || raw === "" ? 1 : Number(raw);
  return Number.isInteger(value) && value >= 0 ? value : 1;
}
