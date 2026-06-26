from __future__ import annotations

import json
import math
import os
import tempfile
import time
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

from .inference_evidence import build_inference_bundle


class CerebrasRunnerError(ValueError):
    """Raised when a Cerebras capture cannot be produced safely."""


class CerebrasRunnerBlocked(RuntimeError):
    """Raised when credentials or the optional official SDK are unavailable."""


_OFFICIAL_BASE_URL = "https://api.cerebras.ai"
_SDK_PACKAGE = "cerebras_cloud_sdk"
_SENSITIVE_KEYS = {"authorization", "api_key", "api-key", "x-api-key"}
_SAFE_RESPONSE_HEADERS = (
    "content-type",
    "date",
    "x-request-id",
    "request-id",
    "cf-ray",
)


def _load_request(path: Path, *, model: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CerebrasRunnerError(
            f"request file must be a regular non-symlink file: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CerebrasRunnerError(f"{path}: invalid request JSON: {exc.msg}") from exc
    except OSError as exc:
        raise CerebrasRunnerError(f"cannot read request file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CerebrasRunnerError("request JSON must be an object")
    sensitive_path = _find_sensitive_key(payload)
    if sensitive_path is not None:
        raise CerebrasRunnerError(
            f"request JSON must not contain authorization or API key fields: {sensitive_path}"
        )
    request_model = payload.get("model")
    if not isinstance(request_model, str) or request_model != model:
        raise CerebrasRunnerError(
            "request JSON model must exactly match the --model value"
        )
    if payload.get("stream") is not True:
        raise CerebrasRunnerError("request JSON stream must be true")
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


def _validate_evidence_dir(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_dir():
        raise CerebrasRunnerError(
            f"evidence directory must be a real directory: {path}"
        )
    if any(path.iterdir()):
        raise CerebrasRunnerError(
            f"evidence directory must be empty or absent: {path}"
        )


def _load_official_sdk() -> tuple[Callable[..., Any], str]:
    try:
        from cerebras.cloud.sdk import Cerebras
    except ImportError as exc:
        raise CerebrasRunnerBlocked(
            "official Cerebras SDK is not installed; run "
            "python -m pip install -e '.[cerebras]'"
        ) from exc
    try:
        version = metadata.version(_SDK_PACKAGE)
    except metadata.PackageNotFoundError as exc:
        raise CerebrasRunnerBlocked(
            "official Cerebras SDK package metadata is unavailable"
        ) from exc
    return Cerebras, version


def _serialize_chunk(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, dict):
        payload = chunk
    elif callable(getattr(chunk, "to_dict", None)):
        payload = chunk.to_dict()
    elif callable(getattr(chunk, "model_dump", None)):
        payload = chunk.model_dump(mode="json")
    else:
        raise CerebrasRunnerError(
            f"unsupported Cerebras stream chunk type: {type(chunk).__name__}"
        )
    if not isinstance(payload, dict):
        raise CerebrasRunnerError("serialized Cerebras stream chunk must be an object")
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CerebrasRunnerError(
            f"Cerebras stream chunk is not strict JSON: {exc}"
        ) from exc
    return payload


def _safe_headers(response: Any) -> dict[str, str]:
    headers = getattr(response, "headers", None)
    if headers is None:
        return {}
    result: dict[str, str] = {}
    for name in _SAFE_RESPONSE_HEADERS:
        try:
            value = headers.get(name)
        except Exception:
            value = None
        if value is not None:
            result[name] = str(value)
    return result


def _response_event(response: Any, *, monotonic_ns: int) -> dict[str, Any] | None:
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, bool) or not isinstance(status_code, int):
        return None
    event: dict[str, Any] = {
        "event": "response_headers",
        "monotonic_ns": monotonic_ns,
        "status_code": status_code,
        "headers": _safe_headers(response),
    }
    http_version = getattr(response, "http_version", None)
    if isinstance(http_version, str) and http_version:
        event["http_version"] = http_version
    url = getattr(response, "url", None)
    if url is not None:
        event["url"] = str(url)
    retries_taken = getattr(response, "retries_taken", None)
    if isinstance(retries_taken, int) and not isinstance(retries_taken, bool):
        event["retries_taken"] = retries_taken
    return event


def _write_event(handle: TextIO, event: dict[str, Any]) -> None:
    handle.write(
        json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    )
    handle.flush()


def _safe_error_text(exc: Exception, *, redactions: tuple[str, ...]) -> str:
    text = str(exc).strip() or type(exc).__name__
    for secret in redactions:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text[:2048]


def capture_cerebras_stream(
    *,
    request_payload: dict[str, Any],
    capture_path: Path,
    client: Any,
    sdk_version: str,
    timeout_seconds: float,
    clock_ns: Callable[[], int] = time.monotonic_ns,
    redactions: tuple[str, ...] = (),
) -> dict[str, Any]:
    if capture_path.exists() or capture_path.is_symlink():
        raise CerebrasRunnerError(f"capture output already exists: {capture_path}")
    capture_path.parent.mkdir(parents=True, exist_ok=True)

    event_count = 0
    chunk_count = 0
    http_status: int | None = None
    response_recorded = False

    with capture_path.open("x", encoding="utf-8") as handle:
        _write_event(
            handle,
            {
                "event": "request_start",
                "monotonic_ns": clock_ns(),
                "provider": "cerebras",
                "endpoint": _OFFICIAL_BASE_URL,
                "sdk_package": _SDK_PACKAGE,
                "sdk_version": sdk_version,
                "timeout_seconds": timeout_seconds,
                "max_retries": 0,
                "warm_tcp_connection": False,
            },
        )
        event_count += 1

        try:
            raw_response = client.chat.completions.with_raw_response.create(
                **request_payload
            )
            response_event = _response_event(raw_response, monotonic_ns=clock_ns())
            if response_event is None:
                raise CerebrasRunnerError(
                    "Cerebras SDK raw response did not expose an integer status_code"
                )
            http_status = response_event["status_code"]
            _write_event(handle, response_event)
            event_count += 1
            response_recorded = True

            stream = raw_response.parse()
            for chunk in stream:
                _write_event(
                    handle,
                    {
                        "event": "chunk",
                        "monotonic_ns": clock_ns(),
                        "payload": _serialize_chunk(chunk),
                    },
                )
                event_count += 1
                chunk_count += 1

            _write_event(
                handle,
                {
                    "event": "request_end",
                    "monotonic_ns": clock_ns(),
                    "chunk_count": chunk_count,
                },
            )
            event_count += 1
            return {
                "status": "CAPTURED",
                "event_count": event_count,
                "chunk_count": chunk_count,
                "http_status": http_status,
            }
        except CerebrasRunnerError:
            raise
        except Exception as exc:
            response = getattr(exc, "response", None)
            if not response_recorded and response is not None:
                response_event = _response_event(response, monotonic_ns=clock_ns())
                if response_event is not None:
                    http_status = response_event["status_code"]
                    _write_event(handle, response_event)
                    event_count += 1
            _write_event(
                handle,
                {
                    "event": "request_error",
                    "monotonic_ns": clock_ns(),
                    "error_type": type(exc).__name__,
                    "error": _safe_error_text(exc, redactions=redactions),
                },
            )
            event_count += 1
            return {
                "status": "REQUEST_FAILED",
                "event_count": event_count,
                "chunk_count": chunk_count,
                "http_status": http_status,
            }


def run_cerebras_inference(
    *,
    request_path: Path,
    evidence_dir: Path,
    model: str,
    project_sha: str,
    timeout_seconds: float = 60.0,
    environ: Mapping[str, str] | None = None,
    client_factory: Callable[..., Any] | None = None,
    sdk_version_override: str | None = None,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> dict[str, Any]:
    if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds):
        raise CerebrasRunnerError("timeout_seconds must be a finite positive number")
    if timeout_seconds <= 0:
        raise CerebrasRunnerError("timeout_seconds must be a finite positive number")
    if not model.strip():
        raise CerebrasRunnerError("model must be a non-empty string")
    if not project_sha.strip():
        raise CerebrasRunnerError("project_sha must be a non-empty string")
    _validate_evidence_dir(evidence_dir)

    request_payload = _load_request(request_path, model=model)
    environment = os.environ if environ is None else environ
    api_key = environment.get("CEREBRAS_API_KEY", "").strip()
    if not api_key:
        raise CerebrasRunnerBlocked(
            "CEREBRAS_API_KEY is not set; no network request was attempted"
        )

    if client_factory is None:
        client_factory, sdk_version = _load_official_sdk()
    else:
        sdk_version = sdk_version_override or "test-double"

    try:
        client = client_factory(
            api_key=api_key,
            base_url=_OFFICIAL_BASE_URL,
            timeout=timeout_seconds,
            max_retries=0,
            warm_tcp_connection=False,
        )
    except Exception as exc:
        raise CerebrasRunnerBlocked(
            f"could not construct official Cerebras client: {type(exc).__name__}: "
            f"{_safe_error_text(exc, redactions=(api_key,))}"
        ) from exc

    close_error: str | None = None
    capture_result: dict[str, Any]
    with tempfile.TemporaryDirectory(prefix="ibex-av-cerebras-") as directory:
        capture_path = Path(directory) / "capture.jsonl"
        try:
            capture_result = capture_cerebras_stream(
                request_payload=request_payload,
                capture_path=capture_path,
                client=client,
                sdk_version=sdk_version,
                timeout_seconds=timeout_seconds,
                clock_ns=clock_ns,
                redactions=(api_key,),
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    close_error = _safe_error_text(exc, redactions=(api_key,))

        manifest = build_inference_bundle(
            capture_path=capture_path,
            request_path=request_path,
            evidence_dir=evidence_dir,
            provider="cerebras",
            model=model,
            project_sha=project_sha,
        )

    runner_metadata = {
        "provider": "cerebras",
        "endpoint": _OFFICIAL_BASE_URL,
        "sdk": {"package": _SDK_PACKAGE, "version": sdk_version},
        "client": {
            "timeout_seconds": timeout_seconds,
            "max_retries": 0,
            "warm_tcp_connection": False,
        },
        "credential_source": "environment:CEREBRAS_API_KEY",
        "clock": "time.monotonic_ns",
        "capture": capture_result,
        "client_close_error": close_error,
        "ignored_environment_base_url": bool(environment.get("CEREBRAS_BASE_URL")),
    }
    manifest["runner"] = runner_metadata
    manifest_path = evidence_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest
