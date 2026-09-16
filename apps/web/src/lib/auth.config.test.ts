import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { authConfig } from "@/lib/auth.config";

const APP_ROOT = resolve(__dirname, "../..");
const SRC = resolve(APP_ROOT, "src");

/** Modules that cannot run on the edge runtime the middleware is bundled for. */
const NODE_ONLY = ["ioredis", "@prisma/client", "bcryptjs"];

function resolveSpecifier(specifier: string, importer: string): string | null {
  let base: string;
  if (specifier.startsWith("@/")) base = resolve(SRC, specifier.slice(2));
  else if (specifier.startsWith(".")) base = resolve(dirname(importer), specifier);
  else return null; // bare specifier — a node_modules package

  for (const candidate of [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    resolve(base, "index.ts"),
    resolve(base, "index.tsx"),
  ]) {
    if (existsSync(candidate) && !candidate.endsWith("/")) {
      try {
        readFileSync(candidate);
        return candidate;
      } catch {
        // a directory — keep looking
      }
    }
  }
  return null;
}

/** Every bare package reachable from `entry` through local imports. */
function externalDeps(entry: string): Set<string> {
  const packages = new Set<string>();
  const seen = new Set<string>();
  const queue = [entry];

  while (queue.length) {
    const file = queue.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);

    const source = readFileSync(file, "utf8");
    const specifiers = [...source.matchAll(/(?:from|import)\s*["']([^"']+)["']/g)].map(
      (m) => m[1]
    );

    for (const specifier of specifiers) {
      const local = resolveSpecifier(specifier, file);
      if (local) {
        queue.push(local);
      } else if (!specifier.startsWith("@/") && !specifier.startsWith(".")) {
        // "@scope/pkg/sub" and "pkg/sub" both collapse to the package name.
        const parts = specifier.split("/");
        packages.add(specifier.startsWith("@") ? parts.slice(0, 2).join("/") : parts[0]);
      }
    }
  }
  return packages;
}

describe("middleware stays edge-safe", () => {
  it("reaches no Node-only package from middleware.ts", () => {
    const deps = externalDeps(resolve(APP_ROOT, "middleware.ts"));
    expect([...deps].filter((d) => NODE_ONLY.includes(d))).toEqual([]);
  });

  it("still reaches those packages from auth.ts, which runs on Node", () => {
    // Guards the test itself: if the walker stopped resolving imports the check
    // above would pass vacuously.
    const deps = externalDeps(resolve(SRC, "lib/auth.ts"));
    expect([...deps].filter((d) => NODE_ONLY.includes(d)).sort()).toEqual(
      [...NODE_ONLY].sort()
    );
  });
});

describe("authConfig", () => {
  it("trusts the host, which Auth.js will not infer from NEXTAUTH_URL", () => {
    expect(authConfig.trustHost).toBe(true);
  });

  it("declares no providers — sign-in belongs to the Node-runtime handler", () => {
    expect(authConfig.providers).toEqual([]);
  });

  it("keeps JWT sessions and the custom sign-in page", () => {
    expect(authConfig.session.strategy).toBe("jwt");
    expect(authConfig.pages.signIn).toBe("/login");
  });

  it("carries the user id from sign-in through the token onto the session", async () => {
    const token = await authConfig.callbacks.jwt({
      token: {},
      user: { id: "user-1" },
    } as never);
    expect(token).toMatchObject({ id: "user-1" });

    const session = await authConfig.callbacks.session({
      session: { user: {} },
      token: { id: "user-1" },
    } as never);
    expect(session).toMatchObject({ user: { id: "user-1" } });
  });

  it("leaves the token alone on a request that carries no user", async () => {
    const token = await authConfig.callbacks.jwt({
      token: { id: "existing" },
      user: undefined,
    } as never);
    expect(token).toEqual({ id: "existing" });
  });
});
