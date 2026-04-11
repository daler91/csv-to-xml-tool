/**
 * Inline loading spinner.
 *
 * Added for UX_REVIEW.md §5.2: buttons that are in a loading state
 * previously relied entirely on text changes ("Uploading…") and a
 * dimmed background. Pair this component with `aria-busy` on the
 * parent button so assistive tech announces the state change.
 *
 * Pure CSS via Tailwind — no dependency, no JS beyond rendering.
 */
export function Spinner({
  className = "",
}: Readonly<{ className?: string }>) {
  return (
    <svg
      className={`animate-spin ${className}`}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="3"
        opacity="0.25"
      />
      <path
        d="M12 2 A10 10 0 0 1 22 12"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}
