# Documentation

Everything written about this project lives here. The repository root keeps only
[`README.md`](../README.md), which is the short front door; this folder is the
reference material behind it.

## Start here

| If you want to… | Read |
|---|---|
| Convert a CSV today, without reading anything else | [Getting started](./getting-started.md) |
| Understand how the pieces fit together | [Architecture](./architecture.md) |
| Know which CSV columns a converter needs | [CSV input reference](./csv-reference.md) |
| Understand what each converter emits and when it invents a value | [Converters](./converters.md) |
| Run the tool from a terminal or a batch script | [CLI reference](./cli.md) |
| Call the HTTP APIs | [API reference](./api-reference.md) |
| Set an environment variable correctly | [Configuration](./configuration.md) |
| Deploy the stack | [Deployment](./deployment.md) |
| Operate the stack (queue, retention, audit, incidents) | [Operations](./operations.md) |
| Fix an error message | [Troubleshooting](./troubleshooting.md) |
| Run or add tests | [Testing](./testing.md) |
| Contribute a change | [CONTRIBUTING](./CONTRIBUTING.md) |
| Report or understand a security issue | [SECURITY](./SECURITY.md) |

## Review registers

[`reviews/`](./reviews/README.md) holds the long-form audits and the debt
registers. They are point-in-time findings with per-finding status markers, not
descriptions of how the system works — read them when you want to know *what is
wrong or was wrong*, not *how it works*.

- [`reviews/CODEBASE_ANALYSIS_2.md`](./reviews/CODEBASE_ANALYSIS_2.md) — the
  current findings register: the second-pass review at `482d235`. Start here.
- [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md) — the first
  full review; mostly `[FIXED]` now, kept for the history and the still-open items.
- [`reviews/TECHNICAL_DEBT.md`](./reviews/TECHNICAL_DEBT.md) — code and security
  debt, item by item.
- [`reviews/UX_REVIEW.md`](./reviews/UX_REVIEW.md) and
  [`reviews/UX_IMPLEMENTATION_PLAN.md`](./reviews/UX_IMPLEMENTATION_PLAN.md) —
  the user-experience audit and the phased plan that worked through it.
- [`reviews/ARCHITECTURE_REVIEW.md`](./reviews/ARCHITECTURE_REVIEW.md) —
  **historical**. Kept for context; its line citations no longer resolve.

[`documentation-audit.md`](./documentation-audit.md) records what this
documentation set was checked against, what was corrected, and what is still
known to be wrong in the code.

## Conventions

- **Guides use `kebab-case.md`.** They describe how the system works today, and
  they are expected to be edited in the same commit as the code they describe.
- **`CONTRIBUTING.md` and `SECURITY.md` keep their uppercase names** because
  GitHub only gives those two files special treatment at these exact paths.
- **Registers under `reviews/` keep their original `UPPER_SNAKE_CASE.md` names.**
  They are referenced by name from ~25 source comments and from commit messages;
  renaming them would break those references for no benefit.
- **Findings carry a status marker** — `[OPEN]`, `[FIXED]`, `[PARTIAL]`,
  `[RESOLVED]`. When you fix something, flip its marker in the same commit.

## Keeping this accurate

Numbers rot faster than prose. Anything counted here (test totals, coverage,
route counts, line counts) is stamped with the commit it was measured at, and
the commands to re-measure are in [`testing.md`](./testing.md). If you are
reading a figure without such a stamp, treat it as approximate.
