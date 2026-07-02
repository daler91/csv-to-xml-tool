"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import type { MappingTemplate, PreviewResponse } from "@/types";
import { useToast } from "@/components/toast";
import { Skeleton, SkeletonTable } from "@/components/skeleton";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

/**
 * Stable stringification of the mapping dict, used to detect dirty
 * state so the Cancel button can confirm before discarding unsaved
 * edits (UX_REVIEW.md §9.5).
 */
function mappingKey(m: Record<string, string>): string {
  return Object.keys(m)
    .sort((a, b) => a.localeCompare(b))
    .map((k) => `${k}=${m[k]}`)
    .join("|");
}

export default function MappingPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const router = useRouter();
  const toast = useToast();
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [initialMappingKey, setInitialMappingKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [converterType, setConverterType] = useState("");
  const [templates, setTemplates] = useState<MappingTemplate[]>([]);
  const [lastJobMapping, setLastJobMapping] = useState<Record<string, string> | null>(null);
  // The "reuse your last mapping" offer only makes sense on a job the
  // user hasn't already mapped — a saved mapping means they were here.
  const [offerLastMapping, setOfferLastMapping] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [savingTemplate, setSavingTemplate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const [previewRes, jobRes] = await Promise.all([
        fetch(`/api/jobs/${jobId}/preview`),
        fetch(`/api/jobs/${jobId}`),
      ]);
      if (!previewRes.ok || !jobRes.ok) {
        throw new Error(
          "We couldn't load the column mapping for this file. The server may be busy or the file may be malformed."
        );
      }
      const data = await previewRes.json();
      const job = await jobRes.json();
      setPreview(data);
      setConverterType(job.converterType ?? "");

      // Saved templates and the last completed job's mapping are
      // nice-to-have — a failure here must not block the mapping page.
      if (job.converterType) {
        try {
          const templatesRes = await fetch(
            `/api/mapping-templates?converterType=${encodeURIComponent(job.converterType)}`
          );
          if (templatesRes.ok) {
            const templateData = await templatesRes.json();
            setTemplates(templateData.templates ?? []);
            setLastJobMapping(templateData.lastJobMapping ?? null);
          }
        } catch {
          // Ignore — the section simply doesn't render.
        }
      }

      // Restore saved mapping if available; otherwise use suggestions
      const hasSavedMapping =
        job.columnMapping &&
        typeof job.columnMapping === "object" &&
        Object.keys(job.columnMapping).length > 0;
      setOfferLastMapping(!hasSavedMapping);
      let nextMapping: Record<string, string>;
      if (hasSavedMapping) {
        // Keep only saved entries whose target is still an expected field, so a
        // stale entry (e.g. a pre-fix {"Class/Event ID":"event_id"}) is dropped
        // rather than carried invisibly in state and re-sent on Convert.
        const expectedFields = new Set([
          ...data.column_status.matched,
          ...data.column_status.missing,
        ]);
        nextMapping = Object.fromEntries(
          Object.entries(job.columnMapping as Record<string, string>).filter(
            ([, target]) => expectedFields.has(target)
          )
        );
      } else {
        nextMapping = {};
        data.column_status.suggestions.forEach(
          (s: { csv_column: string; suggested_match: string }) => {
            nextMapping[s.csv_column] = s.suggested_match;
          }
        );
      }
      setMapping(nextMapping);
      setInitialMappingKey(mappingKey(nextMapping));
    } catch (err) {
      setLoadError(
        err instanceof Error ? err.message : "Failed to load mapping"
      );
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`/api/jobs/${jobId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          columnMapping: mapping,
          status: "mapping",
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "Failed to save mapping");
      }
      toast.success("Mapping saved");
      router.push(`/convert/${jobId}/preview`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to save mapping"
      );
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <main className="max-w-4xl mx-auto px-4 py-8" aria-busy="true">
        <Skeleton className="h-7 w-48 mb-2" />
        <Skeleton className="h-4 w-72 mb-6" />
        <SkeletonTable rows={8} columns={2} />
      </main>
    );
  }

  if (loadError || !preview) {
    return (
      <main className="max-w-2xl mx-auto px-4 py-16">
        <Alert variant="error" title="Couldn't load column mapping">
          <p className="mb-4">
            {loadError || "Failed to load mapping"}
          </p>
          <div className="flex flex-col sm:flex-row gap-2">
            <Button onClick={load}>Try again</Button>
            <Link
              href={`/convert/${jobId}/preview`}
              className="inline-flex items-center justify-center px-4 py-2 border border-gray-300 rounded text-sm font-medium hover:bg-gray-50 text-center"
            >
              Back to preview
            </Link>
          </div>
        </Alert>
      </main>
    );
  }

  const { matched, missing, suggestions, field_requirements, field_descriptions } =
    preview.column_status;
  const allFields = [...matched, ...missing];

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

  /**
   * Applies a stored mapping (template or previous job), keeping only
   * entries whose CSV column exists in this file and whose target is
   * still an expected field — a stale entry is skipped, not carried.
   */
  function applyStoredMapping(source: Record<string, string>, label: string) {
    const headerSet = new Set(preview!.headers);
    const fieldSet = new Set(allFields);
    const applicable = Object.entries(source).filter(
      ([csvCol, field]) => headerSet.has(csvCol) && fieldSet.has(field)
    );
    const skipped = Object.keys(source).length - applicable.length;
    if (applicable.length === 0) {
      toast.error(
        `None of the columns in ${label} match this file, so nothing was applied.`
      );
      return;
    }
    setMapping(Object.fromEntries(applicable));
    toast.success(
      `Applied ${applicable.length} mapping${applicable.length === 1 ? "" : "s"} from ${label}` +
        (skipped > 0
          ? ` (${skipped} skipped — column not in this file)`
          : "")
    );
  }

  async function handleSaveTemplate() {
    const name = templateName.trim();
    if (!name || Object.keys(mapping).length === 0) return;
    setSavingTemplate(true);
    try {
      const res = await fetch("/api/mapping-templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, converterType, mapping }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || "Failed to save template");
      }
      // Overwrite-by-name upsert: replace a same-id entry if present.
      setTemplates((prev) => [
        data.template,
        ...prev.filter((t) => t.id !== data.template.id),
      ]);
      setTemplateName("");
      toast.success(`Template "${name}" saved`);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to save template"
      );
    } finally {
      setSavingTemplate(false);
    }
  }

  async function handleDeleteTemplate() {
    const template = templates.find((t) => t.id === selectedTemplateId);
    if (!template) return;
    if (!window.confirm(`Delete the template "${template.name}"?`)) return;
    try {
      const res = await fetch(`/api/mapping-templates/${template.id}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "Failed to delete template");
      }
      setTemplates((prev) => prev.filter((t) => t.id !== template.id));
      setSelectedTemplateId("");
      toast.success(`Template "${template.name}" deleted`);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to delete template"
      );
    }
  }

  const selectedTemplate = templates.find((t) => t.id === selectedTemplateId);
  const showLastMappingOffer =
    offerLastMapping && lastJobMapping && Object.keys(lastJobMapping).length > 0;
  const showTemplatesSection =
    showLastMappingOffer || templates.length > 0 || Object.keys(mapping).length > 0;

  return (
    <main className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-2">Column Mapping</h1>
      <p className="text-sm text-gray-600 mb-1">
        Map your CSV columns to the expected XML field names. Only map
        columns that need renaming — auto-matched columns stay put.
      </p>
      <p className="text-xs text-gray-500 mb-6">
        Required fields must be mapped or present in your CSV. Conditional
        fields are only needed when their rule triggers — hover the badge
        or read the rule below each field.
      </p>

      {showTemplatesSection && (
        <section
          aria-label="Saved mappings"
          className="bg-white border rounded p-4 mb-4 flex flex-col gap-3"
        >
          {showLastMappingOffer && (
            <div className="flex flex-col sm:flex-row sm:items-center gap-2">
              <p className="text-sm text-gray-700 flex-1">
                You&apos;ve converted this file type before. Start from the
                mapping used on your last completed job?
              </p>
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  applyStoredMapping(lastJobMapping!, "your last job")
                }
              >
                Apply last mapping
              </Button>
            </div>
          )}
          {templates.length > 0 && (
            <div className="flex flex-col sm:flex-row sm:items-center gap-2">
              <label
                htmlFor="template-select"
                className="text-sm font-medium whitespace-nowrap"
              >
                Saved templates
              </label>
              <select
                id="template-select"
                className="flex-1 border rounded px-2 py-1 text-sm"
                value={selectedTemplateId}
                onChange={(e) => setSelectedTemplateId(e.target.value)}
              >
                <option value="">Choose a template…</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({Object.keys(t.mapping).length} columns)
                  </option>
                ))}
              </select>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={!selectedTemplate}
                  onClick={() =>
                    selectedTemplate &&
                    applyStoredMapping(
                      selectedTemplate.mapping,
                      `"${selectedTemplate.name}"`
                    )
                  }
                >
                  Apply
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={!selectedTemplate}
                  onClick={handleDeleteTemplate}
                >
                  Delete
                </Button>
              </div>
            </div>
          )}
          {Object.keys(mapping).length > 0 && (
            <div className="flex flex-col sm:flex-row sm:items-center gap-2">
              <label
                htmlFor="template-name"
                className="text-sm text-gray-600 whitespace-nowrap"
              >
                Save current mapping as
              </label>
              <input
                id="template-name"
                type="text"
                maxLength={60}
                placeholder="e.g. Monthly Salesforce export"
                className="flex-1 border rounded px-2 py-1 text-sm"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
              />
              <Button
                size="sm"
                variant="secondary"
                isLoading={savingTemplate}
                disabled={!templateName.trim()}
                onClick={handleSaveTemplate}
              >
                Save template
              </Button>
            </div>
          )}
        </section>
      )}

      {suggestions.length > 0 && (
        <div className="flex items-center gap-3 mb-4">
          <Button onClick={applyAllSuggestions} size="sm">
            Apply All Suggestions ({suggestions.length})
          </Button>
          <span className="text-xs text-gray-500">
            Click to map all suggested matches at once
          </span>
        </div>
      )}

      {error && (
        <div className="mb-4">
          <Alert variant="error">{error}</Alert>
        </div>
      )}

      <div className="bg-white border rounded">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-gray-50">
              <th scope="col" className="text-left px-4 py-3 font-medium">
                Expected XML Field
              </th>
              <th scope="col" className="text-left px-4 py-3 font-medium">
                Map From CSV Column
              </th>
            </tr>
          </thead>
          <tbody>
            {allFields.map((field) => {
              const isMatched = matched.includes(field);
              const currentCsvCol = Object.entries(mapping).find(
                ([, v]) => v === field
              )?.[0] || (isMatched ? field : "");
              const suggestion = suggestionByField[field];
              const isApplied = suggestion && currentCsvCol === suggestion.csv_column;
              const req = field_requirements?.[field];
              const meta = field_descriptions?.[field];
              const conditionalTitle = meta?.conditional_rule;

              return (
                <tr key={field} className={`border-b ${isMatched ? "bg-green-50/30" : ""}`}>
                  <td className="px-4 py-3 align-top">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs">{field}</span>
                      {req === "required" && (
                        <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold bg-red-100 text-red-700 border border-red-200">
                          Required
                        </span>
                      )}
                      {req === "conditional" && (
                        <span
                          title={conditionalTitle}
                          className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700 border border-amber-200 cursor-help"
                        >
                          Conditional
                        </span>
                      )}
                      {req === "optional" && (
                        <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold bg-gray-100 text-gray-500 border border-gray-200">
                          Optional
                        </span>
                      )}
                      {isMatched && (
                        <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold bg-green-100 text-green-700 border border-green-200">
                          Auto-matched
                        </span>
                      )}
                    </div>
                    {meta?.description && (
                      <p className="mt-1 text-xs text-gray-600 leading-snug">
                        {meta.description}
                      </p>
                    )}
                    {req === "conditional" && meta?.conditional_rule && (
                      <p className="mt-1 text-xs text-amber-700 leading-snug">
                        <span className="font-medium">When required:</span>{" "}
                        {meta.conditional_rule}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col sm:flex-row sm:items-center gap-2">
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
                        {preview.headers.map((col) => (
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
        <Button onClick={handleSave} isLoading={saving}>
          {saving ? "Saving..." : "Save Mapping & Continue"}
        </Button>
        <Button
          variant="secondary"
          onClick={() => {
            const dirty = mappingKey(mapping) !== initialMappingKey;
            if (
              dirty &&
              !window.confirm(
                "Discard your mapping changes and go back to preview?"
              )
            ) {
              return;
            }
            router.push(`/convert/${jobId}/preview`);
          }}
        >
          Cancel
        </Button>
      </div>
    </main>
  );
}
