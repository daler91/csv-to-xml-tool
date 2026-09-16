import NextAuth from "next-auth";
import { authConfig } from "@/lib/auth.config";

// Built from the edge-safe config, not from `@/lib/auth`: importing the full
// config here dragged Prisma, ioredis and bcryptjs into the edge bundle. See
// the comment in `src/lib/auth.config.ts`.
export const { auth: middleware } = NextAuth(authConfig);

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/convert/:path*",
    "/validate/:path*",
    "/audit/:path*",
    "/api/upload/:path*",
    "/api/jobs/:path*",
    "/api/audit/:path*",
    "/api/mapping-templates/:path*",
    "/api/validate-xml/:path*",
    "/api/fix-xml/:path*",
  ],
};
