"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useToast } from "@/components/toast";
import { uploadErrorMessage } from "@/lib/upload-errors";
import { Spinner } from "@/components/spinner";
import { Skeleton } from "@/components/skeleton";

function ConvertForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const toast = useToast();
  const previousJobId = searchParams.get("previousJobId");

  const [converterType, setConverterType] = useState("counseling");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

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
          <div className="flex gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="type"
                value="counseling"
                checked={converterType === "counseling"}
                onChange={(e) => setConverterType(e.target.value)}
              />
              <span className="text-sm">Counseling (Form 641)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="type"
                value="training"
                checked={converterType === "training"}
                onChange={(e) => setConverterType(e.target.value)}
              />
              <span className="text-sm">Training (Form 888)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="type"
                value="training-client"
                checked={converterType === "training-client"}
                onChange={(e) => setConverterType(e.target.value)}
              />
              <span className="text-sm">Training Client (Form 641)</span>
            </label>
          </div>
        </fieldset>

        <div>
          <label htmlFor="file-input" className="block text-sm font-medium mb-2">CSV File</label>
          <div
            role="button"
            tabIndex={0}
            className="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer hover:border-blue-400 transition-colors"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const dropped = e.dataTransfer.files[0];
              if (dropped?.name.endsWith(".csv")) setFile(dropped);
            }}
            onClick={() => document.getElementById("file-input")?.click()}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); document.getElementById("file-input")?.click(); } }}
          >
            <input
              id="file-input"
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            {file ? (
              <div>
                <p className="font-medium">{file.name}</p>
                <p className="text-sm text-gray-500">
                  {(file.size / 1024).toFixed(1)} KB
                </p>
              </div>
            ) : (
              <div>
                <p className="text-gray-500">
                  Drag & drop a CSV file here, or click to browse
                </p>
                <p className="text-xs text-gray-600 mt-1">
                  .csv files only, max 50MB
                </p>
              </div>
            )}
          </div>
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
