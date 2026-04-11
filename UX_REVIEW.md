# UX Review

This document is a severity-ranked audit of the user-facing surfaces of the
CSV-to-XML tool's web application (`apps/web`), produced as a one-time UX
architecture review. It is a companion to `TECHNICAL_DEBT.md` and follows the
same numbered, resolvable-item format — items can be marked **[RESOLVED]** as
they are fixed.

The audit was conducted against the code in this commit. No runtime testing
with a screen reader, Lighthouse, or real mobile device was performed; the
review flags where those tools should be run next.

---

## Executive Summary

1. **The web app has no written orientation.** The landing page, the
   dashboard empty state, and `README.md` all fail to explain what the user
   needs to bring (a CSV in what shape), what the three converter types
   actually do, or where sample files live. External partners arrive
   without a map.
2. **Accessibility is below WCAG 2.1 AA on every page.** The progress bar,
   error alerts, status badges, and summary cards convey state by color
   alone, lack ARIA roles/live regions, and the app ships no visible
   `:focus-visible` styles.
3. **The conversion flow has no escape hatches.** Users cannot cancel a
   running conversion, the 5-minute timeout is a dead end, upload errors
   are generic, and there are no success toasts — on a flaky connection
   the app feels broken even when it succeeds.
4. **Mobile is broken.** Fixed `grid-cols-4` cards, a 7-column dashboard
   table, and an inline desktop-only nav bar make the app unusable below
   ~768px — a real problem for partners who check jobs from a phone.
5. **Column mapping surfaces raw XML field names** (`BranchOfService`,
   `SmallDisadvantagedConcernInd`) to non-technical partners with no
   explanation of what the field means or when a "Conditional" field is
   required. This is where the flow will stall most often.

See the **Prioritized Recommendations** punch list at the end for the top
10 items to ship first.

---

## Scope & Method

### Surfaces Audited

Every user-facing file in the Next.js web app was read end-to-end:

**Landing & auth**
- `apps/web/src/app/page.tsx` — homepage (L1–28)
- `apps/web/src/app/login/page.tsx` — sign-in form (L1–92)
- `apps/web/src/app/signup/page.tsx` — sign-up form (L1–123)

**Shell**
- `apps/web/src/app/layout.tsx` — root layout + metadata (L1–27)
- `apps/web/src/components/nav.tsx` — header nav (L1–57)
- `apps/web/src/components/error-boundary.tsx` — client error fallback (L1–51)
- `apps/web/src/app/globals.css` — Tailwind entry

**Dashboard & history**
- `apps/web/src/app/dashboard/page.tsx` — job list (L1–160)
- `apps/web/src/app/audit/page.tsx` — audit trail (L1–149)

**Conversion flow**
- `apps/web/src/app/convert/page.tsx` — upload (L1–177)
- `apps/web/src/app/convert/[jobId]/preview/page.tsx` — CSV preview (L1–164)
- `apps/web/src/app/convert/[jobId]/mapping/page.tsx` — column mapping (L1–241)
- `apps/web/src/app/convert/[jobId]/progress/page.tsx` — live progress (L1–112)
- `apps/web/src/app/convert/[jobId]/results/page.tsx` — results + diff (L1–443)
- `apps/web/src/app/convert/[jobId]/reupload/page.tsx` — re-upload (L1–120)

**Supporting docs reviewed for cross-surface consistency**
- `README.md` — still describes only the Python CLI
- `TECHNICAL_DEBT.md` — used as the tone/format template for this file

### Persona Assumptions

Per a product-owner scope decision, the primary audience is **external
partners** — SCORE counselors, SBDC staff, and resource partners with
mixed technical skill levels. The review applies four lenses:

1. **Clarity** — a first-time user without XML/XSD knowledge should
   understand what to do next.
2. **Guidance** — the system should volunteer the information the user
   needs, not hide it behind jargon or separate docs.
3. **Forgiveness** — errors should be recoverable, not dead-ends, and
   every destructive or irreversible moment should be labeled.
4. **Mobile support** — partners triage jobs from phones between
   appointments; tables and forms must survive a 375px viewport.

### What Was NOT Reviewed

- Pixel-level visual polish (spacing, rhythm, color palette refinement).
- Copywriting beyond clarity fixes.
- The backend error taxonomy (what the worker returns from `/api/upload`
  is treated as out-of-scope upstream input).
- The Python CLI's UX — it's referenced once as an internal consistency
  benchmark but is not the primary surface for external partners.
- Load/perf testing, real-device testing, and screen-reader walkthroughs —
  the review notes where those should be run.

---

## Severity Legend

- **P0 Blocker** — breaks task completion, violates WCAG 2.1 Level A,
  or loses user data/work. Must fix before the next external rollout.
- **P1 High** — significant friction, WCAG 2.1 Level AA violation, or
  mobile breakage. Fix in the next sprint.
- **P2 Medium** — clarity, polish, missing affordances, or minor a11y
  gaps. Fix opportunistically.
- **P3 Low** — aesthetic, copy, or consistency nits.

Each finding uses this template:

> **Where:** `path:L##-L##`
> **What the user sees:** …
> **Why it hurts:** …
> **Recommendation:** …
> **Effort:** S / M / L

---

## 1. Information Architecture & Navigation

### 1.1 Nav bar does not collapse on mobile **[P1]** **[RESOLVED]**

**Where:** `apps/web/src/components/nav.tsx:19-54`

**What the user sees:** A single-row nav with the "SBA Converter" wordmark,
three primary links (Dashboard, Convert, Audit Trail), the user's email
address (truncated at `max-w-48`), and a Sign Out button — all pinned to a
`h-14` row inside a `max-w-6xl` container. There is no hamburger or
responsive breakpoint handling.

**Why it hurts:** At 375px viewports the email column collides with the
nav links, the "SBA Converter" wordmark is pushed off-screen, or the whole
row wraps to two lines — depending on the user's email length. Partners
checking job status from a phone can't reliably reach Convert or Audit.

**Recommendation:** Hide the three primary links and the email on
`md:hidden`, and replace them with a hamburger button that opens a sheet
or dropdown. Keep the wordmark and Sign Out visible at all sizes. Consider
moving Sign Out and email into an avatar menu to free horizontal space.

**Effort:** M

---

### 1.2 "Convert" nav link loses active state after `/convert/[jobId]/…` steps **[P3]**

**Where:** `apps/web/src/components/nav.tsx:27` —
`pathname === href || pathname.startsWith(href + "/")`

**What the user sees:** The active-link styling (blue-600) works on
`/convert` but also lights up on every `/convert/*` sub-route. That's the
intended behavior for `/convert`, but the dashboard link does the same
prefix match so visiting `/dashboard?page=2` keeps it active (OK), while
landing on `/convert/abc/results` keeps "Convert" highlighted when the
user is really in a results view. There is no breadcrumb or step
indicator to tell them where they are in the 5-step flow.

**Why it hurts:** Users lose their place during multi-step conversions
and can't easily back out to a safe surface.

**Recommendation:** Add a breadcrumb or step indicator to every page
under `/convert/[jobId]/…` (Upload → Preview → Map → Convert → Results).
The Nav's active-link logic can stay.

**Effort:** M

---

### 1.3 No global "Help" or "Docs" entry point **[P2]**

**Where:** `apps/web/src/components/nav.tsx:13-17` — link array

**What the user sees:** The nav has Dashboard / Convert / Audit Trail.
There is no Help, Support, Docs, or "What's this?" link anywhere in the
shell.

**Why it hurts:** Partners with questions have nowhere to go inside the
app. `README.md` documents only the Python CLI, so even users who find
the repo get no answers about the web flow.

**Recommendation:** Add a "Help" link to the nav that opens a simple
`/help` page (or an external doc) covering: what CSVs are supported, the
three converter types, how to read the results page, and who to contact.
Until the web app has its own docs, the link can point to a section in
`README.md`.

**Effort:** S (link) + L (content)

---

## 2. Onboarding & First-Run Experience

### 2.1 Landing page doesn't explain what to bring **[P1]**

**Where:** `apps/web/src/app/page.tsx:1-28`

**What the user sees:** One H1, one sentence of description, and two
buttons (Sign In / Create Account). Nothing tells the user what a valid
CSV looks like, what Form 641 vs Form 888 is, or that sample files
exist.

**Why it hurts:** A partner sent a link to this tool has no way to
evaluate whether it fits their data without creating an account first.
That's a conversion barrier and a trust miss — some users will assume
it's the wrong tool and leave.

**Recommendation:** Expand the homepage to three short sections:

1. **"What this converts"** — one sentence per form, with a link to the
   sample files already in the repo (`Sample641CouselingRecord-2-14.xml`,
   `Sample_Training_888-2-26-2025.xml`).
2. **"How it works"** — a 4-step visual: upload CSV → preview → map
   columns → download XML.
3. **"Need help?"** — contact link or FAQ.

Keep Sign In / Create Account as the primary CTAs but below the fold.

**Effort:** M

---

### 2.2 Dashboard empty state is passive **[P2]**

**Where:** `apps/web/src/app/dashboard/page.tsx:44-50`

**What the user sees:** "No conversions yet. Upload a CSV file to get
started." — two lines of gray text centered on an otherwise blank page.

**Why it hurts:** First-time users get no orientation. The empty state
is prime real estate for onboarding.

**Recommendation:** Replace the empty state with:
- A big "Start a new conversion" button (primary).
- A 3-step diagram of the flow.
- Links to sample CSV files (or a "download a sample" button) so the
  user can round-trip the tool without having to supply their own data.
- A link to the Help page from finding 1.3.

**Effort:** M

---

### 2.3 README is silent on the web app **[P1]**

**Where:** `README.md` (entire file)

**What the user sees:** The README describes `run.py`, `setup.bat`, and
`src/main.py`. It never mentions `apps/web`, `docker-compose up`, the
Next.js UI, authentication, or the web conversion flow.

**Why it hurts:** Any partner who lands on the GitHub repo (e.g. from a
shared link) sees only the CLI path and may not realize a web UI exists.
It also leaves contributors without a pointer to the web app's dev loop.

**Recommendation:** Add a "Web app (recommended for most users)" section
at the top of `README.md` with: a screenshot, a bullet of what it does,
and `docker compose up` instructions. Keep the CLI section below for
advanced users.

**Effort:** S

---

### 2.4 Signup page does not show password rules **[P2]**

**Where:** `apps/web/src/app/signup/page.tsx:91-103`

**What the user sees:** Label says "Password (min 8 characters)". The
`minLength={8}` attribute is the only hint.

**Why it hurts:** The backend rejects passwords that lack an uppercase
letter, a digit, or a special character (`TECHNICAL_DEBT.md` finding
#14). The frontend never tells the user this, so signup fails with
a generic error returned from `/api/auth/signup` and the user doesn't
know what to fix.

**Recommendation:** Show all requirements inline under the password
field as a checklist, and light them up green as the user types. At
minimum, list the rules before submission so users don't have to fail
to discover them.

**Effort:** S

---

## 3. Conversion Flow

### 3.1 Converter types overlap and aren't explained **[P1]**

**Where:** `apps/web/src/app/convert/page.tsx:78-107`

**What the user sees:** Three radio buttons — "Counseling (Form 641)",
"Training (Form 888)", and "Training Client (Form 641)" — laid out
side-by-side with no descriptions. Two of the three reference Form 641.

**Why it hurts:** Partners cannot tell whether their CSV belongs in
"Counseling" or "Training Client" without reading source code. Picking
wrong means the upload succeeds, the preview reports "Missing" for every
important column, and the user loops back to re-upload — possibly
multiple times.

**Recommendation:** Render the three choices as radio cards, each with
a one-line description:

- *Counseling (Form 641)* — Individual client counseling sessions. Each
  row is a counseling visit.
- *Training (Form 888)* — Aggregated training event data with attendee
  demographics per class.
- *Training Client (Form 641)* — Per-attendee rows from a training
  event, exported in the Form 641 schema.

Link each one to the relevant sample XML file so the user can compare
against their source data.

**Effort:** S

---

### 3.2 Re-upload page hardcodes two converter types **[P0 — bug]** **[RESOLVED]**

**Where:** `apps/web/src/app/convert/[jobId]/reupload/page.tsx:81-86`

**What the user sees:** The "Converter Type" display on the re-upload
page is a hardcoded ternary:

```tsx
{converterType === "counseling"
  ? "Counseling (Form 641)"
  : "Training (Form 888)"}
```

**Why it hurts:** A user who started a "Training Client (Form 641)"
conversion on the upload page will see "Training (Form 888)" on the
re-upload page. The original file's type is preserved in the database
and in the POST body (line 40), but the label lies to the user. They
may think the conversion silently changed form types.

**Recommendation:** Map all three types correctly, or better — use a
shared `converterTypeLabel(type)` helper so every page agrees. Consider
extracting converter type metadata (value, label, description, sample
file) into one module and importing it everywhere.

**Effort:** S

---

### 3.3 File upload does not validate before submit **[P2]**

**Where:** `apps/web/src/app/convert/page.tsx:118-132`

**What the user sees:** Drag-and-drop accepts any file whose name ends
in `.csv` (`dropped?.name.endsWith(".csv")`); no size check, no MIME
check, no peek-at-headers. The 50MB limit is a text hint only.

**Why it hurts:** Users who drop a 200MB CSV, a `.CSV` (upper-case
extension, currently rejected silently — the drop handler's
`.endsWith(".csv")` is case-sensitive), or a file renamed from `.xlsx`
only find out after the upload fails on the server. Silent rejection of
upper-case `.CSV` is especially bad because nothing happens at all when
the user drops the file.

**Recommendation:**
1. Make the extension check case-insensitive.
2. Validate `file.size <= 50 * 1024 * 1024` client-side and show an
   inline error before starting the fetch.
3. If the dropped file is rejected, show a toast/alert ("That doesn't
   look like a CSV — we accept `.csv` files up to 50MB.") instead of
   doing nothing.

**Effort:** S

---

### 3.4 Preview page gives no guidance on "Extra" columns **[P2]**

**Where:** `apps/web/src/app/convert/[jobId]/preview/page.tsx:72-88`

**What the user sees:** Three summary cards — Matched / Missing / Extra
— where "Extra" is an opaque count. The user isn't told whether extra
columns will be dropped silently, whether they indicate a schema
mismatch, or whether they're safe to ignore.

**Why it hurts:** "Extra" sits next to "Missing" in a warning-colored
(yellow) card, so users assume it's a problem. They then try to "fix"
it, which is impossible from the mapping page (mapping only covers
missing fields).

**Recommendation:** Change the Extra card to neutral/informational
styling and add a one-line explanation: "Extra columns in your CSV will
be ignored during conversion. This is fine." If the Extra list is
useful (e.g. shows the user they misnamed a column), expose it in a
tooltip or collapsible section.

**Effort:** S

---

### 3.5 Mapping page exposes raw XML field names with no descriptions **[P1]**

**Where:** `apps/web/src/app/convert/[jobId]/mapping/page.tsx:127-221`

**What the user sees:** A two-column table of expected XML field names
like `BranchOfService`, `SmallDisadvantagedConcernInd`, and
`EconomicDevelopmentProgramLocation`, each with a Required / Conditional
/ Optional badge (L154-168). There is no hover tooltip, no description,
and no explanation of when a "Conditional" field becomes required.

**Why it hurts:** This page is where partners stall most often.
"BranchOfService" is meaningless to someone who hasn't read the SBA
schema. "Conditional" with no rule is worse than useless — the user
doesn't know whether to map it or not.

**Recommendation:** Surface field metadata that already exists in
`src/config.py`:

1. Add a plain-language `description` property per field to the preview
   API response (`/api/jobs/[jobId]/preview`).
2. Render the description as the table row's second line, in gray-500
   under the monospace field name.
3. For conditional fields, append the rule ("Required when
   MilitaryStatus = 'Active' or 'Veteran'").
4. Let the user hover the badge for the full rule text.

**Effort:** L (touches worker API too)

---

### 3.6 Progress page has no cancel, no ETA, and a dead-end timeout **[P1]** **[PARTIALLY RESOLVED]**

_Cancel button, dead-end timeout recovery, elapsed-time counter, and
poll-failure banner shipped. True row-level ETA deferred: the worker
does not currently update ``Job.processedRows`` during a conversion,
so there is no denominator for a remaining-time estimate. Would need
either periodic progress writes from inside ``run_conversion`` or an
SSE/WebSocket channel — both out of scope for Phase 3._


**Where:** `apps/web/src/app/convert/[jobId]/progress/page.tsx:69-108`

**What the user sees:** A centered "Converting…" heading, a blue
progress bar, a percentage number, and three counters (Processed /
Errors / Warnings). After 5 minutes (L20, L43-46) the heading flips to
"Conversion Timed Out" and the subtitle says "The conversion is taking
longer than expected. Please check back later or try again." — with no
button, no link, no nothing. The user is stranded on a page that will
never update again.

**Why it hurts:** On a slow connection or a large file the timeout hits
first-time users and gives them no next step. Meanwhile, there is no
way to cancel a stuck conversion at any time — closing the tab is the
only option, and the worker keeps running.

**Recommendation:**
1. On timeout, render three buttons: "Check status again", "Go to
   dashboard", and "Report a problem".
2. Always show a "Cancel conversion" button while `status === "converting"`.
   Wire it to a new `POST /api/jobs/[jobId]/cancel`.
3. Show an estimated time (based on `processedRows` rate) once enough
   data exists — "About 30 seconds remaining".
4. Add `role="progressbar"` with `aria-valuenow`, `aria-valuemin`,
   `aria-valuemax` to the bar (see a11y section 6.1).

**Effort:** M

---

### 3.7 Results page summary uses 4-column grid that breaks on mobile **[P1]** **[RESOLVED]**

**Where:** `apps/web/src/app/convert/[jobId]/results/page.tsx:124-140`

**What the user sees:** `grid grid-cols-4 gap-4 mb-6` — Total /
Successful / Errors / Warnings cards rendered in four fixed columns at
every viewport.

**Why it hurts:** On a 375px phone, each card is ~80px wide. The label
("Total Records") wraps awkwardly and the `text-2xl font-bold` count
crowds the border.

**Recommendation:** Change the class to `grid grid-cols-2 md:grid-cols-4`.
Apply the same fix to the comparison grid at L143-164 (`grid-cols-3`
→ `grid-cols-1 sm:grid-cols-3`).

**Effort:** S

---

### 3.8 Re-upload comparison is counts-only; there is no actual diff **[P1]**

**Where:** `apps/web/src/app/convert/[jobId]/results/page.tsx:142-164`,
`computeComparison` at L234-249

**What the user sees:** After a re-upload, three cards show counts of
Resolved, New Issues, and Persistent issues — and that's it. To see
*which* issues resolved, the user must scroll the combined errors/warnings
tables (which still show the current set) and compare by eye.

**Why it hurts:** The whole point of re-upload is to verify that the
fix worked. Counts alone don't prove it — partners will still have to
eyeball the issue list and guess which ones are new.

**Recommendation:** Make each card clickable and add three anchors or
tabs on the results page:

- Resolved — list the issues that disappeared (green).
- New — list the issues introduced by the re-upload (red).
- Persistent — list the issues still present (yellow).

Even a collapsible `<details>` under each card would be a big win.

**Effort:** M

---

### 3.9 No success confirmation anywhere in the flow **[P1]** **[RESOLVED]**

**Where:** `apps/web/src/app/convert/page.tsx:54` (redirect after
upload); `apps/web/src/app/convert/[jobId]/mapping/page.tsx:58`
(redirect after mapping save); `apps/web/src/app/convert/[jobId]/progress/page.tsx:38-40`
(redirect to results)

**What the user sees:** Every successful action ends in a silent
`router.push`. There is no toast, no green banner, no audio cue.

**Why it hurts:** On a slow network the user stares at a frozen button
and wonders if it worked. On a fast network the next page just appears
with no acknowledgment of what just happened. Forgiveness — the ability
to tell "did that save? did that upload?" — is missing.

**Recommendation:** Introduce a single toast component (e.g. a small
`sonner` or a hand-rolled equivalent mounted in `layout.tsx`). Fire
success toasts on: upload, mapping save, conversion complete, re-upload,
sign-in, sign-up. Use the same component for recoverable errors.

**Effort:** M

---

## 4. Error Handling, Recovery & Messaging

### 4.1 Upload errors are generic **[P1]** **[RESOLVED]**

**Where:** `apps/web/src/app/convert/page.tsx:47-56`

**What the user sees:** On any non-2xx response, the UI shows
`data.error || "Upload failed"`. On a thrown exception, it shows
"Upload failed. Please try again." There is no distinction between
rate limiting, file-too-big, wrong-type, bad-auth, or server errors.

**Why it hurts:** The backend already distinguishes several error
conditions (see `TECHNICAL_DEBT.md` — the upload route returns 400 for
file-required, 400 for non-CSV, 413 for >50MB, 400 for invalid
converter type, 429 for rate-limiting). The frontend flattens all of
them into one line of text without offering a next action.

**Recommendation:** Map each known HTTP status / error code to a
specific message and a suggested action:

- 413 → "This file is larger than 50MB. Split it into smaller batches
  or remove unused columns."
- 429 → "You've uploaded a lot of files recently. Please wait a minute
  and try again."
- 400 ("Only CSV files are accepted") → "That file isn't a CSV. Export
  it from Excel as a `.csv` file."
- 401/403 → "Your session expired. Sign in again." + link.
- 5xx → "Something went wrong on our side. Try again in a minute, and
  if it keeps happening, contact support."

Add `role="alert"` to the error div (see a11y section 6.2).

**Effort:** S

---

### 4.2 Preview/Convert error states are dead ends **[P2]** **[RESOLVED]**

**Where:** `apps/web/src/app/convert/[jobId]/preview/page.tsx:53-59`

**What the user sees:** If the preview fails to load, the entire page
is replaced with a single red line of text: "Failed to load preview".
There's no Retry button, no link back to the upload page, no diagnostic.

**Why it hurts:** The user cannot recover without using the browser back
button. A transient network failure feels like a permanent break.

**Recommendation:** Replace the bare `<p>` with an error card that
includes:
- The error message.
- A "Try again" button that re-fetches.
- A "Back to upload" link.

Apply the same pattern to `mapping/page.tsx` and the top-level catch in
`handleConvert` (line 39-42).

**Effort:** S

---

### 4.3 Mapping save failure is swallowed **[P1]** **[RESOLVED]**

**Where:** `apps/web/src/app/convert/[jobId]/mapping/page.tsx:47-62`

**What the user sees:** `handleSave` uses `try/catch` but on failure
just resets `saving=false` without showing any message:

```ts
} catch {
  setSaving(false);
}
```

If the PATCH fails, the button stops spinning and nothing else happens.
The user assumes it worked and moves on.

**Why it hurts:** Silent data loss. The mapping is not persisted but the
user believes it was, so the next conversion runs with the wrong columns.

**Recommendation:** Set an `error` state and render it above the table.
Reuse the error-alert pattern from `convert/page.tsx:67-71`. Better:
check `!res.ok` explicitly and show the server's error message.

**Effort:** S

---

### 4.4 Error boundary strands the user **[P2]** **[RESOLVED]**

**Where:** `apps/web/src/components/error-boundary.tsx:28-46`

**What the user sees:** "Something went wrong. An unexpected error
occurred. Please try refreshing the page." plus a "Try again" button
that calls `setState({ hasError: false })`.

**Why it hurts:**
1. "Try again" just re-renders the same children — if the error is
   deterministic (bad route, missing data), it crashes again immediately.
2. There's no way to navigate to a safe route (Dashboard) without
   touching the browser URL bar.
3. Errors are only logged to `console.error`; they are not sent to a
   monitoring service, so the team never learns about them.
4. The fallback lacks `role="alert"` so assistive tech doesn't announce it.

**Recommendation:**
- Add a "Go to dashboard" link alongside "Try again".
- Include the error message (at least in dev) so the user can quote it.
- Wire in Sentry or another collector (the repo already has Sentry MCP
  tooling available).
- Add `role="alert"`.

**Effort:** S

---

### 4.5 Progress page silently swallows poll errors **[P2]** **[RESOLVED]**

**Where:** `apps/web/src/app/convert/[jobId]/progress/page.tsx:47-49`

**What the user sees:** If `/api/jobs/[jobId]` returns an error during
polling, the `catch {}` block ignores it and the UI keeps spinning.
Only the 5-minute timeout eventually rescues the user.

**Why it hurts:** If the worker crashes or the user's auth expires, the
progress page looks busy forever.

**Recommendation:** Track consecutive poll failures. After N (e.g. 3)
in a row, show an inline banner: "We're having trouble checking status.
[Retry] [Go to dashboard]." Still keep the 5-minute hard cap as a
safety net.

**Effort:** S

---

## 5. Feedback & System Status

### 5.1 No toast or notification system **[P1]** **[RESOLVED]**

Already noted in 3.9. Cross-references: every successful form submission
(`login/page.tsx:29`, `signup/page.tsx:47`, `convert/page.tsx:54`,
`mapping/page.tsx:58`, `reupload/page.tsx:47`) should emit a success
notification. None currently do.

---

### 5.2 Loading states reuse button copy and lose context **[P2]** **[RESOLVED]**

**Where:** Every submit button in the app — e.g.
`login/page.tsx:79`, `signup/page.tsx:110`, `convert/page.tsx:158`,
`mapping/page.tsx:230`, `reupload/page.tsx:107`, `preview/page.tsx:153`

**What the user sees:** The button text flips to "Signing in…",
"Uploading…", "Converting…", etc., and its `disabled` state dims the
background. There is no spinner icon, no `aria-busy`, and on pages
that trigger a route change (preview → progress) the user sees
"Converting…" for several seconds before anything happens.

**Why it hurts:** Low-confidence feedback. Users tap again, producing
a disabled button they think is broken. On mobile, the text-only change
is easy to miss.

**Recommendation:**
- Add a small inline spinner (`<svg>` + `animate-spin`) to loading
  buttons.
- Add `aria-busy="true"` while loading.
- For long actions (conversion kickoff), show a page-level overlay or
  skeleton so the button isn't the only indicator.

**Effort:** S

---

### 5.3 No skeleton loaders on data pages **[P2]** **[RESOLVED]**

**Where:** `preview/page.tsx:45-51`, `mapping/page.tsx:64-70`,
`audit/page.tsx:84-89`

**What the user sees:** A centered "Loading…" string in gray text
while data fetches.

**Why it hurts:** The layout jumps when the data arrives; users don't
see the shape of the page they're about to interact with. On slow
mobile connections, "Loading…" feels like a stall.

**Recommendation:** Replace the "Loading…" text with a simple skeleton
that mirrors the final layout — a title bar, three gray cards, a
table with 5 empty rows. Tailwind `animate-pulse` on placeholder
`<div>`s is sufficient.

**Effort:** M

---

### 5.4 Real-time counters don't announce changes **[P1 a11y]** **[RESOLVED]**

**Where:** `progress/page.tsx:94-108`

**What the user sees / hears:** Three counters (Processed / Errors /
Warnings) update silently as polling returns new values. Screen reader
users hear nothing.

**Recommendation:** Wrap the counters in `<div aria-live="polite">`
with a sensible `aria-atomic` so screen readers announce each batch
update.

**Effort:** S

---

## 6. Accessibility (WCAG 2.1 AA Focus)

The app scores low against WCAG 2.1 AA. The issues below are the ones
visible from code inspection; a Lighthouse run and a screen-reader pass
are both recommended as a follow-up.

### 6.1 Progress bar lacks ARIA role and values **[P0]** **[RESOLVED]**

**Where:** `apps/web/src/app/convert/[jobId]/progress/page.tsx:85-92`

**What screen reader users get:** Nothing. The bar is a plain
`<div>`/`<div>` pair with width set via inline style. No `role`, no
`aria-valuenow`, no `aria-valuemin`, no `aria-valuemax`, no text
alternative. WCAG 4.1.2 (Name, Role, Value) violation.

**Recommendation:**

```tsx
<div
  role="progressbar"
  aria-valuenow={percentage}
  aria-valuemin={0}
  aria-valuemax={100}
  aria-label={`Conversion progress: ${percentage}%`}
  className="w-full bg-gray-200 rounded-full h-4 mb-6 overflow-hidden"
>
  <div className="bg-blue-600 h-4 rounded-full transition-all duration-500 ease-out" style={{ width: `${percentage}%` }} />
</div>
```

**Effort:** S

---

### 6.2 Error alerts lack `role="alert"` / `aria-live` **[P0]** **[RESOLVED]**

**Where:** `convert/page.tsx:67-71`, `login/page.tsx:42-46`,
`signup/page.tsx:60-64`, `reupload/page.tsx:70-74`, `preview/page.tsx:53-58`

**What screen reader users get:** Nothing. Errors are rendered in a
static `<div>` that the user has already walked past, so ATs never
announce them.

**Recommendation:** Add `role="alert"` (which implies
`aria-live="assertive"` and `aria-atomic="true"`) to every error
container. For non-blocking inline hints (e.g. preview's "Failed to
load"), use `role="status"` / `aria-live="polite"` instead.

**Effort:** S

---

### 6.3 Status and severity conveyed by color alone **[P1]**

**Where:**
- `results/page.tsx:124-139` — Successful / Errors / Warnings cards
  (color is the only distinction).
- `results/page.tsx:398-426` — Cleaning diff uses `bg-red-50` vs
  `bg-green-50` to show original vs cleaned values.
- `dashboard/page.tsx:141-160` — `StatusBadge` uses six color
  combinations with no icon or text prefix.
- `preview/page.tsx:72-88` — Matched/Missing/Extra cards color-only.
- `mapping/page.tsx:154-173` — Required/Conditional/Optional badges
  are text+color but color is the distinguishing signal.

**Why it hurts:** WCAG 1.4.1 (Use of Color) requires that color not be
the only means of conveying information. ~8% of men have some form of
color vision deficiency; red/green pairs are the worst case.

**Recommendation:** Add a short icon prefix (check, warning, x) or a
text tag ("OK / Error / Warning") to every status surface. For the
cleaning diff, prefix original with a minus and cleaned with a plus so
the contrast of the two cells is not the only signal.

**Effort:** M

---

### 6.4 No visible focus-visible styles on interactive elements **[P1]** **[RESOLVED]**

**Where:** All inputs and buttons across the app. `globals.css:1` is a
single `@import "tailwindcss";` line with no custom focus styles, and
no form control has `focus:ring`, `focus:outline`, or
`focus-visible:*` classes. Tailwind v4's defaults leave the browser
outline in place, but several elements override it implicitly.

**Why it hurts:** Keyboard users lose their place. Particularly
problematic on the drag-and-drop dropzone
(`convert/page.tsx:113-125`) which has `tabIndex={0}` and a keyboard
handler — but no focus ring, so a keyboard user can't tell when it's
selected.

**Recommendation:** Add Tailwind focus utilities app-wide by extending
the base layer in `globals.css`, or by adding `focus-visible:ring-2
focus-visible:ring-blue-500 focus-visible:ring-offset-2` to all
buttons, inputs, and the dropzone.

**Effort:** M

---

### 6.5 Drag-and-drop dropzone uses `role="button"` on a `<div>` **[P2]**

**Where:** `apps/web/src/app/convert/page.tsx:113-125`

**What the user sees:** A `<div role="button" tabIndex={0}>` with
Enter/Space keyboard handlers. The keyboard behavior is mostly correct
but:

1. The underlying `<input type="file">` is hidden with `className="hidden"`.
2. The dropzone has no `aria-label` describing what it does (a screen
   reader just hears "button").
3. There's no `aria-describedby` pointing at the "Drag & drop…" or
   ".csv files only, max 50MB" help text.

**Recommendation:** Prefer a real `<label htmlFor="file-input">` on the
dropzone (labels already activate their target input on click and
Enter/Space). Add `aria-label="Upload CSV file"` and
`aria-describedby="file-help"` pointing at the help text `<p>`.

**Effort:** S

---

### 6.6 Table headers are plain `<th>` without scope **[P3]** **[RESOLVED]**

**Where:** All tables — `dashboard/page.tsx`, `audit/page.tsx`,
`preview/page.tsx`, `mapping/page.tsx`, `results/page.tsx`.

**Why it hurts:** WCAG 1.3.1 (Info and Relationships) is satisfied by
default `<th>` in a simple `<thead>`/`<tbody>` table, but adding
`scope="col"` is best practice and required if the tables ever gain row
headers.

**Recommendation:** Add `scope="col"` to every `<th>` inside `<thead>`.

**Effort:** S

---

### 6.7 `<html>` has a single static `lang="en"` **[P3]**

**Where:** `apps/web/src/app/layout.tsx:18`

**What the user sees:** Fine for English-only deployments. Noting it
here because if SBA materials are ever translated, this attribute is
the hook screen readers use to switch voices. No action needed yet.

---

## 7. Responsive & Mobile Experience

### 7.1 Fixed `grid-cols-4` summary cards on results page **[P1]** **[RESOLVED]**

**Where:** `results/page.tsx:126` — `grid grid-cols-4 gap-4 mb-6`

Noted in 3.7. Needs `grid-cols-2 md:grid-cols-4`.

---

### 7.2 Fixed `grid-cols-3` comparison cards **[P1]** **[RESOLVED]**

**Where:** `results/page.tsx:144` — re-upload comparison grid

Same fix pattern: `grid-cols-1 sm:grid-cols-3`.

---

### 7.3 Fixed `grid-cols-3` column-status cards on preview **[P1]** **[RESOLVED]**

**Where:** `preview/page.tsx:72` — Matched / Missing / Extra cards

Same fix: `grid-cols-1 sm:grid-cols-3`.

---

### 7.4 Dashboard table shatters on mobile **[P1]** **[RESOLVED]**

**Where:** `apps/web/src/app/dashboard/page.tsx:53-102`

**What the user sees:** A 7-column table (File / Type / Status /
Records / XSD / Date / Actions) inside `<div className="bg-white
rounded border">`. There's no `overflow-x-auto` wrapper, so on a
375px screen the table overflows its container and pushes page layout
out.

**Recommendation:** Wrap the table in `overflow-x-auto` like
`results/page.tsx:289` already does for issue tables. Longer-term,
hide the least important columns on mobile (`hidden md:table-cell` on
Type, XSD, Date) and collapse the row into a stacked card layout on
the smallest screens.

**Effort:** S (scroll) / M (stacked)

---

### 7.5 Audit table shatters on mobile **[P1]** **[RESOLVED]**

**Where:** `apps/web/src/app/audit/page.tsx:72-123`

**What the user sees:** Same pattern as 7.4 — 5-column table in a
`<div className="bg-white border rounded">` with no overflow wrapper.
The Details cell uses `max-w-[200px] truncate` but the outer table
still pushes the container wider than the viewport.

**Recommendation:** Add `overflow-x-auto` on the wrapper. Consider
hiding Details on small screens.

**Effort:** S

---

### 7.6 Mapping page two-column layout wraps badly **[P2]** **[RESOLVED]**

**Where:** `apps/web/src/app/convert/[jobId]/mapping/page.tsx:127-221`

**What the user sees:** A two-column table. The left cell stacks the
monospace field name and 1-2 badges; the right cell has a `<select>`
and an optional suggestion pill. On a 375px screen the select shrinks
to ~100px and the suggestion pill wraps under it.

**Recommendation:** On mobile, stack the right cell's select and
suggestion pill vertically. Use `flex-col sm:flex-row` on the
`flex items-center gap-2` wrapper at L177.

**Effort:** S

---

### 7.7 Data preview table has no column sticky header **[P2]** **[RESOLVED]**

**Where:** `preview/page.tsx:111-136`

**What the user sees:** A wide CSV preview table with
`overflow-x-auto`. Scrolling right loses the column headers (no
sticky positioning), so users mapping dozens of columns must scroll
back and forth.

**Recommendation:** Add `sticky top-0 bg-gray-50` to the `<thead>
<tr>` or each `<th>`. Similarly, on the dashboard and audit tables
consider sticky column headers for long lists.

**Effort:** S

---

### 7.8 Nav doesn't collapse on mobile **[P1]**

Already filed as 1.1.

---

## 8. Visual Design & Consistency

### 8.1 No design tokens; utility classes repeat everywhere **[P2]**

**Where:** Every page uses raw Tailwind utility strings. For example,
the primary button pattern
`bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700
disabled:opacity-50` appears at least 8 times across pages with slight
variations (`px-4 py-2`, `px-6 py-2`, `py-2 px-4 w-full`, `py-2`).

**Why it hurts:**
- Inconsistent button sizing across screens (the homepage uses
  `px-6 py-2`; convert uses `w-full py-2`; mapping uses `px-4 py-2`).
- Impossible to change the brand color without a find-and-replace.
- New pages drift further from any baseline.

**Recommendation:** Extract a small set of component wrappers
(`<PrimaryButton>`, `<SecondaryButton>`, `<Alert variant=…>`,
`<Card>`, `<StatusBadge>`) under `apps/web/src/components/ui/`.
Convert existing pages to use them. Even 5 components would cover 80%
of the current utility-class duplication.

**Effort:** L

---

### 8.2 `StatusBadge` color map duplicated in dashboard only **[P3]**

**Where:** `apps/web/src/app/dashboard/page.tsx:141-160`

**What the user sees:** The dashboard has its own `StatusBadge`
function. No other page uses it — which is fine today but means the
next screen that needs a status badge will reinvent it.

**Recommendation:** Move `StatusBadge` to
`apps/web/src/components/status-badge.tsx` so it can be reused (e.g.
on the results page header where "converting / complete / error" would
be useful).

**Effort:** S

---

### 8.3 Homepage typography is unbalanced **[P3]**

**Where:** `apps/web/src/app/page.tsx:6-25`

**What the user sees:** `text-4xl` headline above `text-lg` body, then
two buttons at `text-sm`. The buttons look too small for the header
scale.

**Recommendation:** Bump the buttons to `text-base` or
`px-6 py-3 text-base` and tighten the button group's vertical rhythm.

**Effort:** S

---

### 8.4 Gray-400 / gray-500 text fails contrast on white **[P2]** **[RESOLVED]**

**Where:** Multiple — e.g. `convert/page.tsx:145` ("`.csv` files only,
max 50MB" in `text-gray-400`), `dashboard/page.tsx:86`
(`text-gray-500`), `audit/page.tsx:101` (`text-gray-500`),
`preview/page.tsx:115` (`text-gray-500` column header text).

**Why it hurts:** Tailwind's `gray-400` (#9ca3af) on white fails WCAG
AA contrast (3.9:1 on normal text — requirement is 4.5:1).
`gray-500` (#6b7280) passes at 4.83:1 but is marginal and fails on
large gray backgrounds. Needs review.

**Recommendation:** Replace `text-gray-400` with `text-gray-500` or
darker. Run a contrast checker (Lighthouse / axe) across the app and
adjust the gray scale accordingly.

**Effort:** S

---

### 8.5 Inconsistent alert styling across pages **[P3]**

**Where:**
- `convert/page.tsx:67-71` → `bg-red-50 text-red-600 p-3 rounded text-sm`
- `reupload/page.tsx:70-74` → `bg-red-50 border border-red-200 text-red-700 text-sm rounded p-3`
- `login/page.tsx:42-46` → `bg-red-50 text-red-600 p-3 rounded text-sm`

**Why it hurts:** Three slight variations of the same error alert.

**Recommendation:** One `<Alert variant="error">` component. Covered
by 8.1.

**Effort:** S (if 8.1 is done)

---

## 9. Content, Microcopy & Terminology

### 9.1 Inconsistent status vocabulary **[P2]**

**Where:** `apps/web/src/app/dashboard/page.tsx:141-160`

**What the user sees:** Six status values — `uploaded`, `previewed`,
`mapping`, `converting`, `complete`, `error` — mixing past participle
and gerund forms, plus a noun (`error`). Rendered lowercase.

**Why it hurts:** Low-confidence users can't tell what these mean
("What does 'mapping' mean for my job? Is it waiting for me?"). The
grammar mix makes a scan of the dashboard harder.

**Recommendation:** Use one tense and capitalize:

- `uploaded` → **Uploaded**
- `previewed` → **Ready to convert** (the user has seen the preview;
  from their POV the next action is theirs)
- `mapping` → **Needs mapping**
- `converting` → **Converting…**
- `complete` → **Complete**
- `error` → **Failed**

Translate the raw database value in a helper, not by changing schemas.

**Effort:** S

---

### 9.2 Audit "Details" column dumps raw JSON **[P2]**

**Where:** `apps/web/src/app/audit/page.tsx:115-117`

**What the user sees:** `{entry.metadata ? JSON.stringify(entry.metadata) : "-"}`
truncated to `max-w-[200px]`.

**Why it hurts:** Useless to end users; looks unfinished to anyone
reviewing the app.

**Recommendation:** Either render a human-readable summary per action
(the audit actions are a known set — see `audit/page.tsx:53-58`), or
replace the cell with a "View details" toggle that expands a
formatted JSON tree in the row below.

**Effort:** M

---

### 9.3 Upload help text hides the limits **[P3]**

**Where:** `apps/web/src/app/convert/page.tsx:145-147`

**What the user sees:** "`.csv` files only, max 50MB" in `text-xs
text-gray-400`.

**Why it hurts:** The smallest, lowest-contrast text on the page is
the one with the constraint the user will hit most often.

**Recommendation:** Promote to `text-sm text-gray-600` and move it
directly under the "CSV File" label, not inside the dropzone. Related
to 8.4.

**Effort:** S

---

### 9.4 Converter-type labels don't match what users know **[P2]**

**Where:** `apps/web/src/app/convert/page.tsx:86,96,106`

**What the user sees:** "Counseling (Form 641)", "Training (Form
888)", "Training Client (Form 641)".

**Why it hurts:** Some partners know the forms by EDMIS or by the SBA
submission portal, not by these names. The labels are also ambiguous
(see 3.1).

**Recommendation:** After a user-owner decision on terminology, apply
the final names in one place (see 3.1 recommendation to extract
converter type metadata).

**Effort:** S

---

### 9.5 "Skip" on mapping page is ambiguous **[P3]**

**Where:** `apps/web/src/app/convert/[jobId]/mapping/page.tsx:232-237`

**What the user sees:** A button labeled "Skip" next to "Save Mapping
& Continue".

**Why it hurts:** "Skip" sounds like it drops the mapping entirely,
but the `onClick` just navigates back to the preview page — any
unsaved edits are lost without warning.

**Recommendation:** Rename to "Cancel" and, if the user has made
changes, confirm before discarding them.

**Effort:** S

---

## 10. Trust, Safety & Data Handling Cues

### 10.1 Upload screen doesn't disclose what happens to the data **[P1]**

**Where:** `apps/web/src/app/convert/page.tsx:62-161`

**What the user sees:** Nothing. The upload page doesn't say where the
CSV will be stored, for how long, who can see it, or whether any of it
is sent to third-party services.

**Why it hurts:** Counseling data includes client names, contact
details, and demographics — PII under SBA policy. External partners
uploading client data deserve an explicit disclosure, both as a legal
safeguard and as a trust cue that the tool takes their data seriously.

**Recommendation:** Add a short paragraph under the file input:

> "Your CSV will be stored in your account and is visible only to you.
> Files are retained for 30 days and then automatically deleted. Data
> is processed entirely on SBA infrastructure; nothing is sent to
> third-party services."

Adjust the wording to match the actual retention policy (if there is
one; see Open Questions).

**Effort:** S

---

### 10.2 No explicit "last job will be replaced" cue on re-upload **[P3]**

**Where:** `apps/web/src/app/convert/[jobId]/reupload/page.tsx:62-117`

**What the user sees:** A form that looks identical to the regular
upload, with a "Compare against the previous conversion" subtitle. In
reality the re-upload creates a *new* job (`/api/upload` receives
`previousJobId` as a pointer, it does not replace the prior job).

**Why it hurts:** Users may think their original conversion is
destroyed by re-uploading, or conversely may expect it to be replaced
when it's not. Either way there's a mental-model mismatch.

**Recommendation:** Add a one-liner: "Your previous conversion will be
kept as a separate job. You can compare the two side-by-side on the
next screen." Link the previous job from the copy.

**Effort:** S

---

### 10.3 No confirmation before Sign Out or account deletion **[P3]**

**Where:** `apps/web/src/components/nav.tsx:47-52`

**What the user sees:** A "Sign Out" button that immediately signs the
user out. There's no "Are you sure?" for users with unsaved work (e.g.
mid-mapping).

**Why it hurts:** Accidental clicks during a long mapping session lose
progress. Not destructive enough to warrant a modal, but some form of
guardrail is warranted.

**Recommendation:** For now, nothing — but note it for future dirty-state
tracking. If/when mapping gains autosave, this becomes moot.

**Effort:** N/A (watch)

---

## Appendix A — Findings by Page

Quick reference. Each page lists its most impactful findings linked
back to the themed section.

### `page.tsx` — Homepage
- 2.1 Landing page doesn't explain what to bring **[P1]**
- 8.3 Typography unbalanced **[P3]**

### `login/page.tsx`
- 6.2 Error alert lacks `role="alert"` **[P0]**
- 5.2 Loading state reuses button copy **[P2]**
- 6.4 No visible focus ring **[P1]**

### `signup/page.tsx`
- 2.4 Password rules not shown **[P2]**
- 6.2 Error alert lacks `role="alert"` **[P0]**
- 5.2 Loading state reuses button copy **[P2]**

### `layout.tsx`
- 6.7 Static `lang="en"` (watch) **[P3]**
- 5.1 No toast system mounted **[P1]**

### `nav.tsx`
- 1.1 Does not collapse on mobile **[P1]**
- 1.3 No Help/Docs entry point **[P2]**
- 10.3 No sign-out confirmation (watch) **[P3]**

### `error-boundary.tsx`
- 4.4 Error boundary strands the user **[P2]**
- 6.2 No `role="alert"` on fallback **[P0]**

### `dashboard/page.tsx`
- 7.4 Table shatters on mobile **[P1]**
- 2.2 Empty state is passive **[P2]**
- 9.1 Status vocabulary inconsistent **[P2]**
- 6.3 Status badges color-only **[P1]**

### `audit/page.tsx`
- 7.5 Table shatters on mobile **[P1]**
- 9.2 Raw JSON in Details cell **[P2]**
- 5.3 No skeleton loader **[P2]**

### `convert/page.tsx`
- 3.1 Converter types not explained **[P1]**
- 3.3 No client-side file validation **[P2]**
- 4.1 Upload errors are generic **[P1]**
- 6.2 Error alert lacks `role="alert"` **[P0]**
- 6.5 Dropzone uses `role="button"` on a `<div>` **[P2]**
- 10.1 No data-handling disclosure **[P1]**
- 9.3 Limit text hidden in gray-400 **[P3]**

### `convert/[jobId]/preview/page.tsx`
- 7.3 Column-status grid fixed at 3 columns **[P1]**
- 3.4 "Extra" column treated as a problem **[P2]**
- 7.7 No sticky table header **[P2]**
- 4.2 Error state dead-end **[P2]**
- 5.3 No skeleton loader **[P2]**

### `convert/[jobId]/mapping/page.tsx`
- 3.5 Raw XML field names with no descriptions **[P1]**
- 4.3 Save failure swallowed **[P1]**
- 7.6 Two-column layout wraps badly on mobile **[P2]**
- 9.5 "Skip" is ambiguous **[P3]**
- 6.3 Required/Conditional/Optional badges color-coded **[P1]**

### `convert/[jobId]/progress/page.tsx`
- 3.6 No cancel, no ETA, dead-end timeout **[P1]**
- 6.1 Progress bar lacks ARIA **[P0]**
- 5.4 Counters not announced to screen readers **[P1]**
- 4.5 Poll errors swallowed silently **[P2]**

### `convert/[jobId]/results/page.tsx`
- 3.7 4-column grid breaks on mobile **[P1]**
- 3.8 Comparison is counts-only **[P1]**
- 6.3 Severity conveyed by color alone **[P1]**
- 6.6 Tables lack `scope="col"` **[P3]**

### `convert/[jobId]/reupload/page.tsx`
- 3.2 Hardcoded two-type label (bug) **[P0]**
- 10.2 No "previous job is kept" cue **[P3]**
- 6.2 Error alert lacks `role="alert"` **[P0]**

---

## Appendix B — Top 10 Punch List

Ordered for maximum impact per unit of effort. Items link back to the
themed section.

1. **[P0] Fix the hardcoded converter-type label on re-upload.** Bug
   fix. §3.2 — 15 minutes.
2. **[P0] Add `role="alert"` to every error container and
   `role="progressbar"` + `aria-value*` to the progress bar.** §6.1,
   §6.2 — 1 hour.
3. **[P1] Explain the three converter types on the upload page.** §3.1
   — half a day, user-visible win.
4. **[P1] Fix mobile layout: responsive grids on preview/results, add
   `overflow-x-auto` to dashboard and audit tables, collapse the nav
   behind a hamburger.** §1.1, §3.7, §7.1–7.5 — one day.
5. **[P1] Add a cancel button and a recoverable timeout to the
   progress page.** §3.6 — half a day, requires a new worker endpoint.
6. **[P1] Make upload errors actionable.** Map 413/429/400/401/5xx to
   specific messages + next actions. §4.1 — half a day.
7. **[P1] Add column-mapping field descriptions.** Surface
   `src/config.py` metadata in the preview API. §3.5 — requires
   coordinating with the worker; high user impact.
8. **[P1] Add a toast/notification system** mounted in `layout.tsx` and
   fire it on every success. §3.9, §5.1 — half a day.
9. **[P1] Replace color-only status with icon+text prefixes everywhere.**
   §6.3 — half a day.
10. **[P1] Fix the silent mapping-save failure.** §4.3 — 15 minutes,
    prevents silent data loss.

---

## Appendix C — Open Questions for the Product Owner

These are assumptions I made during the review that should be
confirmed before implementation begins.

1. **What is the primary user device?** I assumed a mix of desktop
   (office work) and mobile (on-the-go status checks). If partners
   almost never use mobile, the responsive findings (P1s in §7) drop
   to P2.
2. **Is there a data retention policy?** The disclosure copy in §10.1
   assumes 30 days. Confirm the actual policy (or create one).
3. **Can the converter type list be renamed?** §3.1 and §9.4
   recommend clearer labels; those require a product decision because
   "Form 641" and "Form 888" are canonical SBA names.
4. **Does the worker support job cancellation?** §3.6 assumes a new
   `POST /api/jobs/[jobId]/cancel` can be added. Confirm that
   mid-conversion cancellation is technically feasible in the worker.
5. **Are field descriptions already in `src/config.py`?** §3.5 assumes
   they exist (or can be written). If not, this finding becomes a
   content task rather than a display task.
6. **Is there an existing SBA design system** (brand colors, type
   scale, component library) that the web app should adopt? If so,
   §8.1 should align to it rather than roll a new one.
7. **Should the CLI and web app converge on one surface?** Out of
   scope for this review but worth asking: the CLI (`run.py`) actually
   explains its steps well ("Step 1: Pick Conversion Type") in a way
   the web app does not. Is the plan to deprecate one of the two?

---

## Notes for the Next Reviewer

- **Run axe or Lighthouse.** The a11y findings in §6 are all
  code-visible. A live accessibility audit will surface more
  (especially contrast ratios, focus order, landmark regions).
- **Walk the flow with a screen reader.** VoiceOver on Safari and NVDA
  on Firefox are the two most impactful checks.
- **Test at 375px, 768px, and 1024px.** The findings in §7 are the
  bugs I can see from the code; real-device testing will find layout
  issues I can't predict.
- **Check Sentry (if wired up).** If the team turns on the Sentry MCP
  server, the client error boundary will start collecting real
  user-facing crashes that this review cannot surface.

