# Architecture Review — csv-to-xml-tool (Consolidated)

## Context

The app converts SBA Salesforce CSV exports (counseling Form 641, training Form 888) into
XSD-compliant XML. Monorepo: **Next.js web** (auth, upload, history) + **FastAPI worker**
(runs conversions) + **Postgres** (job/audit state) + **Redis** + a shared **Python lib**
(`src/`) used by the worker and a CLI (`run.py`).

This consolidates **two independent reviews** — an architecture/orchestration + data-correctness
pass and a web/persistence/auth pass — into one report. Every finding below was **verified
against source** (`file:line`). No code was changed. Because the output feeds **federal
reporting**, silent data fabrication is treated as a first-class risk.

---

## TL;DR — highest-priority risks
1. **No durable job pipeline, and a 5-minute HTTP ceiling on top of it** — valid long
   conversions get aborted and marked `error`; crashes/redeploys strand jobs in `converting`
   forever. (ARCH-1)
2. **Missing/invalid input is silently fabricated** into plausible defaults in the output XML
   that ships to the government. (CONV-1)
3. **Authorization gaps:** the worker API is unauthenticated, and `previousJobId` is accepted
   without an ownership check (IDOR). (SEC-1, SEC-2)
4. **Upload can orphan DB rows;** state integrity isn't enforced. (DATA-1, DATA-2)

---

## Architecture & Orchestration

### ARCH-1 (High) — No durable pipeline; un-awaited promise + 5-minute timeout
- Conversion is started "fire-and-forget": `apps/web/.../jobs/[jobId]/start/route.ts:78-88`
  does **not await** `workerFetch`, returns `202` at `:161`, and writes `complete`/`error`
  inside the dangling `.then()/.catch()`.
- That promise's `workerFetch` uses a **hard 5-minute default timeout**
  (`apps/web/src/lib/worker-client.ts:2,8`); `/convert` is called with **no override**
  (`start/route.ts:79`), so a valid conversion >5 min is **aborted and marked `error`**
  (`start/route.ts:133-140`) even if the worker is still running / would have succeeded.
- No durability either: a Node restart/redeploy/crash mid-run strands the job in `converting`
  forever — no reaper, retry, or reconciliation. On serverless the function freezes after the
  202 and the result is silently dropped.
- **Direction:** durable, worker-pulled queue (use the Redis already in the stack), transactional
  status updates, retry + dead-letter, a reaper that fails jobs stuck past a deadline,
  idempotent reconciliation so a late worker success can't leave the DB misleading, and a
  per-conversion (not global 5-min) timeout.

### ARCH-2 (High) — In-memory progress & cancellation registries (single-process only)
- `apps/worker/app/services/progress.py:35-66` and `cancellation.py:30-52` are in-process
  `dict`/`set` singletons that *explicitly document* "single-worker deployment only." Worker
  runs one uvicorn process today (`apps/worker/Dockerfile:15`, no `--workers`).
- **Failure:** add `--workers N` or a second replica and cancel/progress **silently break**
  (request lands on the wrong process). Nothing prevents the misconfiguration.
- **Direction:** move both to Redis (it's already a dependency + compose service).

### ARCH-3 (Medium) — Worker ignores the available Redis
- The **web** layer *does* use Redis: `ioredis` (`package.json:24`) powers token-bucket
  rate-limiting (`src/lib/rate-limit.ts`, used by `upload` and `signup`, fail-open).
- The **worker** lists `redis>=5.0.0` (`apps/worker/requirements.txt:4`) but a grep of
  `apps/worker` finds **no client usage** — it uses the in-memory registries above.
- **Net:** the coordination layer that genuinely needs Redis (queue/progress/cancel, ARCH-1/2)
  is the one part that doesn't use it, even though it's right there.

### ARCH-4 (Medium) — Whole-file-as-JSON data path despite a shared volume
- Web reads the entire input into memory and posts it as a JSON string (`start/route.ts:76,86`);
  worker converts and **reads the full XML back into the HTTP response**
  (`apps/worker/app/routes/convert.py:70-77`); web writes it to disk (`start/route.ts:92-97`).
  Both containers mount the same `shared-data` volume (`docker-compose.yml`, `DATA_DIR`).
- **Failure:** the file exists ~6× simultaneously, plus JSON-encoding a ~50 MB string twice.
- **Direction:** pass **paths** over the shared volume; serve downloads from disk.

### ARCH-5 (Medium) — Size cap is client-side only; memory amplifies under load
- 50 MB limit is enforced only in the browser-facing route (`upload/route.ts:41-46`); neither
  `start` nor the worker `/convert` re-checks size. Conversion then expands the payload in
  memory on both processes (compounds ARCH-4). No per-user/global concurrency control.
- **Direction:** enforce size server-side, stream/hand off references, add conversion concurrency limits.

---

## Security & Authorization

### SEC-1 (High) — Worker API unauthenticated & over-trusting
- `/convert`, `/preview`, `/validate` have **no auth** (`apps/worker/app/routes/`); CORS is
  `allow_methods=["*"], allow_headers=["*"]` (`apps/worker/app/main.py:15-22`); `/convert`
  trusts a caller-supplied `job_id` with no ownership check (`convert.py:29-66`).
- **Failure:** anyone reaching port 8000 can run conversions, cancel arbitrary jobs, or submit
  a multi-GB body (DoS). **Direction:** service-to-service auth (shared secret/mTLS), keep the
  worker private, tighten CORS, enforce limits.

### SEC-2 (High) — `previousJobId` accepted without ownership validation (IDOR)
- `upload/route.ts:25` reads `previousJobId` from form data; `:69` stores it directly
  (`...(previousJobId ? { previousJobId } : {})`) with no lookup. The schema relation
  (`schema.prisma:38-40`, `JobComparison`) is **not user-scoped** (and can't be at the DB level).
- **Failure:** a user can attach a new job to another user's job ID; any comparison/diff flow
  that surfaces the linked job's data becomes a cross-tenant leak.
- **Direction:** when present, look it up with `{ id: previousJobId, userId: user.id }` before
  accepting; centralize all job→job links behind a helper that enforces ownership.

### SEC-3 (Medium) — Email identity not normalized
- Signup stores/checks the raw email (`signup/route.ts:63,73`); login looks up the raw email
  (`auth.ts:18-19`); the unique constraint is exact-string (`schema.prisma:12`).
- **Failure:** `User@example.com` and `user@example.com` become distinct accounts; casing
  changes break login.
- **Direction:** trim + lowercase at signup and login; migrate existing rows.

---

## Data Integrity & Persistence

### DATA-1 (High) — Upload can orphan database jobs
- `upload/route.ts:63-71` creates the Job row with `inputFilePath: ""` **before** writing the
  file (`:73-78`), then updates the path (`:81-84`). If the write fails in between, the catch
  block (`:97-106`) returns 500 but **never deletes the row** — leaving a `uploaded`-status job
  with an empty input path that can't preview or convert.
- **Direction:** write the file first, or wrap in a transaction with compensating cleanup
  (delete the job + partial upload dir on any post-create failure).

### DATA-2 (Medium) — `status` modeled as a free-form string
- `schema.prisma:26` — `status String @default("uploaded")`; valid transitions are enforced
  only in app code (e.g. `STARTABLE_STATUSES` in `start/route.ts:15`).
- **Failure:** any future route/script/migration can write an invalid status that breaks UI
  assumptions. **Direction:** use a Prisma enum + a single service that owns transitions.

---

## Conversion Correctness (Python core — federal-reporting risk)

- **CONV-1 (High) — Silent defaulting fabricates data.** Pervasive `row.get('Col', <default>)`
  with **no header validation**: revenue/profit → `'0'` (`counseling_converter.py:199-202,312-314`),
  female-owned % → `0` (`data_cleaning.py:330-331`), country → `United States` (`:172`), Race →
  `'Prefer not to say'`. A missing column is indistinguishable from a real zero yet still ships.
- **CONV-2 (Med) — Inconsistent parsing + hardcoded encoding.** Counseling: `csv.DictReader` +
  `utf-8-sig` (`counseling_converter.py:35`); training: pandas auto-detect. Header whitespace
  silently breaks every lookup.
- **CONV-3 (Med) — Ambiguous dates.** `DATE_INPUT_FORMATS` mixes US/EU; `format_date` tries in
  order (`data_cleaning.py:236-243`), so `03/04/2025` is always Mar 4, never flagged.
- **CONV-4 (Med) — `clean_numeric` float round-trip** loses precision on large financials
  (`data_cleaning.py:317-321`). Use `Decimal`.
- **CONV-5 (Med) — `split_multi_value` hardcodes `;`** (`data_cleaning.py:297-305`): a field
  containing a semicolon explodes into multiple `<Code>`s.
- **CONV-6 (Med) — Empty/headers-only CSV "succeeds"** with an empty root + success log
  (`counseling_converter.py:53`) instead of erroring.
- **CONV-7 (Low) — `clean_percentage` silently clamps** to `[0,100]` (`data_cleaning.py:339-340`)
  with no audit trail.

---

## Quality / Testing / Ops

- **QUAL-1 (High) — Zero web tests; no `test` script.** `package.json:6-12` has no `test`
  entry; the highest-risk layer (upload, job authz, status transitions, cancellation races,
  `previousJobId` ownership, worker timeout/error handling) is untested.
- **QUAL-2 (Med) — Python suite uses `unittest`** while `pytest` is the declared dep; no
  coverage; no negative/security/concurrency tests.
- **QUAL-3 (Med) — No dependency lockfile;** worker `pandas`/`lxml`/`defusedxml` unpinned;
  `next-auth@5.0.0-beta.30` (pre-release auth); no `pip-audit`/`npm audit` in CI.
- **QUAL-4 (Med) — O(n²) HTML report** via `+=` string concat (`validation_report.py`).
- **QUAL-5 (Low) — Ops:** no log rotation, no request-correlation ID across web↔worker,
  `exc_info=True` traces could leak internals if logs are exposed.

---

## Done well — don't regress
- **XXE:** parsing/validation use `defusedxml` + `resolve_entities=False` (`src/xml_validator.py`).
- **Path traversal:** download guarded by `realpath()` + prefix check (`download/route.ts`);
  uploads use `os.path.basename` + sanitization.
- **Rate limiting:** Redis token-bucket on `upload` + `signup`, fail-open (`rate-limit.ts`).
- **Password complexity** enforced at signup (`signup/route.ts:19-33`).
- **Race-safe status transitions:** guarded `updateMany` avoids reviving cancelled jobs
  (`start/route.ts:48-65,103-116`).
- **Secrets:** `.env` gitignored, `.env.example` placeholders only. Temp files cleaned in
  `finally` (`convert.py:90-99`).

---

## Suggested remediation priority
- **P0 (correctness/safety):** CONV-1 (header validation), SEC-1 (worker auth + server-side
  size cap), SEC-2 (`previousJobId` ownership), DATA-1 (orphaned jobs), ARCH-1 (at minimum a
  per-job timeout + stuck-job reaper).
- **P1 (architecture):** ARCH-1 full durable queue + ARCH-2/ARCH-3 (Redis-backed progress/cancel),
  ARCH-4/ARCH-5 (path-passing, server-side limits, concurrency control).
- **P2 (data quality + integrity):** CONV-2…CONV-7, DATA-2 (status enum), SEC-3 (email normalize).
- **P3 (hygiene):** QUAL-1 web tests, QUAL-2 pytest/coverage, QUAL-3 lockfiles + CI audit,
  QUAL-4, QUAL-5.

## Verification (how to reproduce)
- **ARCH-1 timeout:** convert a CSV that takes >5 min; web marks the job `error` while the
  worker keeps running.
- **DATA-1:** make the upload dir unwritable; observe a `uploaded` job left with empty
  `inputFilePath`.
- **SEC-2:** as user A, upload with `previousJobId` set to user B's job ID; it's accepted.
- **SEC-3:** sign up `a@x.com`, then `A@x.com`; both succeed as separate users.
- **CONV-1/3/6:** drop `Gross Revenues/Sales` (→ `0`), use `Date=03/04/2025` (→ Mar 4),
  convert a headers-only CSV (→ empty root, success log).
- **Tests/build:** `python -m pytest tests/ -v`; `cd apps/web && npm run lint && npm run build`
  (note: `npm test` has no script).
