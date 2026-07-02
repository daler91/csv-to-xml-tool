import { createXmlToolRoute } from "@/lib/xml-tool-route";
import type { XsdErrorDetail } from "@/types";

interface FixXmlResponse {
  changed: boolean;
  fixed_xml_content: string;
  is_valid: boolean;
  errors: string[];
  error_count: number;
  error_details: XsdErrorDetail[];
}

/**
 * Attempt an automatic structural fix of an XML file (element reordering
 * to match the schema — never inventing data), then re-validate the fixed
 * content. Companion to /api/validate-xml against the worker's /fix-xml
 * endpoint (Contract C).
 *
 * The worker's auto-fix only understands counseling-format XML (Form
 * 641); training-client shares that XSD so it's accepted too. Plain
 * "training" (Form 888) is rejected by the worker, so it's rejected here
 * as well.
 */
export const POST = createXmlToolRoute<FixXmlResponse>({
  workerPath: "/fix-xml",
  rateLimitPrefix: "fix-xml",
  schemaTypes: new Set(["counseling", "training-client"]),
  schemaTypeError: "Auto-fix supports counseling-format XML only",
  auditAction: "xml_autofix",
  auditMetadata: (result) => ({
    changed: result.changed,
    isValid: result.is_valid,
  }),
  unavailableError:
    "Auto-fix failed — the fix service may be busy. Try again in a moment.",
  logLabel: "Fix XML error",
});
