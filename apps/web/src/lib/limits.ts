// Maximum accepted input file size, in bytes.
//
// Enforced at upload time (apps/web/src/app/api/upload/route.ts) and re-checked
// server-side before each worker call (the start and preview routes), and used
// for the client-side pre-check on the convert page. Keep these in sync by
// importing this constant rather than duplicating the literal.
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024; // 50MB
