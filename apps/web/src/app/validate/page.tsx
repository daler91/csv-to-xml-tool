"use client";

/**
 * Standalone "validate an existing XML" page: a pre-submission check
 * against the SBA Nexus XSDs for files that didn't come out of a
 * conversion job here — hand-edited XML, output from older tool
 * versions, or files from other systems. No job is created; nothing is
 * stored beyond an audit entry.
 */

import { useState } from "react";
import { StatusIcon } from "@/components/status-icon";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { MAX_UPLOAD_BYTES } from "@/lib/limits";

interface ValidationResult {
  is_valid: boolean;
  errors: string[];
  error_count: number;
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

export default function ValidatePage() {
  const [file, setFile] = useState<File | null>(null);
  const [schemaType, setSchemaType] = useState<string>("counseling");
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ValidationResult | null>(null);

  function acceptFile(candidate: File | undefined | null) {
    if (!candidate) return;
    setError("");
    setResult(null);
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
    setError("");
    setResult(null);
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
              <ul className="text-xs space-y-1 max-h-64 overflow-y-auto">
                {result.errors.map((err) => (
                  <li key={err} className="font-mono">
                    {err}
                  </li>
                ))}
              </ul>
            </Alert>
          )}
        </section>
      )}
    </main>
  );
}
