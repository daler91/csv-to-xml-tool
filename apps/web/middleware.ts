import NextAuth from "next-auth";
import { authConfig } from "@/lib/auth.config";

// Built from the edge-safe config, not from `@/lib/auth`: importing the full
// config here dragged Prisma, ioredis and bcryptjs into the edge bundle. See
// the comment in `src/lib/auth.config.ts`.
export const { auth: middleware } = NextAuth(authConfig);

// The file-upload routes (/api/upload, /api/validate-xml, /api/fix-xml) are
// deliberately absent. Next buffers the body of every request middleware runs
// on and silently truncates it at 10 MB (`proxyClientMaxBodySize`), so a file
// between 10 MB and the upload cap reached `req.formData()` cut short and failed
// with a 5xx. Leaving them out costs nothing: this middleware has no `authorized`
// callback, so it only refreshes the session cookie, and each of those routes
// checks the session itself with `getRequiredUser()`.
export const config = {
  matcher: [
    "/dashboard/:path*",
    "/convert/:path*",
    "/validate/:path*",
    "/audit/:path*",
    "/api/jobs/:path*",
    "/api/audit/:path*",
    "/api/mapping-templates/:path*",
  ],
};
