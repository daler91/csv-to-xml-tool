import { describe, it, expect } from "vitest";

import { describeJobFailure } from "@/lib/job-failure";

describe("describeJobFailure", () => {
  it("surfaces the worker's 422 detail (missing columns) verbatim", () => {
    const text = describeJobFailure({
      action: "conversion_deadlettered",
      metadata: {
        error: 'Worker error 422: {"detail":"Missing required column(s) for counseling: Contact ID"}',
      },
    });
    expect(text).toContain("Missing required column(s) for counseling: Contact ID");
  });

  it("does not leak a worker 5xx body, only that the service failed", () => {
    const text = describeJobFailure({
      action: "conversion_deadlettered",
      metadata: { error: 'Worker error 500: {"detail":"Internal conversion error"}' },
    });
    expect(text).toMatch(/conversion service failed/i);
    expect(text).not.toContain("Internal conversion error");
  });

  it("explains a reaper timeout", () => {
    expect(
      describeJobFailure({ action: "conversion_timeout", metadata: { reason: "stuck" } })
    ).toMatch(/did not finish within the time limit/);
  });

  it("explains a per-attempt worker timeout", () => {
    expect(
      describeJobFailure({
        action: "conversion_deadlettered",
        metadata: { error: "Worker request to /convert timed out after 1800000ms" },
      })
    ).toMatch(/did not respond within/);
  });

  it("explains an exhausted attempts cap", () => {
    expect(
      describeJobFailure({
        action: "conversion_deadlettered",
        metadata: { error: "Attempts exhausted: claimed 4 times without completing (limit 3)" },
      })
    ).toMatch(/retried and crashed/);
  });

  it("has a fallback when nothing was recorded", () => {
    expect(describeJobFailure(null)).toMatch(/no reason was recorded/);
  });
});
