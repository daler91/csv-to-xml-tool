import { createXmlToolRoute } from "@/lib/xml-tool-route";
import type { XsdErrorDetail } from "@/types";

interface ValidateXsdResponse {
  is_valid: boolean;
  errors: string[];
  error_count: number;
  /** Structured per-error details (Contract B); absent on older workers. */
  error_details?: XsdErrorDetail[];
}

/**
 * Standalone pre-submission check: validate an existing XML file
 * (hand-edited, legacy, or from another tool) against the SBA Nexus
 * XSDs without creating a conversion job. Proxies to the worker's
 * content-based /validate-xsd endpoint.
 *
 * Mirrors the worker's schema_type contract: training-client shares the
 * counseling XSD, so the UI only exposes counseling/training, but all
 * three are accepted for future callers.
 */
export const POST = createXmlToolRoute<ValidateXsdResponse>({
  workerPath: "/validate-xsd",
  rateLimitPrefix: "validate-xml",
  schemaTypes: new Set(["counseling", "training", "training-client"]),
  schemaTypeError: "Unknown schema type",
  auditAction: "xml_validated",
  auditMetadata: (result) => ({
    isValid: result.is_valid,
    errorCount: result.error_count,
  }),
  unavailableError:
    "Validation failed — the validation service may be busy. Try again in a moment.",
  logLabel: "Validate XML error",
});
