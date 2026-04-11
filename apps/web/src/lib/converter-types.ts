/**
 * Shared helpers for the three converter types the web app supports.
 *
 * This module is the single source of truth for converter-type labels.
 * Any page that renders a type-specific string should import from here
 * rather than hardcoding the label — this was the source of the
 * re-upload page bug where a "training-client" job displayed as
 * "Training (Form 888)".
 *
 * Phase 4 of the UX implementation plan will extend this with
 * descriptions and sample-file links; keep the API forward-compatible.
 */

export type ConverterType = "counseling" | "training" | "training-client";

export function converterTypeLabel(type: string): string {
  switch (type) {
    case "counseling":
      return "Counseling (Form 641)";
    case "training":
      return "Training (Form 888)";
    case "training-client":
      return "Training Client (Form 641)";
    default:
      return type;
  }
}
