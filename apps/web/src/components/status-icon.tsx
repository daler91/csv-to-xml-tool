/**
 * Inline status icons — used wherever the app conveys state with
 * color (success / warning / error / info / neutral).
 *
 * Resolves UX_REVIEW.md §6.3: the app previously leaned on color
 * alone (green/yellow/red/blue) for summary cards, status badges,
 * column-status cards, and cleaning diff rows, which is a WCAG 1.4.1
 * violation. Pairing each color with a text label *and* a shape gives
 * colorblind users a redundant cue.
 *
 * All icons are 16px SVG with currentColor so they inherit text color.
 * They're aria-hidden because the surrounding text already conveys
 * the meaning.
 */

type StatusKind = "success" | "warning" | "error" | "info" | "neutral";

const PATHS: Record<StatusKind, React.ReactNode> = {
  success: (
    <path
      d="M5 12l4 4L19 7"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  ),
  warning: (
    <>
      <path
        d="M12 3 L22 20 L2 20 Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
        fill="none"
      />
      <line
        x1="12"
        y1="10"
        x2="12"
        y2="14"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle cx="12" cy="17" r="1" fill="currentColor" />
    </>
  ),
  error: (
    <>
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
      />
      <line
        x1="8"
        y1="8"
        x2="16"
        y2="16"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <line
        x1="16"
        y1="8"
        x2="8"
        y2="16"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </>
  ),
  info: (
    <>
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
      />
      <line
        x1="12"
        y1="11"
        x2="12"
        y2="17"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle cx="12" cy="8" r="1.25" fill="currentColor" />
    </>
  ),
  neutral: (
    <circle
      cx="12"
      cy="12"
      r="4"
      stroke="currentColor"
      strokeWidth="2"
      fill="none"
    />
  ),
};

export function StatusIcon({
  kind,
  className = "",
}: Readonly<{ kind: StatusKind; className?: string }>) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      {PATHS[kind]}
    </svg>
  );
}

export type { StatusKind };
