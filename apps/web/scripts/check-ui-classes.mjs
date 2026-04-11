#!/usr/bin/env node
/**
 * Regression guard for the UI primitive refactor (UX_REVIEW.md §8.1).
 *
 * Phase 6 extracted apps/web/src/components/ui/{button,alert,card,
 * status-badge}.tsx so pages stop duplicating utility-class combos.
 * Without enforcement, new code tends to drift back to raw Tailwind.
 *
 * This script walks the app source tree and fails the build if any
 * file outside components/ui/ contains the known raw primitive
 * patterns. It runs as part of `npm run lint` alongside tsc.
 *
 * To whitelist a site: use the matching <Button>, <Alert>, <Card>,
 * or <StatusBadge> component from components/ui/. If you genuinely
 * need an exception, add it to the EXEMPT set below with a comment
 * explaining why.
 */

import { readdir, readFile } from "node:fs/promises";
import { join, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const ROOT = resolve(__filename, "../..");
const SRC = join(ROOT, "src");

// Directories we never scan — these are the source of truth.
const IGNORE_DIRS = new Set([
  "node_modules",
  ".next",
  "ui", // components/ui — intentional home of the primitives
]);

// Files explicitly allowed to contain the patterns. Each exemption
// must include a comment explaining why.
const EXEMPT = new Set([
  // toast.tsx defines the info/error/success variant styling used
  // by the toast primitive itself — it's the source of truth,
  // just like components/ui/ but for runtime notifications.
  "src/components/toast.tsx",
]);

// Fine-grained line exemptions for false positives inside files
// that are otherwise scanned. Match by file + substring of the
// offending line. Each one must include a reason.
const LINE_EXEMPTIONS = [
  {
    // Preview column-status card for "Missing" — a card, not an
    // alert. It uses bg-red-50 border-red-200 to match the card's
    // warning tone when required columns are absent.
    file: "src/app/convert/[jobId]/preview/page.tsx",
    contains: 'bg-red-50 border-red-200',
  },
  {
    // Cleaning diff table cell: red background is the "before"
    // value, not an alert. Pairs with the green "after" cell.
    file: "src/app/convert/[jobId]/results/page.tsx",
    contains: "bg-red-50 text-red-800 font-mono",
  },
  {
    // Landing page's numbered step circle in "How it works" —
    // a 6x6 decorative badge, not a button.
    file: "src/app/page.tsx",
    contains: "w-6 h-6 rounded-full bg-blue-600",
  },
];

const RULES = [
  {
    name: "raw primary button classes",
    // bg-blue-600 with text-white on the same element usually
    // indicates a hand-rolled primary button. Use <Button>.
    pattern: /bg-blue-600[^"'\n]*text-white|text-white[^"'\n]*bg-blue-600/,
    hint: "Use <Button> from components/ui/button.tsx instead.",
  },
  {
    name: "raw error alert classes",
    // bg-red-50 paired with a red border/text usually indicates
    // a hand-rolled error alert. Use <Alert variant="error">.
    pattern: /bg-red-50[^"'\n]*(border-red|text-red)/,
    hint: "Use <Alert variant=\"error\"> from components/ui/alert.tsx instead.",
  },
];

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.isDirectory()) {
      if (IGNORE_DIRS.has(entry.name)) continue;
      files.push(...(await walk(join(dir, entry.name))));
    } else if (/\.(tsx|ts)$/.test(entry.name)) {
      files.push(join(dir, entry.name));
    }
  }
  return files;
}

async function main() {
  const files = await walk(SRC);
  const violations = [];

  for (const file of files) {
    const rel = relative(ROOT, file);
    if (EXEMPT.has(rel)) continue;

    const content = await readFile(file, "utf-8");
    const lines = content.split("\n");

    for (const rule of RULES) {
      for (let i = 0; i < lines.length; i++) {
        if (!rule.pattern.test(lines[i])) continue;
        const lineExempt = LINE_EXEMPTIONS.some(
          (e) => e.file === rel && lines[i].includes(e.contains)
        );
        if (lineExempt) continue;
        violations.push({
          file: rel,
          line: i + 1,
          rule: rule.name,
          hint: rule.hint,
          snippet: lines[i].trim(),
        });
      }
    }
  }

  if (violations.length > 0) {
    console.error(
      `✗ check-ui-classes: ${violations.length} violation(s) found\n`
    );
    for (const v of violations) {
      console.error(`  ${v.file}:${v.line}`);
      console.error(`    rule: ${v.rule}`);
      console.error(`    hint: ${v.hint}`);
      console.error(`    code: ${v.snippet}`);
      console.error("");
    }
    console.error(
      "See UX_REVIEW.md §8.1 and apps/web/src/components/ui/ for the primitives."
    );
    process.exit(1);
  }

  console.log(`✓ check-ui-classes: no violations in ${files.length} files`);
}

main().catch((err) => {
  console.error("check-ui-classes failed:", err);
  process.exit(2);
});
