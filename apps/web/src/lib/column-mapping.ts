/**
 * Validation for the {csvColumn: xmlField} shape shared by Job.columnMapping
 * and MappingTemplate.mapping. One implementation for both writers: the
 * template route always had it, while PATCH /api/jobs/:id stored whatever
 * JSON the browser sent — arrays and nested objects reached the worker's
 * `dict[str, str]` model as a 422 that dead-lettered the job with no
 * user-visible reason.
 *
 * Size caps keep a hostile payload from storing megabytes of JSON per row.
 */

export const MAX_MAPPING_ENTRIES = 200;
export const MAX_ENTRY_LENGTH = 200;

/**
 * Returns the validated mapping, or null when the value is not a flat object
 * of non-empty strings within the size caps. An empty object is rejected
 * unless `allowEmpty` is set — a job legitimately saves an empty mapping when
 * every column already matched, whereas an empty template is meaningless.
 */
export function sanitizeMapping(
  value: unknown,
  options: { allowEmpty?: boolean } = {}
): Record<string, string> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length > MAX_MAPPING_ENTRIES) return null;
  if (entries.length === 0 && !options.allowEmpty) return null;
  const mapping: Record<string, string> = {};
  for (const [key, val] of entries) {
    if (
      typeof val !== "string" ||
      key.length === 0 ||
      key.length > MAX_ENTRY_LENGTH ||
      val.length === 0 ||
      val.length > MAX_ENTRY_LENGTH
    ) {
      return null;
    }
    mapping[key] = val;
  }
  return mapping;
}
