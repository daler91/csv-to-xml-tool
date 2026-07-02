"use client";

/**
 * Standalone "validate an existing XML" page: a pre-submission check
 * against the SBA Nexus XSDs for files that didn't come out of a
 * conversion job here — hand-edited XML, output from older tool
 * versions, or files from other systems. No job is created; nothing is
 * stored beyond an audit entry.
 *
 * When a counseling-format file fails validation, an optional auto-fix
 * (/api/fix-xml) can reorder elements to match the schema — it never
 * invents or changes data — and the reordered file can be downloaded.
 */

import { useState } from "react";
import { StatusIcon } from "@/components/status-icon";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { MAX_UPLOAD_BYTES } from "@/lib/limits";
import type { XsdErrorDetail } from "@/types";

interface ValidationResult {
  is_valid: boolean;
  errors: string[];
  error_count: number;
  /** Structured per-error details (Contract B); absent on older workers. */
  error_details?: XsdErrorDetail[];
}

interface FixResult {
  changed: boolean;
  fixed_xml_content: string;
  is_valid: boolean;
  errors: string[];
  error_count: number;
  error_details: XsdErrorDetail[];
}

const SCHEMA_OPTIONS = [
  {
    value: "counseling",
    label: "Counseling (Form 641)",
    description:
      "Client counseling XML, including Training Client exports — both use the Form 641 schema.",
  },
  {
    value: "training",
    label: "Training (Form 888)",
    description: "Aggregated training event XML (Form 888 schema).",
  },
] as const;

/**
 * "Row 3 — Race (CSV column: Race) — Contact 12345" headline for a
 * structured XSD error. Every trackable field is nullable, so only the
 * parts the worker could map back are shown.
 */
function xsdErrorHeadline(err: XsdErrorDetail): string {
  const parts: string[] = [];
  if (err.row_number !== null) parts.push(`Row ${err.row_number}`);
  const field = err.field_label ?? err.element;
  if (field) {
    parts.push(
      err.csv_column ? `${field} (CSV column: ${err.csv_column})` : field
    );
  }
  if (err.record_id) parts.push(`Contact ${err.record_id}`);
  return parts.length > 0 ? parts.join(" — ") : "Validation error";
}

function ErrorDetailList({
  details,
}: Readonly<{ details: XsdErrorDetail[] }>) {
  return (
    <ul className="text-xs space-y-2 max-h-64 overflow-y-auto">
      {details.map((err, index) => (
        <li key={`${index}-${err.message}`}>
          <p className="font-medium">{xsdErrorHeadline(err)}</p>
          <p>{err.friendly_message}</p>
          <details className="mt-0.5">
            <summary className="cursor-pointer select-none">
              Raw validator message
            </summary>
            <p className="font-mono mt-0.5">{err.message}</p>
          </details>
        </li>
      ))}
    </ul>
  );
}

export default function ValidatePage() {
  const [file, setFile] = useState<File | null>(null);
  const [schemaType, setSchemaType] = useState<string>("counseling");
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [fixing, setFixing] = useState(false);
  const [fixError, setFixError] = useState("");
  const [fixResult, setFixResult] = useState<FixResult | null>(null);

  function resetOutcome() {
    setError("");
    setResult(null);
    setFixError("");
    setFixResult(null);
  }

  function acceptFile(candidate: File | undefined | null) {
    if (!candidate) return;
    resetOutcome();
    if (!candidate.name.toLowerCase().endsWith(".xml")) {
      setError("Only .xml files can be validated here.");
      setFile(null);
      return;
    }
    if (candidate.size > MAX_UPLOAD_BYTES) {
      setError("That file is over the 50MB limit.");
      setFile(null);
      return;
    }
    setFile(candidate);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setValidating(true);
    resetOutcome();
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("schemaType", schemaType);
      const res = await fetch("/api/validate-xml", {
        method: "POST",
        body: formData,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || "Validation failed");
      }
      setResult(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Validation failed"
      );
    } finally {
      setValidating(false);
    }
  }

  async function handleFix() {
    if (!file) return;
    setFixing(true);
    setFixError("");
    setFixResult(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("schemaType", schemaType);
      const res = await fetch("/api/fix-xml", {
        method: "POST",
        body: formData,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || "Auto-fix failed");
      }
      setFixResult(data);
    } catch (err) {
      setFixError(err instanceof Error ? err.message : "Auto-fix failed");
    } finally {
      setFixing(false);
    }
  }

  // Client-side Blob download of the reordered XML — nothing is stored
  // server-side for this ad-hoc flow.
  function downloadFixedXml() {
    if (!fixResult || !file) return;
    const blob = new Blob([fixResult.fixed_xml_content], {
      type: "application/xml",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${file.name.replace(/\.xml$/i, "")}-fixed.xml`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  const canAttemptFix =
    result !== null && !result.is_valid && schemaType === "counseling";

  return (
    <main className="max-w-2xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-2">Validate an XML File</h1>
      <p className="text-sm text-gray-600 mb-6">
        Check an existing XML file against the SBA Nexus schemas before
        submitting it — useful for hand-edited files or output from other
        tools. Files converted here are already validated automatically on
        the results page.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-6">
        <fieldset>
          <legend className="text-sm font-medium mb-2">Schema</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {SCHEMA_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className={`block rounded border p-3 cursor-pointer ${
                  schemaType === opt.value
                    ? "border-blue-500 bg-blue-50/50"
                    : "border-gray-200 hover:border-gray-300"
                }`}
              >
                <span className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="schemaType"
                    value={opt.value}
                    checked={schemaType === opt.value}
                    onChange={() => setSchemaType(opt.value)}
                  />
                  <span className="text-sm font-medium">{opt.label}</span>
                </span>
                <span className="block mt-1 text-xs text-gray-600">
                  {opt.description}
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div>
          <label
            htmlFor="xml-file"
            className="block text-sm font-medium mb-2"
          >
            XML file
          </label>
          <input
            id="xml-file"
            type="file"
            accept=".xml"
            onChange={(e) => acceptFile(e.target.files?.[0])}
            className="block w-full text-sm text-gray-600 file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
          />
          <p className="mt-1 text-sm text-gray-600">
            .xml files only, max 50MB
          </p>
        </div>

        {error && <Alert variant="error">{error}</Alert>}

        <Button type="submit" disabled={!file} isLoading={validating}>
          {validating ? "Validating…" : "Validate"}
        </Button>
      </form>

      {result && (
        <section aria-live="polite" className="mt-8">
          {result.is_valid ? (
            <div className="bg-green-50 border border-green-200 rounded p-4">
              <p className="text-sm text-green-700 font-medium inline-flex items-center gap-1.5">
                <StatusIcon kind="success" />
                {file?.name} is valid against the{" "}
                {SCHEMA_OPTIONS.find((o) => o.value === schemaType)?.label}{" "}
                schema.
              </p>
            </div>
          ) : (
            <Alert
              variant="error"
              title={`${file?.name ?? "File"} failed validation (${result.error_count} ${
                result.error_count === 1 ? "error" : "errors"
              })`}
            >
              {result.error_details && result.error_details.length > 0 ? (
                <ErrorDetailList details={result.error_details} />
              ) : (
                <ul className="text-xs space-y-1 max-h-64 overflow-y-auto">
                  {result.errors.map((err) => (
                    <li key={err} className="font-mono">
                      {err}
                    </li>
                  ))}
                </ul>
              )}
            </Alert>
          )}

          {canAttemptFix && (
            <div className="mt-4 bg-white border rounded p-4">
              <p className="text-sm text-gray-600 mb-3">
                Auto-fix only reorders elements to match the order the Form
                641 schema requires — it never invents or changes your data.
                Issues in the data itself still need to be corrected at the
                source.
              </p>
              <Button
                variant="secondary"
                onClick={handleFix}
                isLoading={fixing}
              >
                {fixing ? "Attempting fix…" : "Attempt automatic fix"}
              </Button>

              {fixError && (
                <Alert variant="error" className="mt-3">
                  {fixError}
                </Alert>
              )}

              {fixResult && !fixResult.changed && (
                <Alert variant="info" className="mt-3">
                  No automatic fixes applied — the issues are in the data,
                  not the element order.
                </Alert>
              )}

              {fixResult && fixResult.changed && fixResult.is_valid && (
                <Alert variant="success" className="mt-3">
                  <p className="mb-2">
                    Element order fixed — the corrected file now passes
                    validation.
                  </p>
                  <Button variant="secondary" onClick={downloadFixedXml}>
                    Download fixed XML
                  </Button>
                </Alert>
              )}

              {fixResult && fixResult.changed && !fixResult.is_valid && (
                <Alert
                  variant="warning"
                  className="mt-3"
                  title={`Element order fixed, but ${fixResult.error_count} ${
                    fixResult.error_count === 1 ? "issue remains" : "issues remain"
                  } in the data`}
                >
                  {fixResult.error_details.length > 0 ? (
                    <ErrorDetailList details={fixResult.error_details} />
                  ) : (
                    <ul className="text-xs space-y-1 max-h-64 overflow-y-auto">
                      {fixResult.errors.map((err) => (
                        <li key={err} className="font-mono">
                          {err}
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="mt-2">
                    <Button variant="secondary" onClick={downloadFixedXml}>
                      Download fixed XML
                    </Button>
                  </div>
                </Alert>
              )}
            </div>
          )}
        </section>
      )}
    </main>
  );
}
