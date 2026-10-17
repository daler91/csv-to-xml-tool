# CLI reference

Four entry points, all running the same conversion core as the web app.

| Entry point | For |
|---|---|
| `run.py` (`run.bat`) | Interactive; no flags to remember |
| `python -m src.main` | Scripted conversions |
| `python -m src.fix_sba_xml` | Repairing element order in existing XML |
| `python -m src.xml_validator` | Validating existing XML, and repairing it with `--fix` |

The `python -m` forms need the repository root as the current directory, or on
`PYTHONPATH`. The fixer and the validator also run by script path
(`python <repo>/src/fix_sba_xml.py`) from any folder; `src/main.py` does not.

## Setup

```bash
pip install -r requirements.txt
```

`requirements.txt` is the hash-locked resolution of `requirements.in`: `pytest`,
`pytest-cov`, `defusedxml` and `lxml`, resolved for Python 3.10 and later. The
CLI itself needs only `lxml`; the other three are for the tests. CSV reading is
stdlib — there is no pandas dependency anywhere in this project.

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
   With none beside it — a clean checkout has none; the samples are in
   `apps/web/public/samples/` — it asks for a path straight away. The input may
   be anywhere; only writes are confined.
3. **Output location** — defaults to `output/<name>_<timestamp>.xml`. A typed
   relative path is resolved against the folder holding `run.py`, not the
   current directory, and one outside it is refused
   ([Output path confinement](#output-path-confinement)).
4. **XSD validation** — optional.

Then a summary and a confirmation (`Y/n`: Enter or `y` converts, anything else
cancels) before any file is written; only the `output/` folder is created
before it.

Outputs, relative to the folder holding `run.py`:

| Directory | Contents |
|---|---|
| `output/` | The XML |
| `reports/` | Validation report: `validation_report_<timestamp>.html`, and `validation_issues_<timestamp>.csv` when there are issues |
| `logs/` | Run log, `SBADataConverter_<timestamp>.log` |

The timestamp is to the second, so two runs in the same second share a log file
and the second's reports replace the first's.

Every conversion checks its XML against the bundled XSD itself and leaves out
records that fail it (see [What it checks, and what it does not](#what-it-checks-and-what-it-does-not));
step 4 is a second check that prints what it finds.

> **Known bug:** step 4 only appears when `run.py` finds `.xsd` files **directly
> beside itself** (`_pick_xsd` searches the script directory alone). The bundled
> schemas live in `schemas/`, so on a clean checkout the prompt is skipped and
> no XSD result is printed. The conversion's own check still runs; a record it
> leaves out is an error in the report. To see the XSD result, copy the XSD you
> need next to `run.py`, or validate separately with
> `python -m src.xml_validator` or the web app's **Validate XML** page. Tracked in
> [documentation-audit.md](./documentation-audit.md#code-issues-found-during-the-audit).

When it does run, validation prints the first 10 errors and then a count of the
rest. For Training Client it picks the counseling XSD without asking. The XML is
still written either way — an invalid file plus its error list is more useful
than no file.

The launcher exits `0` when it finishes (whatever step 4 found) or is
cancelled, and `1` when the input file does not exist or the conversion raises —
including when no row could be converted. A refused output path stops it with a
Python traceback (exit `1`). Every other exit waits for Enter, so a
double-clicked window stays open; `run.bat` pauses after the traceback too.

---

## `python -m src.main` — scripted conversion

```bash
python -m src.main convert <converter_type> --input <csv> [options]
```

Run it from the repository root, where `python -m` finds `src`; `logs/` and
`reports/` are then created there. From any other folder, set `PYTHONPATH` to
the repository root — that folder then becomes the base the writes are confined
to. `python src/main.py` does not work: the module uses relative imports.

### Positional

| Value | Form |
|---|---|
| `counseling` | 641 Counseling |
| `training` | 888 Management Training |
| `training-client` | 641 from per-attendee training rows |

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--input`, `-i` | *(required)* | Path to the input CSV, relative to the current directory |
| `--output`, `-o` | `<input_dir>/<name>_<timestamp>.xml` | Path for the output XML |
| `--log-level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--log-dir` | `logs` | Where run logs go (`SBADataConverter_<timestamp>.log`) |
| `--report-dir` | `reports` | Where validation reports go (`validation_report_<timestamp>.html`, and `validation_issues_<timestamp>.csv` when there are issues) |

A relative `--output`, `--log-dir` or `--report-dir` is resolved against the
[base](#output-path-confinement), which is the current directory unless
`SBA_OUTPUT_BASE` says otherwise.

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

### What it checks, and what it does not

Every converted file is checked against SBA's XSD before it is kept
(`BaseConverter._write_valid_xml`): the bundled schema in `schemas/`, or the one
in `SCHEMAS_DIR` when that is set ([configuration.md](./configuration.md#about-schemas_dir)).
A record that fails is left out, with an error per XSD message naming its row and
column, and the file is written again, so the file kept passes the XSD. When
the file fails but no record on its own does, the file is kept and the report
carries one file-level error quoting the first three XSD messages. Without the
schema file — a broken install — the XML is written unchecked. A pass is
silent; records left out are counted on the console (`Left out N record(s) that
failed XSD validation`) and named in the report.

It does **not** check the header row. The required-column tier
([csv-reference.md](./csv-reference.md#requirement-tiers)) is the web worker's
alone, so a counseling CSV with only a `Contact ID` column converts here and
passes the XSD: `Race` is filed as `Prefer not to say` and 0.5 contact hours a
session, each with a warning, while `Telephone`, `English` and not-in-business
are filed without one ([csv-reference.md](./csv-reference.md#counseling-form-641)).

To check a file again, or one made elsewhere:

```bash
python -m src.xml_validator --xmlfile output/counseling.xml \
  --xsd schemas/SBA_NEXUS_Counseling-2-14.xsd
```

Remember that `training-client` output validates against the **counseling**
schema, not the training one.

### Exit codes

`0` on success. `1` when:

- the input file does not exist (the log file has been created by then);
- no row could be converted — an empty file, every row without its ID, or every
  record rejected by the schema — in which case no XML and no report is written,
  and the reason is in the log;
- `--output` or `--log-dir` is outside the base: a Python traceback, before
  anything is converted;
- `--report-dir` is outside the base: logged, after the XML is written;
- any other error during conversion or reporting (logged with a traceback at the
  configured log level).

Data-quality issues do not affect the exit code: a conversion that records
hundreds of warnings, or errors on rows it still files, exits `0`, as does one
whose schema check left records out. If you need CI to fail on them, read the
issues CSV (its `severity` column) yourself. `src.xml_validator` exits `1` only
for a file that still fails the XSD, which after this check is only the case no
single record explains.

---

## Output path confinement

The conversion's writes — XML, reports, logs — are confined to a base directory.
Passing a path outside it fails with *"Refusing to write outside …"*, exit `1`:
a Python traceback, except for `--report-dir`, which is refused with a logged
error once the XML is written. This is a path-traversal guard
(`src/path_safety.resolve_within`), and it applies to `src.main`'s `--output`,
`--report-dir` and `--log-dir` alike, to the launcher's output path, `logs/` and
`reports/`, and to the fixer's `--log-file`. A relative path is resolved against
the base, not the current directory.

The validator's and the fixer's `--directory` are held to the same base, as is
their output directory: `--directory` names the folder the glob walks (and,
without an output directory, rewrites in place), and `--pattern` must be a bare
file-name glob: one with a directory part, such as `../*.xml`, is refused. A
file the glob reaches through a symlink that leads outside the folder is skipped
with a warning.

The fixer's and the validator's single-file mode is **not** confined:
`--file`/`--xmlfile` and `--output` are used as given, and the fixer's backup is
written beside the file.

The base is:

- **`SBA_OUTPUT_BASE` if set** — an explicit environment override.
- Otherwise, **the current working directory** for `src.main`, the fixer and
  the validator, and **the folder containing `run.py`** for the launcher.

There is one deliberate exception: when `--output` is omitted, the XML is written
next to the input file and confined to the *input's* directory, so an absolute
`--input` still works and its output lands beside it.

To write somewhere else:

```bash
SBA_OUTPUT_BASE=/srv/sba-output python -m src.main convert counseling \
  --input report.csv --output /srv/sba-output/counseling.xml
```

`logs/` and `reports/` then land in `/srv/sba-output` too, since the defaults are
relative to the base.

For the launcher, `SBA_OUTPUT_BASE` can only widen the base to a folder that
contains `run.py`'s: it always writes `logs/` and `reports/` beside `run.py`, so
with any other base the default output is refused at step 3, and a typed path
inside the base gets past step 3 only for the log folder to be refused after
the confirmation. Nothing is converted either way.

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
| `--output`, `-o` | Output file or directory; default: the input, rewritten in place |
| `--no-backup` | Do not back up the original |
| `--recursive`, `-r` | Recurse into subdirectories (with `--directory`); an output directory mirrors them |
| `--pattern` | Glob for directory mode (default `*.xml`) |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` (default `INFO`) |
| `--log-file` | A switch, not a path: also write the log to `sba_xml_fixer_wrapper_<timestamp>.log` in the base (the current directory) |

The backup is single-file only. Fixing a `--file` in place first copies it to
`<file>.<timestamp>.bak.fromwrapper`, even when nothing then moves; directory
mode makes no backups, in place or not. In directory mode the console and the
log file get the summary and the names of the files that did not pass; each
failing file's XSD errors are printed bare, and the per-file progress lines are
not shown at all.

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
listed, since reordering cannot fix a wrong value or a missing element, and the
reordered file is written all the same. In directory mode the summary counts the
files that pass, still fail, and could not be fixed, and names each one that did
not pass. A refused `--directory`, output directory or `--pattern` is a Python
traceback, also `1`.

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
| `--directory` | A directory of XML files (mutually exclusive with `--xmlfile`), with `--recursive` (`-r`) and `--pattern` as above |
| `--xsd` | The schema to validate against, and with `--fix` to order by (default with `--fix`: the root element's schema) |
| `--output` | Where `--fix` writes (file, or directory with `--directory`); default in place, with no backup |
| `--fix` | Repair the order as `fix_sba_xml` does, then re-validate the result |
| `--add-missing` | With `--fix`: add a missing `CurrentlyInBusiness` to `ClientIntake` as `Undetermined`, with a warning naming each record. Other missing required elements (`Race`) are reported, not added — no answer would be true for every client |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` (default `INFO`) |

Without `--fix` there is no default schema: `--xmlfile` or `--directory` alone
checks nothing. With both `--xsd` and `--fix`, the original is validated first
(its errors logged), then fixed; the exit code is the fixed file's. With
`--fix`, an `--xsd` whose root element is not the file's is refused as not
fixable.

**Exit codes:** `0` when the file (with `--fix`, the fixed file) passes the
schema, or when there was nothing to check. `1` when it fails, or could not be
fixed; in directory mode, when any file did. A refused `--directory`, `--output`
directory or `--pattern` is a Python traceback, also `1`.

---

## Logging

`src/logging_util.ConversionLogger` writes to the console and, when file logging
is on, to a timestamped file: in `--log-dir` for `src.main` and `logs/` for
`run.py` (always on), in the base for the fixer with `--log-file`, and never for
the validator. Each file rotates at 10 MB, keeping five backups
(`RotatingFileHandler`), but every run starts a new timestamped file and nothing
deletes old ones, so a job run on a schedule accumulates one file per run —
prune them externally.

Tracebacks are logged with `exc_info=True`. If your logs are exposed anywhere,
treat them as potentially containing internal paths.
