/**
 * Shared metadata for the three converter types the web app supports.
 *
 * This module is the single source of truth for converter labels and
 * descriptions. Any page that renders a type-specific string should
 * import from here rather than hardcoding — this was the source of the
 * re-upload page bug where a "training-client" job displayed as
 * "Training (Form 888)", fixed in Phase 1.
 *
 * Phase 4 extends this with descriptions and sample-file links so the
 * converter picker (and the landing page / dashboard empty state) can
 * explain what each type is for without requiring users to read
 * source code — see UX_REVIEW.md §3.1, §9.4, §2.1, §2.2.
 */

export type ConverterType = "counseling" | "training" | "training-client";

export interface ConverterTypeMeta {
  value: ConverterType;
  label: string;
  description: string;
  /** Relative link to the sample XML/CSV under /samples. */
  sample: string;
  /** Short form name partners use when talking about the data. */
  formName: string;
}

export const CONVERTER_TYPES: readonly ConverterTypeMeta[] = [
  {
    value: "counseling",
    label: "Counseling (Form 641)",
    description:
      "Individual client counseling sessions. Each row is one counseling visit.",
    sample: "/samples/counseling-sample.csv",
    formName: "Form 641",
  },
  {
    value: "training",
    label: "Training (Form 888)",
    description:
      "Aggregated training event data with attendee demographics rolled up per class.",
    sample: "/samples/training-sample.csv",
    formName: "Form 888",
  },
  {
    value: "training-client",
    label: "Training Client (Form 641)",
    description:
      "Per-attendee rows from a training event, exported in the Form 641 schema.",
    sample: "/samples/training-client-sample.csv",
    formName: "Form 641",
  },
] as const;

export function converterTypeLabel(type: string): string {
  return (
    CONVERTER_TYPES.find((t) => t.value === type)?.label ?? type
  );
}

export function converterTypeMeta(type: string): ConverterTypeMeta | undefined {
  return CONVERTER_TYPES.find((t) => t.value === type);
}
