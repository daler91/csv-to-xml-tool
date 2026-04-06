"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import type { PreviewResponse } from "@/types";

export default function MappingPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const router = useRouter();
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`/api/jobs/${jobId}/preview`);
        const data = await res.json();
        setPreview(data);

        // Pre-populate with fuzzy match suggestions
        const initial: Record<string, string> = {};
        data.column_status.suggestions.forEach(
          (s: { csv_column: string; suggested_match: string }) => {
            initial[s.csv_column] = s.suggested_match;
          }
        );
        setMapping(initial);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [jobId]);

  async function handleSave() {
    setSaving(true);
    try {
      await fetch(`/api/jobs/${jobId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          columnMapping: mapping,
          status: "mapping",
        }),
      });
      router.push(`/convert/${jobId}/preview`);
    } catch {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <main className="max-w-4xl mx-auto px-4 py-8">
        <p className="text-gray-500">Loading columns...</p>
      </main>
    );
  }

  if (!preview) return null;

  const { missing, extra, suggestions } = preview.column_status;

  // Build lookup: expected field name -> { csv_column, score }
  const suggestionByField: Record<string, { csv_column: string; score: number }> = {};
  suggestions.forEach((s) => {
    suggestionByField[s.suggested_match] = { csv_column: s.csv_column, score: s.score };
  });

  function applySuggestion(field: string, csvCol: string) {
    const newMapping = { ...mapping };
    // Remove any existing mapping to this field
    Object.entries(newMapping).forEach(([k, v]) => {
      if (v === field) delete newMapping[k];
    });
    newMapping[csvCol] = field;
    setMapping(newMapping);
  }

  function applyAllSuggestions() {
    const newMapping = { ...mapping };
    suggestions.forEach((s) => {
      // Remove any existing mapping to this field
      Object.entries(newMapping).forEach(([k, v]) => {
        if (v === s.suggested_match) delete newMapping[k];
      });
      newMapping[s.csv_column] = s.suggested_match;
    });
    setMapping(newMapping);
  }

  return (
    <main className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-2">Column Mapping</h1>
      <p className="text-sm text-gray-500 mb-6">
        Map your CSV columns to the expected field names. Only map columns that
        need renaming.
      </p>

      {suggestions.length > 0 && (
        <div className="flex items-center gap-3 mb-4">
          <button
            onClick={applyAllSuggestions}
            className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700"
          >
            Apply All Suggestions ({suggestions.length})
          </button>
          <span className="text-xs text-gray-500">
            Click to map all suggested matches at once
          </span>
        </div>
      )}

      <div className="bg-white border rounded">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-gray-50">
              <th className="text-left px-4 py-3 font-medium">
                Expected Field (missing)
              </th>
              <th className="text-left px-4 py-3 font-medium">
                Map From CSV Column
              </th>
            </tr>
          </thead>
          <tbody>
            {missing.map((field) => {
              const currentCsvCol = Object.entries(mapping).find(
                ([, v]) => v === field
              )?.[0] || "";
              const suggestion = suggestionByField[field];
              const isApplied = suggestion && currentCsvCol === suggestion.csv_column;

              return (
                <tr key={field} className="border-b">
                  <td className="px-4 py-3 font-mono text-xs">{field}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <select
                        className="flex-1 border rounded px-2 py-1 text-sm"
                        value={currentCsvCol}
                        onChange={(e) => {
                          const csv_col = e.target.value;
                          const newMapping = { ...mapping };
                          Object.entries(newMapping).forEach(([k, v]) => {
                            if (v === field) delete newMapping[k];
                          });
                          if (csv_col) {
                            newMapping[csv_col] = field;
                          }
                          setMapping(newMapping);
                        }}
                      >
                        <option value="">(not mapped)</option>
                        {extra.map((col) => (
                          <option key={col} value={col}>
                            {col}
                          </option>
                        ))}
                      </select>
                      {suggestion && (
                        isApplied ? (
                          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-green-50 border border-green-200 text-green-700 whitespace-nowrap">
                            &#10003; {suggestion.csv_column} ({suggestion.score}%)
                          </span>
                        ) : (
                          <button
                            onClick={() => applySuggestion(field, suggestion.csv_column)}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-blue-50 border border-blue-200 text-blue-700 hover:bg-blue-100 cursor-pointer whitespace-nowrap"
                            title={`Map "${suggestion.csv_column}" to "${field}"`}
                          >
                            &#8592; {suggestion.csv_column} ({suggestion.score}%)
                          </button>
                        )
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex gap-4 mt-6">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save Mapping & Continue"}
        </button>
        <button
          onClick={() => router.push(`/convert/${jobId}/preview`)}
          className="px-4 py-2 border border-gray-300 rounded text-sm hover:bg-gray-50"
        >
          Skip
        </button>
      </div>
    </main>
  );
}
