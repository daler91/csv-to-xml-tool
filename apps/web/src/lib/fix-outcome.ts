/**
 * What the validate page says after an auto-fix attempt (worker /fix-xml).
 *
 * The page used to decide from `changed` alone: "the issues are in the
 * data, not the element order" whenever nothing moved, even when the fixer
 * had refused the file or the remaining error was an element out of place,
 * and "Element order fixed, but N issues remain in the data" whenever
 * something had moved. It now says what the fixer did and what remains.
 */

export interface FixOutcomeInput {
  changed: boolean;
  is_valid: boolean;
  errors: string[];
  error_count: number;
  /** Why the fixer could not process the file; absent on older workers. */
  fix_error?: string | null;
}

export interface FixOutcome {
  variant: "success" | "warning" | "info";
  title: string;
  /** List the errors that remain under the title. */
  showErrors: boolean;
  /** Offer the reordered file for download. */
  offerDownload: boolean;
}

// libxml2's wording for an element that is missing, or not allowed where it
// stands (an extra repeat, one under the wrong parent). The fixer puts every
// sequence in schema order, so what is left of this kind is not the order.
const STRUCTURE_ERROR = /This element is not expected|Missing child element/;

export function hasStructureErrors(errors: readonly string[]): boolean {
  return errors.some((error) => STRUCTURE_ERROR.test(error));
}

function remain(count: number): string {
  return `${count} ${count === 1 ? "issue remains" : "issues remain"}`;
}

const STRUCTURE_ADVICE =
  "elements that are missing, repeated, or not allowed where they are. Auto-fix only reorders elements, so these need correcting at the source.";

export function describeFixOutcome(result: FixOutcomeInput): FixOutcome {
  if (result.fix_error) {
    return {
      variant: "warning",
      title: `Auto-fix couldn't process this file: ${result.fix_error}`,
      showErrors: false,
      offerDownload: false,
    };
  }
  if (result.is_valid) {
    return {
      variant: "success",
      title: result.changed
        ? "Element order fixed — the corrected file now passes validation."
        : "No changes were needed — the file passes validation.",
      showErrors: false,
      offerDownload: result.changed,
    };
  }
  const structure = hasStructureErrors(result.errors);
  if (result.changed) {
    return {
      variant: "warning",
      title: structure
        ? `Element order fixed, but ${remain(result.error_count)}: ${STRUCTURE_ADVICE}`
        : `Element order fixed, but ${remain(result.error_count)} in the data`,
      showErrors: true,
      offerDownload: true,
    };
  }
  if (structure) {
    return {
      variant: "warning",
      title: `No element was out of order. The remaining issues are ${STRUCTURE_ADVICE}`,
      showErrors: true,
      offerDownload: false,
    };
  }
  return {
    variant: "info",
    title: "No automatic fixes applied — the issues are in the data, not the element order.",
    showErrors: false,
    offerDownload: false,
  };
}
