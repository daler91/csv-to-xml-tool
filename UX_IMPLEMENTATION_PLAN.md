# UX Implementation Plan

This document sequences the findings from `UX_REVIEW.md` into six
executable phases, ordered by impact and dependency. It is the
companion to that review — every item here references a finding in
`UX_REVIEW.md` by its section number (e.g. "§3.5" points to
`UX_REVIEW.md` finding 3.5).

## How to Read This Plan

- **Phases are releasable slices, not sprints.** Each phase is a
  coherent set of changes that can ship as one or more PRs without
  depending on later phases.
- **Findings are referenced by their `UX_REVIEW.md` number.** Don't
  duplicate rationale here — click through to the review.
- **Effort tags (S/M/L)** come from `UX_REVIEW.md`. S = <½ day,
  M = ½–2 days, L = multi-day.
- **No time estimates.** Sequence matters; duration depends on the
  team.
- **Progress tracking** — when a finding is shipped, mark it
  `**[RESOLVED]**` in `UX_REVIEW.md` (same convention as
  `TECHNICAL_DEBT.md`).

## Phase Overview

| # | Phase | Goal | Risk if deferred |
|---|-------|------|------------------|
| 1 | Stop the Bleed | Fix the P0 bug, silent data loss, and the worst a11y gaps. | Users lose data; legal/a11y exposure. |
| 2 | Mobile Usable | Make the app survive a 375px viewport. | Phone users can't triage jobs. |
| 3 | Recoverable Errors & Live Feedback | Toasts, cancel, actionable errors, loading polish. | Flow feels broken on every edge case. |
| 4 | Onboarding & Clarity | Landing, empty states, content fixes, converter-type explanations. | First-time users stall or churn. |
| 5 | Mapping Page Overhaul | Field descriptions, diff view, human audit log. | The step where partners stall most often. |
| 6 | Design System & Shell Polish | Component library, breadcrumbs, help page, typography. | Drift accelerates; every new page is hand-rolled. |

---

## Phase 1 — Stop the Bleed

**Goal:** Ship the smallest possible change that fixes the P0 bug,
closes the silent-data-loss path, and gets the app onto the WCAG 2.1
Level A floor. Everything here is low-effort and should land as one PR
if possible.

### Findings addressed

| ID | Finding | Effort |
|----|---------|--------|
| §3.2 | Re-upload hardcoded two-type label (bug) | S |
| §4.3 | Silent mapping-save failure | S |
| §6.1 | Progress bar lacks ARIA role and values | S |
| §6.2 | Error alerts lack `role="alert"` / `aria-live` | S |
| §5.4 | Progress counters not announced to screen readers | S |
| §6.6 | Table headers lack `scope="col"` | S |

### File changes

- `apps/web/src/app/convert/[jobId]/reupload/page.tsx` — replace the
  hardcoded ternary at L81-86 with a shared `converterTypeLabel()`
  helper that handles all three types. Put the helper in
  `apps/web/src/lib/converter-types.ts` (new file) so it can be
  imported from the upload page too.
- `apps/web/src/app/convert/[jobId]/mapping/page.tsx:47-62` — add
  `error` state, set it on non-2xx and in `catch`, render it above the
  table using the same red-alert pattern as `convert/page.tsx:67-71`.
- `apps/web/src/app/convert/[jobId]/progress/page.tsx:85-92` — wrap
  the progress bar in a `<div role="progressbar" aria-valuenow={…}
  aria-valuemin={0} aria-valuemax={100} aria-label={…}>`. Wrap the
  counters (L94-108) in `<div aria-live="polite" aria-atomic="true">`.
- Every error-alert `<div>` in the app — add `role="alert"`:
  `convert/page.tsx:67-71`, `login/page.tsx:42-46`,
  `signup/page.tsx:60-64`, `reupload/page.tsx:70-74`,
  `preview/page.tsx:53-58`, and the mapping-page alert being added in
  this phase.
- Every `<th>` inside `<thead>` — add `scope="col"`:
  `dashboard/page.tsx:57-64`, `audit/page.tsx:75-82`,
  `preview/page.tsx:113-121`, `mapping/page.tsx:129-138`,
  `results/page.tsx:291-298`, `results/page.tsx:400-408`.

### Dependencies

None. This phase has no blockers and no coordination with the worker
backend.

### Verification

1. **Manual smoke test:** start a counseling conversion, re-upload a
   training-client CSV, confirm the label shows "Training Client (Form
   641)".
2. **Silent data loss:** break the PATCH endpoint (temporarily return
   500), click Save Mapping & Continue, confirm the error alert
   appears and the page does not redirect.
3. **Screen reader spot-check:** VoiceOver or NVDA on the progress
   page; announce should say "Conversion progress, 45%".
4. **Axe automated scan:** run axe DevTools on every page; the
   "ARIA role on progress bar", "ARIA label on alerts", and "scope on
   `<th>`" violations should all be gone.

### Out of scope for this phase

Focus-visible rings (§6.4), color-only status (§6.3), and mobile nav
(§1.1) are deferred to phases 2 and 4.

---

## Phase 2 — Mobile Usable

**Goal:** Make every page survive a 375px viewport without horizontal
overflow or illegible content. External partners check job status from
phones and the current layout breaks on every screen below ~768px.

### Findings addressed

| ID | Finding | Effort |
|----|---------|--------|
| §1.1 | Nav bar does not collapse on mobile | M |
| §3.7 | Results page 4-column summary grid | S |
| §7.1 | `grid-cols-4` on results summary | S |
| §7.2 | `grid-cols-3` on re-upload comparison | S |
| §7.3 | `grid-cols-3` on preview column-status | S |
| §7.4 | Dashboard table shatters on mobile | S |
| §7.5 | Audit table shatters on mobile | S |
| §7.6 | Mapping two-column layout wraps badly | S |
| §7.7 | Data preview has no sticky header | S |
| §6.4 | No visible `:focus-visible` styles | M |
| §8.4 | Gray-400 text fails contrast | S |

### File changes

**Responsive grids (trivial one-line fixes):**
- `results/page.tsx:126` → `grid-cols-2 md:grid-cols-4`.
- `results/page.tsx:144` → `grid-cols-1 sm:grid-cols-3`.
- `preview/page.tsx:72` → `grid-cols-1 sm:grid-cols-3`.
- `progress/page.tsx:95` → leave `grid-cols-3` (3 cards are narrow
  enough at 375px).

**Table overflow wrappers:**
- `dashboard/page.tsx:53` — wrap `<table>` in `<div className="overflow-x-auto">`.
- `audit/page.tsx:72` — same.
- `preview/page.tsx:111` — already wrapped, but add sticky header:
  `<thead className="sticky top-0 bg-gray-50">`.

**Mapping page vertical stack on mobile:**
- `mapping/page.tsx:177` — change `flex items-center gap-2` to
  `flex flex-col sm:flex-row sm:items-center gap-2`.

**Nav hamburger (§1.1):**
- `apps/web/src/components/nav.tsx` — split the current single-row
  nav into two states:
  - Desktop (`md:flex`): current layout.
  - Mobile (`md:hidden`): wordmark + hamburger button. Clicking the
    button opens a vertical dropdown sheet with the three links, the
    user's email, and Sign Out.
- New small state hook `useState(false)` for open/closed. No new
  dependencies needed; reuse Tailwind classes.
- Close the sheet on route change — wire the existing `usePathname`
  effect.

**Focus rings (§6.4):**
- Add to `globals.css` (below the `@import`):
  ```css
  @layer base {
    *:focus-visible {
      @apply outline-2 outline-offset-2 outline-blue-500;
    }
  }
  ```
- Remove ad-hoc focus overrides if any creep in later.

**Contrast fixes (§8.4):**
- Find/replace `text-gray-400` → `text-gray-600` app-wide, except
  inside intentional placeholder contexts (e.g. `text-gray-400` on
  the preview row number column at `preview/page.tsx:126` is OK
  because it sits on gray-50).
- Specific hits: `convert/page.tsx:145`, `preview/page.tsx:115`.

### Dependencies

None. Pair-review with a designer if one is available; otherwise this
is all mechanical.

### Verification

1. **Chrome DevTools device emulator:** walk the entire flow at 375px
   (iPhone SE), 390px (iPhone 12), 768px (iPad), and 1024px (desktop).
2. **No horizontal overflow at 375px:** dashboard, audit, preview,
   mapping, progress, results, all auth pages.
3. **Keyboard tab through every interactive element** and confirm a
   visible focus ring on each.
4. **axe contrast pass:** no `text-gray-400 on white` violations.
5. **VoiceOver rotor check:** mobile nav dropdown is reachable and
   closes on route change.

### Out of scope

Collapsing table columns into card layouts on the smallest screens
(§7.4 stretch goal) is deferred to Phase 6.

---

## Phase 3 — Recoverable Errors & Live Feedback

**Goal:** Give every user action a clear success signal, make every
error recoverable, and kill all dead-end states. This is the phase
that turns "feels broken" into "feels solid".

### Findings addressed

| ID | Finding | Effort |
|----|---------|--------|
| §3.6 | Progress page has no cancel and a dead-end timeout | M |
| §3.9 | No success toasts anywhere | M |
| §5.1 | No toast / notification system | M |
| §5.2 | Loading buttons reuse copy, no spinner, no `aria-busy` | S |
| §5.3 | No skeleton loaders on data pages | M |
| §4.1 | Upload errors are generic | S |
| §4.2 | Preview/Convert error states are dead ends | S |
| §4.4 | Error boundary strands the user | S |
| §4.5 | Progress page silently swallows poll errors | S |

### File changes

**Toast system (prerequisite for everything else in this phase):**
- Add a minimal toast primitive. Two options:
  1. Use `sonner` (4kB, already React-friendly). Pros: shipped,
     a11y-correct. Cons: one more dep.
  2. Hand-roll: `apps/web/src/components/toast.tsx` with a
     `ToastProvider` exposing `showToast({variant, message})` via
     React context + a portaled viewport in `layout.tsx`.
- Recommendation: hand-roll. The app already avoids heavy deps and
  the primitive is ~80 lines including `role="status"` /
  `role="alert"` handling.
- Mount the viewport in `apps/web/src/app/layout.tsx` inside
  `<Providers>`.
- Fire toasts on success:
  - `login/page.tsx:29` — "Signed in"
  - `signup/page.tsx:47` — "Account created"
  - `convert/page.tsx:54` — "File uploaded — preview loading"
  - `mapping/page.tsx:58` — "Mapping saved"
  - `reupload/page.tsx:47` — "Re-upload received"
  - `results/page.tsx` — on initial load when `status === "complete"`
    and the session is fresh, fire "Conversion complete".

**Specific upload error messages (§4.1):**
- `convert/page.tsx:47-56` — switch on `res.status`:
  ```ts
  if (res.status === 413) setError("This file is larger than 50MB…");
  else if (res.status === 429) setError("You've uploaded a lot…");
  else if (res.status === 401 || res.status === 403) setError("Your session expired. Sign in again.");
  else setError(data.error || "Upload failed.");
  ```
- Same treatment on `reupload/page.tsx:44-50`.

**Preview / mapping error cards (§4.2):**
- `preview/page.tsx:53-59` — replace the bare `<p>` with a card that
  renders the error + a Retry button that re-runs `loadPreview()`.
- `mapping/page.tsx` — same pattern on load failure.
- Add "Back to upload" link on each.

**Progress cancel + timeout recovery (§3.6):**
- Requires a new worker endpoint. Coordinate with backend before
  this phase starts. New route:
  `apps/web/src/app/api/jobs/[jobId]/cancel/route.ts` → proxies to
  worker `POST /jobs/{id}/cancel`. Worker owns the actual cancel
  mechanics (which this plan does not specify).
- `progress/page.tsx:69-108` — add:
  - "Cancel conversion" button visible when `status === "converting"`.
  - On timeout: render "Check status", "Go to dashboard", "Report a
    problem" buttons instead of a dead headline.
  - Track consecutive poll failures (§4.5); after 3 failures show an
    inline banner with Retry / Dashboard buttons.
  - ETA estimation: once `processedRows > 10` and `totalRows > 0`,
    compute `rate = processedRows / elapsedSeconds` and display
    `Math.round((totalRows - processedRows) / rate)` seconds
    remaining.

**Button spinners & `aria-busy` (§5.2):**
- Add a small `<Spinner />` component (inline SVG with
  `animate-spin`).
- Update every submit button that currently flips its text on
  loading to also render the spinner + `aria-busy={loading}`:
  `login/page.tsx:74-80`, `signup/page.tsx:105-111`,
  `convert/page.tsx:153-159`, `mapping/page.tsx:225-231`,
  `reupload/page.tsx:102-108`, `preview/page.tsx:148-154`.

**Skeleton loaders (§5.3):**
- New component `apps/web/src/components/skeleton.tsx` exporting
  `<Skeleton />` (a single gray div with `animate-pulse`) and
  `<SkeletonTable rows={5} columns={...}/>`.
- Replace "Loading…" text with matching skeletons at:
  - `preview/page.tsx:45-51`
  - `mapping/page.tsx:64-70`
  - `audit/page.tsx:84-89`
  - `convert/page.tsx:169-172` (Suspense fallback)
  - `reupload/page.tsx:54-60`

**Error boundary improvements (§4.4):**
- `components/error-boundary.tsx:28-46`:
  - Add `role="alert"`.
  - Add "Go to dashboard" link alongside "Try again".
  - In dev (`process.env.NODE_ENV !== "production"`) show the error
    message and stack.
  - TODO comment: wire Sentry once enabled.

### Dependencies

- **Worker cancel endpoint** (§3.6). If the worker can't support
  mid-conversion cancel, the UI shipping in this phase should still
  include the button but grey it out with a tooltip ("Cancel is not
  yet supported by the worker"). Don't block the rest of the phase.
- Toast component must land before the success-toast changes.

### Verification

1. **Happy path smoke test:** sign in → upload → preview → map →
   convert → download → re-upload. Every successful action should
   flash a toast. No page should feel silent.
2. **Error injection:** temporarily make `/api/upload` return 413,
   429, 401, 500. Confirm the error message changes per status code
   and is announced by screen reader (`role="alert"`).
3. **Cancel test:** start a conversion, click Cancel, confirm the
   progress page transitions to "Cancelled" and returns to the
   dashboard with a toast.
4. **Timeout test:** set `MAX_WAIT_MS` to 5s locally, start a job,
   confirm the 3-button recovery UI appears.
5. **Skeleton visual check:** throttle the network to Slow 3G and
   confirm skeletons render on every data page instead of raw
   "Loading…" text.

### Out of scope

- Error-boundary Sentry wiring. TODO comment only; the actual Sentry
  setup is a separate infra ticket.
- Toast queue / dismissal animations — ship the simplest possible
  version first.

---

## Phase 4 — Onboarding & Clarity

**Goal:** A first-time partner with no XML knowledge can land on the
app, understand what it does, pick the right converter type, upload a
file, and know what will happen to their data — all without reading
source code.

### Findings addressed

| ID | Finding | Effort |
|----|---------|--------|
| §2.1 | Landing page doesn't explain what to bring | M |
| §2.2 | Dashboard empty state is passive | M |
| §2.3 | README silent on the web app | S |
| §2.4 | Signup password rules not shown | S |
| §3.1 | Converter types overlap and aren't explained | S |
| §3.3 | Upload does not validate client-side | S |
| §3.4 | Preview "Extra" column treated as a problem | S |
| §6.3 | Status conveyed by color alone | M |
| §6.5 | Dropzone uses `role="button"` on `<div>` | S |
| §9.1 | Inconsistent status vocabulary | S |
| §9.3 | Upload limit text hidden in gray-400 | S |
| §9.4 | Converter-type labels don't match what users know | S |
| §9.5 | "Skip" on mapping is ambiguous | S |
| §10.1 | No data-handling disclosure on upload | S |
| §10.2 | No "previous job is kept" cue on re-upload | S |

### File changes

**Converter-type metadata module (shared by §3.1, §9.4, §3.2):**
- Extend `apps/web/src/lib/converter-types.ts` (created in Phase 1) to
  export:
  ```ts
  export const CONVERTER_TYPES = [
    { value: "counseling", label: "Counseling (Form 641)", description: "Individual client counseling sessions.", sample: "Sample641CouselingRecord-2-14.xml" },
    { value: "training", label: "Training (Form 888)", description: "Aggregated training event data.", sample: "Sample_Training_888-2-26-2025.xml" },
    { value: "training-client", label: "Training Client (Form 641)", description: "Per-attendee rows from a training event.", sample: "Sample641CouselingRecord-2-14.xml" },
  ] as const;
  ```
- Import into `convert/page.tsx`, `reupload/page.tsx`,
  `dashboard/page.tsx`, and the new landing page.

**Landing page rebuild (§2.1):**
- `apps/web/src/app/page.tsx` — expand to three sections:
  - Hero: H1 + one-line pitch + Sign In / Create Account CTAs.
  - "What this converts": three converter-type cards, each with
    label, description, and a "Download sample" link pointing at the
    sample XML in the repo (served as a static asset).
  - "How it works": 4-step diagram (Upload → Preview → Map →
    Download).
- Copy the two sample XML files into `apps/web/public/samples/` as
  part of the PR.

**Dashboard empty state (§2.2):**
- `dashboard/page.tsx:44-50` — replace the two-line text with:
  - Big "Start a new conversion" button (primary).
  - 3-step visual of the flow.
  - "Download a sample CSV" link (point to a new
    `apps/web/public/samples/counseling-sample.csv` — this plan
    assumes one can be produced from the existing sample XML).

**Converter-type cards (§3.1):**
- `convert/page.tsx:78-109` — replace the flat radio row with a
  grid of radio cards generated from `CONVERTER_TYPES`. Each card
  shows label, description, and a "see sample" link. Keep the
  underlying `<input type="radio">` for form semantics.

**Client-side upload validation (§3.3):**
- `convert/page.tsx:118-132` — change `dropped?.name.endsWith(".csv")`
  to a case-insensitive check (`.toLowerCase().endsWith(".csv")`).
- Add a `MAX_FILE_BYTES = 50 * 1024 * 1024` constant; reject
  oversized files client-side with an inline error before hitting
  `/api/upload`.
- When a drop is rejected, fire a toast (from Phase 3): "That file
  isn't a CSV up to 50MB."

**Dropzone label refactor (§6.5):**
- `convert/page.tsx:112-150` — prefer a real `<label
  htmlFor="file-input">` wrapping the dropzone `<div>`. Remove
  `role="button"` and the manual keyboard handler; the label will
  activate the hidden input on click and keyboard. Add
  `aria-describedby="file-help"` pointing at the help `<p>`.

**Signup password rules (§2.4):**
- `signup/page.tsx:91-103` — add a rules list below the password
  input. Track password value in state and mark each rule (≥8
  chars, uppercase, digit, special char) with a check/cross as the
  user types. Backend rules already enforced — the frontend just
  mirrors them.

**Preview "Extra" column (§3.4):**
- `preview/page.tsx:83-88` — change styling from yellow-50 warning
  to gray-50 neutral, and add a one-liner: "Extra columns will be
  ignored. This is fine."

**Data-handling disclosure (§10.1):**
- `convert/page.tsx:145-147` — below the dropzone add a paragraph:
  > "Your CSV is stored in your account and is visible only to
  > you. Files are retained for 30 days. Data is processed on SBA
  > infrastructure; nothing is sent to third-party services."
- The exact retention number is a product decision (see Open
  Question §C.2 in `UX_REVIEW.md`). Before merging, confirm the
  retention policy or replace the number with "per SBA policy".

**Re-upload "previous kept" cue (§10.2):**
- `reupload/page.tsx:63-68` — expand the subtitle to "Your previous
  conversion will be kept as a separate job. Compare the two on
  the next screen."

**Status vocabulary (§9.1):**
- `dashboard/page.tsx:141-160` — change the `colors` map to return
  both color and label:
  ```ts
  const STATUS = {
    uploaded: { color: "bg-gray-100 text-gray-700", label: "Uploaded" },
    previewed: { color: "bg-blue-100 text-blue-700", label: "Ready to convert" },
    mapping: { color: "bg-yellow-100 text-yellow-700", label: "Needs mapping" },
    converting: { color: "bg-blue-100 text-blue-700", label: "Converting…" },
    complete: { color: "bg-green-100 text-green-700", label: "Complete" },
    error: { color: "bg-red-100 text-red-700", label: "Failed" },
  };
  ```
- Render `label` in the badge, keep the raw `status` as a
  `data-status` attribute for tests.

**Color-only status (§6.3):**
- Add a small icon set (inline SVG: check, warning triangle, x,
  info). Prefix every color-coded status surface with the icon:
  - `StatusBadge` on dashboard (above).
  - Summary cards on results (`results/page.tsx:124-139`).
  - Column-status cards on preview (`preview/page.tsx:72-88`).
  - Cleaning diff rows — prefix Original with `−` and Cleaned with
    `+` (`results/page.tsx:416-421`).
  - Mapping requirement badges (`mapping/page.tsx:154-173`) —
    already have text ("Required" / "Conditional" / "Optional") so
    this is color-redundant; just add icons for quick scanning.

**"Skip" → "Cancel" (§9.5):**
- `mapping/page.tsx:232-237` — rename "Skip" to "Cancel". Track
  dirty state (any mapping change since load); if dirty, confirm
  via `window.confirm("Discard unsaved mapping changes?")` before
  navigating away.

**Upload limit text (§9.3):**
- `convert/page.tsx:145-147` — move this text out of the dropzone
  `<div>` and under the "CSV File" label, with
  `text-sm text-gray-600`.

**README web-app section (§2.3):**
- `README.md` — add a new top section "Web app (recommended)" with:
  - One paragraph on what it does.
  - A screenshot (to be captured as part of this PR).
  - `docker compose up` instructions (pointing at the existing
    `docker-compose.yml`).
  - A link to `UX_REVIEW.md` and `UX_IMPLEMENTATION_PLAN.md` for
    contributors.
- Keep the current CLI section below.

### Dependencies

- **Product decision on retention copy** (§10.1). Do not ship the
  "30 days" number without confirmation.
- **Sample CSV files** — create them from the existing sample XML or
  export from Salesforce. Before merging, ensure samples do not
  contain real client data.
- Toast system from Phase 3 is required for the file-rejection UX
  in §3.3. If Phase 3 slips, use an inline alert instead.

### Verification

1. **First-time-user walkthrough:** have someone who has never used
   the tool land on the homepage and reach a successful conversion
   using only the sample CSV. Time it, note confusions.
2. **Converter-type labels:** confirm every page that shows a
   converter type pulls from `CONVERTER_TYPES` (search for hardcoded
   "Form 641", "Form 888" strings; there should be none outside the
   new module).
3. **Password rules:** confirm every backend rule is mirrored in the
   UI checklist. Mismatch = bug.
4. **Drop a `.CSV` (uppercase):** confirms the case-insensitive fix.
5. **Drop a 100MB file:** should be rejected client-side without a
   network request.
6. **Screen reader:** converter type cards and dropzone label
   announce correctly with VoiceOver.
7. **Lighthouse a11y:** target score ≥ 90 on every page.

### Out of scope

- Actual SBA brand compliance — visual design (§8.1, §8.3) is
  deferred to Phase 6.
- Localization — landing page copy is English-only for now.

---

## Phase 5 — Mapping Page Overhaul

**Goal:** Turn the mapping page from a jargon wall into a guided
screen. This is where most partners stall today. The phase also
finishes the re-upload comparison feature.

### Findings addressed

| ID | Finding | Effort |
|----|---------|--------|
| §3.5 | Raw XML field names with no descriptions | L |
| §3.8 | Re-upload comparison is counts-only | M |
| §9.2 | Audit details cell dumps raw JSON | M |

### File changes

**Field metadata surfacing (§3.5):**

This is the only phase that requires coordinated backend changes.

- `src/config.py` — extend the existing `CounselingConfig` /
  `TrainingConfig` field maps with a `description` and optional
  `conditional_rule` per field. Where descriptions don't exist, write
  them; this is a content task as much as a code one.
- `apps/worker` (worker API) — update the preview response shape to
  include `field_descriptions: Record<string, { description: string,
  conditional_rule?: string }>` alongside the existing
  `field_requirements`.
- `apps/web/src/types/index.ts` — extend `PreviewResponse` to match.
- `apps/web/src/app/convert/[jobId]/mapping/page.tsx:149-175` —
  render the description under the monospace field name in
  `text-xs text-gray-600`. For conditional fields, render
  `conditional_rule` in the badge tooltip (`title` attribute) and
  below the description.
- `apps/web/src/app/convert/[jobId]/preview/page.tsx` — the preview
  page's column-status cards can stay counts-only, but the "missing"
  list when expanded should also show descriptions.

**Re-upload comparison drilldown (§3.8):**
- `apps/web/src/app/convert/[jobId]/results/page.tsx:142-164` —
  convert the three comparison cards into a tabbed view (or
  collapsible `<details>`). Each tab renders a filtered `IssueTable`:
  - Resolved — styled green.
  - New — styled red.
  - Persistent — styled yellow.
- The `computeComparison` helper at L234-249 already returns the
  three filtered arrays; feed them into `IssueTable` directly.
- Default tab: "New" (the issues the user most likely cares about).

**Audit details cell (§9.2):**
- `audit/page.tsx:115-117` — replace
  `JSON.stringify(entry.metadata)` with an action-aware renderer. Add
  a helper `formatAuditMetadata(action, metadata)` that returns a
  short human-readable summary per action type:
  - `upload` → `"{fileName} ({size})"`
  - `conversion_started` → `"{totalRows} rows"`
  - `conversion_complete` → `"{successful}/{total} successful, {errors} errors"`
  - `conversion_failed` → `"{error message}"`
  - `download` → `"-"`
- For completeness, add a "View raw" toggle that expands the row and
  pretty-prints the JSON. Use `<details>`/`<summary>` — no extra JS.

### Dependencies

- **Worker API change** is the critical path. This phase cannot
  start until the worker team agrees on the preview-response shape.
- **Content writing** — someone needs to write plain-language field
  descriptions for ~80 SBA fields. This is the slowest part of the
  phase and can start in parallel with the backend plumbing.

### Verification

1. **Mapping page walkthrough:** every field should show a
   description; no field should appear with monospace-only.
2. **Conditional fields:** hover a conditional badge, confirm the
   rule text appears; confirm the description below also shows it.
3. **Re-upload drilldown:** intentionally fix one issue and add
   another, upload as a re-upload, confirm the Resolved / New /
   Persistent tabs each list the correct rows.
4. **Audit page:** every action type renders a readable summary; the
   "View raw" toggle shows the full JSON.

### Out of scope

- Auto-suggest improvements on the mapping page (beyond what
  already exists).
- Persistent column mappings across jobs (a future feature — users
  re-map the same columns on every upload today).

---

## Phase 6 — Design System & Shell Polish

**Goal:** Stop the drift. Every new page in phases 1-5 currently
hand-rolls its own button/alert/card utility-class combo; this phase
extracts the shared primitives and finishes the navigational polish.

### Findings addressed

| ID | Finding | Effort |
|----|---------|--------|
| §1.2 | No breadcrumb / step indicator in convert flow | M |
| §1.3 | No global Help / Docs entry point | S + L |
| §4.4 | Error boundary — Sentry wiring (follow-up) | S |
| §8.1 | No design tokens; utility classes repeat | L |
| §8.2 | `StatusBadge` duplicated on dashboard only | S |
| §8.3 | Homepage typography unbalanced | S |
| §8.5 | Inconsistent alert styling | S |
| §10.3 | Dirty-state tracking on Sign Out (watch) | — |

### File changes

**Component library extraction (§8.1):**

Create `apps/web/src/components/ui/` with:

- `button.tsx` — `<Button variant="primary|secondary|destructive"
  size="sm|md" isLoading={...}>`.
- `alert.tsx` — `<Alert variant="error|warning|info|success"
  title?={...}>` with `role="alert"` built in.
- `card.tsx` — `<Card>` with standard border/padding/bg.
- `summary-card.tsx` — `<SummaryCard label value color>` (already
  exists locally at `results/page.tsx:251-274`; extract and reuse
  on dashboard and audit).
- `status-badge.tsx` — move from `dashboard/page.tsx:141-160`;
  consume the `STATUS` map added in Phase 4.
- `skeleton.tsx` — the Phase 3 skeleton, now under `ui/`.
- `spinner.tsx` — the Phase 3 spinner, now under `ui/`.
- `icon.tsx` — `<Icon name="check|warning|x|info|…" />` (the Phase 4
  icons).

Then **convert existing pages to use the library**. This is a
large mechanical refactor and should land as its own PR. Estimated
touch points:

- All 10 pages in the conversion flow + auth + dashboard + audit.
- ~30 button sites, ~10 alert sites, ~15 card sites.

Set up a lint rule (eslint-plugin-tailwindcss or a custom
`no-raw-button-classes` rule) to prevent regression if possible.

**Breadcrumb / step indicator (§1.2):**
- New component `apps/web/src/components/ui/step-indicator.tsx`
  rendering a 5-step progress strip: Upload → Preview → Map →
  Convert → Results.
- Mount it at the top of every page under `/convert/[jobId]/…` via
  a new `apps/web/src/app/convert/[jobId]/layout.tsx`. The layout
  reads the pathname and lights up the current step.
- Each step is a link (back-navigation only — users can't jump
  forward past the current step).

**Help page (§1.3):**
- New route: `apps/web/src/app/help/page.tsx`. Content sections:
  - What does this tool do?
  - Supported CSV formats and the three converter types (link to
    sample files).
  - Reading the preview and column-mapping pages.
  - Reading the results page (what do the summary cards mean).
  - Common errors and how to fix them.
  - Contact / support info.
- Add "Help" link to `nav.tsx:13-17`.
- Add a contextual "?" help button in the page header of the
  mapping and results pages that links directly to the relevant
  help section.

**Error boundary Sentry hookup (§4.4 follow-up):**
- Once the Sentry MCP integration in the repo is live, add
  `Sentry.captureException(error, { extra: info })` in
  `error-boundary.tsx:24-26`.
- Add a "Report this error" button to the fallback that opens a
  Sentry user-feedback dialog.

**Homepage typography (§8.3):**
- After §2.1 rebuilds the homepage, adjust H1/body/button
  proportions. With the new component library, the fix is
  replacing `text-sm` buttons with `<Button size="md">`.

**Alert consolidation (§8.5):**
- Falls out of §8.1 automatically. Every hand-rolled red/blue/green
  alert becomes `<Alert variant="…">`.

**StatusBadge move (§8.2):**
- Falls out of §8.1 automatically.

### Dependencies

- **§8.1 (component library)** should land before the other items
  in this phase so they can be implemented using the new
  components instead of utility classes.
- **Sentry infra** needs to exist before §4.4 follow-up can ship.

### Verification

1. **Search for raw button classes:** `grep -r "bg-blue-600 text-white"
   apps/web/src/app` should return zero hits outside `components/ui/`.
2. **Visual diff:** before/after screenshots of every page to confirm
   the refactor didn't change layouts.
3. **Step indicator:** click through the convert flow and confirm the
   indicator highlights the correct step on each page.
4. **Help page:** every H2 in the page has an `id` so contextual "?"
   buttons can deep-link.
5. **Lint rule:** intentionally add a raw `bg-blue-600 text-white`
   class in a PR and confirm CI fails.

### Out of scope

- SBA brand adoption (logo, brand colors, font family). Requires a
  product/design decision.
- Dark mode.
- Animation polish beyond the existing Tailwind `transition-*`
  utilities.

---

## Cross-Phase Dependencies

```
Phase 1 ──────────────────────────────────────────┐
   │                                              │
   ├──> Phase 2 ──────────────────────────────┐   │
   │       (independent of 3)                 │   │
   │                                          │   │
   ├──> Phase 3 ──────────────────────────┐   │   │
   │       (toast system required by 4)   │   │   │
   │                                      │   │   │
   └──> Phase 4 <─ requires toast from 3 ─┘   │   │
           │                                  │   │
           └──> Phase 5 <─ worker API  ───────┘   │
                  │                               │
                  └──> Phase 6 <─ component lib ──┘
```

**Key dependencies:**

- **Phase 1 → everything.** The shared `converter-types.ts` module
  created in Phase 1 is imported by Phases 3, 4, 5.
- **Phase 3 → Phase 4.** The toast system from Phase 3 is used in
  Phase 4 for file-rejection UX. If Phase 3 slips, Phase 4 can fall
  back to inline alerts.
- **Phase 4 + Phase 5.** The `STATUS` vocabulary map from Phase 4
  (§9.1) is consumed by the `<StatusBadge>` extraction in Phase 6.
- **Phase 5 needs worker coordination.** The field-description API
  change is the critical path; start that conversation at the
  beginning of Phase 3 so it's ready when Phase 5 starts.
- **Phase 6 is mostly independent.** It can start in parallel with
  Phase 5 if two people are available — one writes content, the
  other extracts components.

## What This Plan Does NOT Cover

- **Feature additions.** No new features; only fixes and polish
  for what's already built.
- **Backend refactoring** beyond the single preview-response shape
  change in Phase 5.
- **SBA brand compliance** — requires a product/design decision.
- **Analytics / telemetry** — not a UX finding, tracked elsewhere.
- **Performance optimization** — not a UX finding.
- **Python CLI UX.** The `run.py` launcher is out of scope per the
  decision in `UX_REVIEW.md` Scope & Method.
- **`next-auth@5.0.0-beta.30` upgrade** (`TECHNICAL_DEBT.md` §5) —
  tracked in the tech debt register.

## Tracking Progress

1. **Per-finding tracking:** as each finding ships, mark it
   `**[RESOLVED]**` in `UX_REVIEW.md` — same convention as
   `TECHNICAL_DEBT.md`. Don't delete the finding; the resolved
   record is useful history.
2. **Per-phase tracking:** at the end of each phase, link the
   merged PRs at the top of the phase section in this file.
3. **Retro after Phase 3:** Phase 3 is the most user-visible slice.
   After it ships, do a mini-retro with a real partner to validate
   the assumptions in this plan before committing to Phase 4.
4. **Re-run this audit after Phase 6.** Six months after Phase 6
   ships, redo the UX review. Drift is the enemy of a design
   system.

## Open Questions

These are blockers that need product-owner answers before the
affected phase can start. They mirror the open questions at the end
of `UX_REVIEW.md`.

1. **Retention policy** (blocks Phase 4, §10.1). What is the actual
   retention for uploaded CSVs?
2. **Worker cancel support** (blocks Phase 3, §3.6). Can the worker
   accept a mid-conversion cancel request? If not, how does the UI
   express "please stop"?
3. **Converter type renaming** (blocks Phase 4, §3.1/§9.4). Are the
   current labels canonical, or can they be renamed for clarity?
4. **Field descriptions** (blocks Phase 5, §3.5). Do plain-language
   descriptions exist anywhere today, or does this phase include
   the content-writing work?
5. **SBA design system** (affects Phase 6, §8.1). Is there an
   existing SBA brand library the web app should adopt?
6. **Sample CSV files** (blocks Phase 4, §2.1/§2.2). Can sanitized
   sample CSVs be produced for the landing page and empty state,
   or does this plan need to generate them from the sample XML?
