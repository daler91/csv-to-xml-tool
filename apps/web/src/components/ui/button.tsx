"use client";

/**
 * Shared button primitive.
 *
 * Consolidates the ~8 hand-rolled button variants that existed
 * across the app into a single component with variant / size /
 * isLoading props. Resolves UX_REVIEW.md §8.1 for buttons.
 *
 * Variants:
 *   primary     — blue-600, white text, used for the main action
 *                 per form (Sign In, Upload, Save, Download, etc.)
 *   secondary   — gray border, white bg, used for cancel / back
 *                 / alternate actions.
 *   destructive — red-600, white text (reserved for future use).
 *
 * Sizes:
 *   sm — px-3 py-1.5 text-xs (dense lists, header buttons)
 *   md — px-4 py-2 text-sm   (default form submit)
 *
 * isLoading wires up an inline Spinner + aria-busy so every
 * loading button in the app shows the same affordance. Also
 * disables the button while loading.
 */

import { forwardRef } from "react";
import { Spinner } from "@/components/spinner";

type ButtonVariant = "primary" | "secondary" | "destructive";
type ButtonSize = "sm" | "md" | "lg";

interface ButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
  fullWidth?: boolean;
  children: React.ReactNode;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-blue-600 text-white hover:bg-blue-700 border border-transparent",
  secondary:
    "bg-white text-gray-800 hover:bg-gray-50 border border-gray-300",
  destructive:
    "bg-red-600 text-white hover:bg-red-700 border border-transparent",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
  lg: "px-6 py-3 text-base",
};

/**
 * Class-string builder for <Link>-as-button sites.
 *
 * Next.js <Link> renders an <a>, not a <button>, so it can't just
 * accept our <Button> component. This helper lets Link sites
 * share the same variant/size source of truth as Button without
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
    VARIANT_CLASSES[variant],
    SIZE_CLASSES[size],
    fullWidth ? "w-full" : "",
  ]
    .filter(Boolean)
    .join(" ");
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = "primary",
      size = "md",
      isLoading = false,
      fullWidth = false,
      disabled,
      className = "",
      children,
      ...rest
    },
    ref
  ) {
    const effectiveDisabled = disabled || isLoading;
    const classes = [
      "inline-flex items-center justify-center gap-2 rounded font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
      VARIANT_CLASSES[variant],
      SIZE_CLASSES[size],
      fullWidth ? "w-full" : "",
      className,
    ]
      .filter(Boolean)
      .join(" ");

    return (
      <button
        ref={ref}
        disabled={effectiveDisabled}
        aria-busy={isLoading || undefined}
        className={classes}
        {...rest}
      >
        {isLoading && <Spinner />}
        {children}
      </button>
    );
  }
);
