"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useToast } from "@/components/toast";
import { uploadErrorMessage } from "@/lib/upload-errors";
import { Spinner } from "@/components/spinner";
import { Skeleton } from "@/components/skeleton";
import { CONVERTER_TYPES } from "@/lib/converter-types";

const MAX_FILE_BYTES = 50 * 1024 * 1024; // 50MB, mirrors /api/upload

function isCsvFile(f: File): boolean {
  return f.name.toLowerCase().endsWith(".csv");
}

function ConvertForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const toast = useToast();
  const previousJobId = searchParams.get("previousJobId");

  const [converterType, setConverterType] = useState("counseling");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  function acceptFile(candidate: File | undefined | null) {
    if (!candidate) return;
    if (!isCsvFile(candidate)) {
      toast.error(
        "That doesn't look like a CSV. We accept .csv files only."
      );
      return;
    }
    if (candidate.size > MAX_FILE_BYTES) {
      toast.error(
        "That file is larger than 50MB. Split it into smaller batches and try again."
      );
      return;
    }
    setFile(candidate);
    setError("");
  }

  useEffect(() => {
    if (previousJobId) {
      fetch(`/api/jobs/${previousJobId}`)
        .then((r) => r.json())
        .then((job) => {
          if (job.converterType) setConverterType(job.converterType);
        })
        .catch(() => {});
    }
  }, [previousJobId]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;

    setUploading(true);
    setError("");

    const formData = new FormData();
    formData.append("file", file);
    formData.append("converterType", converterType);
    if (previousJobId) {
      formData.append("previousJobId", previousJobId);
    }

    try {
      const res = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(uploadErrorMessage(res.status, data.error));
        return;
      }

      const { jobId } = await res.json();
      toast.success("File uploaded — loading preview");
      router.push(`/convert/${jobId}/preview`);
    } catch {
      setError(
        "Couldn't reach the server. Check your internet connection and try again."
      );
    } finally {
      setUploading(false);
    }
  }

  return (
    <main className="max-w-2xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-6">New Conversion</h1>

      <form onSubmit={handleUpload} className="space-y-6">
        {error && (
          <div
            role="alert"
            className="bg-red-50 text-red-600 p-3 rounded text-sm"
          >
            {error}
          </div>
        )}

        <fieldset>
          <legend className="block text-sm font-medium mb-2">
            Converter Type
          </legend>
          <div className="grid gap-3 sm:grid-cols-3">
            {CONVERTER_TYPES.map(({ value, label, description, sample }) => {
              const isSelected = converterType === value;
              return (
                <label
                  key={value}
                  className={`cursor-pointer rounded-lg border p-3 flex items-start gap-3 transition-colors ${
                    isSelected
                      ? "border-blue-500 bg-blue-50"
                      : "border-gray-300 hover:border-gray-400"
                  }`}
                >
                  <input
                    type="radio"
                    name="type"
                    value={value}
                    checked={isSelected}
                    onChange={(e) => setConverterType(e.target.value)}
                    className="sr-only"
                  />
                  <span
                    aria-hidden="true"
                    className={`flex-shrink-0 mt-0.5 w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                      isSelected
                        ? "border-blue-600 bg-blue-600"
                        : "border-gray-400 bg-white"
                    }`}
                  >
                    {isSelected && (
                      <span className="block w-1.5 h-1.5 rounded-full bg-white" />
                    )}
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium leading-snug">{label}</p>
                    <p className="text-xs text-gray-600 mt-1 leading-snug">
                      {description}
                    </p>
                    <a
                      href={sample}
                      onClick={(e) => e.stopPropagation()}
                      className="inline-block mt-2 text-xs text-blue-700 underline"
                    >
                      See sample
                    </a>
                  </div>
                </label>
              );
            })}
          </div>
        </fieldset>

        <div>
          <span id="file-label" className="block text-sm font-medium mb-1">
            CSV File
          </span>
          <p id="file-help" className="text-xs text-gray-600 mb-2">
            .csv files only, up to 50MB.
          </p>
          <label
            htmlFor="file-input"
            aria-labelledby="file-label"
            aria-describedby="file-help"
            className="block border-2 border-dashed border-gray-300 rounded-lg p-8 text-center cursor-pointer hover:border-blue-400 transition-colors"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              acceptFile(e.dataTransfer.files[0]);
            }}
          >
            <input
              id="file-input"
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              onChange={(e) => acceptFile(e.target.files?.[0])}
            />
            {file ? (
              <div>
                <p className="font-medium break-all">{file.name}</p>
                <p className="text-sm text-gray-600 mt-1">
                  {(file.size / 1024).toFixed(1)} KB
                </p>
              </div>
            ) : (
              <p className="text-gray-600">
                Drag &amp; drop a CSV file here, or click to browse
              </p>
            )}
          </label>
        </div>

        <button
          type="submit"
          disabled={!file || uploading}
          aria-busy={uploading}
          className="w-full inline-flex items-center justify-center gap-2 bg-blue-600 text-white rounded py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {uploading && <Spinner />}
          {uploading ? "Uploading..." : "Upload & Preview"}
        </button>
      </form>
    </main>
  );
}

export default function ConvertPage() {
  return (
    <Suspense
      fallback={
        <main className="max-w-2xl mx-auto px-4 py-8" aria-busy="true">
          <Skeleton className="h-7 w-48 mb-6" />
          <Skeleton className="h-4 w-24 mb-2" />
          <Skeleton className="h-8 w-full mb-6" />
          <Skeleton className="h-32 w-full mb-6" />
          <Skeleton className="h-10 w-full" />
        </main>
      }
    >
      <ConvertForm />
    </Suspense>
  );
}
