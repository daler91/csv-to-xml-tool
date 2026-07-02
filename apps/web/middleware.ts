export { auth as middleware } from "@/lib/auth";

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
