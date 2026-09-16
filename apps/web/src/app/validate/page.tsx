/**
 * Server component wrapper for the validate page, so the upload cap the
 * client enforces is the MAX_UPLOAD_BYTES the server reads at runtime
 * (same split as convert/page.tsx and for the same reason).
 */

import { MAX_UPLOAD_BYTES } from "@/lib/limits";
import { ValidateTool } from "./validate-tool";

// Without this the page is statically prerendered at build time and the
// env-less Docker build would bake in the default cap.
export const dynamic = "force-dynamic";

export default function ValidatePage() {
  return <ValidateTool maxUploadBytes={MAX_UPLOAD_BYTES} />;
}
