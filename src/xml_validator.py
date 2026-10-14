"""
XML validator and fixer utility for SBA Counseling (Form 641) and Training
(Form 888) XML. This module validates files against SBA's XSDs and puts their
elements back in the order the schema requires.
"""

import functools
import os
import shutil
import sys
import threading
from dataclasses import dataclass, field

from lxml import etree

import logging
import re

try:
    from .path_safety import output_base, resolve_within
except ImportError:
    from path_safety import output_base, resolve_within

try:
    from .schema_rules import load_rules, schema_path
except ImportError:
    # Imported as a top-level module, with src/ on sys.path (fix_sba_xml and
    # the tests do this): schema_rules imports its siblings relative to the
    # package, so it is reached through the package.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.schema_rules import load_rules, schema_path


# Logger will be instantiated in main() using ConversionLogger,
# but for standalone functions we provide a fallback
logger = logging.getLogger(__name__)

def _setup_sys_path():
    """Ensure the script can be run standalone by adding its directory to sys.path."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ConversionLogger is imported lazily in main() to avoid breaking package imports

def _is_within(path, base):
    """True when `path` is `base` or sits underneath it.

    The separator suffix matters: a bare ``startswith(base)`` also accepts
    sibling directories that merely share a prefix, so ``/data-evil/x.xml``
    passed as being inside ``/data``. Mirrors src/path_safety.resolve_within.
    """
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def _validate_file_paths(xml_file, xsd_file, enforce_data_dir=False):
    """Resolve and validate file paths against traversal. Returns (xml_path, xsd_path) or an error dict."""
    xml_file = os.path.realpath(xml_file)
    xsd_file = os.path.realpath(xsd_file)
    if enforce_data_dir:
        _data_dir_env = os.environ.get("DATA_DIR", "")
        if _data_dir_env:
            _data_dir = os.path.realpath(_data_dir_env)
            if not _is_within(xml_file, _data_dir):
                return {"is_valid": False, "errors": ["Invalid XML file path"]}
    # os.path.isabs, not startswith(os.sep): on Windows a realpath'd path looks
    # like "C:\\...", which does not start with a separator, so this check
    # rejected *every* schema and made validation fail on the one platform
    # run.bat/setup.bat exist to serve.
    if not os.path.isabs(xsd_file):
        return {"is_valid": False, "errors": ["Invalid XSD file path"]}
    return xml_file, xsd_file


# What validate_against_xsd reports when libxml2 gives up on the document
# (an invalid email its pattern engine backtracks on too long): no line, and
# every other error in the file goes unreported with it.
VALIDATOR_GAVE_UP = "SBA's schema validator could not finish checking this"

# How validate_against_xsd's error for a document that isn't well-formed
# XML begins; libxml2's own message follows.
XML_PARSE_ERROR = "XML parse error"

# What the validator and the fixer say about a document whose DOCTYPE
# declares (or that uses) entities.
ENTITIES_NOT_SUPPORTED = "DTD/entity declarations are not supported"


def _parser():
    """The parser for every document the tool is given to check or fix.

    Entities are never expanded and nothing is fetched (no XXE, no billion
    laughs), and DTD attribute defaults are not applied, so the validator and
    the fixer see the same document. CDATA sections are kept so the fixer
    writes back what it read.
    """
    return etree.XMLParser(resolve_entities=False, no_network=True, strip_cdata=False)


def _entity_problem(tree):
    """Why this document's entities stop it being checked or fixed, or None.

    Expanding entities is how an XML file reads files off the server or grows
    to gigabytes, so the tool never does; the fixer used defusedxml, which
    refuses any entity declaration, for the same reason. Left unexpanded, an
    entity reference stops libxml2's schema check with an "internal error".
    So a file with them is refused with what to change, by both routes alike.
    """
    if not tree.docinfo.doctype:
        return None  # no DOCTYPE: an undeclared entity is already a parse error
    dtd = tree.docinfo.internalDTD
    names = [entity.name for entity in dtd.iterentities()] if dtd is not None else []
    if not names:
        # Used, but declared in an external DTD the parser never reads.
        names = sorted({node.name for node in tree.iter(etree.Entity)})
    if not names:
        return None
    shown = ", ".join(f"&{name};" for name in names[:3])
    if len(names) > 3:
        shown += f" and {len(names) - 3} more"
    noun = "entity" if len(names) == 1 else "entities"
    return (f"{ENTITIES_NOT_SUPPORTED}: this file's DOCTYPE declares or uses the {noun} {shown}. "
            "Write each value out in full, remove the DOCTYPE, and try again.")


def _validate(xmlschema, xml_doc):
    problem = _entity_problem(xml_doc)
    if problem:
        return {"is_valid": False, "errors": [problem]}
    try:
        is_valid = xmlschema.validate(xml_doc)
    except etree.XMLSchemaValidateError as e:
        return {"is_valid": False, "errors": [f"{VALIDATOR_GAVE_UP} ({e})."]}
    errors = [] if is_valid else [f"Line {error.line}: {error.message}" for error in xmlschema.error_log]
    return {"is_valid": is_valid, "errors": errors}


def validate_xml_content(content: bytes, xsd_file):
    """validate_against_xsd for a document held in memory, against a schema
    compiled once per path: the converters check records one at a time."""
    try:
        xmlschema, lock = _compiled_schema(xsd_file)
        document = etree.fromstring(content, _parser()).getroottree()
    except etree.XMLSyntaxError as e:
        return {"is_valid": False, "errors": [f"{XML_PARSE_ERROR}: {e}"]}
    # One check at a time per schema, as schema_rules._ValueChecker does: the
    # worker converts in several threads, and an XMLSchema's error log belongs
    # to the object, so two checks at once read each other's errors -- another
    # upload's values -- or none at all.
    with lock:
        return _validate(xmlschema, document)


@functools.lru_cache(maxsize=8)
def _compiled_schema(xsd_file):
    """(the compiled schema, the lock its callers take to use it)."""
    return etree.XMLSchema(etree.parse(xsd_file, etree.XMLParser(resolve_entities=False))), threading.Lock()


def validate_against_xsd(xml_file, xsd_file, enforce_data_dir=False):
    """
    Validate XML against an XSD schema.

    Args:
        xml_file: Path to the XML file
        xsd_file: Path to the XSD schema file
        enforce_data_dir: If True, require xml_file to be under DATA_DIR

    Returns:
        Dict with 'is_valid' bool and 'errors' list
    """
    try:
        path_result = _validate_file_paths(xml_file, xsd_file, enforce_data_dir=enforce_data_dir)
        if isinstance(path_result, dict):
            return path_result
        xml_file, xsd_file = path_result

        xmlschema_doc = etree.parse(xsd_file, parser=etree.XMLParser(resolve_entities=False))
        xmlschema = etree.XMLSchema(xmlschema_doc)
        xml_doc = etree.parse(xml_file, parser=_parser())

        return _validate(xmlschema, xml_doc)
    except etree.XMLSyntaxError as e:
        # Unparseable XML is a validation *result*, not an internal error:
        # surface the parse message so callers (e.g. the worker's /validate-xsd
        # route) can show the user what is wrong with the document.
        logger.exception("Error during XML/XSD validation")
        return {"is_valid": False, "errors": [f"{XML_PARSE_ERROR}: {e}"]}
    except (OSError, etree.XMLSchemaError, etree.XMLSchemaParseError):
        logger.exception("Error during XML/XSD validation")
        return {"is_valid": False, "errors": ["Validation error"]}

def extract_validation_details(error_message):
    """
    Extract element names and expected elements from a validation error message.

    Args:
        error_message: The validation error message

    Returns:
        Tuple (invalid_element, expected_elements)
    """
    invalid_match = re.search(r"Invalid content was found starting with element '([^']+)'", error_message)
    expected_match = re.search(r"One of '{([^}]+)}' is expected", error_message)

    invalid_element = invalid_match.group(1) if invalid_match else None
    expected_elements = expected_match.group(1).split(', ') if expected_match else []

    return invalid_element, expected_elements


# The required ClientIntake elements --add-missing fills, each with the one
# answer that claims nothing about the client. It used to file
# CurrentlyInBusiness as 'No', an answer the client never gave. Race has no
# such answer ('Prefer not to say' is the client's own choice), so a missing
# Race is reported, not filled.
_UNDETERMINED_ANSWERS = {"CurrentlyInBusiness": "Undetermined"}


def add_missing_required_elements(client_intake, record_id):
    """
    Add the required ClientIntake elements _UNDETERMINED_ANSWERS can fill.

    Each one is still an answer the file did not give, so each is a warning
    naming the record.

    Args:
        client_intake: ClientIntake element (lxml or ElementTree)
        record_id: ID of the counseling record (for logging)

    Returns:
        True when an element was added.
    """
    elements_added = False
    for tag, answer in _UNDETERMINED_ANSWERS.items():
        if client_intake.find(tag) is not None:
            continue
        # makeelement + append rather than SubElement: the element may be
        # lxml's (the fixer's) or ElementTree's, and each library's
        # SubElement takes only its own kind of parent.
        element = client_intake.makeelement(tag, {})
        element.text = answer
        if len(client_intake):
            # Take the last child's place in the indentation.
            last = client_intake[-1]
            element.tail = last.tail
            last.tail = client_intake[-2].tail if len(client_intake) > 1 else client_intake.text
        client_intake.append(element)
        logger.warning(f"Record {record_id}: ClientIntake had no {tag}, which SBA requires; "
                       f"added '{answer}'. Change it to Yes or No if the client said.")
        elements_added = True
    return elements_added


# The schema a file is fixed by, from its root element, unless one is named.
_SCHEMA_FOR_ROOT = {
    "CounselingInformation": "counseling",      # Form 641, and training-client output
    "ManagementTrainingReport": "training",     # Form 888
}


@dataclass
class FixResult:
    """What fix_element_order did with one file (and, after
    fix_and_revalidate, whether what it wrote passes the schema)."""

    ok: bool                       # False: nothing was written, and `error` says why
    error: str | None = None
    xsd_file: str | None = None    # the schema whose order was applied
    reordered: int = 0             # elements whose children were put back in order
    added: list[str] = field(default_factory=list)    # what --add-missing filled in
    missing: list[str] = field(default_factory=list)  # required elements it could not
    valid: bool | None = None      # set by fix_and_revalidate
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        """Whether any element moved or was added: nothing else is changed."""
        return bool(self.reordered or self.added)


@functools.lru_cache(maxsize=8)
def _child_order(xsd_file):
    """Each element path's children, ranked in the order the schema lists them.

    load_rules walks the schema depth-first and inserts each element's path
    before its children's, so a parent's child paths appear in it in schema
    order. SBA's schemas repeat single elements but never a whole sequence,
    so sorting children into this order is always the order they require.
    """
    order = {}
    for path in load_rules(xsd_file):
        if len(path) > 1:
            siblings = order.setdefault(path[:-1], {})
            siblings.setdefault(path[-1], len(siblings))
    return order


def _sort_children(parent, rank):
    """Stable-sort parent's child elements by `rank` (tag -> position).

    Tags the rank doesn't know go last, and repeated elements keep their
    order. A comment or processing instruction travels with the element after
    it, and the whitespace between children stays where it was, so the file's
    indentation doesn't change. Returns True when an element moved.
    """
    groups, pending = [], []
    for node in parent:
        pending.append(node)
        if isinstance(node.tag, str):  # an element, not a comment or PI
            groups.append(pending)
            pending = []
    unknown = len(rank)
    ordered = sorted(groups, key=lambda group: rank.get(group[-1].tag, unknown))
    if all(a is b for a, b in zip(ordered, groups, strict=True)):
        return False
    tails = [node.tail for node in parent]
    parent[:] = [node for group in ordered for node in group] + pending
    for node, tail in zip(parent, tails, strict=True):
        node.tail = tail
    return True


def _reorder_tree(root, order):
    """Sort the children of every element the schema knows; returns how many
    elements had a child moved."""
    reordered = 0
    stack = [(root, (root.tag,))]
    while stack:
        element, path = stack.pop()
        rank = order.get(path)
        if rank is None:
            continue  # not in the schema, so neither are its children
        if _sort_children(element, rank):
            reordered += 1
        stack.extend((child, path + (child.tag,)) for child in element if isinstance(child.tag, str))
    return reordered


def _add_missing(root, rules, result):
    """--add-missing: fill what add_missing_required_elements can in each
    ClientIntake, and report the required elements it can't."""
    intake_path = (root.tag, "CounselingRecord", "ClientIntake")
    required = [path[-1] for path, rule in rules.items() if path[:-1] == intake_path and not rule.optional]
    for position, record in enumerate(root.findall("CounselingRecord"), 1):
        record_id = (record.findtext("PartnerClientNumber") or "").strip() or f"#{position}"
        client_intake = record.find("ClientIntake")
        if client_intake is None:
            continue  # the schema check reports it; there is nothing to add to
        had = {child.tag for child in client_intake}
        if add_missing_required_elements(client_intake, record_id):
            result.added += [f"Record {record_id}: {child.tag}" for child in client_intake
                             if isinstance(child.tag, str) and child.tag not in had]
        for tag in required:
            if client_intake.find(tag) is None:
                message = (f"Record {record_id}: ClientIntake has no {tag}, which SBA requires; "
                           "--add-missing can't supply it, so add it at the source.")
                logger.warning(message)
                result.missing.append(message)


def _not_fixed(reason):
    return FixResult(ok=False, error=reason)


def _same_file(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


def fix_element_order(xml_file, output_file=None, add_missing_elements_flag=False, xsd_file=None):
    """
    Put every element's children in the order SBA's schema lists them.

    The order is read from the schema itself: the one the root element belongs
    to (CounselingInformation: Form 641, ManagementTrainingReport: Form 888),
    unless xsd_file names one. The file is read the way validate_against_xsd
    reads it and written with the same library, so comments, processing
    instructions, the DOCTYPE and characters such as a CR written as &#13;
    come through as they were. Nothing but the order changes, unless
    add_missing_elements_flag adds what add_missing_required_elements can.

    Args:
        xml_file: Path to the XML file
        output_file: Path to save the fixed XML file (if None, will modify the original)
        add_missing_elements_flag: If True, add missing required ClientIntake elements.
        xsd_file: The schema to order by (default: from the root element)

    Returns:
        A FixResult. Nothing is written when it is not ok.
    """
    if output_file is None:
        output_file = xml_file
    try:
        tree = etree.parse(xml_file, _parser())
    except etree.XMLSyntaxError as e:
        return _not_fixed(f"{XML_PARSE_ERROR}: {e}")
    except OSError as e:
        return _not_fixed(f"Could not read the file: {e}")
    problem = _entity_problem(tree)
    if problem:
        return _not_fixed(problem)

    root = tree.getroot()
    if xsd_file is None:
        if root.tag not in _SCHEMA_FOR_ROOT:
            return _not_fixed((
                f"The root element is <{root.tag}>, not <CounselingInformation> (Form 641) or "
                "<ManagementTrainingReport> (Form 888), so there is no SBA schema to order it by."))
        xsd_file = schema_path(_SCHEMA_FOR_ROOT[root.tag])
    try:
        order = _child_order(xsd_file)
    except (OSError, etree.XMLSyntaxError) as e:
        return _not_fixed(f"Could not read the schema {xsd_file}: {e}")
    if (root.tag,) not in order:
        return _not_fixed(f"<{root.tag}> is not the root element of {os.path.basename(xsd_file)}.")

    result = FixResult(ok=True, xsd_file=xsd_file)
    if add_missing_elements_flag:
        _add_missing(root, load_rules(xsd_file), result)
    result.reordered = _reorder_tree(root, order)
    try:
        if result.changed:
            tree.write(output_file, encoding="utf-8", xml_declaration=True)
        elif not _same_file(xml_file, output_file):
            # Nothing moved: the output is the input, byte for byte.
            shutil.copyfile(xml_file, output_file)
    except OSError as e:
        return _not_fixed(f"Could not write {output_file}: {e}")
    return result


def fix_and_revalidate(xml_file, output_file=None, add_missing_elements_flag=False, xsd_file=None):
    """fix_element_order, then check what it wrote against the same schema.

    Reordering can't fix a wrong value or a missing element, so a fixed file
    is not a valid one until this says so.
    """
    output_file = output_file or xml_file
    result = fix_element_order(xml_file, output_file, add_missing_elements_flag, xsd_file)
    if result.ok:
        outcome = validate_against_xsd(output_file, result.xsd_file)
        result.valid, result.errors = outcome["is_valid"], outcome["errors"]
    return result


def log_fix_result(result, xml_file, output_file=None, log=None):
    """Say what fix_and_revalidate did and whether the file now passes.

    Returns True only when it does.
    """
    log = log or logger
    output_file = output_file or xml_file
    if not result.ok:
        log.error(f"Could not fix {xml_file}: {result.error}")
        return False
    if result.reordered:
        log.info(f"Put the children of {result.reordered} element(s) in the order "
                 f"{os.path.basename(result.xsd_file)} lists them; saved to {output_file}")
    elif not result.changed and _same_file(xml_file, output_file):
        log.info(f"No element was out of order; {xml_file} is unchanged.")
    else:
        log.info(f"No element was out of order; saved to {output_file}")
    if result.valid:
        log.info(f"{output_file} passes SBA's schema.")
        return True
    log.error(f"{output_file} still fails SBA's schema with {len(result.errors)} error(s), "
              "which reordering can't fix:")
    for i, error_msg in enumerate(result.errors, 1):
        log.error(f"Error {i}: {error_msg}")
    return False


def fix_client_intake_element_order(xml_file, output_file=None, add_missing_elements_flag=False):
    """
    fix_element_order's success alone, for callers written when the fixer
    knew only ClientIntake's order. Every sequence is put in order now.

    Returns:
        Boolean indicating the file was read and written
    """
    result = fix_element_order(xml_file, output_file, add_missing_elements_flag)
    if not result.ok:
        logger.error(f"Could not fix {xml_file}: {result.error}")
    return result.ok


def reorder_elements(parent, element_order):
    """
    Reorder child elements according to the specified order.

    Args:
        parent: Parent element (lxml or ElementTree)
        element_order: List of element names in the correct order

    Returns:
        True when an element moved.
    """
    return _sort_children(parent, {tag: position for position, tag in enumerate(element_order)})

def _resolve_output_path(file_path, input_dir, output_dir):
    """Compute the output path for a file, creating directories as needed."""
    if not output_dir:
        return file_path
    rel_path = os.path.relpath(file_path, input_dir)
    # Confine the per-file output within output_dir: a crafted rel_path (e.g.
    # "../..") derived from an input name must not escape it (CWE-22).
    output_path = resolve_within(output_dir, rel_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    return output_path

def _validate_and_log(file_path, xsd_file, label=""):
    """Validate an XML file against XSD and log the result. Returns (is_valid, errors)."""
    logger.info(f"Validating {label}file {file_path} against {xsd_file}...")
    result = validate_against_xsd(file_path, xsd_file)
    is_valid, errors = result["is_valid"], result["errors"]
    if is_valid:
        logger.info(f"{label.capitalize() if label else ''}File {file_path} is valid.")
    else:
        log_fn = logger.warning if label == "original " else logger.error
        log_fn(f"{label.capitalize() if label else ''}File {file_path} is NOT valid. Errors: {errors}")
    return is_valid, errors

def _files_within(files, input_dir):
    """Drop glob results that resolve outside ``input_dir``.

    A symlink inside the directory can make the glob return a path that
    escapes the confined input directory even though the directory itself
    (and the pattern) were checked.
    """
    kept = []
    for file_path in files:
        if _is_within(os.path.realpath(file_path), input_dir):
            kept.append(file_path)
        else:
            logger.warning(f"Skipping {file_path}: resolves outside {input_dir}")
    return kept


@dataclass
class DirectorySummary:
    """What process_directory found. A file counts as valid or invalid only
    when it was checked: with fix (after fixing) or with an XSD."""

    files: list[str] = field(default_factory=list)
    valid: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)   # the output that still fails
    failed: list[str] = field(default_factory=list)    # could not be read or fixed

    @property
    def ok(self) -> bool:
        return not self.invalid and not self.failed

    def describe(self) -> str:
        if not (self.valid or self.invalid or self.failed):
            return f"{len(self.files)} file(s) found; none checked (no fix requested, no XSD)."
        return (f"{len(self.files)} file(s): {len(self.valid)} pass SBA's schema, "
                f"{len(self.invalid)} still fail it, {len(self.failed)} could not be fixed.")


def _process_file(file_path, input_dir, output_dir, xsd_file, fix, add_missing_elements_flag,
                  summary: DirectorySummary) -> None:
    """Validate and/or fix one file of process_directory's, recording in
    `summary` whether it passes the schema, still fails it, or could not be
    fixed."""
    logger.info(f"--- Processing file: {file_path} ---")
    summary.files.append(file_path)
    current_output_path = _resolve_output_path(file_path, input_dir, output_dir)

    is_valid, checked_path = None, file_path
    if xsd_file:
        is_valid, _ = _validate_and_log(file_path, xsd_file, "original ")

    if fix:
        logger.info(f"Attempting to fix {file_path} -> {current_output_path}")
        result = fix_and_revalidate(file_path, current_output_path, add_missing_elements_flag, xsd_file)
        log_fix_result(result, file_path, current_output_path)
        if not result.ok:
            summary.failed.append(file_path)
            return
        # A file used to count as "processed successfully" once it was
        # rewritten, however it then validated.
        is_valid, checked_path = result.valid, current_output_path

    if is_valid is None:
        logger.info(f"File {file_path} found (no fix requested, no XSD for validation).")
    elif is_valid:
        summary.valid.append(checked_path)
    else:
        summary.invalid.append(checked_path)


def process_directory(input_dir, output_dir=None, recursive=False, pattern="*.xml", xsd_file=None, fix=False, add_missing_elements_flag=False):
    """
    Process all XML files in a directory.
    (Function adapted from fix-sba-xml.py)

    Args:
        input_dir: Input directory containing XML files
        output_dir: Output directory for fixed files (default: same as input, overwrites if fix is True)
        recursive: Whether to recursively process subdirectories
        pattern: File pattern to match
        xsd_file: Path to XSD schema for validation (optional; with fix, the
                  schema of each file's root element is used)
        fix: Boolean, if True, fix the XML files.
        add_missing_elements_flag: Boolean, if True and fix is True, add missing elements.

    Returns:
        A DirectorySummary: the files found, and which pass the schema, still
        fail it, or could not be fixed.
    """
    import glob

    # Confine the input directory within the allowed base (CWE-22): --directory
    # comes straight from the command line, and a "../.." or absolute path would
    # otherwise point the glob (and, with --fix, the in-place rewrite) anywhere
    # on the filesystem. Same base as --output; SBA_OUTPUT_BASE widens it.
    input_dir = resolve_within(output_base(), input_dir)
    # --pattern is caller-controlled too. It is a file-name glob, so it must
    # carry no directory part: "../*.xml" would otherwise walk the glob out of
    # the confined directory. basename() is the sanitizer; anything it changes
    # was a path, not a pattern.
    if os.path.basename(pattern) != pattern:
        raise ValueError(
            f"--pattern must be a file name pattern such as '*.xml', not a path: {pattern!r}"
        )
    pattern = os.path.basename(pattern)
    logger.info(f"Processing XML files in directory: {input_dir}")
    if recursive:
        logger.info(f"Recursive mode enabled, pattern: {pattern}")
    if output_dir:
        # Confine the chosen output directory within the allowed base (CWE-22).
        output_dir = resolve_within(output_base(), output_dir)
        logger.info(f"Output directory: {output_dir}")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            logger.info(f"Created output directory: {output_dir}")

    search_pattern = os.path.join(input_dir, "**", pattern) if recursive else os.path.join(input_dir, pattern)
    files = _files_within(glob.glob(search_pattern, recursive=recursive), input_dir)
    logger.info(f"Found {len(files)} XML files to process.")

    summary = DirectorySummary()
    for file_path in files:
        _process_file(file_path, input_dir, output_dir, xsd_file, fix, add_missing_elements_flag, summary)

    logger.info(f"Finished processing directory. {summary.describe()}")
    return summary


def parse_arguments():
    """Parse command line arguments."""
    import argparse

    parser = argparse.ArgumentParser(description='XML Validator and Fixer for SBA Counseling and Training XML.')

    # Input: single file or directory
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--xmlfile', help='Path to a single XML file to process.')
    input_group.add_argument('--directory', help='Path to a directory of XML files to process.')

    # XSD for validation
    parser.add_argument('--xsd', help='Path to the XSD schema file for validation (and, with --fix, the order to fix by).')

    # Output options
    parser.add_argument('--output', help='Path to save the fixed XML file (for single file mode) or output directory (for directory mode).')

    # Directory processing options
    parser.add_argument('--recursive', '-r', action='store_true', help='Recursively process subdirectories (used with --directory).')
    parser.add_argument('--pattern', default="*.xml", help='File pattern for XML files (default: *.xml, used with --directory).')

    # Fixing options
    parser.add_argument('--fix', action='store_true', help='Put elements in the order the schema requires, then re-validate the result.')
    parser.add_argument('--add-missing', action='store_true',
                        help="When fixing, also add a missing CurrentlyInBusiness to ClientIntake as 'Undetermined' "
                             "(a warning per record). Other missing required elements are reported, not added.")

    # Logging options
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        default='INFO', help='Logging level.')

    return parser.parse_args()

def _validate_and_report(xml_file, xsd_file, logger):
    """Validate XML against XSD and log detailed error information. Returns True when valid."""
    logger.info(f"Validating {xml_file} against {xsd_file}...")
    result = validate_against_xsd(xml_file, xsd_file)
    is_valid, errors = result["is_valid"], result["errors"]
    if is_valid:
        logger.info("XML is valid!")
        return True
    logger.error(f"XML is not valid. Found {len(errors)} errors:")
    for i, error_msg in enumerate(errors, 1):
        logger.error(f"Error {i}: {error_msg}")
        invalid_element, expected_elements = extract_validation_details(error_msg)
        if invalid_element:
            logger.info(f"  Invalid element: '{invalid_element}'")
        if expected_elements:
            logger.info(f"  Expected elements: {', '.join(expected_elements)}")
    return False

def _fix_single_file(args, logger):
    """Fix a single XML file and re-validate it. Returns True when the fixed file is valid."""
    output_file_path = args.output if args.output else args.xmlfile
    logger.info(f"Fixing XML file '{args.xmlfile}' and saving to '{output_file_path}'...")
    result = fix_and_revalidate(args.xmlfile, output_file_path, args.add_missing, args.xsd)
    return log_fix_result(result, args.xmlfile, output_file_path, logger)

def process_single_file(args, logger):
    """Process a single XML file for validation and/or fixing.

    Returns the exit status: 1 when the file (with --fix, the fixed file)
    fails the schema or could not be fixed.
    """
    logger.info(f"Mode: Processing single file '{args.xmlfile}'")

    passes = True
    if args.xsd:
        passes = _validate_and_report(args.xmlfile, args.xsd, logger)

    if args.fix:
        passes = _fix_single_file(args, logger)
    elif not args.xsd:
        logger.info(f"XML file '{args.xmlfile}' processed (no fix requested, no XSD for validation).")
    return 0 if passes else 1

def main():
    """Main entry point for the script. Returns the exit status: 0 only when
    every file checked passes the schema."""
    _setup_sys_path()
    from logging_util import ConversionLogger

    args = parse_arguments()

    # Setup logger using ConversionLogger
    log_level_val = getattr(logging, args.log_level.upper(), logging.INFO)
    # For xml-validator, default to console-only logging unless a --log-file arg is added later.
    # The module's own logger, so what process_directory and the fixer log
    # reaches the console too: it has no handler otherwise.
    logger = ConversionLogger(
        logger_name=__name__,
        log_level=log_level_val,
        log_to_file=False
    ).logger # Get the actual logger instance

    if args.directory:
        # Process directory
        logger.info(f"Mode: Processing directory '{args.directory}'")
        output_dir_for_process = args.output # If None, process_directory handles it (in-place if fix is True)

        summary = process_directory(
            input_dir=args.directory,
            output_dir=output_dir_for_process,
            recursive=args.recursive,
            pattern=args.pattern,
            xsd_file=args.xsd,
            fix=args.fix,
            add_missing_elements_flag=args.add_missing
        )
        return 0 if summary.ok else 1
    elif args.xmlfile:
        return process_single_file(args, logger)
    else:
        # Should not happen due to mutually_exclusive_group
        logger.error("No input specified. Use --xmlfile or --directory.")
        return 2

if __name__ == "__main__":
    sys.exit(main())
