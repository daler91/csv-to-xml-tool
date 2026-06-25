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
  const rows = Array.from({ length: lines }, (_, i) => ({
    key: `line-${i}`,
    isLast: i === lines - 1,
  }));
  return (
    <div className={`space-y-2 ${className}`} aria-hidden="true">
      {rows.map(({ key, isLast }) => (
        <Skeleton
          key={key}
          className={`h-4 ${isLast ? "w-2/3" : "w-full"}`}
        />
      ))}
    </div>
  );
}

export function SkeletonTable({
  rows = 5,
  columns = 4,
}: Readonly<{ rows?: number; columns?: number }>) {
  const columnKeys = Array.from({ length: columns }, (_, i) => `col-${i}`);
  const rowKeys = Array.from({ length: rows }, (_, i) => `row-${i}`);
  return (
    <output
      aria-label="Loading"
      className="block bg-white border rounded overflow-hidden"
    >
      <div aria-hidden="true" className="border-b bg-gray-50 flex gap-3 px-4 py-3">
        {columnKeys.map((colKey) => (
          <Skeleton key={colKey} className="h-4 flex-1" />
        ))}
      </div>
      {rowKeys.map((rowKey) => (
        <div
          key={rowKey}
          aria-hidden="true"
          className="border-b flex gap-3 px-4 py-3 last:border-b-0"
        >
          {columnKeys.map((colKey) => (
            <Skeleton key={`${rowKey}-${colKey}`} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </output>
  );
}
