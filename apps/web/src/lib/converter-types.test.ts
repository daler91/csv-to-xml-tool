import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  CONVERTER_TYPES,
  converterTypeLabel,
  converterTypeMeta,
} from "@/lib/converter-types";

const WEB_ROOT = resolve(__dirname, "../..");
const REPO_ROOT = resolve(WEB_ROOT, "../..");

const values = CONVERTER_TYPES.map((t) => t.value);

describe("CONVERTER_TYPES", () => {
  it("offers exactly the converter types the worker accepts", () => {
    // The worker's request models type converter_type as this Literal; a type
    // offered here but missing there is a 422 that dead-letters every job.
    const schemas = readFileSync(
      resolve(REPO_ROOT, "apps/worker/app/models/schemas.py"),
      "utf8"
    );
    const literal = /^ConverterType = Literal\[([^\]]*)\]/m.exec(schemas);
    expect(literal, "ConverterType Literal not found in schemas.py").not.toBeNull();
    const workerTypes = [...literal![1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect([...values].sort()).toEqual([...workerTypes].sort());
  });

  it("gives every type a distinct value and a distinct label", () => {
    expect(new Set(values).size).toBe(CONVERTER_TYPES.length);
    expect(new Set(CONVERTER_TYPES.map((t) => t.label)).size).toBe(CONVERTER_TYPES.length);
  });

  it("names the form each type files in its label", () => {
    for (const type of CONVERTER_TYPES) {
      expect(type.label).toContain(type.formName);
    }
  });

  it("links each type to the sample the Python suite proves converts cleanly", () => {
    // tests/test_integration_xsd.py (TestShippedSamplesValidate) converts
    // public/samples/<type>-sample.csv with that type's converter and requires
    // schema-valid XML. Linking any other file would hand a first-time user a
    // sample nothing has checked.
    for (const type of CONVERTER_TYPES) {
      expect(type.sample).toBe(`/samples/${type.value}-sample.csv`);
      expect(existsSync(resolve(WEB_ROOT, "public", `.${type.sample}`)), type.sample).toBe(true);
    }
  });
});

describe("converterTypeLabel", () => {
  it("labels each type from its own entry", () => {
    for (const type of CONVERTER_TYPES) {
      expect(converterTypeLabel(type.value)).toBe(type.label);
    }
  });

  it("does not label a training-client job as Training (Form 888)", () => {
    // The re-upload page once showed exactly that for a training-client job.
    expect(converterTypeLabel("training-client")).not.toBe(converterTypeLabel("training"));
    expect(converterTypeLabel("training-client")).toContain("Form 641");
  });

  it("falls back to the stored value for a type it does not know", () => {
    expect(converterTypeLabel("legacy-type")).toBe("legacy-type");
  });
});

describe("converterTypeMeta", () => {
  it("returns the matching entry", () => {
    expect(converterTypeMeta("training")).toBe(CONVERTER_TYPES.find((t) => t.value === "training"));
  });

  it("matches whole values only", () => {
    expect(converterTypeMeta("train")).toBeUndefined();
    expect(converterTypeMeta("legacy-type")).toBeUndefined();
  });
});
