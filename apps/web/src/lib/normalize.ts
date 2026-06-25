/**
 * Normalize an email address for storage and comparison.
 *
 * Trims surrounding whitespace and lowercases so that addresses differing only
 * in case or padding (e.g. " Test@Example.com ") resolve to a single identity.
 * Apply at every write and lookup so the `@unique` constraint is meaningful.
 */
export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}
