"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

const POLL_FAILURE_THRESHOLD = 3;

function formatElapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const rem = seconds % 60;
  return `${mins}m ${rem.toString().padStart(2, "0")}s`;
}

function formatEta(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "";
  if (seconds < 10) return "a few seconds";
  if (seconds < 60) return `about ${Math.round(seconds / 5) * 5} seconds`;
  const mins = Math.round(seconds / 60);
  if (mins === 1) return "about a minute";
  return `about ${mins} minutes`;
}

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
  const [elapsedMs, setElapsedMs] = useState(0);
  const [consecutiveFailures, setConsecutiveFailures] = useState(0);
  const [pollRetryNonce, setPollRetryNonce] = useState(0);
  const startedAtRef = useRef<number>(Date.now());

  // Elapsed-time ticker. Independent of polling so it keeps counting
  // even when the network is flaky.
  useEffect(() => {
    const t = setInterval(() => {
      setElapsedMs(Date.now() - startedAtRef.current);
    }, 1000);
    return () => clearInterval(t);
  }, []);

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
        if (!res.ok) throw new Error(`status ${res.status}`);
        const job = await res.json();

        setStatus(job.status);
        setProcessed(job.processedRows || 0);
        setTotal(job.totalRows || 0);
        setConsecutiveFailures(0);

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
        // Track consecutive poll failures so we can show a banner after
        // a few in a row (§4.5). Transient single failures are still
        // silently retried.
        setConsecutiveFailures((n) => n + 1);
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
  }, [jobId, router, pollRetryNonce]);

  function retryPolling() {
    setConsecutiveFailures(0);
    setPollRetryNonce((n) => n + 1);
  }

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
  const showPollFailureBanner =
    isConverting && consecutiveFailures >= POLL_FAILURE_THRESHOLD;

  let heading: string;
  if (isTimedOut) heading = "Conversion Timed Out";
  else if (isCancelled) heading = "Conversion Cancelled";
  else heading = "Converting...";

  // Rate-based ETA. We start computing it once at least 5% of the
  // work is done, so the first noisy ticks don't produce wild
  // estimates. The rate is rows/ms; remaining is total-processed.
  let etaText = "";
  if (isConverting && total > 0 && processed > 0 && elapsedMs > 2000) {
    const fractionDone = processed / total;
    if (fractionDone >= 0.05 && fractionDone < 1) {
      const rate = processed / elapsedMs; // rows per ms
      const remainingRows = total - processed;
      const remainingMs = remainingRows / rate;
      etaText = formatEta(remainingMs / 1000);
    }
  }

  let subtitle: string;
  if (isTimedOut) {
    subtitle =
      "The conversion is taking longer than expected. Please check back later or try again.";
  } else if (isCancelled) {
    subtitle = "Taking you back to the dashboard…";
  } else if (isConverting) {
    const elapsed = `Running for ${formatElapsed(elapsedMs)}`;
    if (total > 0) {
      const rowSummary = `${processed.toLocaleString()} of ${total.toLocaleString()} records`;
      subtitle = etaText
        ? `${rowSummary} · ${elapsed} · ${etaText} remaining`
        : `${rowSummary} · ${elapsed}`;
    } else {
      subtitle = elapsed;
    }
  } else {
    subtitle = status;
  }

  return (
    <main className="max-w-2xl mx-auto px-4 py-16">
      <div className="text-center mb-8">
        <h1 className="text-2xl font-bold mb-2">{heading}</h1>
        <p className="text-sm text-gray-600">{subtitle}</p>
      </div>

      {/* Poll-failure banner (§4.5): show after consecutive failures */}
      {showPollFailureBanner && (
        <div className="mb-6">
          <Alert variant="warning">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <span>
                We&apos;re having trouble checking the conversion status.
                Your file may still be processing in the background.
              </span>
              <div className="flex gap-2 flex-shrink-0">
                <Button size="sm" onClick={retryPolling}>
                  Retry
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => router.push("/dashboard")}
                >
                  Go to dashboard
                </Button>
              </div>
            </div>
          </Alert>
        </div>
      )}

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
        <div className="mb-4">
          <Alert variant="error">{cancelError}</Alert>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex justify-center gap-3">
        {isConverting && (
          <Button
            variant="secondary"
            onClick={handleCancel}
            isLoading={cancelling}
          >
            {cancelling ? "Cancelling…" : "Cancel conversion"}
          </Button>
        )}
        {isTimedOut && (
          <>
            <Button onClick={() => window.location.reload()}>
              Check status again
            </Button>
            <Button
              variant="secondary"
              onClick={() => router.push("/dashboard")}
            >
              Go to dashboard
            </Button>
          </>
        )}
      </div>
    </main>
  );
}
