/**
 * Server component wrapper for the convert page. It exists so the
 * retention window in the privacy copy and the upload size cap are read
 * from the server's runtime environment (RETENTION_DAYS, MAX_UPLOAD_BYTES)
 * on every render and passed to the client form as props — a
 * process.env read in the client bundle is `undefined` there (the var is
 * not NEXT_PUBLIC_*), and a NEXT_PUBLIC_* one would be inlined at build
 * time; either way the browser would enforce a different limit from the
 * server.
 */

import { MAX_UPLOAD_BYTES, RETENTION_DAYS } from "@/lib/limits";
import { ConvertForm } from "./convert-form";

// Without this the page is statically prerendered at build time and the
// env-less Docker build would bake in the default retention value — the
// exact bug this server/client split fixes.
export const dynamic = "force-dynamic";

export default function ConvertPage() {
  return (
    <ConvertForm retentionDays={RETENTION_DAYS} maxUploadBytes={MAX_UPLOAD_BYTES} />
  );
}
