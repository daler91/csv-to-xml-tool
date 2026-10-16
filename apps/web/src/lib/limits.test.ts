import { describe, it, expect, vi, afterEach } from "vitest";
import { formatMegabytes } from "@/lib/limits";

const MB = 1024 * 1024;

describe("formatMegabytes", () => {
  it.each([
    [50 * MB, "50MB"],
    [1 * MB, "1MB"],
    [0, "0MB"],
  ])("shows whole megabytes without a decimal (%i bytes -> %s)", (bytes, shown) => {
    expect(formatMegabytes(bytes)).toBe(shown);
  });

  it.each([
    [10.5 * MB, "10.5MB"],
    [512 * 1024, "0.5MB"],
    [Math.round(25.6 * MB), "25.6MB"],
  ])("keeps one decimal for a fractional cap (%i bytes -> %s)", (bytes, shown) => {
    expect(formatMegabytes(bytes)).toBe(shown);
  });
});

/**
 * Both limits are read from the environment once, when the module loads, so
 * each case stubs the variable and then imports a fresh copy.
 */
async function loadLimits() {
  vi.resetModules();
  return import("@/lib/limits");
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("MAX_UPLOAD_BYTES", () => {
  it("defaults to 50MB", async () => {
    vi.stubEnv("MAX_UPLOAD_BYTES", undefined);
    expect((await loadLimits()).MAX_UPLOAD_BYTES).toBe(50 * MB);
  });

  it("takes an override in bytes", async () => {
    vi.stubEnv("MAX_UPLOAD_BYTES", String(10 * MB));
    expect((await loadLimits()).MAX_UPLOAD_BYTES).toBe(10 * MB);
  });

  it.each([
    ["blank (a declared but empty .env line)", ""],
    ["not a number", "fifty megabytes"],
  ])("falls back to the default when %s", async (_label, value) => {
    vi.stubEnv("MAX_UPLOAD_BYTES", value);
    expect((await loadLimits()).MAX_UPLOAD_BYTES).toBe(50 * MB);
  });
});

describe("RETENTION_DAYS", () => {
  it("defaults to 30", async () => {
    vi.stubEnv("RETENTION_DAYS", undefined);
    expect((await loadLimits()).RETENTION_DAYS).toBe(30);
  });

  it("takes an override", async () => {
    vi.stubEnv("RETENTION_DAYS", "7");
    expect((await loadLimits()).RETENTION_DAYS).toBe(7);
  });

  it.each([
    ["blank", ""],
    ["not a number", "forever"],
  ])("falls back to the default when %s", async (_label, value) => {
    vi.stubEnv("RETENTION_DAYS", value);
    expect((await loadLimits()).RETENTION_DAYS).toBe(30);
  });
});
