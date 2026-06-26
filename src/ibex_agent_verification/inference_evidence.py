from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .evidence import collect_files, sha256_file


class InferenceEvidenceError(ValueError):
    """Raised when an inference capture cannot be verified safely."""


_ALLOWED_EVENTS = {
    "request_start",
    "response_headers",
    "chunk",
    "request_end",
    "request_error",
}
_TERMINAL_EVENTS = {"request_end", "request_error"}
_SENSITIVE_KEYS = {"authorization", "api_key", "api-key", "x-api-key"}


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InferenceEvidenceError(f"{path}: invalid {label} JSON: {exc.msg}") from exc
    except OSError as exc:
        raise InferenceEvidenceError(f"cannot read {label} file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InferenceEvidenceError(f"{label} must be a JSON object")
    return payload


def _find_sensitive_key(value: Any, *, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text.lower() in _SENSITIVE_KEYS:
                return child_path
            found = _find_sensitive_key(item, path=child_path)
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _find_sensitive_key(item, path=f"{path}[{index}]")
            if found is not None:
                return found
    return None


def load_capture(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise InferenceEvidenceError(f"cannot read inference capture {path}: {exc}") from exc

    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InferenceEvidenceError(
                f"{path}:{line_number}: invalid JSON: {exc.msg}"
            ) from exc
        if not isinstance(event, dict):
            raise InferenceEvidenceError(f"{path}:{line_number}: event must be an object")
        events.append(event)

    if not events:
        raise InferenceEvidenceError("inference capture must contain at least one event")
    return events


def _event_timestamp(event: dict[str, Any], *, index: int) -> int:
    value = event.get("monotonic_ns")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InferenceEvidenceError(
            f"capture event {index} monotonic_ns must be a non-negative integer"
        )
    return value


def _event_type(event: dict[str, Any], *, index: int) -> str:
    value = event.get("event")
    if not isinstance(value, str) or value not in _ALLOWED_EVENTS:
        raise InferenceEvidenceError(
            f"capture event {index} event must be one of {sorted(_ALLOWED_EVENTS)}"
        )
    return value


def _chunk_has_output(payload: dict[str, Any]) -> bool:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if isinstance(content, str) and content:
            return True
        for key in ("tool_calls", "function_call", "refusal"):
            if delta.get(key):
                return True
    return False


def _chunk_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return ""
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "".join(parts)


def _usage_from_payload(payload: dict[str, Any]) -> dict[str, int] | None:
    usage = payload.get("usage")
    if usage is None:
        return None
    if not isinstance(usage, dict):
        raise InferenceEvidenceError("chunk usage must be an object when present")

    normalized: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise InferenceEvidenceError(
                f"chunk usage.{key} must be a non-negative integer"
            )
        normalized[key] = value
    if normalized["total_tokens"] != (
        normalized["prompt_tokens"] + normalized["completion_tokens"]
    ):
        raise InferenceEvidenceError(
            "chunk usage.total_tokens must equal prompt_tokens + completion_tokens"
        )
    return normalized


def analyze_capture(
    events: Iterable[dict[str, Any]], *, provider: str, model: str
) -> dict[str, Any]:
    if not provider.strip():
        raise InferenceEvidenceError("provider must be a non-empty string")
    if not model.strip():
        raise InferenceEvidenceError("model must be a non-empty string")

    items = list(events)
    if not items:
        raise InferenceEvidenceError("inference capture must contain at least one event")

    event_types: list[str] = []
    timestamps: list[int] = []
    for index, event in enumerate(items):
        if not isinstance(event, dict):
            raise InferenceEvidenceError(f"capture event {index} must be an object")
        event_types.append(_event_type(event, index=index))
        timestamps.append(_event_timestamp(event, index=index))

    if event_types[0] != "request_start":
        raise InferenceEvidenceError("capture must start with request_start")
    if event_types[-1] not in _TERMINAL_EVENTS:
        raise InferenceEvidenceError("capture must end with request_end or request_error")
    if event_types.count("request_start") != 1:
        raise InferenceEvidenceError("capture must contain exactly one request_start")
    if sum(event in _TERMINAL_EVENTS for event in event_types) != 1:
        raise InferenceEvidenceError("capture must contain exactly one terminal event")
    if any(current < previous for previous, current in zip(timestamps, timestamps[1:])):
        raise InferenceEvidenceError("capture monotonic_ns values must be non-decreasing")

    start_ns = timestamps[0]
    terminal_ns = timestamps[-1]
    status_code: int | None = None
    first_output_ns: int | None = None
    usage: dict[str, int] | None = None
    output_parts: list[str] = []
    error: str | None = None

    for index, (event, event_type, timestamp) in enumerate(
        zip(items, event_types, timestamps)
    ):
        if event_type == "response_headers":
            value = event.get("status_code")
            if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
                raise InferenceEvidenceError(
                    f"capture event {index} status_code must be an integer from 100 to 599"
                )
            if status_code is not None:
                raise InferenceEvidenceError("capture must contain at most one response_headers")
            status_code = value
        elif event_type == "chunk":
            payload = event.get("payload")
            if not isinstance(payload, dict):
                raise InferenceEvidenceError(
                    f"capture event {index} payload must be an object"
                )
            if first_output_ns is None and _chunk_has_output(payload):
                first_output_ns = timestamp
            output_parts.append(_chunk_text(payload))
            chunk_usage = _usage_from_payload(payload)
            if chunk_usage is not None:
                if usage is not None and usage != chunk_usage:
                    raise InferenceEvidenceError("capture contains conflicting usage objects")
                usage = chunk_usage
        elif event_type == "request_error":
            value = event.get("error")
            if not isinstance(value, str) or not value.strip():
                raise InferenceEvidenceError("request_error must contain a non-empty error")
            error = value

    duration_ns = terminal_ns - start_ns
    ttft_ns = None if first_output_ns is None else first_output_ns - start_ns
    generation_ns = (
        None if first_output_ns is None else max(0, terminal_ns - first_output_ns)
    )
    completion_tokens = None if usage is None else usage["completion_tokens"]
    output_tokens_per_second: float | None = None
    if completion_tokens is not None and generation_ns is not None and generation_ns > 0:
        output_tokens_per_second = completion_tokens / (generation_ns / 1_000_000_000)

    output_text = "".join(output_parts)
    request_succeeded = (
        event_types[-1] == "request_end"
        and status_code is not None
        and 200 <= status_code < 300
    )

    return {
        "schema_version": 1,
        "status": "COMPLETE" if request_succeeded else "REQUEST_FAILED",
        "provider": provider,
        "model": model,
        "event_count": len(items),
        "http_status": status_code,
        "error": error,
        "timing": {
            "duration_ms": duration_ns / 1_000_000,
            "time_to_first_output_ms": None if ttft_ns is None else ttft_ns / 1_000_000,
            "generation_ms": None if generation_ns is None else generation_ns / 1_000_000,
        },
        "usage": usage,
        "throughput": {
            "output_tokens_per_second": output_tokens_per_second,
            "source": "provider_usage" if usage is not None else None,
            "estimated": False,
        },
        "output": {
            "text_characters": len(output_text),
            "text_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
        },
        "claim_boundary": (
            "This report verifies a recorded OpenAI-compatible API interaction and its "
            "derived timing metrics. It does not verify provider hardware, internal RTL, "
            "model quality, energy efficiency, or an independent tokens-per-second claim."
        ),
    }


def build_inference_bundle(
    *,
    capture_path: Path,
    request_path: Path,
    evidence_dir: Path,
    provider: str,
    model: str,
    project_sha: str,
) -> dict[str, Any]:
    if evidence_dir.exists():
        if evidence_dir.is_symlink() or not evidence_dir.is_dir():
            raise InferenceEvidenceError(
                f"evidence directory must be a real directory: {evidence_dir}"
            )
        if any(evidence_dir.iterdir()):
            raise InferenceEvidenceError(
                f"evidence directory must be empty or absent: {evidence_dir}"
            )
    if capture_path.is_symlink() or not capture_path.is_file():
        raise InferenceEvidenceError(
            f"capture file must be a regular non-symlink file: {capture_path}"
        )
    if request_path.is_symlink() or not request_path.is_file():
        raise InferenceEvidenceError(
            f"request file must be a regular non-symlink file: {request_path}"
        )
    if not project_sha.strip():
        raise InferenceEvidenceError("project_sha must be a non-empty string")

    request_payload = _load_json_object(request_path, label="request")
    sensitive_path = _find_sensitive_key(request_payload)
    if sensitive_path is not None:
        raise InferenceEvidenceError(
            f"request JSON must not contain authorization or API key fields: {sensitive_path}"
        )
    request_model = request_payload.get("model")
    if not isinstance(request_model, str) or request_model != model:
        raise InferenceEvidenceError(
            "request JSON model must exactly match the --model value"
        )
    if request_payload.get("stream") is not True:
        raise InferenceEvidenceError("request JSON stream must be true")

    events = load_capture(capture_path)
    analysis = analyze_capture(events, provider=provider, model=model)

    raw_dir = evidence_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_request = raw_dir / "request.json"
    raw_capture = raw_dir / "capture.jsonl"
    shutil.copyfile(request_path, raw_request)
    shutil.copyfile(capture_path, raw_capture)

    analysis_path = evidence_dir / "analysis.json"
    analysis_path.write_text(
        json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    manifest_path = evidence_dir / "manifest.json"
    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": {
            "repository": "safal207/ibex-agent-verification",
            "commit": project_sha,
        },
        "workload": {
            "kind": "openai_compatible_chat_completions",
            "provider": provider,
            "model": model,
            "request_sha256": sha256_file(raw_request),
            "capture_sha256": sha256_file(raw_capture),
        },
        "result": {
            "status": analysis["status"],
            "http_status": analysis["http_status"],
            "time_to_first_output_ms": analysis["timing"]["time_to_first_output_ms"],
            "output_tokens_per_second": analysis["throughput"][
                "output_tokens_per_second"
            ],
        },
        "claim_boundary": analysis["claim_boundary"],
        "files": collect_files(evidence_dir, manifest_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest
