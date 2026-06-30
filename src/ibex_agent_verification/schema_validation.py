"""Dependency-free validation helpers for the packaged guardrail schema."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from typing import Any, Mapping


@lru_cache(maxsize=1)
def load_guardrail_decision_schema() -> dict[str, Any]:
    """Load and cache the packaged GuardrailDecision JSON Schema."""

    schema_path = files("ibex_agent_verification").joinpath(
        "schemas/guardrail-decision.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_guardrail_decision(instance: Mapping[str, Any]) -> tuple[str, ...]:
    """Return deterministic validation errors for one guardrail decision."""

    if not isinstance(instance, Mapping):
        return ("$: expected object",)
    errors: list[str] = []
    _validate(instance, load_guardrail_decision_schema(), "$", errors)
    return tuple(errors)


def _validate(value: Any, schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    """Recursively apply the schema keywords used by the guardrail contract."""

    for sub_schema in schema.get("allOf", []):
        _validate(value, sub_schema, path, errors)

    condition = schema.get("if")
    if isinstance(condition, Mapping):
        condition_errors: list[str] = []
        _validate(value, condition, path, condition_errors)
        branch = schema.get("then") if not condition_errors else schema.get("else")
        if isinstance(branch, Mapping):
            _validate(value, branch, path, errors)

    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(f"{path}: expected constant {schema['const']!r}")
        return

    if "enum" in schema and not any(
        _json_equal(value, candidate) for candidate in schema["enum"]
    ):
        errors.append(f"{path}: value is not in enum")
        return

    declared_type = schema.get("type")
    if declared_type is not None:
        allowed_types = (
            list(declared_type) if isinstance(declared_type, list) else [declared_type]
        )
        if not any(_matches_type(value, item) for item in allowed_types):
            errors.append(f"{path}: expected type {allowed_types}")
            return

    if isinstance(value, Mapping):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}: required property is missing")

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key}: additional property is not allowed")

        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, Mapping):
                _validate(value[key], child_schema, f"{path}.{key}", errors)

    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path}: fewer than {min_items} items")
        if isinstance(max_items, int) and len(value) > max_items:
            errors.append(f"{path}: more than {max_items} items")
            return
        if schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if any(_json_equal(item, previous) for previous in value[:index]):
                    errors.append(f"{path}: duplicate items are not allowed")
                    break
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate(item, item_schema, f"{path}[{index}]", errors)

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path}: shorter than {min_length} characters")
        if isinstance(max_length, int) and len(value) > max_length:
            errors.append(f"{path}: longer than {max_length} characters")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
            errors.append(f"{path}: does not match required pattern")
        if schema.get("format") == "date-time" and not _is_datetime(value):
            errors.append(f"{path}: invalid date-time")

    minimum = schema.get("minimum")
    if isinstance(minimum, (int, float)) and _is_number(value) and value < minimum:
        errors.append(f"{path}: value is below minimum {minimum}")


def _json_equal(left: Any, right: Any) -> bool:
    """Compare values using JSON type identity instead of Python coercion."""

    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if _is_number(left) and _is_number(right):
        return left == right
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            return False
        return all(_json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    if type(left) is not type(right):
        return False
    try:
        return left == right
    except Exception:
        return False


def _matches_type(value: Any, declared: str) -> bool:
    """Return whether a Python value matches one JSON Schema type name."""

    if declared == "null":
        return value is None
    if declared == "object":
        return isinstance(value, Mapping)
    if declared == "array":
        return isinstance(value, list)
    if declared == "string":
        return isinstance(value, str)
    if declared == "number":
        return _is_number(value)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    return False


def _is_number(value: Any) -> bool:
    """Return whether a value is a finite JSON number rather than a boolean."""

    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _is_datetime(value: str) -> bool:
    """Return whether a string is a timezone-aware ISO-8601 date-time."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None
