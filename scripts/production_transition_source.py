#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts import proofqa_gate_v3 as json_support
    from scripts.proofqa_transition_preflight import validate_transition_evidence
except ImportError:  # Direct execution from the scripts directory.
    import proofqa_gate_v3 as json_support
    from proofqa_transition_preflight import validate_transition_evidence


class ProductionTransitionSourceError(ValueError):
    """Raised when a production transition source is malformed or untrusted."""


_EXPECTED_FILES = {
    "source-provenance.json",
    "transition-report.json",
    "evidence/intent.json",
    "evidence/action.json",
    "evidence/result.json",
    "evidence/verification.json",
}
_EXPECTED_DIRECTORIES = {"evidence"}
_ROLE_PATHS = {
    "intent_ref": "evidence/intent.json",
    "action_ref": "evidence/action.json",
    "result_ref": "evidence/result.json",
    "verification_ref": "evidence/verification.json",
}
_REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/"
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})$"
)
_HEX_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,199}$")
_MAX_JSON_BYTES = 1024 * 1024

_PROVENANCE_KEYS = {
    "schema_version",
    "kind",
    "repository",
    "source_commit",
    "deployment",
    "destination",
    "release",
    "claim_boundary",
}
_DEPLOYMENT_KEYS = {"workflow", "run_id", "run_attempt", "event", "branch"}
_DESTINATION_KEYS = {"environment", "identity"}
_RELEASE_KEYS = {"release_id", "subject_digest"}
_COMMON_EVIDENCE_KEYS = {
    "schema_version",
    "kind",
    "transition_id",
    "repository",
    "source_commit",
    "release_id",
    "destination",
}
_EVIDENCE_KEYS = {
    "intent": _COMMON_EVIDENCE_KEYS | {"statement"},
    "action": _COMMON_EVIDENCE_KEYS
    | {"deployment", "subject_digest", "status"},
    "result": _COMMON_EVIDENCE_KEYS
    | {"deployment_id", "subject_digest", "status"},
    "verification": _COMMON_EVIDENCE_KEYS
    | {"subject_digest", "observed_destination", "status", "checks"},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductionTransitionSourceError(
                f"JSON object contains duplicate key: {key}"
            )
        result[key] = value
    return result


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProductionTransitionSourceError(
            f"{label} must be a regular non-symlink file: {path}"
        )
    size = path.stat().st_size
    if size <= 0 or size > _MAX_JSON_BYTES:
        raise ProductionTransitionSourceError(
            f"{label} must contain between 1 and {_MAX_JSON_BYTES} bytes"
        )
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except UnicodeDecodeError as error:
        raise ProductionTransitionSourceError(
            f"{path}: {label} must be UTF-8"
        ) from error
    except json.JSONDecodeError as error:
        raise ProductionTransitionSourceError(
            f"{path}: invalid {label} JSON: {error.msg}"
        ) from error
    if not isinstance(value, dict):
        raise ProductionTransitionSourceError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ProductionTransitionSourceError(
            f"{label} keys mismatch; missing={missing}, unexpected={unexpected}"
        )


def _text(
    value: Any,
    *,
    label: str,
    maximum: int = 500,
    single_line: bool = True,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or (single_line and ("\n" in value or "\r" in value))
    ):
        qualifier = "single-line " if single_line else ""
        raise ProductionTransitionSourceError(
            f"{label} must be a {qualifier}non-empty string of at most {maximum} characters"
        )
    return value.strip()


def _positive_integer(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProductionTransitionSourceError(f"{label} must be a positive integer")
    return value


def _repository(value: Any, *, label: str) -> str:
    normalized = _text(value, label=label, maximum=201)
    if not _REPOSITORY_RE.fullmatch(normalized):
        raise ProductionTransitionSourceError(
            f"{label} must use canonical owner/repository form"
        )
    return normalized


def _commit(value: Any, *, label: str) -> str:
    normalized = _text(value, label=label, maximum=40)
    if not _HEX_SHA_RE.fullmatch(normalized):
        raise ProductionTransitionSourceError(
            f"{label} must be 40 lowercase hexadecimal characters"
        )
    return normalized


def _digest(value: Any, *, label: str) -> str:
    normalized = _text(value, label=label, maximum=71)
    if not _DIGEST_RE.fullmatch(normalized):
        raise ProductionTransitionSourceError(
            f"{label} must use lowercase sha256:<64-hex> form"
        )
    return normalized


def _identifier(value: Any, *, label: str) -> str:
    normalized = _text(value, label=label, maximum=200)
    if not _ID_RE.fullmatch(normalized):
        raise ProductionTransitionSourceError(
            f"{label} contains unsupported characters"
        )
    return normalized


def _workflow_path(value: Any, *, label: str) -> str:
    normalized = _text(value, label=label, maximum=300)
    if "\\" in normalized or normalized.startswith("/"):
        raise ProductionTransitionSourceError(
            f"{label} must be a canonical relative POSIX workflow path"
        )
    path = PurePosixPath(normalized)
    if (
        len(path.parts) < 3
        or path.parts[:2] != (".github", "workflows")
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix not in {".yml", ".yaml"}
        or path.as_posix() != normalized
    ):
        raise ProductionTransitionSourceError(
            f"{label} must identify one .github/workflows/*.yml or *.yaml file"
        )
    return normalized


def _destination(value: Any, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ProductionTransitionSourceError(f"{label} must be an object")
    _exact_keys(value, _DESTINATION_KEYS, label=label)
    return {
        "environment": _identifier(
            value["environment"], label=f"{label}.environment"
        ),
        "identity": _text(value["identity"], label=f"{label}.identity", maximum=500),
    }


def _deployment(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProductionTransitionSourceError(f"{label} must be an object")
    _exact_keys(value, _DEPLOYMENT_KEYS, label=label)
    return {
        "workflow": _workflow_path(value["workflow"], label=f"{label}.workflow"),
        "run_id": _positive_integer(value["run_id"], label=f"{label}.run_id"),
        "run_attempt": _positive_integer(
            value["run_attempt"], label=f"{label}.run_attempt"
        ),
        "event": _identifier(value["event"], label=f"{label}.event"),
        "branch": _identifier(value["branch"], label=f"{label}.branch"),
    }


def _validate_layout(source_dir: Path) -> Path:
    if source_dir.is_symlink():
        raise ProductionTransitionSourceError(
            f"production source directory must not be a symlink: {source_dir}"
        )
    try:
        root = source_dir.resolve(strict=True)
    except OSError as error:
        raise ProductionTransitionSourceError(
            f"production source directory does not exist: {source_dir}"
        ) from error
    if not root.is_dir():
        raise ProductionTransitionSourceError(
            f"production source path is not a directory: {source_dir}"
        )

    files: set[str] = set()
    directories: set[str] = set()
    for candidate in root.rglob("*"):
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            raise ProductionTransitionSourceError(
                f"production source contains a symlink: {relative}"
            )
        if candidate.is_dir():
            directories.add(relative)
        elif candidate.is_file():
            files.add(relative)
        else:
            raise ProductionTransitionSourceError(
                f"production source contains a non-regular path: {relative}"
            )

    if files != _EXPECTED_FILES or directories != _EXPECTED_DIRECTORIES:
        raise ProductionTransitionSourceError(
            "production source layout mismatch; "
            f"missing_files={sorted(_EXPECTED_FILES - files)}, "
            f"unexpected_files={sorted(files - _EXPECTED_FILES)}, "
            f"missing_directories={sorted(_EXPECTED_DIRECTORIES - directories)}, "
            f"unexpected_directories={sorted(directories - _EXPECTED_DIRECTORIES)}"
        )
    return root


def _validate_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(payload, _PROVENANCE_KEYS, label="source provenance")
    if payload["schema_version"] != 1:
        raise ProductionTransitionSourceError(
            "source provenance schema_version must equal 1"
        )
    if payload["kind"] != "production-transition-source":
        raise ProductionTransitionSourceError(
            "source provenance kind must equal production-transition-source"
        )
    release = payload["release"]
    if not isinstance(release, dict):
        raise ProductionTransitionSourceError(
            "source provenance release must be an object"
        )
    _exact_keys(release, _RELEASE_KEYS, label="source provenance release")
    claim_boundary = _text(
        payload["claim_boundary"],
        label="source provenance claim_boundary",
        maximum=2000,
        single_line=False,
    )
    return {
        "schema_version": 1,
        "kind": "production-transition-source",
        "repository": _repository(
            payload["repository"], label="source provenance repository"
        ),
        "source_commit": _commit(
            payload["source_commit"], label="source provenance source_commit"
        ),
        "deployment": _deployment(
            payload["deployment"], label="source provenance deployment"
        ),
        "destination": _destination(
            payload["destination"], label="source provenance destination"
        ),
        "release": {
            "release_id": _identifier(
                release["release_id"], label="source provenance release.release_id"
            ),
            "subject_digest": _digest(
                release["subject_digest"],
                label="source provenance release.subject_digest",
            ),
        },
        "claim_boundary": claim_boundary,
    }


def _require_equal(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise ProductionTransitionSourceError(
            f"{label} mismatch: expected {expected!r}, got {actual!r}"
        )


def _validate_common_evidence(
    payload: dict[str, Any],
    *,
    role: str,
    provenance: dict[str, Any],
    transition_id: str,
) -> None:
    _exact_keys(payload, _EVIDENCE_KEYS[role], label=f"{role} evidence")
    if payload["schema_version"] != 1:
        raise ProductionTransitionSourceError(
            f"{role} evidence schema_version must equal 1"
        )
    expected_kind = f"production-transition-{role}"
    if payload["kind"] != expected_kind:
        raise ProductionTransitionSourceError(
            f"{role} evidence kind must equal {expected_kind}"
        )
    normalized = {
        "transition_id": _identifier(
            payload["transition_id"], label=f"{role} evidence transition_id"
        ),
        "repository": _repository(
            payload["repository"], label=f"{role} evidence repository"
        ),
        "source_commit": _commit(
            payload["source_commit"], label=f"{role} evidence source_commit"
        ),
        "release_id": _identifier(
            payload["release_id"], label=f"{role} evidence release_id"
        ),
        "destination": _destination(
            payload["destination"], label=f"{role} evidence destination"
        ),
    }
    _require_equal(
        normalized["transition_id"], transition_id, label=f"{role} evidence transition_id"
    )
    _require_equal(
        normalized["repository"],
        provenance["repository"],
        label=f"{role} evidence repository",
    )
    _require_equal(
        normalized["source_commit"],
        provenance["source_commit"],
        label=f"{role} evidence source_commit",
    )
    _require_equal(
        normalized["release_id"],
        provenance["release"]["release_id"],
        label=f"{role} evidence release_id",
    )
    _require_equal(
        normalized["destination"],
        provenance["destination"],
        label=f"{role} evidence destination",
    )


def _validate_evidence(
    *,
    root: Path,
    provenance: dict[str, Any],
    transition: dict[str, Any],
) -> None:
    transition_id = transition["transition_id"]

    intent = _load_json_object(root / "evidence/intent.json", label="intent evidence")
    _validate_common_evidence(
        intent, role="intent", provenance=provenance, transition_id=transition_id
    )
    _text(
        intent["statement"],
        label="intent evidence statement",
        maximum=2000,
        single_line=False,
    )

    action = _load_json_object(root / "evidence/action.json", label="action evidence")
    _validate_common_evidence(
        action, role="action", provenance=provenance, transition_id=transition_id
    )
    action_deployment = action["deployment"]
    if not isinstance(action_deployment, dict):
        raise ProductionTransitionSourceError(
            "action evidence deployment must be an object"
        )
    _exact_keys(
        action_deployment,
        {"workflow", "run_id", "run_attempt"},
        label="action evidence deployment",
    )
    normalized_action_deployment = {
        "workflow": _workflow_path(
            action_deployment["workflow"], label="action evidence deployment.workflow"
        ),
        "run_id": _positive_integer(
            action_deployment["run_id"], label="action evidence deployment.run_id"
        ),
        "run_attempt": _positive_integer(
            action_deployment["run_attempt"],
            label="action evidence deployment.run_attempt",
        ),
    }
    expected_action_deployment = {
        key: provenance["deployment"][key]
        for key in ("workflow", "run_id", "run_attempt")
    }
    _require_equal(
        normalized_action_deployment,
        expected_action_deployment,
        label="action evidence deployment",
    )
    _require_equal(
        _digest(action["subject_digest"], label="action evidence subject_digest"),
        provenance["release"]["subject_digest"],
        label="action evidence subject_digest",
    )
    if action["status"] != "COMPLETED":
        raise ProductionTransitionSourceError(
            "action evidence status must equal COMPLETED"
        )

    result = _load_json_object(root / "evidence/result.json", label="result evidence")
    _validate_common_evidence(
        result, role="result", provenance=provenance, transition_id=transition_id
    )
    _identifier(result["deployment_id"], label="result evidence deployment_id")
    _require_equal(
        _digest(result["subject_digest"], label="result evidence subject_digest"),
        provenance["release"]["subject_digest"],
        label="result evidence subject_digest",
    )
    if result["status"] != "SUCCEEDED":
        raise ProductionTransitionSourceError(
            "result evidence status must equal SUCCEEDED"
        )

    verification = _load_json_object(
        root / "evidence/verification.json", label="verification evidence"
    )
    _validate_common_evidence(
        verification,
        role="verification",
        provenance=provenance,
        transition_id=transition_id,
    )
    _require_equal(
        _digest(
            verification["subject_digest"],
            label="verification evidence subject_digest",
        ),
        provenance["release"]["subject_digest"],
        label="verification evidence subject_digest",
    )
    observed_destination = _destination(
        verification["observed_destination"],
        label="verification evidence observed_destination",
    )
    _require_equal(
        observed_destination,
        provenance["destination"],
        label="verification evidence observed_destination",
    )
    if verification["status"] != "VERIFIED":
        raise ProductionTransitionSourceError(
            "verification evidence status must equal VERIFIED"
        )
    checks = verification["checks"]
    if not isinstance(checks, list) or not checks or len(checks) > 100:
        raise ProductionTransitionSourceError(
            "verification evidence checks must be a non-empty array of at most 100 strings"
        )
    normalized_checks = [
        _text(item, label="verification evidence checks item", maximum=500)
        for item in checks
    ]
    if len(set(normalized_checks)) != len(normalized_checks):
        raise ProductionTransitionSourceError(
            "verification evidence checks must not contain duplicates"
        )


def validate_production_transition_source(
    *,
    source_dir: Path,
    expected_repository: str,
    expected_commit: str,
    expected_workflow: str,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_event: str,
    expected_branch: str,
    expected_environment: str,
    expected_destination_id: str,
) -> dict[str, Any]:
    root = _validate_layout(source_dir)
    provenance = _validate_provenance(
        _load_json_object(root / "source-provenance.json", label="source provenance")
    )

    expected = {
        "repository": _repository(expected_repository, label="expected repository"),
        "source_commit": _commit(expected_commit, label="expected commit"),
        "deployment": {
            "workflow": _workflow_path(expected_workflow, label="expected workflow"),
            "run_id": _positive_integer(expected_run_id, label="expected run id"),
            "run_attempt": _positive_integer(
                expected_run_attempt, label="expected run attempt"
            ),
            "event": _identifier(expected_event, label="expected event"),
            "branch": _identifier(expected_branch, label="expected branch"),
        },
        "destination": {
            "environment": _identifier(
                expected_environment, label="expected environment"
            ),
            "identity": _text(
                expected_destination_id,
                label="expected destination identity",
                maximum=500,
            ),
        },
    }
    _require_equal(
        provenance["repository"], expected["repository"], label="source provenance repository"
    )
    _require_equal(
        provenance["source_commit"],
        expected["source_commit"],
        label="source provenance source_commit",
    )
    _require_equal(
        provenance["deployment"],
        expected["deployment"],
        label="source provenance deployment",
    )
    _require_equal(
        provenance["destination"],
        expected["destination"],
        label="source provenance destination",
    )

    transition_report = _load_json_object(
        root / "transition-report.json", label="transition report"
    )
    transition = validate_transition_evidence(transition_report)
    if transition["status"] != "VERIFIED":
        raise ProductionTransitionSourceError(
            "production transition report must be VERIFIED"
        )
    _require_equal(
        transition_report.get("claim_boundary"),
        provenance["claim_boundary"],
        label="transition claim_boundary",
    )
    for role, path in _ROLE_PATHS.items():
        _require_equal(
            transition["evidence"][role],
            f"manifest:{path}",
            label=f"transition evidence {role}",
        )

    _validate_evidence(root=root, provenance=provenance, transition=transition)

    inventory = [
        {
            "path": relative,
            "size_bytes": (root / relative).stat().st_size,
            "sha256": sha256_file(root / relative),
        }
        for relative in sorted(_EXPECTED_FILES)
    ]
    source_set_bytes = json.dumps(
        inventory, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    source_set_digest = hashlib.sha256(source_set_bytes).hexdigest()

    return {
        "schema_version": 1,
        "kind": "production-transition-source-validation",
        "status": "VALIDATED",
        "repository": provenance["repository"],
        "source_commit": provenance["source_commit"],
        "transition_id": transition["transition_id"],
        "deployment": provenance["deployment"],
        "destination": provenance["destination"],
        "release": provenance["release"],
        "claim_boundary": provenance["claim_boundary"],
        "files_checked": len(inventory),
        "files": inventory,
        "source_set_digest": f"sha256:{source_set_digest}",
    }


def write_validation_report(
    *,
    path: Path,
    payload: dict[str, Any],
    source_dir: Path,
) -> None:
    source_root = source_dir.resolve(strict=True)
    if path.is_symlink() or path.is_dir():
        raise ProductionTransitionSourceError(
            f"validation report must be a writable regular-file path: {path}"
        )
    resolved = path.resolve(strict=False)
    if resolved.is_relative_to(source_root):
        raise ProductionTransitionSourceError(
            "validation report must be written outside the production source directory"
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate one immutable production transition source"
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--expected-repository", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-workflow", required=True)
    parser.add_argument("--expected-run-id", type=int, required=True)
    parser.add_argument("--expected-run-attempt", type=int, required=True)
    parser.add_argument("--expected-event", required=True)
    parser.add_argument("--expected-branch", required=True)
    parser.add_argument("--expected-environment", required=True)
    parser.add_argument("--expected-destination-id", required=True)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = validate_production_transition_source(
            source_dir=args.source_dir,
            expected_repository=args.expected_repository,
            expected_commit=args.expected_commit,
            expected_workflow=args.expected_workflow,
            expected_run_id=args.expected_run_id,
            expected_run_attempt=args.expected_run_attempt,
            expected_event=args.expected_event,
            expected_branch=args.expected_branch,
            expected_environment=args.expected_environment,
            expected_destination_id=args.expected_destination_id,
        )
        if args.report is not None:
            write_validation_report(
                path=args.report, payload=result, source_dir=args.source_dir
            )
    except (OSError, ProductionTransitionSourceError, ValueError) as error:
        message = json_support._escape_workflow_command(str(error))
        print(f"::error title=Production transition source error::{message}")
        print(f"Production transition source error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
