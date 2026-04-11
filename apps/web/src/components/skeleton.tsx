/**
 * Skeleton placeholder primitives.
 *
 * Added for UX_REVIEW.md §5.3. Pages that load async data previously
 * showed a centered "Loading…" string; the layout jumped when the
 * real content arrived and on slow mobile connections it felt like a
 * stall. These primitives render animated gray bars that mirror the
 * shape of the final page so the transition is smoother.
 */

export function Skeleton({
  className = "",
}: Readonly<{ className?: string }>) {
  return (
    <div
      aria-hidden="true"
      className={`animate-pulse bg-gray-200 rounded ${className}`}
    />
  );
}

export function SkeletonText({
  lines = 1,
  className = "",
}: Readonly<{ lines?: number; className?: string }>) {
  return (
    <div className={`space-y-2 ${className}`} aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={`h-4 ${i === lines - 1 ? "w-2/3" : "w-full"}`}
        />
      ))}
    </div>
  );
}

export function SkeletonTable({
  rows = 5,
  columns = 4,
}: Readonly<{ rows?: number; columns?: number }>) {
  return (
    <div
      aria-hidden="true"
      role="status"
      aria-label="Loading"
      className="bg-white border rounded overflow-hidden"
    >
      <div className="border-b bg-gray-50 flex gap-3 px-4 py-3">
        {Array.from({ length: columns }).map((_, i) => (
          <Skeleton key={i} className="h-4 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="border-b flex gap-3 px-4 py-3 last:border-b-0">
          {Array.from({ length: columns }).map((_, c) => (
            <Skeleton key={c} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}
