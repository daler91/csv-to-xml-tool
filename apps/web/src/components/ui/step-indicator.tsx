"use client";

/**
 * Step indicator for the conversion flow.
 *
 * Resolves UX_REVIEW.md §1.2. Previously the convert flow (Upload →
 * Preview → Map → Convert → Results) had no visible progress cue;
 * partners in the middle of a multi-step conversion lost their place
 * and had to rely on the browser URL bar or the Nav's "Convert" link
 * (which doesn't distinguish between steps).
 *
 * This component derives the active step from the current pathname
 * and renders a horizontal strip of 5 steps. Past steps are
 * clickable (back-navigation); the current and future steps are not.
 * Horizontal overflow is allowed on mobile so the whole strip stays
 * visible even on narrow viewports.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { StatusIcon } from "@/components/status-icon";

type StepKey = "upload" | "preview" | "mapping" | "progress" | "results";

interface Step {
  key: StepKey;
  label: string;
}

const STEPS: readonly Step[] = [
  { key: "upload", label: "Upload" },
  { key: "preview", label: "Preview" },
  { key: "mapping", label: "Map" },
  { key: "progress", label: "Convert" },
  { key: "results", label: "Results" },
] as const;

function deriveCurrentStep(pathname: string): StepKey {
  if (/^\/convert\/[^/]+\/preview/.test(pathname)) return "preview";
  if (/^\/convert\/[^/]+\/mapping/.test(pathname)) return "mapping";
  if (/^\/convert\/[^/]+\/progress/.test(pathname)) return "progress";
  if (/^\/convert\/[^/]+\/results/.test(pathname)) return "results";
  // /convert (the upload page) and /convert/[id]/reupload both land
  // users at the Upload step.
  return "upload";
}

function extractJobId(pathname: string): string | null {
  const match = /^\/convert\/([^/]+)(?:\/|$)/.exec(pathname);
  if (!match) return null;
  // /convert/[id]/... — but NOT plain /convert which has nothing after.
  if (match[1] === "") return null;
  return match[1];
}

export function StepIndicator() {
  const pathname = usePathname();
  const currentKey = deriveCurrentStep(pathname);
  const currentIndex = STEPS.findIndex((s) => s.key === currentKey);
  const jobId = extractJobId(pathname);

  function hrefFor(step: Step, index: number): string | null {
    if (index >= currentIndex) return null;
    if (step.key === "upload") return "/convert";
    if (!jobId) return null;
    // Mapping lives under /convert/[id]/mapping; progress under /progress.
    return `/convert/${jobId}/${step.key}`;
  }

  return (
    <nav
      aria-label="Conversion steps"
      className="max-w-4xl mx-auto px-4 pt-6"
    >
      <ol className="flex items-center gap-1 sm:gap-2 overflow-x-auto text-xs sm:text-sm">
        {STEPS.map((step, i) => {
          const isActive = i === currentIndex;
          const isDone = i < currentIndex;
          const href = hrefFor(step, i);

          const circleClasses = isActive
            ? "bg-blue-600 text-white border-blue-600"
            : isDone
              ? "bg-green-600 text-white border-green-600"
              : "bg-white text-gray-500 border-gray-300";

          const labelClasses = isActive
            ? "text-blue-700 font-medium"
            : isDone
              ? "text-gray-700"
              : "text-gray-500";

          const inner = (
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
              <span
                aria-hidden="true"
                className={`flex-shrink-0 w-6 h-6 rounded-full border flex items-center justify-center text-xs font-semibold ${circleClasses}`}
              >
                {isDone ? <StatusIcon kind="success" /> : i + 1}
              </span>
              <span className={labelClasses}>{step.label}</span>
            </span>
          );

          return (
            <li
              key={step.key}
              className="flex items-center gap-1 sm:gap-2"
              aria-current={isActive ? "step" : undefined}
            >
              {href ? (
                <Link href={href} className="hover:underline">
                  {inner}
                </Link>
              ) : (
                inner
              )}
              {i < STEPS.length - 1 && (
                <span aria-hidden="true" className="text-gray-300">
                  ›
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
