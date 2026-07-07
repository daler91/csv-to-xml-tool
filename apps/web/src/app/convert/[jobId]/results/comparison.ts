import type { ValidationIssue } from "@/types";

/**
 * Classify a re-upload's issues against the previous job's issues.
 *
 * The key includes event_id only when every issue on both sides carries the
 * field: jobs stored before event_id existed have no value, and keying on it
 * across that boundary would mark every persistent issue as new+resolved.
 * When both jobs are post-migration, the event-level key distinguishes e.g.
 * "event A-100's issue was fixed but the same rule now fails on new event
 * A-200" (one resolved + one new) from a genuinely persistent issue.
 */
export function computeComparison(
  prevIssues: ValidationIssue[],
  currIssues: ValidationIssue[]
) {
  const useEventId = [...prevIssues, ...currIssues].every(
    (i) => i.event_id !== undefined
  );
  const key = (i: ValidationIssue) =>
    useEventId
      ? `${i.record_id}|${i.event_id}|${i.field_name}|${i.category}`
      : `${i.record_id}|${i.field_name}|${i.category}`;

  const prevSet = new Set(prevIssues.map(key));
  const currSet = new Set(currIssues.map(key));

  return {
    resolved: prevIssues.filter((i) => !currSet.has(key(i))),
    newIssues: currIssues.filter((i) => !prevSet.has(key(i))),
    persistent: currIssues.filter((i) => prevSet.has(key(i))),
  };
}
