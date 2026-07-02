/**
 * Server component wrapper for the convert page. It exists so the
 * retention window in the privacy copy is read from the server's
 * runtime environment (RETENTION_DAYS) on every render and passed to
 * the client form as a prop — a NEXT_PUBLIC_* read in the client
 * bundle would be inlined at build time and drift from what the
 * retention sweep actually enforces.
 */

import { RETENTION_DAYS } from "@/lib/limits";
import { ConvertForm } from "./convert-form";

// Without this the page is statically prerendered at build time and the
// env-less Docker build would bake in the default retention value — the
// exact bug this server/client split fixes.
export const dynamic = "force-dynamic";

export default function ConvertPage() {
  return <ConvertForm retentionDays={RETENTION_DAYS} />;
}
