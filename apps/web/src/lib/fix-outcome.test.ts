import { describe, it, expect } from "vitest";

import { describeFixOutcome, hasStructureErrors } from "@/lib/fix-outcome";

const ORDER_ERROR =
  "Line 88: Element 'Language': This element is not expected. Expected is one of ( CounselorNotes, ExportCountries, TrainingSession ).";
const MISSING_ERROR =
  "Line 24: Element 'ClientIntake': Missing child element(s). Expected is ( CurrentlyInBusiness ).";
const DATA_ERROR =
  "Line 84: Element 'DateCounseled': '2025-13-45' is not a valid value of the atomic type 'xs:date'.";

function outcome(fields: {
  changed: boolean;
  is_valid?: boolean;
  errors?: string[];
  fix_error?: string | null;
}) {
  const errors = fields.errors ?? [];
  return describeFixOutcome({
    changed: fields.changed,
    is_valid: fields.is_valid ?? errors.length === 0,
    errors,
    error_count: errors.length,
    fix_error: fields.fix_error,
  });
}

describe("hasStructureErrors", () => {
  it("recognises libxml2's unexpected and missing element messages", () => {
    expect(hasStructureErrors([DATA_ERROR, ORDER_ERROR])).toBe(true);
    expect(hasStructureErrors([MISSING_ERROR])).toBe(true);
    expect(hasStructureErrors([DATA_ERROR])).toBe(false);
  });
});

describe("describeFixOutcome", () => {
  it("says why when the fixer refused the file, not that the data is wrong", () => {
    const result = outcome({
      changed: false,
      errors: [ORDER_ERROR],
      fix_error: "DTD/entity declarations are not supported: ...",
    });
    expect(result.title).toContain("Auto-fix couldn't process this file: DTD/entity");
    expect(result.title).not.toContain("in the data");
    expect(result.offerDownload).toBe(false);
  });

  it("does not blame the data when an element is still unexpected", () => {
    const unchanged = outcome({ changed: false, errors: [ORDER_ERROR] });
    expect(unchanged.title).not.toContain("in the data");
    expect(unchanged.title).toContain("No element was out of order");
    expect(unchanged.showErrors).toBe(true);

    const changed = outcome({ changed: true, errors: [MISSING_ERROR] });
    expect(changed.title).toMatch(/^Element order fixed, but 1 issue remains: elements that are missing/);
    expect(changed.offerDownload).toBe(true);
  });

  it("keeps the data message for value errors", () => {
    expect(outcome({ changed: false, errors: [DATA_ERROR] }).title).toBe(
      "No automatic fixes applied — the issues are in the data, not the element order."
    );
    expect(outcome({ changed: true, errors: [DATA_ERROR, DATA_ERROR] }).title).toBe(
      "Element order fixed, but 2 issues remain in the data"
    );
  });

  it("offers the corrected file when it now passes", () => {
    const result = outcome({ changed: true });
    expect(result).toMatchObject({ variant: "success", offerDownload: true, showErrors: false });
  });
});
