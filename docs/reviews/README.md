# Review registers

Point-in-time audits and debt registers. They record **what is wrong or was
wrong**; the guides in [`../`](../README.md) describe **how the system works**.
If you want to know how something behaves today, read a guide — these documents
are deliberately written in the past tense of a problem.

## The registers

| Document | What it is | Trust it? |
|---|---|---|
| [`CODEBASE_ANALYSIS_2.md`](./CODEBASE_ANALYSIS_2.md) | **Second-pass** review at `482d235`, after the first register's Tier 1–5 remediation. Same method (every finding verified by execution); does not repeat the first register. Length facets, case-sensitive Yes/No, unaudited fabrications, training race counting, the web boot/consumer failure modes. | **Yes.** The current findings register — start here. |
| [`CODEBASE_ANALYSIS.md`](./CODEBASE_ANALYSIS.md) | First full review of `src/`, `apps/web`, `apps/worker`, tests, CI and deployment, organised into five severity tiers. Every finding was verified by *executing* the code, not by reading it. Most items are now `[FIXED]`; the still-open ones are listed in `CODEBASE_ANALYSIS_2.md` §5.4. | **Yes**, for what it covers. One stale marker: 2.3 lists `npm ci` under `[FIXED] (most)`; the web Dockerfile still uses `npm install` (second pass, 3.4). |
| [`TECHNICAL_DEBT.md`](./TECHNICAL_DEBT.md) | 19 numbered debt items by priority, each with a fix. | Yes, with the caveats below. |
| [`UX_REVIEW.md`](./UX_REVIEW.md) | Severity-ranked audit of every user-facing surface, with inline `[RESOLVED]` markers. Well maintained. | Yes, with one stale marker (below). |
| [`UX_IMPLEMENTATION_PLAN.md`](./UX_IMPLEMENTATION_PLAN.md) | The six-phase plan that sequenced the UX findings into shippable slices. | As a record of what was done. |
| [`ARCHITECTURE_REVIEW.md`](./ARCHITECTURE_REVIEW.md) | The earliest review. | **No — historical only.** ~20 of its 24 findings are fixed and **every** `file:line` citation is stale. Its own banner says so. |

## Status markers

| Marker | Meaning |
|---|---|
| `[OPEN]` | Verified present at the stated commit |
| `[FIXED]` / `[RESOLVED]` | Addressed; the entry stays in place for context |
| `[PARTIAL]` / `[PARTIALLY FIXED]` | Some of it landed; the entry says which part |

**When you fix something, flip its marker in the same commit.** A register whose
markers are not maintained does not become merely outdated — it becomes actively
misleading, because it still reads as a current risk register. That is exactly
what happened to `ARCHITECTURE_REVIEW.md`, and it is why every other register
here carries markers.

## What is genuinely still open

Checked against the code on 2026-09-16 at commit `d0e71f0`. Full detail in
[`../documentation-audit.md`](../documentation-audit.md).

**Correctness**

- Training demographics count **rows, not distinct people**
  (`training_converter.py` — `'total': max(len(rows), 1)`).
- Event-level fields come from the **first row of each group**
  (`training_converter.py:142`); disagreeing rows are silently overruled.

**Architecture**

- The converter abstraction is still inverted (§5.1); counseling still reads ~70
  headers as string literals (§5.2).
- Whole files are held in memory during a conversion (#16).
- Redis has no persistence configured.

**Web duplication (§5.6)**

- `results/page.tsx` is 685 lines and re-declares two types from
  `types/index.ts`.
- "50MB" is hardcoded in ~9 user-facing strings.
- `prisma/schema.prisma` and `scripts/migrate.js` are two sources of truth for
  the DDL.
- The audit page offers a `conversion_failed` filter nothing writes, and six
  written actions render as "—".

**Tooling (§5.5)**

- No formatter, no type checker, no ESLint. Ruff runs correctness rules only,
  which is deliberate.

**Dependencies**

- `next-auth@5.0.0-beta.30` — pre-release auth in production (#5).

**Accessibility**

- `<html lang="en">` is static (UX §6.7).

## Corrections applied to these registers

The documentation audit corrected these in place rather than leaving them wrong:

- **`CODEBASE_ANALYSIS.md` §2 baseline health** — the measured figures were from
  an earlier commit (281 pytest / 86.79% / 113 vitest). Re-measured.
- **`TECHNICAL_DEBT.md` #2, #7, #11** — referenced pandas exception types and
  pinning style after pandas was removed, and an outdated web test count.
- **`UX_REVIEW.md` §7.8** — "Nav doesn't collapse on mobile" was unmarked while
  §1.1 recorded the same fix as `[RESOLVED]`. The nav does collapse
  (`components/nav.tsx`).

`ARCHITECTURE_REVIEW.md` was deliberately **not** corrected. Its banner already
states it is historical, and rewriting a historical record to match current code
destroys the thing it is useful for.
