/**
 * Shared rendering for structured XSD validation errors (worker
 * Contract B). Pure presentational — no hooks or handlers — so it works
 * in both server components (results page) and client components
 * (validate page).
 */

import type { XsdErrorDetail } from "@/types";

/**
 * "Row 3 — Race (CSV column: Race) — Contact 12345" headline for a
 * structured XSD error. Every trackable field is nullable, so only the
 * parts the worker could map back are shown.
 */
export function xsdErrorHeadline(err: XsdErrorDetail): string {
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

/** One structured error: headline, friendly message, raw message collapsed. */
export function XsdErrorDetailItem({
  err,
}: Readonly<{ err: XsdErrorDetail }>) {
  return (
    <>
      <p className="font-medium">{xsdErrorHeadline(err)}</p>
      <p>{err.friendly_message}</p>
      <details className="mt-0.5">
        <summary className="cursor-pointer select-none text-gray-500">
          Raw validator message
        </summary>
        <p className="font-mono mt-0.5">{err.message}</p>
      </details>
    </>
  );
}

export function XsdErrorDetailList({
  details,
}: Readonly<{ details: XsdErrorDetail[] }>) {
  return (
    <ul className="text-xs space-y-2 max-h-64 overflow-y-auto">
      {details.map((err, index) => (
        <li key={`${index}-${err.message}`}>
          <XsdErrorDetailItem err={err} />
        </li>
      ))}
    </ul>
  );
}
