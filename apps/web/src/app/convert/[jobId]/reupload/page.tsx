"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { converterTypeLabel } from "@/lib/converter-types";
import { useToast } from "@/components/toast";
import { uploadErrorMessage } from "@/lib/upload-errors";
import { Spinner } from "@/components/spinner";
import { Skeleton } from "@/components/skeleton";

export default function ReuploadPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const router = useRouter();
  const toast = useToast();

  const [converterType, setConverterType] = useState("");
  const [fileName, setFileName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`/api/jobs/${jobId}`)
      .then((r) => r.json())
      .then((data) => {
        setConverterType(data.converterType || "");
        setFileName(data.inputFileName || "");
        setLoading(false);
      })
      .catch(() => {
        setError("Failed to load job details");
        setLoading(false);
      });
  }, [jobId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    setUploading(true);
    setError("");

    const formData = new FormData();
    formData.append("file", file);
    formData.append("converterType", converterType);
    formData.append("previousJobId", jobId);

    try {
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(uploadErrorMessage(res.status, data.error));
        setUploading(false);
        return;
      }
      const data = await res.json();
      toast.success("Re-upload received — loading preview");
      router.push(`/convert/${data.jobId}/preview`);
    } catch {
      setError(
        "Couldn't reach the server. Check your internet connection and try again."
      );
      setUploading(false);
    }
  };

  if (loading) {
    return (
      <main className="max-w-2xl mx-auto px-4 py-8" aria-busy="true">
        <Skeleton className="h-7 w-56 mb-2" />
        <Skeleton className="h-4 w-80 mb-6" />
        <Skeleton className="h-14 w-full mb-4" />
        <Skeleton className="h-10 w-full mb-4" />
      </main>
    );
  }

  return (
    <main className="max-w-2xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-2">Re-upload Fixed CSV</h1>
      <p className="text-sm text-gray-500 mb-6">
        Upload a corrected version of <strong>{fileName}</strong> to compare
        against the previous conversion.
      </p>

      {error && (
        <div
          role="alert"
          className="bg-red-50 border border-red-200 text-red-700 text-sm rounded p-3 mb-4"
        >
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <span className="block text-sm font-medium mb-1">
            Converter Type
          </span>
          <p className="text-sm text-gray-600 bg-gray-50 border rounded px-3 py-2">
            {converterTypeLabel(converterType)}
          </p>
        </div>

        <div>
          <label htmlFor="reupload-file" className="block text-sm font-medium mb-1">
            Updated CSV File
          </label>
          <input
            id="reupload-file"
            type="file"
            accept=".csv"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="block w-full text-sm border rounded p-2"
          />
        </div>

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={!file || uploading}
            aria-busy={uploading}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {uploading && <Spinner />}
            {uploading ? "Uploading..." : "Upload & Compare"}
          </button>
          <button
            type="button"
            onClick={() => router.push(`/convert/${jobId}/results`)}
            className="px-4 py-2 border border-gray-300 rounded text-sm hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
      </form>
    </main>
  );
}
