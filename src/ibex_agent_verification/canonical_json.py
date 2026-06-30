"""Restricted RFC 8785-compatible canonical JSON for contract identifiers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

MAX_SAFE_INTEGER = 9_007_199_254_740_991


class CanonicalizationError(ValueError):
    """Raised when a value is outside the canonical contract profile."""


def canonicalize_jcs(value: Any) -> bytes:
    """Serialize a JSON value with the contract's restricted JCS profile.

    The profile follows RFC 8785 key ordering and string serialization, but
    deliberately rejects floating-point values. Contract identifier preimages
    must use strings, booleans, null, arrays, objects, and interoperable
    integers only.
    """

    return _serialize(value).encode("utf-8")


def sha256_jcs(value: Any) -> str:
    """Return a content identifier for one canonical JSON value."""

    return f"sha256:{hashlib.sha256(canonicalize_jcs(value)).hexdigest()}"


def _serialize(value: Any) -> str:
    """Serialize one supported Python value into canonical JSON text."""

    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise CanonicalizationError(
                "integer exceeds the interoperable IEEE-754 safe range"
            )
        return str(value)
    if isinstance(value, float):
        raise CanonicalizationError(
            "floating-point values are not permitted in identifier preimages"
        )
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, list):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    if isinstance(value, Mapping):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalizationError("JSON object keys must be strings")
            _reject_surrogates(key)
        members = (
            f"{_quote(key)}:{_serialize(value[key])}"
            for key in sorted(value, key=_utf16_sort_key)
        )
        return "{" + ",".join(members) + "}"
    raise CanonicalizationError(
        f"unsupported value type in identifier preimage: {type(value).__name__}"
    )


def _quote(value: str) -> str:
    """Quote one validated string using compact JSON escaping rules."""

    _reject_surrogates(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _utf16_sort_key(value: str) -> bytes:
    """Return the RFC 8785 property-name ordering key."""

    return value.encode("utf-16-be")


def _reject_surrogates(value: str) -> None:
    """Reject lone UTF-16 surrogate code points that violate I-JSON."""

    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise CanonicalizationError("lone UTF-16 surrogate is not valid I-JSON")
