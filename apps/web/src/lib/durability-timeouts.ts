/**
 * The three interlocking timeouts of the durable queue (ARCH-1), in one
 * place so their ordering can be checked at startup instead of by hand.
 *
 *   CONVERSION_TIMEOUT_MS  how long one /convert attempt may run before the
 *                          web aborts it (job-runner.ts)
 *   VISIBILITY_TIMEOUT_MS  a claimed job not acked within this is treated as
 *                          abandoned and re-queued by the sweep (job-queue.ts)
 *   REAP_DEADLINE_MS       a job stuck queued/converting past this is failed
 *                          outright by the reaper (job-reaper.ts)
 *
 * They must satisfy CONVERSION < VISIBILITY < REAP (CONTRIBUTING rule 7).
 * If the sweep window is shorter than one conversion attempt, the sweep
 * re-queues a job a live consumer is still running and two consumers convert
 * it at once, each writing "conversion_started" and racing to complete. If
 * the reaper deadline is shorter than the sweep window, the reaper fails a
 * job the sweep was about to retry. The defaults and both .env.example files
 * are ordered correctly; this guards the override that is not.
 */

function envMs(name: string, fallbackMs: number): number {
  const raw = process.env[name];
  const value = raw === undefined || raw === "" ? NaN : Number(raw);
  return Number.isFinite(value) && value > 0 ? value : fallbackMs;
}

export const CONVERSION_TIMEOUT_MS = envMs("CONVERSION_TIMEOUT_MS", 30 * 60 * 1000);
export const VISIBILITY_TIMEOUT_MS = envMs("VISIBILITY_TIMEOUT_MS", 40 * 60 * 1000);
export const REAP_DEADLINE_MS = envMs("REAP_DEADLINE_MS", 60 * 60 * 1000);

/**
 * Throws when the three timeouts are not strictly ascending. Called once
 * from the consumer's startup so a misordered override stops the process
 * with a message naming the values, rather than silently double-running
 * conversions.
 */
export function assertTimeoutOrdering(
  timeouts: {
    conversion: number;
    visibility: number;
    reap: number;
  } = {
    conversion: CONVERSION_TIMEOUT_MS,
    visibility: VISIBILITY_TIMEOUT_MS,
    reap: REAP_DEADLINE_MS,
  }
): void {
  const { conversion, visibility, reap } = timeouts;
  if (conversion < visibility && visibility < reap) return;
  throw new Error(
    "Durability timeouts are misordered: require " +
      "CONVERSION_TIMEOUT_MS < VISIBILITY_TIMEOUT_MS < REAP_DEADLINE_MS, got " +
      `${conversion} / ${visibility} / ${reap}. ` +
      "A sweep window shorter than a conversion attempt re-queues jobs that are still running."
  );
}
