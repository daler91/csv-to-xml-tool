import { describe, it, expect } from "vitest";

import { computeComparison } from "./comparison";
import type { ValidationIssue } from "@/types";

function issue(overrides: Partial<ValidationIssue>): ValidationIssue {
  return {
    record_id: "C-001",
    severity: "error",
    category: "missing_required_field",
    field_name: "CounselingSeeking",
    message: "Counseling Seeking is required under Part 2 if Client is in Business.",
    ...overrides,
  };
}

describe("computeComparison", () => {
  it("classifies per event when both jobs carry event_id", () => {
    // Event A-100's issue was fixed; the same rule now fails on new event
    // A-200. Contact-level keying would call this "persistent".
    const prev = [issue({ event_id: "A-100" })];
    const curr = [issue({ event_id: "A-200" })];

    const result = computeComparison(prev, curr);

    expect(result.resolved).toEqual([issue({ event_id: "A-100" })]);
    expect(result.newIssues).toEqual([issue({ event_id: "A-200" })]);
    expect(result.persistent).toEqual([]);
  });

  it("keeps a same-event issue persistent", () => {
    const prev = [issue({ event_id: "A-100" })];
    const curr = [issue({ event_id: "A-100" })];

    const result = computeComparison(prev, curr);

    expect(result.resolved).toEqual([]);
    expect(result.newIssues).toEqual([]);
    expect(result.persistent).toEqual([issue({ event_id: "A-100" })]);
  });

  it("falls back to the contact-level key when the previous job predates event_id", () => {
    // Pre-migration jobs stored issues without the field; event-level keying
    // would mark every persistent issue as new+resolved across that boundary.
    const prev = [issue({})];
    const curr = [issue({ event_id: "A-200" })];

    const result = computeComparison(prev, curr);

    expect(result.resolved).toEqual([]);
    expect(result.newIssues).toEqual([]);
    expect(result.persistent).toEqual([issue({ event_id: "A-200" })]);
  });

  it("treats blank event ids as present, not as pre-migration data", () => {
    const prev = [issue({ event_id: "" })];
    const curr = [issue({ event_id: "" }), issue({ event_id: "A-300" })];

    const result = computeComparison(prev, curr);

    expect(result.resolved).toEqual([]);
    expect(result.newIssues).toEqual([issue({ event_id: "A-300" })]);
    expect(result.persistent).toEqual([issue({ event_id: "" })]);
  });
});
