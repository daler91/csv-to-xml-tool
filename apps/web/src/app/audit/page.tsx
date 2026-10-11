"use client";

import { useEffect, useState } from "react";
import { Skeleton } from "@/components/skeleton";

interface AuditEntry {
  id: string;
  action: string;
  metadata: Record<string, unknown> | null;
  createdAt: string;
  job: { inputFileName: string; converterType: string } | null;
}

/**
 * Human-friendly summaries for audit-entry metadata.
 *
 * Resolves docs/reviews/UX_REVIEW.md §9.2. Previously the Details cell rendered
 * ``JSON.stringify(entry.metadata)`` truncated to 200 chars, which
 * was useless for end users and looked unfinished. This helper
 * interprets the known action types and produces a plain sentence.
 *
 * Keep ACTION_LABELS and METADATA_FORMATTERS in sync with every action string the app
 * writes (grep for `action:` in src/app/api and src/lib). Actions with no
 * label used to show as raw keys and could not be picked in the filter.
 */
type MetadataGetter = <T>(key: string) => T | undefined;
type MetadataFormatter = (get: MetadataGetter) => string;

const fileName: MetadataFormatter = (get) => get<string>("fileName") ?? "—";

const failure: MetadataFormatter = (get) => {
  const err = get<string>("error");
  return err ? `Failed: ${err}` : "Failed";
};

const templateName: MetadataFormatter = (get) => {
  const name = get<string>("name");
  return name ? `Template "${name}"` : "—";
};

// One formatter per action: a Map rather than a switch (or an object indexed
// by the action), so adding an action is one entry here.
const METADATA_FORMATTERS = new Map<string, MetadataFormatter>([
  ["upload", (get) => {
    const name = get<string>("fileName");
    const size = get<number>("fileSize");
    const sizeStr = typeof size === "number" ? ` (${(size / 1024).toFixed(1)} KB)` : "";
    return name ? `${name}${sizeStr}` : "—";
  }],
  ["conversion_started", () => "Conversion started"],
  ["conversion_retried", (get) => {
    const attempt = get<number>("attempt");
    return attempt ? `Retried (attempt ${attempt})` : "Retried";
  }],
  ["conversion_complete", (get) =>
    `${get<number>("successful") ?? 0}/${get<number>("total") ?? 0} successful, ` +
    `${get<number>("errors") ?? 0} errors`],
  ["conversion_failed", failure],
  ["conversion_deadlettered", failure],
  ["conversion_timeout", (get) => get<string>("reason") ?? "Timed out"],
  ["conversion_cancelled", () => "Cancelled by user"],
  ["download", () => "XML downloaded"],
  ["job_deleted", (get) => {
    const name = get<string>("fileName");
    return name ? `Deleted ${name}` : "Deleted";
  }],
  ["files_purged", (get) => {
    const days = get<number>("retentionDays");
    return days ? `Files removed after ${days} days` : "Files removed";
  }],
  ["mapping_changed", (get) => {
    const renames = Object.entries(get<Record<string, string>>("mapping") ?? {}).map(
      ([from, to]) => `${from} → ${to}`
    );
    return renames.length ? renames.join(", ") : "All columns matched by name";
  }],
  ["xml_validated", fileName],
  ["xml_autofix", fileName],
  ["mapping_template_saved", templateName],
  ["mapping_template_deleted", templateName],
]);

function formatAuditMetadata(
  action: string,
  metadata: Record<string, unknown> | null
): string {
  const formatter = METADATA_FORMATTERS.get(action);
  if (!metadata || !formatter) return "—";
  return formatter(<T,>(key: string) => metadata[key] as T | undefined);
}

const ACTION_LABELS = new Map<string, string>([
  ["upload", "Upload"],
  ["mapping_changed", "Column mapping changed"],
  ["conversion_started", "Conversion started"],
  ["conversion_retried", "Conversion retried"],
  ["conversion_complete", "Conversion complete"],
  ["conversion_failed", "Conversion failed"],
  ["conversion_deadlettered", "Conversion failed"],
  ["conversion_timeout", "Conversion timed out"],
  ["conversion_cancelled", "Conversion cancelled"],
  ["download", "Download"],
  ["job_deleted", "Job deleted"],
  ["files_purged", "Files removed (retention)"],
  ["xml_validated", "XML validated"],
  ["xml_autofix", "XML auto-fixed"],
  ["mapping_template_saved", "Template saved"],
  ["mapping_template_deleted", "Template deleted"],
  ["sign_in", "Signed in"],
  ["sign_in_failed", "Sign-in failed (wrong password)"],
]);

// "conversion_failed" is no longer written (dead-lettering replaced it), so
// the filter offers only the actions current code produces.
const FILTER_ACTIONS = [...ACTION_LABELS].filter(([action]) => action !== "conversion_failed");

function formatActionLabel(action: string): string {
  return ACTION_LABELS.get(action) ?? action;
}

const SKELETON_ROW_KEYS = ["sk-1", "sk-2", "sk-3", "sk-4", "sk-5"];

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [actionFilter, setActionFilter] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      const params = new URLSearchParams({ page: String(page), pageSize: "25" });
      if (actionFilter) params.set("action", actionFilter);

      const res = await fetch(`/api/audit?${params}`);
      const data = await res.json();
      setEntries(data.entries);
      setTotal(data.total);
      setTotalPages(data.totalPages);
      setLoading(false);
    }
    load();
  }, [page, actionFilter]);

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Audit Trail</h1>
          <p className="text-sm text-gray-500">{total} entries</p>
        </div>
        <div className="flex gap-2">
          <select
            className="border rounded px-3 py-1.5 text-sm"
            value={actionFilter}
            onChange={(e) => {
              setActionFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All actions</option>
            {FILTER_ACTIONS.map(([action, label]) => (
              <option key={action} value={action}>
                {label}
              </option>
            ))}
          </select>
          <a
            href={
              "/api/audit?format=csv" +
              (actionFilter ? "&action=" + encodeURIComponent(actionFilter) : "")
            }
            className="px-4 py-1.5 border rounded text-sm hover:bg-gray-50"
          >
            Export CSV
          </a>
        </div>
      </div>

      <div className="bg-white border rounded overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-gray-50">
              <th scope="col" className="text-left px-4 py-3 font-medium">Date</th>
              <th scope="col" className="text-left px-4 py-3 font-medium">Action</th>
              <th scope="col" className="text-left px-4 py-3 font-medium">File</th>
              <th scope="col" className="text-left px-4 py-3 font-medium">Type</th>
              <th scope="col" className="text-left px-4 py-3 font-medium">Details</th>
            </tr>
          </thead>
          <tbody>
            {loading &&
              SKELETON_ROW_KEYS.map((rowKey) => (
                <tr key={rowKey} className="border-b">
                  <td className="px-4 py-3"><Skeleton className="h-4 w-32" /></td>
                  <td className="px-4 py-3"><Skeleton className="h-4 w-20" /></td>
                  <td className="px-4 py-3"><Skeleton className="h-4 w-40" /></td>
                  <td className="px-4 py-3"><Skeleton className="h-4 w-20" /></td>
                  <td className="px-4 py-3"><Skeleton className="h-4 w-48" /></td>
                </tr>
              ))}
            {!loading && entries.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                  No audit entries found
                </td>
              </tr>
            )}
            {!loading && entries.length > 0 &&
              entries.map((entry) => (
                <tr key={entry.id} className="border-b hover:bg-gray-50 align-top">
                  <td className="px-4 py-3 text-gray-600 text-xs whitespace-nowrap">
                    {new Date(entry.createdAt).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-0.5 bg-gray-100 rounded text-xs whitespace-nowrap">
                      {formatActionLabel(entry.action)}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs break-all">
                    {entry.job?.inputFileName || "—"}
                  </td>
                  <td className="px-4 py-3 capitalize text-xs">
                    {entry.job?.converterType || "—"}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-700 max-w-sm">
                    <div>{formatAuditMetadata(entry.action, entry.metadata)}</div>
                    {entry.metadata && Object.keys(entry.metadata).length > 0 && (
                      <details className="mt-1">
                        <summary className="cursor-pointer text-[10px] text-gray-500 hover:text-gray-700">
                          View raw
                        </summary>
                        <pre className="mt-1 p-2 bg-gray-50 border rounded text-[10px] font-mono text-gray-700 whitespace-pre-wrap break-all">
                          {JSON.stringify(entry.metadata, null, 2)}
                        </pre>
                      </details>
                    )}
                  </td>
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 border rounded text-sm disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-sm text-gray-500">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-3 py-1 border rounded text-sm disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </main>
  );
}
