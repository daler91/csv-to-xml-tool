# Review registers

Point-in-time audits and debt registers. They record **what is wrong or was
wrong**; the guides in [`../`](../README.md) describe **how the system works**.
If you want to know how something behaves today, read a guide — these documents
are deliberately written in the past tense of a problem.

## The registers

| Document | What it is | Trust it? |
|---|---|---|
| [`XSD_VALIDITY_ANALYSIS.md`](./XSD_VALIDITY_ANALYSIS.md) | Whether every file the tool produces passes SBA's two XSDs: a first pass (V.1–V.7, decisions D1–D4) and a second pass (W.1–W.6) that fuzzed all three converters, the final XSD check and the fix-XML tool. | **Yes.** Every finding was reproduced by a script before it was fixed. |
| [`CODEBASE_ANALYSIS_3.md`](./CODEBASE_ANALYSIS_3.md) | **Third-pass** review at `5d865e4`. Re-verified the second pass's open Tier 1–2 items (all open then, all fixed since in PR #131) and added new findings: control characters and notes truncation in the core, job-pipeline races and retry budget in the web, worker availability under a stalled Redis, and a red `npm audit` gate. | **Yes.** The newest register — start here. Re-verified at `7b14f3b`: everything is `[FIXED]` except D.7 (signup's 409) and D.9 (one race answer), both `[PARTIAL]`. |
| [`CODEBASE_ANALYSIS_2.md`](./CODEBASE_ANALYSIS_2.md) | **Second-pass** review at `482d235`, after the first register's Tier 1–5 remediation. Same method (every finding verified by execution); does not repeat the first register. Length facets, case-sensitive Yes/No, unaudited fabrications, training race counting, the web boot/consumer failure modes. | **Yes.** Re-verified at `7b14f3b`: Tiers 1–4 are `[FIXED]`; of Tier 5, 5.1 is `[PARTIAL]` (no generic audit-completeness test) and §5.4 lists what is still open from the first pass. |
| [`CODEBASE_ANALYSIS.md`](./CODEBASE_ANALYSIS.md) | First full review of `src/`, `apps/web`, `apps/worker`, tests, CI and deployment, organised into five severity tiers. Every finding was verified by *executing* the code, not by reading it. Most items are now `[FIXED]`; the still-open ones are listed in `CODEBASE_ANALYSIS_2.md` §5.4. | **Yes**, for what it covers. Markers re-verified at `7b14f3b`; each still-open item carries a dated **Still open** line with its current location. |
| [`TECHNICAL_DEBT.md`](./TECHNICAL_DEBT.md) | 19 numbered debt items by priority, each with a fix. | Yes. Re-verified at `7b14f3b`: #5, #16, #18 and #19 are open, the rest `[RESOLVED]`. |
| [`UX_REVIEW.md`](./UX_REVIEW.md) | Severity-ranked audit of every user-facing surface, with inline `[RESOLVED]` markers. Well maintained. | Yes. Re-verified at `7b14f3b`: §6.7 and the §10.3 watch item are open. |
| [`UX_IMPLEMENTATION_PLAN.md`](./UX_IMPLEMENTATION_PLAN.md) | The six-phase plan that sequenced the UX findings into shippable slices. | As a record of what was done. Two deferred follow-ups are open (Sentry wiring, phone-width card tables). |
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

Checked against the code on 2026-10-17 at commit `7b14f3b`, finding by finding,
across every register, plus the code defects the second documentation audit
found on the way. Full detail in
[`../documentation-audit.md`](../documentation-audit.md).

**Correctness**

- Training demographics count **rows, not distinct people**
  (`training_converter.py` — `'total': max(len(rows), 1)`). Now a recorded
  decision ([`XSD_VALIDITY_ANALYSIS.md`](./XSD_VALIDITY_ANALYSIS.md#decisions-not-changed)).
- Training counts "Middle Eastern or North African" under **both**
  `MiddleEastern` and `NorthAfrican` (`classify_races`; third pass D.9).
- Two defaults are filed with no report: a counseling file's `LocationCode`
  `249003` when it has no such column, and a training client's revenue and profit
  of `0` ([`../converters.md`](../converters.md#known-gaps)).

**Architecture**

- The converter abstraction is still inverted: `convert()` is per-subclass and
  the converter map is declared three times (§5.1). Counseling reads 64 of its 74
  headers as literals rather than through `COLUMN_MAPPING` (§5.2).
- Whole files are held in memory end to end (#16), now bounded by the worker's
  four-request concurrency cap.
- Redis has no persistence configured (no volume, no `appendonly`).
- On SIGTERM the web consumer stops claiming but does not drain the job in
  flight, and its two `setInterval`s are never cleared.
- `Job.processedRows` is declared but never written (§5.3).
- `run.py`'s `_pick_xsd` looks for schemas only beside `run.py`, so the
  launcher's validation step is never offered. Less harmful than it was: each
  converter now validates its own file (`BaseConverter._write_valid_xml`).

**Web**

- `results/page.tsx` is 721 lines and re-declares `ValidationIssue` (drifted:
  `severity: string`) and `CleaningDiffEntry` from `types/index.ts`.
- "50MB" is hardcoded in 9 user-facing strings, though `MAX_UPLOAD_BYTES` is
  configurable; `DATA_DIR` is defined 5×; `["queued", "converting"]` 8+×.
- `prisma/schema.prisma` and `scripts/migrate.js` are two sources of truth for
  the DDL, with no test holding them together.
- `GET /api/jobs/:jobId` returns absolute file paths and the full issue and diff
  arrays on every progress poll.
- A body that is not valid multipart is answered 500 (upload) or 502 (the XML
  tools) instead of 400.

**Security**

- Signup's 409 tells a caller an account exists (third pass D.7); hiding it
  needs email verification, which the app has no mail for.
- No CSRF token or Origin check, `trustHost: true`, no JWT `maxAge` (§3.10).
- The web sends no `Authorization` header when `WORKER_AUTH_TOKEN` is empty, with
  no startup check, and worker responses are cast, not validated (§3.11).
- The CSP keeps `script-src 'unsafe-inline'`; a nonce CSP is deferred (§3.3 note).

**Deployment**

- The web image has no `HEALTHCHECK`, and the worker's `/health` answers 200 when
  degraded, so Railway's status-code check proves only liveness.

**Tooling and tests**

- No formatter, no type checker, no ESLint (§5.5). Ruff runs correctness rules
  only, which is deliberate.
- No generic audit-completeness test: only the columns in
  `COUNSELING_FABRICATION_DEFAULTS` are checked for a report (second pass 5.1).

**Dependencies**

- `next-auth` is pre-release: `^5.0.0-beta.30`, locked at `5.0.0-beta.32` (#5).

**Accessibility and UX**

- `<html lang="en">` is static (UX §6.7); Sign Out has no confirmation (§10.3,
  watch); the error boundary has no Sentry wiring; tables only scroll sideways
  at phone width.

**Repository**

- No `LICENSE`, `CODEOWNERS` or `CLAUDE.md`.

## Corrections applied to these registers

The second documentation audit (2026-10-17, `7b14f3b`) re-verified every
not-fixed finding and flipped what had been fixed without its marker moving:

- **`CODEBASE_ANALYSIS.md`** — 1.7's event-level fields, 2.3's `npm ci`, 3.7,
  5.4 and the audit-page part of 5.6 are fixed; 5.1, 5.3, 5.5, 5.6 and 5.7 are
  partial. Its 3.7 link to the third pass had broken when that heading's marker
  flipped.
- **`CODEBASE_ANALYSIS_2.md`** — 5.2 and 5.3 fixed, 5.1 partial; §5.4 now says
  which first-pass items are still open.
- **`CODEBASE_ANALYSIS_3.md`** — §2's "all still open" table is fixed since PR
  #131; the recommended sequence is done.
- **`UX_REVIEW.md`** §9.3 resolved; **`TECHNICAL_DEBT.md`** #12 and #15 carry
  dated corrections to their descriptions.

The first documentation audit (2026-09-16, `d0e71f0`) corrected these:

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
