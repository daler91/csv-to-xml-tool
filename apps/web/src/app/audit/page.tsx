"use client";

import { useEffect, useState } from "react";

interface AuditEntry {
  id: string;
  action: string;
  metadata: Record<string, unknown> | null;
  createdAt: string;
  job: { inputFileName: string; converterType: string } | null;
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
            <option value="conversion_started">Conversion Started</option>
            <option value="conversion_complete">Conversion Complete</option>
            <option value="conversion_failed">Conversion Failed</option>
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

      <div className="bg-white border rounded">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-gray-50">
              <th className="text-left px-4 py-3 font-medium">Date</th>
              <th className="text-left px-4 py-3 font-medium">Action</th>
              <th className="text-left px-4 py-3 font-medium">File</th>
              <th className="text-left px-4 py-3 font-medium">Type</th>
              <th className="text-left px-4 py-3 font-medium">Details</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                  Loading...
                </td>
              </tr>
            )}
            {!loading && entries.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                  No audit entries found
                </td>
              </tr>
            )}
            {!loading && entries.length > 0 &&
              entries.map((entry) => (
                <tr key={entry.id} className="border-b hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {new Date(entry.createdAt).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-0.5 bg-gray-100 rounded text-xs">
                      {entry.action}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">
                    {entry.job?.inputFileName || "-"}
                  </td>
                  <td className="px-4 py-3 capitalize">
                    {entry.job?.converterType || "-"}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500 max-w-[200px] truncate">
                    {entry.metadata ? JSON.stringify(entry.metadata) : "-"}
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
