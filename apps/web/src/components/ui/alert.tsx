/**
 * Shared alert primitive.
 *
 * Consolidates the ~6 hand-rolled red/blue/green alert variants
 * that existed across the app. Resolves UX_REVIEW.md §8.1 / §8.5.
 *
 * Variants map to tone:
 *   error   — red-50 bg, red-200 border, red-800 text, role=alert
 *   warning — yellow-50 / yellow-200 / yellow-800, role=status
 *   info    — blue-50 / blue-200 / blue-800, role=status
 *   success — green-50 / green-200 / green-800, role=status
 *
 * Errors use role=alert so assistive tech interrupts; non-errors
 * use role=status for polite announcement.
 */

import { StatusIcon } from "@/components/status-icon";

type AlertVariant = "error" | "warning" | "info" | "success";

interface AlertProps {
  variant: AlertVariant;
  title?: string;
  children: React.ReactNode;
  className?: string;
}

const STYLES: Record<AlertVariant, string> = {
  error: "bg-red-50 border-red-200 text-red-800",
  warning: "bg-yellow-50 border-yellow-200 text-yellow-800",
  info: "bg-blue-50 border-blue-200 text-blue-800",
  success: "bg-green-50 border-green-200 text-green-800",
};

const ICON_KIND: Record<AlertVariant, "error" | "warning" | "info" | "success"> = {
  error: "error",
  warning: "warning",
  info: "info",
  success: "success",
};

export function Alert({
  variant,
  title,
  children,
  className = "",
}: Readonly<AlertProps>) {
  const role = variant === "error" ? "alert" : "status";
  return (
    <div
      role={role}
      className={`border rounded p-3 text-sm ${STYLES[variant]} ${className}`}
    >
      <div className="flex gap-2">
        <span className="flex-shrink-0 mt-0.5">
          <StatusIcon kind={ICON_KIND[variant]} />
        </span>
        <div className="flex-1 min-w-0">
          {title && <p className="font-semibold mb-1">{title}</p>}
          <div>{children}</div>
        </div>
      </div>
    </div>
  );
}
