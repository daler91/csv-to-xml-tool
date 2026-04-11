"use client";

/**
 * Shared button primitive.
 *
 * Consolidates the ~8 hand-rolled button variants that existed
 * across the app into a single component with variant / size /
 * isLoading props. Resolves UX_REVIEW.md §8.1 for buttons.
 *
 * Class-string tokens live in ./button-classes (a non-client
 * file) so server components can share them via ``buttonClasses()``
 * for <Link>-as-button sites.
 *
 * Variants:
 *   primary     — blue-600, white text, used for the main action
 *                 per form (Sign In, Upload, Save, Download, etc.)
 *   secondary   — gray border, white bg, used for cancel / back
 *                 / alternate actions.
 *   destructive — red-600, white text (reserved for future use).
 *
 * Sizes: sm / md / lg
 *
 * isLoading wires up an inline Spinner + aria-busy so every loading
 * button in the app shows the same affordance. Also disables the
 * button while loading.
 */

import { forwardRef } from "react";
import { Spinner } from "@/components/spinner";
import {
  buttonClasses,
  type ButtonVariant,
  type ButtonSize,
} from "./button-classes";

interface ButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
  fullWidth?: boolean;
  children: React.ReactNode;
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
      buttonClasses({ variant, size, fullWidth }),
      "disabled:opacity-50 disabled:cursor-not-allowed",
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
