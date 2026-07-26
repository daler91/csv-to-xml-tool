import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { compare } from "bcryptjs";
import { prisma } from "./prisma";
import { normalizeEmail } from "./normalize";
import { rateLimit, resetRateLimit } from "./rate-limit";

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

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
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

        const forwarded = request?.headers
          ?.get("x-forwarded-for")
          ?.split(",")[0]
          ?.trim();
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
        if (!user) return null;

        const isValid = await compare(
          credentials.password as string,
          user.passwordHash
        );

        if (!isValid) return null;

        // Don't leave a legitimate user throttled because they mistyped first.
        await resetRateLimit(emailKey);

        return { id: user.id, email: user.email, name: user.name };
      },
    }),
  ],
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
  },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.id = user.id;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user && token.id) {
        session.user.id = token.id as string;
      }
      return session;
    },
  },
});
