import { isIP } from "node:net";

/**
 * The client IP for rate-limit keys, or null when none can be trusted.
 *
 * Only the first `X-Forwarded-For` token is used (the client, as appended by
 * the first proxy) and only when it parses as an IPv4 or IPv6 address. Before
 * this check the raw token — any string of any length an attacker chose to
 * send — became a Redis key verbatim. Without a trusted-proxy allowlist the
 * header is still spoofable, which is why the login throttle keys primarily
 * on the email and treats the IP as a secondary control.
 */
export function clientIpFromHeaders(headers: Headers): string | null {
  const forwarded = headers.get("x-forwarded-for");
  if (!forwarded) return null;
  const first = forwarded.split(",")[0].trim();
  // 45 is the longest textual IPv6 form; anything longer is not an address.
  if (!first || first.length > 45 || isIP(first) === 0) return null;
  return first;
}
