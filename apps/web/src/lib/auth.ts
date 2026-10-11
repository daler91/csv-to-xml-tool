import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { compare } from "bcryptjs";
import { prisma } from "./prisma";
import { normalizeEmail } from "./normalize";
import { rateLimit, resetRateLimit } from "./rate-limit";
import { authConfig } from "./auth.config";
import { clientIpFromHeaders } from "./client-ip";
import { recordAudit } from "./audit";

/**
 * Sign-in throttling.
 *
 * Signup and upload were rate-limited but the credentials callback was not:
 * `/api/auth/*` is outside the middleware matcher, so password guessing was
 * bounded only by bcrypt's cost factor. There is no account-lockout column in
 * the schema, so this is a Redis counter rather than persistent state.
 *
 * Keyed on the normalized email, which is what actually throttles credential
 * stuffing against a known account. An IP-derived key is layered on when a
 * forwarded address is available, but it is deliberately secondary: without a
 * trusted-proxy allowlist an attacker can rotate `X-Forwarded-For` freely, so
 * it must not be the only control.
 */
const LOGIN_MAX_ATTEMPTS = 10;
const LOGIN_WINDOW_SECONDS = 15 * 60;
const LOGIN_IP_MAX_ATTEMPTS = 50;

// A bcrypt hash at the cost signup uses (12) of a random password nobody has.
// Comparing against it when the email is unknown makes that failure take as
// long as a wrong password; returning straight away answered about 250 ms
// sooner, which told a caller the address had no account.
const DUMMY_PASSWORD_HASH = "$2b$12$iHtg.KAbRw7x.keyCjz3guGISulIU0grVX1ithEy743EPHMAcETmW";

export const { handlers, auth, signIn, signOut } = NextAuth({
  ...authConfig,
  providers: [
    Credentials({
      name: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials, request) {
        if (!credentials?.email || !credentials?.password) return null;

        const email = normalizeEmail(credentials.email as string);
        const emailKey = `login:email:${email}`;

        const byEmail = await rateLimit(
          emailKey,
          LOGIN_MAX_ATTEMPTS,
          LOGIN_WINDOW_SECONDS
        );
        if (!byEmail.success) return null;

        // Validated as an IP before it becomes a Redis key; the raw header
        // token used to be interpolated verbatim, whatever it contained.
        const forwarded = request?.headers
          ? clientIpFromHeaders(request.headers)
          : null;
        if (forwarded) {
          const byIp = await rateLimit(
            `login:ip:${forwarded}`,
            LOGIN_IP_MAX_ATTEMPTS,
            LOGIN_WINDOW_SECONDS
          );
          if (!byIp.success) return null;
        }

        const user = await prisma.user.findUnique({ where: { email } });

        // Returning null for every failure — throttled, unknown user, or wrong
        // password — is deliberate: the login page renders one message for all
        // of them, so none of these states is distinguishable to a caller.
        const isValid = await compare(
          credentials.password as string,
          user?.passwordHash ?? DUMMY_PASSWORD_HASH
        );

        if (!user) return null;
        if (!isValid) {
          // Audited for an existing account only: an entry needs a user,
          // and an unknown address has none.
          await recordAudit({ userId: user.id, action: "sign_in_failed" });
          return null;
        }

        // Don't leave a legitimate user throttled because they mistyped first.
        await resetRateLimit(emailKey);
        await recordAudit({ userId: user.id, action: "sign_in" });

        return { id: user.id, email: user.email, name: user.name };
      },
    }),
  ],
});
