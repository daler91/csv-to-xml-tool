/**
 * Shared status badge.
 *
 * Extracted from dashboard/page.tsx so results, audit, and future
 * screens can reuse the same icon + label + color combo without
 * duplicating the STATUS_META map. Resolves UX_REVIEW.md §8.2.
 *
 * Labels are intentionally human-friendly (§9.1):
 *   uploaded   -> Uploaded
 *   previewed  -> Ready to convert
 *   mapping    -> Needs mapping
 *   converting -> Converting
 *   complete   -> Complete
 *   error      -> Failed
 *   cancelled  -> Cancelled
 *
 * A ``data-status`` attribute preserves the raw DB value for tests.
 */

import { StatusIcon, type StatusKind } from "@/components/status-icon";

interface StatusMeta {
  label: string;
  kind: StatusKind;
  color: string;
}

const STATUS_META: Record<string, StatusMeta> = {
  uploaded: {
    label: "Uploaded",
    kind: "neutral",
    color: "bg-gray-100 text-gray-800",
  },
  previewed: {
    label: "Ready to convert",
    kind: "info",
    color: "bg-blue-100 text-blue-800",
  },
  mapping: {
    label: "Needs mapping",
    kind: "warning",
    color: "bg-yellow-100 text-yellow-800",
  },
  converting: {
    label: "Converting",
    kind: "info",
    color: "bg-blue-100 text-blue-800",
  },
  complete: {
    label: "Complete",
    kind: "success",
    color: "bg-green-100 text-green-800",
  },
  error: {
    label: "Failed",
    kind: "error",
    color: "bg-red-100 text-red-800",
  },
  cancelled: {
    label: "Cancelled",
    kind: "neutral",
    color: "bg-gray-100 text-gray-700",
  },
};

export function StatusBadge({ status }: Readonly<{ status: string }>) {
  const meta =
    STATUS_META[status] ?? {
      label: status,
      kind: "neutral" as StatusKind,
      color: "bg-gray-100 text-gray-700",
    };

  return (
    <span
      data-status={status}
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium ${meta.color}`}
    >
      <StatusIcon kind={meta.kind} />
      {meta.label}
    </span>
  );
}
