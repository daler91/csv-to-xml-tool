export { auth as middleware } from "@/lib/auth";

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/convert/:path*",
    "/audit/:path*",
    "/api/upload/:path*",
    "/api/jobs/:path*",
    "/api/audit/:path*",
  ],
};
