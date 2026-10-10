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
  what was lost. Otherwise it is kept and recorded as an error, so the problem
  is reported against its row before XSD validation rather than only after.
"""

from __future__ import annotations

import datetime
import functools
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from lxml import etree

from .config import ValidationCategory
from . import data_cleaning
from . import xsd_error_mapping

if TYPE_CHECKING:
    from .validation_report import ValidationTracker

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
_ILLEGAL_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")

# xs:decimal's lexical space. Python's Decimal also accepts exponents, NaN and
# Infinity, none of which the schema allows.
_DECIMAL_LEXICAL = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")
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
    patterns: tuple[re.Pattern, ...] = ()
    min_inclusive: Decimal | None = None
    max_inclusive: Decimal | None = None
    has_children: bool = False       # complex type: its own text is not checked


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
            patterns.append(re.compile(value))
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


def _content_elements(node):
    """Yield the xs:element children of a complexType's content model,
    descending through sequence/choice/all."""
    for child in node:
        if not isinstance(child.tag, str):
            continue
        name = _local(child.tag)
        if name == "element":
            yield child
        elif name in ("sequence", "choice", "all", "complexType"):
            yield from _content_elements(child)


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

    def visit(element, parent_path: tuple[str, ...], stack: frozenset) -> None:
        path = parent_path + (element.get("name"),)
        facets: dict = {}
        type_ref = element.get("type", "")
        complex_node = None
        if type_ref.startswith("xs:"):
            facets["base"] = type_ref[3:]
        elif type_ref in simple_types:
            facets["type_name"] = type_ref
            _merge_simple_type(simple_types[type_ref], simple_types, facets)
        elif type_ref in complex_types:
            complex_node = complex_types[type_ref]
        else:
            inline_simple = element.find(f"{_XS}simpleType")
            if inline_simple is not None:
                _merge_simple_type(inline_simple, simple_types, facets)
            complex_node = element.find(f"{_XS}complexType")
        rules[path] = ElementRule(
            optional=element.get("minOccurs") == "0",
            has_children=complex_node is not None,
            **facets,
        )
        # `stack` holds the named complex types being expanded, so a type that
        # (indirectly) contains itself can't recurse forever. Inline types have
        # no name and can't recur, so they are never added to it.
        if complex_node is not None and type_ref not in stack:
            for child in _content_elements(complex_node):
                visit(child, path, stack | {type_ref} if type_ref else stack)

    for top in schema.findall(f"{_XS}element"):
        visit(top, (), frozenset())
    return rules


def schema_path(schema_type: str) -> str:
    return os.path.join(os.environ.get("SCHEMAS_DIR") or _DEFAULT_SCHEMAS_DIR, XSD_FILES[schema_type])


def strip_illegal_xml_chars(text: str) -> str:
    """Replace characters XML 1.0 cannot carry with a space.

    A space, not nothing: the usual source is a line break pasted from Word
    (a vertical tab), and deleting it would glue "123 Main St" to "Suite 5".
    """
    if not _ILLEGAL_XML_CHARS.search(text):
        return text
    return re.sub(r"[ \t]{2,}", " ", _ILLEGAL_XML_CHARS.sub(" ", text)).strip()


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
    if rule.patterns and not any(p.fullmatch(text) for p in rule.patterns):
        return text, "is not in the format SBA requires"
    if rule.length is not None and len(text) != rule.length:
        return text, f"must be exactly {_chars(rule.length)}"
    if rule.base in _DECIMAL_BASES:
        if not _DECIMAL_LEXICAL.fullmatch(text):
            return text, "is not a number"
        number = Decimal(text)
        if rule.base in _INTEGER_BASES:
            if number != number.to_integral_value():
                return text, "must be a whole number"
            text = str(int(number))  # "12.0" -> "12": same value, integer lexical form
        if rule.base == "positiveInteger" and number < 1:
            return text, "must be 1 or more"
        if rule.min_inclusive is not None and number < rule.min_inclusive:
            return text, f"must be at least {_plain(rule.min_inclusive)}"
        if rule.max_inclusive is not None and number > rule.max_inclusive:
            return text, f"must be at most {_plain(rule.max_inclusive)}"
    elif rule.base == "date":
        try:
            datetime.date.fromisoformat(text)
        except ValueError:
            return text, "is not a valid date (YYYY-MM-DD)"
    return text, None


def _is_code_list(element: ET.Element) -> bool:
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
        path = schema_path(schema_type)
        try:
            self.rules = load_rules(path)
        except (OSError, etree.XMLSyntaxError) as exc:
            # Never block a conversion on this: the facet checks are skipped
            # (illegal characters are still stripped) and the post-conversion
            # XSD validation remains the backstop.
            (log or logger).warning(f"Schema facets unavailable ({path}): {exc}; value checks skipped.")
            self.rules = {}

    def enforce(self, record: ET.Element, record_id: str, parent_path: tuple[str, ...]) -> None:
        """Check every element of `record` in place. `parent_path` is the tag
        path of the record's parent from the document root."""
        self._reported: set[tuple[str, str]] = set()
        self._pending_invalid = 0
        self._visit(record, parent_path + (record.tag,), None, str(record_id))

    def _report(self, record_id: str, severity: str, category: str, field: str, message: str) -> None:
        # Name, email and address are written to both Part 1 and Part 3 from
        # the same CSV cell; one issue per cell, not one per copy.
        if (field, message) in self._reported:
            return
        self._reported.add((field, message))
        self.validator.add_issue(record_id, severity, category, field, message)

    def _field(self, element: ET.Element, parent: ET.Element | None) -> str:
        label, csv_column = xsd_error_mapping.resolve_element_field(
            element.tag, parent.tag if parent is not None else None, self._element_fields)
        return csv_column or label or element.tag

    def _visit(self, element: ET.Element, path: tuple[str, ...], parent: ET.Element | None,
               record_id: str) -> None:
        rule = self.rules.get(path)
        if element.text is not None and len(element) == 0:
            self._check_text(element, path, parent, rule, record_id)
        for child in list(element):
            self._visit(child, path + (child.tag,), element, record_id)
        if self._pending_invalid:
            self._prune_childless_required(element, path, parent, record_id)

    def _check_text(self, element, path, parent, rule, record_id) -> None:
        def field() -> str:
            return self._field(element, parent)

        cleaned = strip_illegal_xml_chars(element.text)
        if cleaned != element.text:
            removed = len(_ILLEGAL_XML_CHARS.findall(element.text))
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
        if problem is None and rule.max_length is not None and len(text) > rule.max_length:
            problem = f"is longer than the {_chars(rule.max_length)} SBA allows"
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
            self._report(
                record_id, "error", ValidationCategory.INVALID_VALUE, self._field(child, element),
                f"{reason}. This field is required, so the file will fail SBA validation "
                "until the value in the CSV is corrected.")
