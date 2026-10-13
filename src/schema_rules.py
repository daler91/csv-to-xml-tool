"""
Enforce the bundled XSDs' value facets on each record before it is written.

The converters build every element in schema order, but until this module they
never checked the *values* against the schema's facets: a 41-character last
name, a middle name where the XSD allows one character, ``yes`` for a
``YesNoType``, ``Ontario`` for a US-state enumeration, a vertical tab pasted in
from Word. Each one made the whole file fail SBA validation, and the row had
"converted successfully" with nothing in the report.

Rather than wiring a check into each of ~80 call sites, the facets are read
from the XSD itself -- so the rules can never drift from the schema -- and
applied to each finished record element by :class:`SchemaGuard`:

* Characters XML 1.0 cannot carry are removed from every element.
* An enumeration value is matched case- and whitespace-insensitively (and Yes/No
  synonyms such as ``Y``/``true`` are resolved) to the schema's own spelling.
* A string over ``maxLength`` is truncated, with a ``TRUNCATED_VALUE`` warning
  -- except identifiers, which are never altered.
* A value that still violates a facet is dropped when the schema lets the
  element (or its immediate optional parent) be omitted, with a warning naming
  what was lost. Otherwise the record cannot be filed: it is recorded as an
  error, and ``enforce`` returns the reasons so the converter leaves the record
  out of the XML rather than writing a file SBA would reject.
* Repeats beyond the schema's ``maxOccurs`` are dropped, with a warning.

Whether a value is valid is finally decided by libxml2, the validator the
output is checked with, against the element's own simple type: XSD regexes are
a different dialect from Python's (``\\d``, ``\\w``, ``^``/``$`` and character
classes all differ), Python's backtracking engine hangs on SBA's email
pattern, and Python's ``Decimal``/``date`` parsers accept forms ``xs:decimal``
and ``xs:date`` don't. The Python checks before it only canonicalize values and
explain, in the user's terms, what is wrong.
"""

from __future__ import annotations

import copy
import datetime
import functools
import logging
import os
import re
import threading
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import TYPE_CHECKING

from lxml import etree

from .config import ValidationCategory
from . import data_cleaning
from . import xsd_error_mapping

if TYPE_CHECKING:
    from .validation_report import ValidationTracker
    # Annotations only: the guard walks Element trees the converters built
    # and never parses XML with the stdlib (the XSD is read with lxml above).
    from .xml_utils import Element

logger = logging.getLogger(__name__)

_XS = "{http://www.w3.org/2001/XMLSchema}"

# Bundled next to src/ in every layout: the repository, the CLI zip, and the
# worker image (which copies both to /app). SCHEMAS_DIR overrides, matching
# the worker's own setting.
_DEFAULT_SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas")

XSD_FILES = {
    "counseling": "SBA_NEXUS_Counseling-2-14.xsd",
    "training": "SBA_NEXUS_Training-2-25-2025.xsd",
    "training-client": "SBA_NEXUS_Counseling-2-14.xsd",
}

# Identifiers are never truncated or rewritten: a shortened Contact ID would
# file the session against a different client. An over-length one is reported
# as an error instead.
_IDENTIFIER_TAGS = frozenset({"PartnerClientNumber", "PartnerSessionNumber", "PartnerTrainingNumber"})

# XML 1.0 Char production: everything below 0x20 except tab, LF and CR, plus
# the two non-characters at the top of the BMP and lone surrogates.
_ILLEGAL_XML_CODEPOINTS = frozenset([
    *range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20),
    0xFFFE, 0xFFFF,
    *range(0xD800, 0xE000),
])
# str.translate table mapping each of them to a space.
_ILLEGAL_TO_SPACE = dict.fromkeys(_ILLEGAL_XML_CODEPOINTS, " ")

# xs:decimal's lexical space. Python's Decimal also accepts exponents, NaN,
# Infinity and non-ASCII digits ("１９１５３"), none of which the schema allows.
_DECIMAL_LEXICAL = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)")
# xs:date's lexical space for four-digit years; fromisoformat also accepts ISO
# basic and week dates ("20250115", "2025-W03-3"), which xs:date does not.
_DATE_LEXICAL = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(Z|[+-][0-9]{2}:[0-9]{2})?")
_INTEGER_BASES = {"integer", "int", "positiveInteger", "nonNegativeInteger", "long", "short"}
_DECIMAL_BASES = {"decimal"} | _INTEGER_BASES

# The two Yes/No enumerations get the same synonyms the converter's own
# is_affirmative/is_negative helpers accept.
_YES_NO_TYPES = {"YesNoType", "YesNoUndeterminedType"}


@dataclass(frozen=True)
class ElementRule:
    """The facets that constrain one element's text, as declared in the XSD."""

    optional: bool
    base: str | None = None          # built-in xs: type the value restricts, e.g. "string"
    type_name: str | None = None     # named simpleType, e.g. "YesNoType"
    max_length: int | None = None
    length: int | None = None
    enumeration: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()   # as written in the XSD; only libxml2 runs them
    min_inclusive: Decimal | None = None
    max_inclusive: Decimal | None = None
    has_children: bool = False       # complex type: its own text is not checked
    max_occurs: int | None = 1       # None: unbounded
    # The element's simple type, as libxml2 judges it (see _ValueChecker).
    checker: _ValueChecker | None = field(default=None, compare=False, repr=False)
    check_tag: str | None = None


class _ValueChecker:
    """Validates single values with libxml2 against the simple types of one XSD.

    Built once per schema: a small schema holding a copy of every named
    simpleType and one element per distinct element type (``v0`` typed
    ``YesNoType``, ``v1`` with a copy of an inline restriction, ...). A value is
    accepted exactly when ``<vN>value</vN>`` validates.
    """

    def __init__(self, schema_root) -> None:
        # The source's own prefixes, so "xs:string" in a copied type and in
        # a type reference resolves as it does there.
        self._root = etree.Element(f"{_XS}schema", nsmap=schema_root.nsmap)
        for simple_type in schema_root.findall(f"{_XS}simpleType"):
            self._root.append(copy.deepcopy(simple_type))
        self._tags: dict[str, str] = {}
        self._schema: etree.XMLSchema | None = None
        # One validation at a time: the worker converts in several threads,
        # and an XMLSchema object's error log is shared by its callers.
        self._lock = threading.Lock()
        self.accepts = functools.lru_cache(maxsize=65536)(self._accepts)

    def tag_for(self, type_ref: str, inline_simple) -> str:
        """The element name standing for this type, declaring it on first use."""
        key = type_ref or etree.tostring(inline_simple, encoding="unicode")
        if key not in self._tags:
            tag = self._tags[key] = f"v{len(self._tags)}"
            declaration = etree.SubElement(self._root, f"{_XS}element", name=tag)
            if type_ref:
                declaration.set("type", type_ref)
            else:
                declaration.append(copy.deepcopy(inline_simple))
        return self._tags[key]

    def compile(self) -> None:
        self._schema = etree.XMLSchema(self._root)

    def _accepts(self, tag: str, text: str) -> bool:
        element = etree.Element(tag)
        element.text = text
        with self._lock:
            try:
                return self._schema.validate(etree.ElementTree(element))
            except etree.XMLSchemaValidateError:
                # libxml2 gives up on a regex that backtracks too much -- an
                # invalid email with a dozen dotted labels, after ~2 seconds.
                # Not a value the schema accepts, and dropping it is safe.
                return False


def _local(tag: str) -> str:
    return tag[len(_XS):] if tag.startswith(_XS) else tag


def _merge_restriction(restriction, simple_types: dict, facets: dict) -> None:
    """Fold a restriction's facets into `facets`, following named base types.

    Facets on the derived type win over the base's (they can only narrow it),
    so the base is folded in first and then overwritten.
    """
    base = restriction.get("base", "")
    if base.startswith("xs:"):
        facets.setdefault("base", base[3:])
    elif base in simple_types:
        facets.setdefault("type_name", base)
        _merge_simple_type(simple_types[base], simple_types, facets)
    enumeration, patterns = [], []
    for facet in restriction:
        if not isinstance(facet.tag, str):
            continue  # comment
        name, value = _local(facet.tag), facet.get("value")
        if name == "enumeration":
            enumeration.append(value)
        elif name == "pattern":
            patterns.append(value)
        elif name in ("maxLength", "length"):
            facets[{"maxLength": "max_length", "length": "length"}[name]] = int(value)
        elif name in ("minInclusive", "maxInclusive"):
            facets[{"minInclusive": "min_inclusive", "maxInclusive": "max_inclusive"}[name]] = Decimal(value)
    if enumeration:
        facets["enumeration"] = tuple(enumeration)
    if patterns:
        facets["patterns"] = tuple(patterns)


def _merge_simple_type(simple_type, simple_types: dict, facets: dict) -> None:
    for child in simple_type:
        if isinstance(child.tag, str) and _local(child.tag) == "restriction":
            _merge_restriction(child, simple_types, facets)


def _content_elements(node, repeated: bool = False):
    """Yield (xs:element, repeated) for a complexType's content model,
    descending through sequence/choice/all. `repeated` is True inside a
    compositor that may itself occur more than once, where the element's own
    maxOccurs no longer bounds how often it appears."""
    for child in node:
        if not isinstance(child.tag, str):
            continue
        name = _local(child.tag)
        if name == "element":
            yield child, repeated
        elif name in ("sequence", "choice", "all", "complexType"):
            yield from _content_elements(child, repeated or child.get("maxOccurs", "1") != "1")


def _max_occurs(element, repeated: bool) -> int | None:
    value = element.get("maxOccurs", "1")
    return None if repeated or value == "unbounded" else int(value)


@functools.lru_cache(maxsize=None)
def load_rules(xsd_path: str) -> dict[tuple[str, ...], ElementRule]:
    """Map each element's tag path from the document root to its facets.

    Paths are tuples such as ``("CounselingInformation", "CounselingRecord",
    "ClientRequest", "ClientNamePart1", "Middle")`` because the same tag means
    different things in different places (``Code`` alone has dozens of
    enumerations).
    """
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    schema = etree.parse(xsd_path, parser).getroot()
    simple_types = {st.get("name"): st for st in schema.findall(f"{_XS}simpleType")}
    complex_types = {ct.get("name"): ct for ct in schema.findall(f"{_XS}complexType")}
    rules: dict[tuple[str, ...], ElementRule] = {}
    checker = _ValueChecker(schema)

    def visit(element, parent_path: tuple[str, ...], stack: frozenset,
              repeated: bool = False) -> None:
        path = parent_path + (element.get("name"),)
        facets: dict = {}
        type_ref = element.get("type", "")
        complex_node = None
        if type_ref.startswith("xs:"):
            facets["base"] = type_ref[3:]
            facets["check_tag"] = checker.tag_for(type_ref, None)
        elif type_ref in simple_types:
            facets["type_name"] = type_ref
            _merge_simple_type(simple_types[type_ref], simple_types, facets)
            facets["check_tag"] = checker.tag_for(type_ref, None)
        elif type_ref in complex_types:
            complex_node = complex_types[type_ref]
        else:
            inline_simple = element.find(f"{_XS}simpleType")
            if inline_simple is not None:
                _merge_simple_type(inline_simple, simple_types, facets)
                facets["check_tag"] = checker.tag_for("", inline_simple)
            complex_node = element.find(f"{_XS}complexType")
        rules[path] = ElementRule(
            optional=element.get("minOccurs") == "0",
            has_children=complex_node is not None,
            max_occurs=_max_occurs(element, repeated),
            checker=checker,
            **facets,
        )
        # `stack` holds the named complex types being expanded, so a type that
        # (indirectly) contains itself can't recurse forever. Inline types have
        # no name and can't recur, so they are never added to it.
        if complex_node is not None and type_ref not in stack:
            for child, child_repeated in _content_elements(complex_node):
                visit(child, path, stack | {type_ref} if type_ref else stack, child_repeated)

    for top in schema.findall(f"{_XS}element"):
        visit(top, (), frozenset())
    try:
        checker.compile()
    except etree.XMLSchemaParseError as exc:
        # Values are then judged by the Python checks alone, and the XSD
        # check of the finished file is the backstop for the rest.
        logger.warning(f"Could not build the value checks for {xsd_path}: {exc}")
        rules = {path: replace(rule, checker=None) for path, rule in rules.items()}
    return rules


def schema_path(schema_type: str) -> str:
    return os.path.join(os.environ.get("SCHEMAS_DIR") or _DEFAULT_SCHEMAS_DIR, XSD_FILES[schema_type])


def strip_illegal_xml_chars(text: str) -> str:
    """Replace characters XML 1.0 cannot carry with a space.

    A space, not nothing: the usual source is a line break pasted from Word
    (a vertical tab), and deleting it would glue "123 Main St" to "Suite 5".
    """
    spaced = text.translate(_ILLEGAL_TO_SPACE)
    if spaced == text:
        return text
    return re.sub(r"[ \t]{2,}", " ", spaced).strip()


def count_illegal_xml_chars(text: str) -> int:
    return sum(1 for ch in text if ord(ch) in _ILLEGAL_XML_CODEPOINTS)


def _chars(n: int) -> str:
    return f"{n} character" if n == 1 else f"{n} characters"


def _show(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _normalize_token(value: str) -> str:
    return " ".join(value.split()).casefold()


def _resolve_enumeration(text: str, rule: ElementRule) -> str | None:
    """The schema's own spelling of `text`, or None when it isn't a member."""
    if text in rule.enumeration:
        return text
    wanted = _normalize_token(text)
    for value in rule.enumeration:
        if _normalize_token(value) == wanted:
            return value
    if rule.type_name in _YES_NO_TYPES:
        if data_cleaning.is_affirmative(text):
            return "Yes"
        if data_cleaning.is_negative(text):
            return "No"
    return None


def _check_value(text: str, rule: ElementRule) -> tuple[str, str | None]:
    """(possibly canonicalized text, reason it violates a facet or None)."""
    if rule.enumeration:
        resolved = _resolve_enumeration(text, rule)
        if resolved is None:
            shown = ", ".join(f"'{v}'" for v in rule.enumeration[:8])
            more = f" (and {len(rule.enumeration) - 8} more)" if len(rule.enumeration) > 8 else ""
            return text, f"is not one of the values SBA accepts: {shown}{more}"
        text = resolved
    if rule.base in _DECIMAL_BASES:
        if not _DECIMAL_LEXICAL.fullmatch(text):
            return text, "is not a number"
        number = Decimal(text)
        if rule.base in _INTEGER_BASES:
            if number != number.to_integral_value():
                return text, "must be a whole number"
            # "12.0" -> "12": same value, integer lexical form. Only a fraction
            # is rewritten -- a leading zero is valid integer syntax, and FIPS
            # codes like "01001" (every Alabama county) depend on it. Cut as
            # text: int() refuses more than 4,300 digits.
            if "." in text:
                whole = text.split(".")[0]
                text = whole if whole.lstrip("+-") else whole + "0"
        if rule.base == "positiveInteger" and number < 1:
            return text, "must be 1 or more"
        if rule.min_inclusive is not None and number < rule.min_inclusive:
            return text, f"must be at least {_plain(rule.min_inclusive)}"
        if rule.max_inclusive is not None and number > rule.max_inclusive:
            return text, f"must be at most {_plain(rule.max_inclusive)}"
    elif rule.base == "date":
        try:
            if not _DATE_LEXICAL.fullmatch(text):
                raise ValueError
            datetime.date.fromisoformat(text[:10])
        except ValueError:
            return text, "is not a valid date (YYYY-MM-DD)"
    if rule.length is not None and len(text) != rule.length:
        return text, f"must be exactly {_chars(rule.length)}"
    # Only identifiers get here over length: everything else was truncated.
    if rule.max_length is not None and len(text) > rule.max_length:
        return text, f"is longer than the {_chars(rule.max_length)} SBA allows"
    # The verdict, on the final text after any rewrite above.
    if rule.checker is not None and rule.check_tag and not rule.checker.accepts(rule.check_tag, text):
        if rule.patterns:
            return text, "is not in the format SBA requires"
        return text, "is not a value SBA's schema accepts"
    return text, None


def _is_code_list(element: Element) -> bool:
    """True for a small optional section such as Media or LegalEntity, made
    only of Code values and an optional Other text.

    Only these are ever dropped whole for an invalid required child. Dropping
    a larger optional parent -- ClientIntake for one bad CurrentlyInBusiness,
    say -- would throw away far more than the bad value.
    """
    return all(len(child) == 0 and child.tag in ("Code", "Other") for child in element)


def _plain(number: Decimal) -> str:
    return format(number.normalize(), "f")


class SchemaGuard:
    """Applies one schema's facets to finished record elements."""

    def __init__(self, schema_type: str, validator: ValidationTracker,
                 log: logging.Logger | None = None) -> None:
        self.schema_type = schema_type
        self.validator = validator
        self._element_fields = xsd_error_mapping.element_field_map(schema_type)
        self._columns: dict[str, str] = {}
        path = schema_path(schema_type)
        try:
            self.rules = load_rules(path)
        except (OSError, etree.XMLSyntaxError) as exc:
            # Never block a conversion on this: the facet checks are skipped
            # (illegal characters are still stripped) and the post-conversion
            # XSD validation remains the backstop.
            (log or logger).warning(f"Schema facets unavailable ({path}): {exc}; value checks skipped.")
            self.rules = {}

    def enforce(self, record: Element, record_id: str, parent_path: tuple[str, ...],
                columns: dict[str, str] | None = None) -> list[str]:
        """Check every element of `record` in place. `parent_path` is the tag
        path of the record's parent from the document root; `columns` maps
        "Parent/Tag" (or "Tag") to the CSV column that supplied it, where that
        varies by row (see BaseConverter.record_sources).

        Returns why the record cannot be filed -- a required value no fix can
        make valid, as "Contact ID: '...' is longer than the 20 characters SBA
        allows" -- or [] when it can. Each reason has been recorded as an
        error; the caller leaves the record out of the XML.
        """
        self._columns = columns or {}
        self._reported: set[tuple[str, str]] = set()
        self._pending_invalid = 0
        self._unfileable: list[str] = []
        self._visit(record, parent_path + (record.tag,), None, str(record_id))
        return self._unfileable

    def _report(self, record_id: str, severity: str, category: str, field: str, message: str) -> None:
        # Name, email and address are written to both Part 1 and Part 3 from
        # the same CSV cell; one issue per cell, not one per copy.
        if (field, message) in self._reported:
            return
        self._reported.add((field, message))
        self.validator.add_issue(record_id, severity, category, field, message)

    def _field(self, element: Element, parent: Element | None) -> str:
        label, csv_column = xsd_error_mapping.resolve_element_field(
            element.tag, parent.tag if parent is not None else None, self._element_fields,
            self._columns, self.schema_type)
        return csv_column or label or element.tag

    def _visit(self, element: Element, path: tuple[str, ...], parent: Element | None,
               record_id: str) -> None:
        rule = self.rules.get(path)
        if element.text is not None and len(element) == 0:
            self._check_text(element, path, parent, rule, record_id)
        for child in list(element):
            self._visit(child, path + (child.tag,), element, record_id)
        self._limit_repeats(element, path, record_id)
        if self._pending_invalid:
            self._prune_childless_required(element, path, parent, record_id)

    def _limit_repeats(self, element, path, record_id) -> None:
        """Drop children beyond the schema's maxOccurs (Media allows 13 Codes,
        LegalEntity 6, ...), keeping the first ones. Runs after the children
        were checked, so values already dropped as invalid don't count."""
        seen: dict[str, list] = {}
        for child in element:
            seen.setdefault(child.tag, []).append(child)
        for tag, children in seen.items():
            rule = self.rules.get(path + (tag,))
            if rule is None or rule.max_occurs is None or len(children) <= rule.max_occurs:
                continue
            if any("_schema_invalid" in child.attrib for child in children):
                # Then none of them is valid (see _has_valid_sibling), and the
                # pass below drops the section or leaves the record out.
                continue
            extra = children[rule.max_occurs:]
            for child in extra:
                element.remove(child)
            limit = rule.max_occurs
            self._report(
                record_id, "warning", ValidationCategory.DOWNGRADED_VALUE, self._field(extra[0], element),
                f"SBA allows at most {limit} {tag} value{'s' if limit != 1 else ''} in {element.tag}; "
                f"kept the first {limit} and left out "
                + ", ".join(f"'{_show(child.text or '')}'" for child in extra) + ".")

    def _check_text(self, element, path, parent, rule, record_id) -> None:
        def field() -> str:
            return self._field(element, parent)

        cleaned = strip_illegal_xml_chars(element.text)
        if cleaned != element.text:
            removed = count_illegal_xml_chars(element.text)
            self._report(
                record_id, "warning", ValidationCategory.STANDARDIZED_VALUE, field(),
                f"Replaced {removed} control character(s) that XML cannot carry with a space "
                "(usually a line break pasted from Word or Excel).")
            element.text = cleaned
        if rule is None or rule.has_children:
            return

        text = cleaned
        if rule.max_length is not None and len(text) > rule.max_length and element.tag not in _IDENTIFIER_TAGS:
            truncated = text[:rule.max_length].rstrip()
            what = "kept the initial" if rule.max_length == 1 else f"truncated to {_chars(rule.max_length)}"
            self._report(
                record_id, "warning", ValidationCategory.TRUNCATED_VALUE, field(),
                f"'{_show(text)}' is longer than the {_chars(rule.max_length)} SBA allows; "
                f"{what}: '{_show(truncated)}'.")
            text = truncated

        text, problem = _check_value(text, rule)
        if problem is None:
            element.text = text
            return

        if rule.optional and parent is not None:
            parent.remove(element)
            self._report(
                record_id, "warning", ValidationCategory.INVALID_VALUE, field(),
                f"'{_show(text)}' {problem}, so it was omitted from the XML.")
            return
        if parent is not None and self._has_valid_sibling(parent, element, path, rule):
            parent.remove(element)
            self._report(
                record_id, "warning", ValidationCategory.INVALID_VALUE, field(),
                f"'{_show(text)}' {problem}, so it was omitted; the other value(s) were kept.")
            return
        # Marked so the parent pass below can drop an optional parent instead.
        element.set("_schema_invalid", f"'{_show(text)}' {problem}")
        self._pending_invalid += 1

    def _has_valid_sibling(self, parent, element, path, rule) -> bool:
        for sibling in parent:
            if sibling is element or sibling.tag != element.tag or "_schema_invalid" in sibling.attrib:
                continue
            _, problem = _check_value(strip_illegal_xml_chars(sibling.text or ""), rule)
            if problem is None:
                return True
        return False

    def _prune_childless_required(self, element, path, parent, record_id) -> None:
        """Resolve children marked invalid: drop the whole element when it is
        an optional code list (the schema then accepts its absence), else
        report them as errors."""
        invalid = [child for child in element if "_schema_invalid" in child.attrib]
        if not invalid:
            return
        self._pending_invalid -= len(invalid)
        rule = self.rules.get(path)
        if rule is not None and rule.optional and parent is not None and _is_code_list(element):
            parent.remove(element)
            lost = "; ".join(child.attrib["_schema_invalid"] for child in invalid)
            kept = [child for child in element if "_schema_invalid" not in child.attrib and child.text]
            also = (" Also dropped with it: " + ", ".join(f"'{c.text}'" for c in kept) + ".") if kept else ""
            self._report(
                record_id, "warning", ValidationCategory.DOWNGRADED_VALUE, self._field(invalid[0], element),
                f"{lost}. {element.tag} cannot be filed without a valid value, so the whole "
                f"{element.tag} section was omitted from the XML.{also}")
            return
        for child in invalid:
            reason = child.attrib.pop("_schema_invalid")
            field = self._field(child, element)
            self._unfileable.append(f"{field}: {reason}")
            self._report(
                record_id, "error", ValidationCategory.INVALID_VALUE, field,
                f"{reason}. This field is required, so the record was left out of the XML; "
                "correct the value in the CSV and convert again.")
