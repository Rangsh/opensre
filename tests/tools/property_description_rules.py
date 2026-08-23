"""Actionable-description rules for model-facing tool property schemas.

A description that exists but cannot be filled still fails the call. These
rules infer field shape from the property name plus schema, then require the
description to carry the missing fill-in detail. Detection is conservative:
uncertain shapes are skipped rather than flagged.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple

from core.tool import RegisteredTool

RULE_TIME = "time_unit_and_format"
RULE_ENUM = "enum_values"
RULE_IDENTIFIER = "identifier_kind"
RULE_EXCLUSIVE = "mutual_exclusion"

_TIME_EXACT = frozenset(
    {
        "since",
        "until",
        "duration",
        "timeout",
        "interval",
        "lookback",
        "ttl",
        "delay",
        "timestamp",
        "datetime",
        "time",
        "time_range",
        "time_window",
        "time_from",
        "time_to",
        "from_time",
        "to_time",
        "start_time",
        "end_time",
        "start_at",
        "end_at",
        "start_timestamp",
        "end_timestamp",
        "starttime",
        "endtime",
        "hours",
        "minutes",
        "seconds",
        "days",
        "window_minutes",
        "window_seconds",
        "window_hours",
        "window_days",
        "lookback_minutes",
        "lookback_hours",
        "lookback_seconds",
        "lookback_days",
        "period_seconds",
        "period_ms",
        "period_milliseconds",
        "hours_ago",
        "minutes_ago",
        "days_ago",
        "created_at",
        "updated_at",
        "modified_at",
        "deleted_at",
        "occurred_at",
        "expires_at",
        "expired_at",
        "started_at",
        "ended_at",
        "closed_at",
        "opened_at",
        "published_at",
        "last_seen_at",
        "first_seen_at",
    }
)
_TIME_SUFFIXES = frozenset(
    {
        "time",
        "times",
        "timestamp",
        "timestamps",
        "datetime",
        "timeout",
        "interval",
        "lookback",
        "duration",
        "ttl",
        "delay",
    }
)
_TIME_UNIT_QUALIFIERS = frozenset(
    {
        "window",
        "lookback",
        "look",
        "period",
        "offset",
        "age",
        "timeout",
        "duration",
        "ttl",
        "delay",
        "interval",
    }
)
_TIME_UNIT_WORDS = frozenset(
    {
        "minutes",
        "seconds",
        "hours",
        "days",
        "ms",
        "millis",
        "milliseconds",
    }
)
_AT_PREFIXES = frozenset(
    {
        "created",
        "updated",
        "modified",
        "deleted",
        "occurred",
        "expires",
        "expired",
        "started",
        "ended",
        "closed",
        "opened",
        "published",
        "last",
        "first",
        "seen",
        "last_seen",
        "first_seen",
        "last_seen_at",
    }
)

# ISO-8601 / RFC3339 document both the unit (datetime) and the accepted format.
_TIME_UNIT_AND_FORMAT = (
    "iso-8601",
    "iso8601",
    "iso 8601",
    "rfc3339",
    "rfc 3339",
    "rfc-3339",
)
_TIME_UNIT = (
    "nanosecond",
    "nanoseconds",
    "microsecond",
    "microseconds",
    "millisecond",
    "milliseconds",
    "msec",
    "millis",
    "second",
    "seconds",
    "sec",
    "secs",
    "minute",
    "minutes",
    "min",
    "mins",
    "hour",
    "hours",
    "hr",
    "hrs",
    "day",
    "days",
    "week",
    "weeks",
    "month",
    "months",
    "year",
    "years",
    "unix",
    "epoch",
)
_TIME_FORMAT = (
    "iso-8601",
    "iso8601",
    "iso 8601",
    "rfc3339",
    "rfc 3339",
    "rfc-3339",
    "unix",
    "epoch",
    "posix",
    "yyyy-mm-dd",
    "yyyy-mm-ddthh",
    "hh:mm",
    "relative",
    "duration string",
    "go duration",
    "prometheus",
    "unix timestamp",
    "unix epoch",
    "epoch millis",
    "epoch milliseconds",
    "epoch seconds",
    "integer",
    "int ",
)

_ID_EXACT = frozenset(
    {
        "id",
        "ids",
        "name",
        "owner",
        "repo",
        "repository",
        "org",
        "organization",
        "username",
        "user",
        "account",
        "identifier",
        "selector",
        "arn",
        "urn",
        "uuid",
        "guid",
        "slug",
    }
)
_ID_KIND_HINTS = (
    "numeric",
    "integer",
    "uuid",
    "guid",
    "slug",
    "display name",
    "display-name",
    "full name",
    "full-name",
    "owner/repo",
    "owner/name",
    "org/repo",
    "arn",
    "url",
    "uri",
    "urn",
    "email",
    "hostname",
    "fqdn",
    "sha256",
    "sha1",
    "sha-1",
    "commit hash",
    "fingerprint",
    "hex",
    "namespace",
    "fully-qualified",
    "fully qualified",
    "qualified name",
    "username",
    "login",
    "handle",
    "canonical",
    "snowflake",
    "ulid",
    "human-readable",
    "human readable",
    "resource name",
    "resource id",
    "instance identifier",
    "cluster name",
    "login name",
)

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "to",
        "for",
        "this",
        "that",
        "used",
        "use",
        "using",
        "optional",
        "required",
        "parameter",
        "argument",
        "value",
        "field",
        "param",
        "given",
        "specify",
        "specified",
        "provided",
        "provide",
        "set",
        "when",
        "if",
        "or",
        "and",
        "with",
        "from",
        "into",
        "by",
        "is",
        "be",
        "as",
        "in",
        "on",
        "at",
        "vs",
        "versus",
        "id",
        "ids",
        "name",
        "names",
        "identifier",
        "identifiers",
        "selector",
        "selectors",
    }
)
_SYNONYMS: dict[str, frozenset[str]] = {
    "repo": frozenset({"repository", "repositories"}),
    "repository": frozenset({"repo", "repositories"}),
    "org": frozenset({"organization", "organisation", "orgs"}),
    "organization": frozenset({"org", "organisation"}),
    "user": frozenset({"username", "login", "users"}),
    "username": frozenset({"user", "login"}),
    "id": frozenset({"identifier", "ids"}),
    "ids": frozenset({"id", "identifier"}),
    "identifier": frozenset({"id", "ids"}),
    "name": frozenset({"names"}),
    "url": frozenset({"uri", "link", "href"}),
    "uri": frozenset({"url", "urn"}),
}

_EXCLUSIVE_HINTS = (
    "mutually exclusive",
    "mutually-exclusive",
    "instead of",
    "not both",
    "do not pass both",
    "don't pass both",
    "cannot be used with",
    "cannot be combined",
    "exclusive with",
    "xor",
    "either ",
    "one of these",
    "omit if",
    "if omitted",
    "when omitted",
    "is omitted",
    "conflicts with",
    "rather than",
    "as an alternative",
    "alternative to",
    "do not set both",
    "don't set both",
    "not used with",
    "cannot both",
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class PropertyViolation(NamedTuple):
    """One property that failed one actionable-description rule."""

    tool_name: str
    source: str
    property_name: str
    rule: str
    reason: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.tool_name, self.property_name, self.rule)


def collect_violations(tools: Iterable[RegisteredTool]) -> list[PropertyViolation]:
    """Return every actionable-description miss on ``tools``' public schemas."""
    violations: list[PropertyViolation] = []
    for tool in tools:
        schema = tool.public_input_schema
        if not isinstance(schema, dict):
            continue
        violations.extend(
            collect_schema_violations(
                tool_name=tool.name,
                source=str(tool.source),
                schema=schema,
            )
        )
    return violations


def collect_schema_violations(
    *, tool_name: str, source: str, schema: Mapping[str, Any]
) -> list[PropertyViolation]:
    """Run every rule against one object schema's top-level properties."""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []

    violations: list[PropertyViolation] = []
    exclusive_groups = _exclusive_property_groups(schema)

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_name, str) or not isinstance(prop_schema, dict):
            continue
        description = _property_description(prop_schema)
        lowered = description.lower()

        if _is_time_field(prop_name) and not _time_description_is_actionable(prop_schema, lowered):
            violations.append(
                PropertyViolation(
                    tool_name,
                    source,
                    prop_name,
                    RULE_TIME,
                    "time/duration/window field must state a unit and an accepted format",
                )
            )

        enum_values = _enum_values(prop_schema)
        if enum_values and not _enum_values_are_documented(enum_values, lowered):
            violations.append(
                PropertyViolation(
                    tool_name,
                    source,
                    prop_name,
                    RULE_ENUM,
                    "enum property must document its allowed values in the description",
                )
            )

        if _is_identifier_field(prop_name) and not _identifier_description_is_actionable(
            prop_name, lowered
        ):
            violations.append(
                PropertyViolation(
                    tool_name,
                    source,
                    prop_name,
                    RULE_IDENTIFIER,
                    "id/name/selector field must say which identifier to send",
                )
            )

    for group in exclusive_groups:
        named = [name for name in group if name in properties]
        if len(named) < 2:
            continue
        for prop_name in named:
            prop_schema = properties[prop_name]
            if not isinstance(prop_schema, dict):
                continue
            others = [name for name in named if name != prop_name]
            if not _exclusive_description_names_conflict(
                _property_description(prop_schema).lower(), others
            ):
                violations.append(
                    PropertyViolation(
                        tool_name,
                        source,
                        prop_name,
                        RULE_EXCLUSIVE,
                        "mutually exclusive parameter must say so and name the other field",
                    )
                )
    return violations


def violations_by_source(violations: Sequence[PropertyViolation]) -> dict[str, int]:
    """Return violator counts keyed by tool source (one count per property hit)."""
    counts: dict[str, int] = defaultdict(int)
    for violation in violations:
        counts[violation.source] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def format_source_counts(counts: Mapping[str, int]) -> str:
    """Render per-source counts as stable, reviewable lines."""
    if not counts:
        return "(none)"
    width = max(len(source) for source in counts)
    return "\n".join(f"  {source:<{width}}  {count}" for source, count in counts.items())


def _property_description(prop_schema: Mapping[str, Any]) -> str:
    parts: list[str] = []
    raw = prop_schema.get("description")
    if isinstance(raw, str) and raw.strip():
        parts.append(raw)
    for key in ("allOf", "oneOf", "anyOf"):
        variants = prop_schema.get(key)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, dict):
                nested = variant.get("description")
                if isinstance(nested, str) and nested.strip():
                    parts.append(nested)
    return " ".join(parts)


def _schema_types(prop_schema: Mapping[str, Any]) -> frozenset[str]:
    declared = prop_schema.get("type")
    types: set[str] = set()
    if isinstance(declared, str):
        types.add(declared)
    elif isinstance(declared, list):
        types.update(item for item in declared if isinstance(item, str))
    for key in ("oneOf", "anyOf"):
        variants = prop_schema.get(key)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, dict):
                types.update(_schema_types(variant))
    types.discard("null")
    return frozenset(types)


def _is_time_field(name: str) -> bool:
    lowered = name.lower()
    if lowered in _TIME_EXACT:
        return True
    if lowered.endswith("_at"):
        return lowered[: -len("_at")] in _AT_PREFIXES or lowered in _TIME_EXACT
    if lowered.endswith("_ts") or lowered.endswith("_timestamp"):
        return True
    parts = lowered.split("_")
    if parts[-1] in _TIME_SUFFIXES:
        return True
    return parts[-1] in _TIME_UNIT_WORDS and any(part in _TIME_UNIT_QUALIFIERS for part in parts)


def _contains_phrase(text: str, phrases: Sequence[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _has_unit_token(text: str) -> bool:
    if _contains_phrase(text, _TIME_UNIT_AND_FORMAT):
        return True
    if _contains_phrase(text, _TIME_UNIT):
        return True
    return bool(re.search(r"\b(?:ns|us|µs|ms|msec|sec|mins?|hrs?)\b", text))


def _has_format_token(text: str) -> bool:
    if _contains_phrase(text, _TIME_UNIT_AND_FORMAT):
        return True
    if _contains_phrase(text, _TIME_FORMAT):
        return True
    if re.search(r"\b\d{4}-\d{2}-\d{2}", text):
        return True
    return bool(re.search(r"\b\d+(?:ns|us|ms|s|m|h|d)\b", text))


def _time_description_is_actionable(prop_schema: Mapping[str, Any], description: str) -> bool:
    if not description.strip():
        return False
    types = _schema_types(prop_schema)
    has_unit = _has_unit_token(description)
    has_format = _has_format_token(description)
    if types <= frozenset({"integer", "number"}):
        # Integer durations are filled as a count of the stated unit.
        return has_unit
    return has_unit and has_format


def _enum_values(prop_schema: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    raw = prop_schema.get("enum")
    if isinstance(raw, list):
        values.extend(str(item) for item in raw if item is not None and str(item) != "")
    items = prop_schema.get("items")
    if isinstance(items, dict):
        values.extend(_enum_values(items))
    for key in ("oneOf", "anyOf", "allOf"):
        variants = prop_schema.get(key)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, dict):
                values.extend(_enum_values(variant))
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return tuple(unique)


def _enum_values_are_documented(values: Sequence[str], description: str) -> bool:
    if not description.strip() or not values:
        return False
    return all(_enum_value_in_description(value, description) for value in values)


def _enum_value_in_description(value: str, description: str) -> bool:
    needle = value.lower()
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", description) is not None


def _is_identifier_field(name: str) -> bool:
    lowered = name.lower()
    if lowered in _ID_EXACT:
        return True
    if lowered.endswith("_id") or lowered.endswith("_ids"):
        return True
    if lowered.endswith("_identifier") or lowered.endswith("_identifiers"):
        return True
    return lowered.endswith("_selector") or lowered.endswith("_selectors")


def _identifier_description_is_actionable(prop_name: str, description: str) -> bool:
    if not description.strip():
        return False
    if any(hint in description for hint in _ID_KIND_HINTS):
        return True
    return _has_residual_identifier_detail(prop_name, description)


def _has_residual_identifier_detail(prop_name: str, description: str) -> bool:
    """Return True when the description says more than the property name."""
    strip_tokens = set(prop_name.lower().split("_"))
    for token in tuple(strip_tokens):
        strip_tokens.update(_SYNONYMS.get(token, ()))
    leftover = [
        token
        for token in _TOKEN_RE.findall(description.lower())
        if token not in strip_tokens and token not in _STOPWORDS and len(token) >= 3
    ]
    return bool(leftover)


def _exclusive_property_groups(schema: Mapping[str, Any]) -> list[tuple[str, ...]]:
    groups: list[tuple[str, ...]] = []
    properties = schema.get("properties")
    names = set(properties) if isinstance(properties, dict) else set()

    # JSON Schema ``anyOf`` allows multiple branches to match, so it is not
    # exclusive. Only ``oneOf`` is a true XOR of required properties.
    variants = schema.get("oneOf")
    if isinstance(variants, list):
        required_sets = [
            frozenset(str(item) for item in variant.get("required", []) if isinstance(item, str))
            for variant in variants
            if isinstance(variant, dict)
        ]
        required_sets = [group for group in required_sets if group]
        if len(required_sets) >= 2:
            counts: Counter[str] = Counter(name for group in required_sets for name in group)
            exclusive = tuple(sorted(name for name, count in counts.items() if count == 1))
            if len(exclusive) >= 2:
                groups.append(exclusive)

    if not names:
        return groups

    prefixes_with_id = {name[: -len("_id")]: name for name in names if name.endswith("_id")}
    for prefix, id_name in prefixes_with_id.items():
        if not prefix:
            continue
        for suffix in ("_url", "_key", "_uri"):
            other = f"{prefix}{suffix}"
            if other in names:
                groups.append(tuple(sorted((id_name, other))))

    for left, right in (
        ("query", "query_file"),
        ("query", "file_path"),
        ("content", "file_path"),
        ("content", "path"),
        ("sql", "query_file"),
        ("body", "file_path"),
    ):
        if left in names and right in names:
            groups.append((left, right))
    return groups


def _exclusive_description_names_conflict(description: str, others: Sequence[str]) -> bool:
    if not description.strip():
        return False
    names_other = any(other.lower() in description for other in others)
    hinted = _contains_phrase(description, _EXCLUSIVE_HINTS)
    return names_other and hinted
