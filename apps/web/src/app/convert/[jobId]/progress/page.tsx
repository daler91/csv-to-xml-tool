"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

export default function ProgressPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const router = useRouter();
  const [status, setStatus] = useState("converting");
  const [processed, setProcessed] = useState(0);
  const [total, setTotal] = useState(0);
  const [errors, setErrors] = useState(0);
  const [warnings, setWarnings] = useState(0);

  useEffect(() => {
    let pollInterval = 1000;
    let timeoutId: ReturnType<typeof setTimeout>;
    let cancelled = false;
    const startTime = Date.now();
    const MAX_WAIT_MS = 5 * 60 * 1000; // 5 minutes

    async function poll() {
      if (cancelled) return;
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        const job = await res.json();

        setStatus(job.status);
        setProcessed(job.processedRows || 0);
        setTotal(job.totalRows || 0);

        if (job.summary) {
          const s = job.summary as Record<string, number>;
          setErrors(s.errors || 0);
          setWarnings(s.warnings || 0);
        }

        if (job.status === "complete" || job.status === "error") {
          router.push(`/convert/${jobId}/results`);
          return;
        }

        if (Date.now() - startTime > MAX_WAIT_MS) {
          setStatus("timeout");
          return;
        }
      } catch {
        // ignore transient poll errors
      }

      // Gradually back off: 1s -> 2s -> 5s
      if (pollInterval < 2000) pollInterval = 2000;
      else if (pollInterval < 5000) pollInterval = 5000;

      if (!cancelled) {
        timeoutId = setTimeout(poll, pollInterval);
      }
    }

    timeoutId = setTimeout(poll, pollInterval);
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [jobId, router]);

  const percentage = total > 0 ? Math.round((processed / total) * 100) : 0;

  return (
    <main className="max-w-2xl mx-auto px-4 py-16">
      <div className="text-center mb-8">
        <h1 className="text-2xl font-bold mb-2">
          {status === "timeout" ? "Conversion Timed Out" : "Converting..."}
        </h1>
        <p className="text-sm text-gray-500">
          {status === "timeout"
            ? "The conversion is taking longer than expected. Please check back later or try again."
            : status === "converting"
              ? `Processing row ${processed} of ${total}`
              : status}
        </p>
      </div>

      {/* Progress Bar */}
      <div className="w-full bg-gray-200 rounded-full h-4 mb-6 overflow-hidden">
        <div
          className="bg-blue-600 h-4 rounded-full transition-all duration-500 ease-out"
          style={{ width: `${percentage}%` }}
        />
      </div>

      <div className="text-center text-lg font-semibold mb-8">{percentage}%</div>

      {/* Live Counters */}
      <div className="grid grid-cols-3 gap-4">
        <div className="text-center">
          <p className="text-sm text-gray-500">Processed</p>
          <p className="text-xl font-bold">{processed}</p>
        </div>
        <div className="text-center">
          <p className="text-sm text-gray-500">Errors</p>
          <p className="text-xl font-bold text-red-600">{errors}</p>
        </div>
        <div className="text-center">
          <p className="text-sm text-gray-500">Warnings</p>
          <p className="text-xl font-bold text-yellow-600">{warnings}</p>
        </div>
      </div>
    </main>
  );
}
