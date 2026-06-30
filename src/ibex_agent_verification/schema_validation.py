from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from typing import Any, Mapping, Sequence


@lru_cache(maxsize=1)
def load_guardrail_decision_schema() -> dict[str, Any]:
    """Load the packaged GuardrailDecision schema used by the runtime gate."""

    schema_path = files("ibex_agent_verification").joinpath(
        "schemas/guardrail-decision.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_guardrail_decision(instance: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate one decision against the published schema subset used here.

    The validator is dependency-free but data-driven: every enforced constraint
    is read from the packaged JSON Schema rather than duplicated as constants in
    the crosswalk implementation.
    """

    if not isinstance(instance, Mapping):
        return ("$: expected object",)
    errors: list[str] = []
    _validate(instance, load_guardrail_decision_schema(), "$", errors)
    return tuple(errors)


def _validate(value: Any, schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    for sub_schema in schema.get("allOf", []):
        _validate(value, sub_schema, path, errors)

    condition = schema.get("if")
    if isinstance(condition, Mapping):
        condition_errors: list[str] = []
        _validate(value, condition, path, condition_errors)
        branch = schema.get("then") if not condition_errors else schema.get("else")
        if isinstance(branch, Mapping):
            _validate(value, branch, path, errors)

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
        return

    if "enum" in schema and value not in schema["enum"]:
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
        if schema.get("uniqueItems") is True:
            canonical = [
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in value
            ]
            if len(set(canonical)) != len(canonical):
                errors.append(f"{path}: duplicate items are not allowed")
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


def _matches_type(value: Any, declared: str) -> bool:
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
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_datetime(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None
