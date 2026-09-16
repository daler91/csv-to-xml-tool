import { describe, it, expect } from "vitest";

import {
  assertTimeoutOrdering,
  CONVERSION_TIMEOUT_MS,
  VISIBILITY_TIMEOUT_MS,
  REAP_DEADLINE_MS,
} from "@/lib/durability-timeouts";

describe("durability timeouts", () => {
  it("defaults are correctly ordered (CONTRIBUTING rule 7)", () => {
    expect(CONVERSION_TIMEOUT_MS).toBeLessThan(VISIBILITY_TIMEOUT_MS);
    expect(VISIBILITY_TIMEOUT_MS).toBeLessThan(REAP_DEADLINE_MS);
    expect(() => assertTimeoutOrdering()).not.toThrow();
  });

  it("rejects a sweep window shorter than a conversion attempt", () => {
    expect(() =>
      assertTimeoutOrdering({ conversion: 40, visibility: 30, reap: 60 })
    ).toThrow(/CONVERSION_TIMEOUT_MS < VISIBILITY_TIMEOUT_MS < REAP_DEADLINE_MS/);
  });

  it("rejects a reaper deadline that precedes the sweep window", () => {
    expect(() =>
      assertTimeoutOrdering({ conversion: 10, visibility: 60, reap: 40 })
    ).toThrow(/misordered/);
  });

  it("rejects equal values (the ordering is strict)", () => {
    expect(() =>
      assertTimeoutOrdering({ conversion: 30, visibility: 30, reap: 60 })
    ).toThrow();
  });
});
