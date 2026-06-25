import { describe, it, expect } from "vitest";
import { normalizeEmail } from "@/lib/normalize";

describe("normalizeEmail", () => {
  it("lowercases and trims surrounding whitespace", () => {
    expect(normalizeEmail("  Test@Example.COM  ")).toBe("test@example.com");
  });

  it("is idempotent on an already-normalized address", () => {
    expect(normalizeEmail("test@example.com")).toBe("test@example.com");
  });

  it("collapses case-only variants to a single identity", () => {
    expect(normalizeEmail("USER@Example.com")).toBe(normalizeEmail("user@example.COM"));
  });

  it("reduces a whitespace-only string to empty", () => {
    expect(normalizeEmail("   ")).toBe("");
  });
});
