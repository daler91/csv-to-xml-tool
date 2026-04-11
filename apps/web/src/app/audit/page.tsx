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
 * Resolves UX_REVIEW.md §9.2. Previously the Details cell rendered
 * ``JSON.stringify(entry.metadata)`` truncated to 200 chars, which
 * was useless for end users and looked unfinished. This helper
 * interprets the known action types and produces a plain sentence.
 *
 * Keep the switch in sync with the action strings written by:
 *   - apps/web/src/app/api/upload/route.ts             ("upload")
 *   - apps/web/src/app/api/jobs/[jobId]/start/route.ts ("conversion_started", "conversion_complete", "conversion_failed")
 *   - apps/web/src/app/api/jobs/[jobId]/cancel/route.ts ("conversion_cancelled")
 *   - apps/web/src/app/api/jobs/[jobId]/download/route.ts ("download")
 */
function formatAuditMetadata(
  action: string,
  metadata: Record<string, unknown> | null
): string {
  if (!metadata) return "—";

  const get = <T,>(key: string): T | undefined =>
    metadata[key] as T | undefined;

  switch (action) {
    case "upload": {
      const fileName = get<string>("fileName");
      const size = get<number>("fileSize");
      const sizeStr =
        typeof size === "number"
          ? ` (${(size / 1024).toFixed(1)} KB)`
          : "";
      return fileName ? `${fileName}${sizeStr}` : "—";
    }
    case "conversion_started":
      return "Conversion started";
    case "conversion_complete": {
      const successful = get<number>("successful") ?? 0;
      const total = get<number>("total") ?? 0;
      const errors = get<number>("errors") ?? 0;
      return `${successful}/${total} successful, ${errors} errors`;
    }
    case "conversion_failed": {
      const err = get<string>("error");
      return err ? `Failed: ${err}` : "Failed";
    }
    case "conversion_cancelled":
      return "Cancelled by user";
    case "download":
      return "XML downloaded";
    default:
      return "—";
  }
}

function formatActionLabel(action: string): string {
  const labels: Record<string, string> = {
    upload: "Upload",
    conversion_started: "Conversion started",
    conversion_complete: "Conversion complete",
    conversion_failed: "Conversion failed",
    conversion_cancelled: "Conversion cancelled",
    download: "Download",
  };
  return labels[action] ?? action;
}

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
            <option value="upload">Upload</option>
            <option value="conversion_started">Conversion started</option>
            <option value="conversion_complete">Conversion complete</option>
            <option value="conversion_failed">Conversion failed</option>
            <option value="conversion_cancelled">Conversion cancelled</option>
            <option value="download">Download</option>
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
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={`skeleton-${i}`} className="border-b">
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
