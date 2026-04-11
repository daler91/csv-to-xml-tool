/**
 * Pure class-string helpers for button-styled elements.
 *
 * Split out of button.tsx so server components (which can't import
 * from "use client" files) can still share the same variant / size
 * tokens as the <Button> client component. The Button component
 * imports from here too, so there's one source of truth.
 *
 * See UX_REVIEW.md §8.1. The regression guard in
 * scripts/check-ui-classes.mjs exempts components/ui/ as a
 * directory, so the raw utility-class strings below don't trip the
 * check.
 */

export type ButtonVariant = "primary" | "secondary" | "destructive";
export type ButtonSize = "sm" | "md" | "lg";

export const BUTTON_VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-blue-600 text-white hover:bg-blue-700 border border-transparent",
  secondary:
    "bg-white text-gray-800 hover:bg-gray-50 border border-gray-300",
  destructive:
    "bg-red-600 text-white hover:bg-red-700 border border-transparent",
};

export const BUTTON_SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
  lg: "px-6 py-3 text-base",
};

/**
 * Class-string builder for both <Button> and <Link>-as-button sites.
 *
 * Next.js <Link> renders an <a>, not a <button>, so it can't just
 * accept our <Button> component. This helper lets Link sites share
 * the same variant/size source of truth as Button without
 * hand-rolling utility classes — the regression guard in
 * scripts/check-ui-classes.mjs only exempts components/ui/, so any
 * page that hand-rolls these classes still fails the check.
 */
export function buttonClasses(
  opts: {
    variant?: ButtonVariant;
    size?: ButtonSize;
    fullWidth?: boolean;
  } = {}
): string {
  const { variant = "primary", size = "md", fullWidth = false } = opts;
  return [
    "inline-flex items-center justify-center gap-2 rounded font-medium transition-colors",
    BUTTON_VARIANT_CLASSES[variant],
    BUTTON_SIZE_CLASSES[size],
    fullWidth ? "w-full" : "",
  ]
    .filter(Boolean)
    .join(" ");
}
