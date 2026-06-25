import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

// paths.ts reads DATA_DIR at module-load time, so set it before importing.
let dataDir: string;
let resolveWithinDataDir: typeof import("@/lib/paths").resolveWithinDataDir;

beforeAll(async () => {
  dataDir = await mkdtemp(path.join(os.tmpdir(), "datadir-"));
  process.env.DATA_DIR = dataDir;
  ({ resolveWithinDataDir } = await import("@/lib/paths"));
});

afterAll(async () => {
  await rm(dataDir, { recursive: true, force: true });
});

describe("resolveWithinDataDir", () => {
  it("returns the realpath for a file inside DATA_DIR", async () => {
    const sub = path.join(dataDir, "output", "job1");
    await mkdir(sub, { recursive: true });
    const file = path.join(sub, "job1.xml");
    await writeFile(file, "<xml/>");

    const resolved = await resolveWithinDataDir(file);
    expect(resolved.endsWith(path.join("output", "job1", "job1.xml"))).toBe(true);
  });

  it("throws when the path escapes DATA_DIR", async () => {
    await expect(resolveWithinDataDir("/etc/passwd")).rejects.toThrow(
      /escapes DATA_DIR/
    );
  });

  it("throws when the path does not exist (realpath fails)", async () => {
    await expect(
      resolveWithinDataDir(path.join(dataDir, "missing.xml"))
    ).rejects.toThrow();
  });
});
