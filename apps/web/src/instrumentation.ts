/**
 * Next.js instrumentation hook — runs once per server process at startup
 * (stable since Next 15; no config flag needed).
 *
 * We use it to boot the durable-queue consumer (ARCH-1). Guards:
 *   - only the Node.js runtime (never edge);
 *   - never during `next build` (so we don't open a blocking Redis connection
 *     at build time).
 * The consumer module is loaded via dynamic import so it (and ioredis) is never
 * even evaluated on the edge runtime or at build.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  if (process.env.NEXT_PHASE === "phase-production-build") return;

  const { startConsumer } = await import("@/lib/job-consumer");
  await startConsumer();
}
