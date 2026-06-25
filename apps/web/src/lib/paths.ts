import { realpath } from "node:fs/promises";
import path from "node:path";

const DATA_DIR = process.env.DATA_DIR || "/data";

/**
 * Resolve `p` and assert it stays within DATA_DIR (the shared volume), returning
 * the realpath. Throws if the path escapes DATA_DIR or does not exist.
 *
 * Centralizes the path-traversal guard used by the download route and the ARCH-4
 * path-handoff (job-runner records the worker-written output path). The
 * `turbopackIgnore` comments tell the bundler's file tracer not to statically
 * resolve these runtime, DB-sourced paths — without them Turbopack's NFT walker
 * gives up and flags the whole project, including next.config.ts.
 */
export async function resolveWithinDataDir(p: string): Promise<string> {
  const resolved = await realpath(/* turbopackIgnore: true */ p);
  const resolvedDataDir = await realpath(/* turbopackIgnore: true */ DATA_DIR);
  if (!resolved.startsWith(resolvedDataDir + path.sep)) {
    throw new Error("Path escapes DATA_DIR");
  }
  return resolved;
}
