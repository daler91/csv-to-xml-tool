# CLI reference

Four entry points, all running the same conversion core as the web app.

| Entry point | For |
|---|---|
| `run.py` (`run.bat`) | Interactive; no flags to remember |
| `python -m src.main` | Scripted conversions |
| `python -m src.fix_sba_xml` | Repairing element order in existing XML |
| `python -m src.xml_validator` | Validating existing XML, and repairing it with `--fix` |

## Setup

```bash
pip install -r requirements.txt
```

That is `pytest`, `pytest-cov`, `defusedxml` and `lxml`. CSV reading is stdlib —
there is no pandas dependency anywhere in this project.

On Windows, `setup.bat` does the same thing and checks that Python is on PATH
first.

---

## `run.py` — interactive launcher

```bash
python run.py        # macOS/Linux
run.bat              # Windows (double-click also works)
```

Four prompts:

1. **Converter type** — Counseling (Form 641), Training (Management Training
   Report), or Training Client (Form 641 from per-attendee rows).
2. **Input CSV** — pick from the `.csv` files beside `run.py`, or type a path.
3. **Output location** — defaults to `output/<name>_<timestamp>.xml`.
4. **XSD validation** — optional.

Then a summary and a confirmation before anything is written.

Outputs, relative to the folder holding `run.py`:

| Directory | Contents |
|---|---|
| `output/` | The XML |
| `reports/` | Validation report, CSV and HTML |
| `logs/` | Run log |

> **Known bug:** step 4 only appears when `run.py` finds `.xsd` files **directly
> beside itself**. The bundled schemas live in `schemas/`, so on a clean checkout
> the prompt is skipped and the XML is written unvalidated. Workarounds: copy the
> XSD you need next to `run.py`, or validate separately with the web app's
> **Validate XML** page. Tracked in
> [documentation-audit.md](./documentation-audit.md#code-issues-found-during-the-audit).

When it does run, validation prints the first 10 errors and then a count of the
rest. The XML is still written either way — an invalid file plus its error list
is more useful than no file.

---

## `python -m src.main` — scripted conversion

```bash
python -m src.main convert <converter_type> --input <csv> [options]
```

### Positional

| Value | Form |
|---|---|
| `counseling` | 641 Counseling |
| `training` | 888 Management Training |
| `training-client` | 641 from per-attendee training rows |

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--input`, `-i` | *(required)* | Path to the input CSV |
| `--output`, `-o` | `<input_dir>/<name>_<timestamp>.xml` | Path for the output XML |
| `--log-level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--log-dir` | `logs` | Where run logs go |
| `--report-dir` | `reports` | Where validation reports go |

### Examples

```bash
# Counseling
python -m src.main convert counseling \
  --input report.csv --output output/counseling.xml

# Training, verbose, reports elsewhere
python -m src.main convert training \
  --input training_export.csv \
  --output output/training.xml \
  --report-dir build/reports --log-level DEBUG

# Training attendees as Form 641 records
python -m src.main convert training-client \
  --input attendees.csv --output output/641_from_training.xml
```

### What it does not do

`src.main convert` does **not** validate against an XSD. It writes the XML and
the validation reports. To validate, use `run.py`, the web app's Validate XML
page, or lxml directly:

```bash
python -c "
from lxml import etree
schema = etree.XMLSchema(etree.parse('schemas/SBA_NEXUS_Counseling-2-14.xsd'))
doc = etree.parse('output/counseling.xml')
print('valid' if schema.validate(doc) else list(schema.error_log))
"
```

Remember that `training-client` output validates against the **counseling**
schema, not the training one.

### Exit codes

`0` on success. `1` if the input file does not exist, or on any unexpected error
during conversion (logged with a traceback at the configured log level).

Data-quality issues do not affect the exit code: a conversion that records
hundreds of warnings still exits `0`. Because this command performs no XSD
validation at all, schema-invalid output also exits `0`. If you need CI to fail
on either, read the report or run the lxml snippet above and check its result
yourself.

---

## Output path confinement

Every write — XML, reports, logs — is confined to a base directory. Passing a
path outside it fails with *"Refusing to write outside …"*. This is a
path-traversal guard (`src/path_safety.py`), and it applies to `--output`,
`--report-dir` and `--log-dir` alike. The validator's `--directory` is held to
the same base: it names the folder the glob walks (and, with `--fix`, rewrites
in place), and `--pattern` must be a bare file-name glob: one with a directory
part, such as `../*.xml`, is refused.

The base is:

- **`SBA_OUTPUT_BASE` if set** — an explicit environment override.
- Otherwise, **the current working directory** for `src.main`, and **the folder
  containing `run.py`** for the launcher.

There is one deliberate exception: when `--output` is omitted, the XML is written
next to the input file and confined to the *input's* directory, so an absolute
`--input` still works and its output lands beside it.

To write somewhere else:

```bash
SBA_OUTPUT_BASE=/srv/sba-output python -m src.main convert counseling \
  --input report.csv --output /srv/sba-output/counseling.xml
```

---

## `python -m src.fix_sba_xml` — repair element order

Puts the elements of an existing XML file in the order its schema's
`xs:sequence`s require — every one of them, read from the XSD itself — then
checks the result against that XSD. It never invents data: if an element is
missing, it stays missing; only the order changes.

```bash
python -m src.fix_sba_xml --file invalid.xml --output fixed.xml
```

| Flag | Meaning |
|---|---|
| `--file`, `-f` | A single XML file to fix |
| `--directory`, `-d` | A directory of XML files (mutually exclusive with `--file`) |
| `--output`, `-o` | Output file or directory |
| `--no-backup` | Do not back up the original |
| `--recursive`, `-r` | Recurse into subdirectories (with `--directory`) |
| `--pattern` | Glob for directory mode (default `*.xml`) |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--log-file` | Also write the log to a file |

This is what fixes `cvc-complex-type.2.4.a` errors ("This element is not
expected") that come from order alone. The schema is chosen by the root
element: `CounselingInformation` is Form 641 (which `training-client` output
also uses), `ManagementTrainingReport` is Form 888. A file with any other root
is refused, as is one whose DOCTYPE declares entities ("DTD/entity
declarations are not supported").

The file is read and written the way the validator reads it, so comments,
processing instructions, the DOCTYPE and a carriage return written as `&#13;`
come through unchanged. A file already in order is not rewritten (with
`--output`, it is copied as it is).

**Exit codes:** `0` only when every file now passes its schema. `1` when a file
could not be read or fixed, or still fails the schema — its remaining errors are
listed, since reordering cannot fix a wrong value or a missing element. In
directory mode the summary counts the files that pass, still fail, and could
not be fixed, and names each one that did not pass.

The web app exposes the same thing, for counseling-format XML, at `/validate` →
auto-fix.

---

## `python -m src.xml_validator` — validate, and optionally fix

```bash
python -m src.xml_validator --xmlfile report.xml --xsd schemas/SBA_NEXUS_Counseling-2-14.xsd
python -m src.xml_validator --xmlfile report.xml --output fixed.xml --fix
```

| Flag | Meaning |
|---|---|
| `--xmlfile` | A single XML file |
| `--directory` | A directory of XML files (mutually exclusive with `--xmlfile`), with `--recursive` and `--pattern` as above |
| `--xsd` | The schema to validate against, and with `--fix` to order by (default with `--fix`: the root element's schema) |
| `--output` | Where `--fix` writes (file, or directory with `--directory`); default in place |
| `--fix` | Repair the order as `fix_sba_xml` does, then re-validate the result |
| `--add-missing` | With `--fix`: add a missing `CurrentlyInBusiness` to `ClientIntake` as `Undetermined`, with a warning naming each record. Other missing required elements (`Race`) are reported, not added — no answer would be true for every client |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

**Exit codes:** `0` when the file (with `--fix`, the fixed file) passes the
schema, or when there was nothing to check. `1` when it fails, or could not be
fixed; in directory mode, when any file did.

---

## Logging

`src/logging_util.py` writes to the console and, when file logging is on, to
`--log-dir`. There is no rotation — a long-running scripted job accumulates log
files, so rotate them externally if you run this on a schedule
([`reviews/TECHNICAL_DEBT.md`](./reviews/TECHNICAL_DEBT.md)).

Tracebacks are logged with `exc_info=True`. If your logs are exposed anywhere,
treat them as potentially containing internal paths.
