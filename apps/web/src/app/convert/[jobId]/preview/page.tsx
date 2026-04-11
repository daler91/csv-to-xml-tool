"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import type { PreviewResponse } from "@/types";

export default function PreviewPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const router = useRouter();
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [converting, setConverting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadPreview() {
      try {
        // Call worker preview via our API proxy
        const res = await fetch(`/api/jobs/${jobId}/preview`);
        if (!res.ok) throw new Error("Failed to load preview");
        const data = await res.json();
        setPreview(data);
      } catch {
        setError("Failed to load preview");
      } finally {
        setLoading(false);
      }
    }
    loadPreview();
  }, [jobId]);

  async function handleConvert() {
    setConverting(true);
    try {
      const res = await fetch(`/api/jobs/${jobId}/start`, { method: "POST" });
      if (!res.ok) throw new Error("Conversion failed");
      router.push(`/convert/${jobId}/progress`);
    } catch {
      setError("Conversion failed");
      setConverting(false);
    }
  }

  if (loading) {
    return (
      <main className="max-w-6xl mx-auto px-4 py-8">
        <p className="text-gray-500">Loading preview...</p>
      </main>
    );
  }

  if (error || !preview) {
    return (
      <main className="max-w-6xl mx-auto px-4 py-8">
        <p role="alert" className="text-red-600">
          {error || "Failed to load preview"}
        </p>
      </main>
    );
  }

  const { column_status } = preview;
  const hasMissing = column_status.missing.length > 0;

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-2">CSV Preview</h1>
      <p className="text-sm text-gray-500 mb-6">
        Showing {preview.rows.length} of {preview.total_rows} rows
      </p>

      {/* Column Status */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-green-50 border border-green-200 rounded p-3">
          <p className="text-sm font-medium text-green-700">
            Matched: {column_status.matched.length}
          </p>
        </div>
        <div className={`border rounded p-3 ${hasMissing ? "bg-red-50 border-red-200" : "bg-gray-50 border-gray-200"}`}>
          <p className={`text-sm font-medium ${hasMissing ? "text-red-700" : "text-gray-700"}`}>
            Missing: {column_status.missing.length}
          </p>
        </div>
        <div className="bg-yellow-50 border border-yellow-200 rounded p-3">
          <p className="text-sm font-medium text-yellow-700">
            Extra: {column_status.extra.length}
          </p>
        </div>
      </div>

      {/* Fuzzy Match Suggestions */}
      {column_status.suggestions.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded p-4 mb-6">
          <p className="text-sm font-medium text-blue-700 mb-2">
            Column mapping suggestions:
          </p>
          {column_status.suggestions.map((s) => (
            <p key={s.csv_column} className="text-sm text-blue-600">
              &quot;{s.csv_column}&quot; looks like &quot;{s.suggested_match}&quot; ({s.score}% match)
            </p>
          ))}
          <Link
            href={`/convert/${jobId}/mapping`}
            className="inline-block mt-2 text-sm text-blue-700 underline"
          >
            Map columns manually
          </Link>
        </div>
      )}

      {/* Data Table */}
      <div className="bg-white border rounded overflow-x-auto mb-6">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-gray-50">
              <th scope="col" className="px-3 py-2 text-left font-medium text-gray-500">#</th>
              {preview.headers.map((h) => (
                <th
                  key={h}
                  scope="col"
                  className="px-3 py-2 text-left font-medium whitespace-nowrap"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, rowIndex) => (
              <tr key={`row-${rowIndex}-${row[preview.headers[0]] ?? ""}`} className="border-b hover:bg-gray-50">
                <td className="px-3 py-2 text-gray-400">{rowIndex + 1}</td>
                {preview.headers.map((h) => (
                  <td key={h} className="px-3 py-2 whitespace-nowrap max-w-[200px] truncate">
                    {row[h] || ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Actions */}
      <div className="flex gap-4">
        {hasMissing && (
          <Link
            href={`/convert/${jobId}/mapping`}
            className="px-4 py-2 bg-yellow-500 text-white rounded text-sm font-medium hover:bg-yellow-600"
          >
            Map Columns
          </Link>
        )}
        <button
          onClick={handleConvert}
          disabled={converting}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {converting ? "Converting..." : "Confirm & Convert"}
        </button>
        <Link
          href="/convert"
          className="px-4 py-2 border border-gray-300 rounded text-sm hover:bg-gray-50"
        >
          Cancel
        </Link>
      </div>
    </main>
  );
}
