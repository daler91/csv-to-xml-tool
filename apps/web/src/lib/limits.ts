// Maximum accepted input file size, in bytes.
//
// Enforced at upload time (apps/web/src/app/api/upload/route.ts) and re-checked
// server-side before each worker call (the start and preview routes), and used
// for the client-side pre-check on the convert page. Keep these in sync by
// importing this constant rather than duplicating the literal.
//
// Override with the MAX_UPLOAD_BYTES env var (in bytes); defaults to 50MB.
export const MAX_UPLOAD_BYTES =
  Number(process.env.MAX_UPLOAD_BYTES) || 50 * 1024 * 1024; // 50MB default

// How long uploaded CSVs and generated XML stay on disk before the lazy
// retention sweep (lib/retention.ts) removes them. The job row and audit
// trail are kept; only the files are purged.
//
// NEXT_PUBLIC_RETENTION_DAYS is read first so the client-side privacy
// copy on the convert page can state the same number that the server
// enforces — set both vars together (see .env.example). Defaults to 30.
export const RETENTION_DAYS =
  Number(
    process.env.NEXT_PUBLIC_RETENTION_DAYS ?? process.env.RETENTION_DAYS
  ) || 30;
