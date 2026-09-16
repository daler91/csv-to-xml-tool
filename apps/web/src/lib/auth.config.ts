import type { NextAuthConfig } from "next-auth";

/**
 * The half of the Auth.js config that is safe to evaluate anywhere.
 *
 * `middleware.ts` runs on the edge runtime, and it used to import the full
 * config from `auth.ts`. That pulled the credentials `authorize` callback into
 * the middleware bundle, and with it `@prisma/client` (including the 2.3 MB
 * wasm query engine), `ioredis` and `bcryptjs` — none of which can run there:
 * ioredis needs `net`/`tls` sockets the edge runtime has no polyfill for.
 *
 * The middleware never needs any of that. All it does is read and re-issue the
 * JWT session cookie, which needs the secret, the session strategy and the
 * cookie-shaping callbacks — everything below and nothing more. `providers` is
 * deliberately empty here: a provider is only consulted while *signing in*,
 * which happens in the route handler on the Node runtime.
 *
 * This is the split Auth.js documents for edge middleware; keep anything that
 * touches the database, Redis or bcrypt in `auth.ts`.
 */
export const authConfig = {
  // Auth.js only infers trustHost from AUTH_URL / AUTH_TRUST_HOST, not from
  // this app's NEXTAUTH_URL, so behind Railway's proxy it has to be explicit.
  // Without it `trustHost` resolves to false in production and every auth
  // request fails with `UntrustedHost`.
  trustHost: true,
  providers: [],
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
} satisfies NextAuthConfig;
