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
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState("");

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

        if (job.status === "cancelled") {
          // Give the user a beat to see the status flip, then send them
          // back to the dashboard where the job appears as cancelled.
          setTimeout(() => router.push("/dashboard"), 800);
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

  async function handleCancel() {
    if (cancelling) return;
    setCancelling(true);
    setCancelError("");
    try {
      const res = await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "Failed to cancel conversion");
      }
      // The next poll tick will pick up the "cancelled" status and
      // route us to the dashboard. Optimistically reflect the state
      // here so the UI feels instant.
      setStatus("cancelled");
    } catch (err) {
      setCancelError(
        err instanceof Error ? err.message : "Failed to cancel conversion"
      );
      setCancelling(false);
    }
  }

  const percentage = total > 0 ? Math.round((processed / total) * 100) : 0;
  const isConverting = status === "converting";
  const isCancelled = status === "cancelled";
  const isTimedOut = status === "timeout";

  let heading: string;
  if (isTimedOut) heading = "Conversion Timed Out";
  else if (isCancelled) heading = "Conversion Cancelled";
  else heading = "Converting...";

  let subtitle: string;
  if (isTimedOut) {
    subtitle =
      "The conversion is taking longer than expected. Please check back later or try again.";
  } else if (isCancelled) {
    subtitle = "Taking you back to the dashboard…";
  } else if (isConverting) {
    subtitle = total > 0
      ? `Processing row ${processed} of ${total}`
      : "Preparing your file…";
  } else {
    subtitle = status;
  }

  return (
    <main className="max-w-2xl mx-auto px-4 py-16">
      <div className="text-center mb-8">
        <h1 className="text-2xl font-bold mb-2">{heading}</h1>
        <p className="text-sm text-gray-600">{subtitle}</p>
      </div>

      {/* Progress Bar */}
      <div
        role="progressbar"
        aria-valuenow={percentage}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Conversion progress: ${percentage}%`}
        className="w-full bg-gray-200 rounded-full h-4 mb-6 overflow-hidden"
      >
        <div
          className={`h-4 rounded-full transition-all duration-500 ease-out ${
            isCancelled ? "bg-gray-400" : "bg-blue-600"
          }`}
          style={{ width: `${percentage}%` }}
        />
      </div>

      <div className="text-center text-lg font-semibold mb-8">{percentage}%</div>

      {/* Live Counters */}
      <div
        aria-live="polite"
        aria-atomic="true"
        className="grid grid-cols-3 gap-4 mb-8"
      >
        <div className="text-center">
          <p className="text-sm text-gray-600">Processed</p>
          <p className="text-xl font-bold">{processed}</p>
        </div>
        <div className="text-center">
          <p className="text-sm text-gray-600">Errors</p>
          <p className="text-xl font-bold text-red-600">{errors}</p>
        </div>
        <div className="text-center">
          <p className="text-sm text-gray-600">Warnings</p>
          <p className="text-xl font-bold text-yellow-600">{warnings}</p>
        </div>
      </div>

      {cancelError && (
        <div
          role="alert"
          className="bg-red-50 border border-red-200 text-red-700 text-sm rounded p-3 mb-4"
        >
          {cancelError}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex justify-center gap-3">
        {isConverting && (
          <button
            type="button"
            onClick={handleCancel}
            disabled={cancelling}
            aria-busy={cancelling}
            className="px-4 py-2 border border-gray-300 rounded text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            {cancelling ? "Cancelling…" : "Cancel conversion"}
          </button>
        )}
        {isTimedOut && (
          <>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700"
            >
              Check status again
            </button>
            <button
              type="button"
              onClick={() => router.push("/dashboard")}
              className="px-4 py-2 border border-gray-300 rounded text-sm font-medium hover:bg-gray-50"
            >
              Go to dashboard
            </button>
          </>
        )}
      </div>
    </main>
  );
}
