import { describe, it, expect } from "vitest";
import {
  sanitizeMapping,
  MAX_MAPPING_ENTRIES,
  MAX_ENTRY_LENGTH,
} from "@/lib/column-mapping";

/**
 * sanitizeMapping is the one gate in front of Job.columnMapping and
 * MappingTemplate.mapping. What it lets through is sent to the worker's
 * `dict[str, str]` model, where anything else is a 422 that dead-letters the
 * job with no reason the user can see — so a rejected value must come back as
 * null for the route to answer 400, never as a partial mapping.
 */

/** A mapping with `count` distinct, valid entries. */
function mappingOf(count: number): Record<string, string> {
  return Object.fromEntries(
    Array.from({ length: count }, (_, i) => [`CSV column ${i}`, `Field ${i}`])
  );
}

describe("sanitizeMapping", () => {
  it("accepts a flat object of non-empty strings", () => {
    const mapping = { "My Contact Col": "Contact ID", "E-mail": "Email" };
    expect(sanitizeMapping(mapping)).toEqual(mapping);
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
    ["a string", "Contact ID"],
    ["a number", 42],
    ["a boolean", true],
    ["an array of pairs", [["My Col", "Contact ID"]]],
  ])("rejects %s", (_label, value) => {
    expect(sanitizeMapping(value)).toBeNull();
  });

  it.each([
    ["a number", 42],
    ["null", null],
    ["a nested object", { field: "Contact ID" }],
    ["an array", ["Contact ID"]],
    ["a boolean", false],
  ])("rejects the whole mapping when one value is %s", (_label, bad) => {
    // One bad entry voids the mapping rather than being dropped: a silently
    // shortened mapping would convert with columns the user thought were mapped.
    expect(sanitizeMapping({ "Good Col": "Contact ID", "Bad Col": bad })).toBeNull();
  });

  it("rejects an empty column name or an empty field name", () => {
    expect(sanitizeMapping({ "": "Contact ID" })).toBeNull();
    expect(sanitizeMapping({ "My Col": "" })).toBeNull();
  });

  describe("emptiness", () => {
    it("rejects an empty object by default (an empty template is meaningless)", () => {
      expect(sanitizeMapping({})).toBeNull();
    });

    it("accepts an empty object with allowEmpty (every column already matched)", () => {
      expect(sanitizeMapping({}, { allowEmpty: true })).toEqual({});
    });

    it("does not let allowEmpty admit an empty array", () => {
      // [] has no entries either; only the array check keeps it out.
      expect(sanitizeMapping([], { allowEmpty: true })).toBeNull();
    });

    it("does not relax any other rule under allowEmpty", () => {
      expect(sanitizeMapping({ "My Col": 1 }, { allowEmpty: true })).toBeNull();
      expect(sanitizeMapping(mappingOf(MAX_MAPPING_ENTRIES + 1), { allowEmpty: true })).toBeNull();
    });
  });

  describe("size caps", () => {
    it(`accepts exactly ${MAX_MAPPING_ENTRIES} entries and rejects one more`, () => {
      expect(sanitizeMapping(mappingOf(MAX_MAPPING_ENTRIES))).not.toBeNull();
      expect(sanitizeMapping(mappingOf(MAX_MAPPING_ENTRIES + 1))).toBeNull();
    });

    it(`accepts a column name of exactly ${MAX_ENTRY_LENGTH} characters and rejects one more`, () => {
      expect(sanitizeMapping({ ["k".repeat(MAX_ENTRY_LENGTH)]: "Contact ID" })).not.toBeNull();
      expect(sanitizeMapping({ ["k".repeat(MAX_ENTRY_LENGTH + 1)]: "Contact ID" })).toBeNull();
    });

    it(`accepts a field name of exactly ${MAX_ENTRY_LENGTH} characters and rejects one more`, () => {
      expect(sanitizeMapping({ "My Col": "v".repeat(MAX_ENTRY_LENGTH) })).not.toBeNull();
      expect(sanitizeMapping({ "My Col": "v".repeat(MAX_ENTRY_LENGTH + 1) })).toBeNull();
    });
  });
});
