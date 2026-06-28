#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.proofqa_transition_manifest import (
        TransitionManifestError,
        _load_json,
        _manifest_inventory,
        _manifest_reference,
        verify_transition_manifest,
    )
except ImportError:  # Direct execution from scripts directory.
    from proofqa_transition_manifest import (
        TransitionManifestError,
        _load_json,
        _manifest_inventory,
        _manifest_reference,
        verify_transition_manifest,
    )


class ResponseIntegrityError(ValueError):
    """Raised when response claims do not match manifest-bound observations."""


_PROFILE = "org.ibex.response-integrity.v0.1"
_RESPONSE_PROFILE = "org.liminal.trustworthy-transition.response.v0.1"
_CLAIM_PROFILE = "org.liminal.trustworthy-transition.claim.v0.1"
_SHA256_URI_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CLAIM_VERDICTS = {"SUPPORTED", "CONTRADICTED", "UNVERIFIABLE", "OUT_OF_SCOPE"}
_OVERALL_VERDICTS = {"VERIFIED", "FAILED", "PARTIAL", "NOT_EVALUATED"}
_CLAIM_KEYS = {
    "claim_id",
    "claim_text",
    "claim_digest",
    "observation_refs",
    "comparison",
    "verdict",
    "reason_code",
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest_uri(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ResponseIntegrityError(
            f"{label} must be a non-empty string of at most {maximum} characters"
        )
    return value.strip()


def _json_pointer(document: Any, pointer: Any, *, label: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ResponseIntegrityError(f"{label} must be a JSON Pointer beginning with /")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(token)
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                raise KeyError(token)
            current = current[int(token)]
        else:
            raise KeyError(token)
    return current


def _derived_overall(verdicts: list[str]) -> str:
    if "CONTRADICTED" in verdicts:
        return "FAILED"
    if "UNVERIFIABLE" in verdicts:
        return "PARTIAL" if "SUPPORTED" in verdicts else "FAILED"
    if verdicts and set(verdicts) == {"OUT_OF_SCOPE"}:
        return "NOT_EVALUATED"
    return "VERIFIED"


def _evaluate_claim(
    claim: dict[str, Any],
    *,
    root: Path,
    inventory: dict[str, dict[str, Any]],
    index: int,
) -> tuple[str, list[str]]:
    label = f"response_integrity.claims[{index}]"
    if set(claim) != _CLAIM_KEYS:
        raise ResponseIntegrityError(f"{label} must contain exactly {sorted(_CLAIM_KEYS)}")

    claim_id = _text(claim["claim_id"], label=f"{label}.claim_id", maximum=160)
    claim_text = _text(claim["claim_text"], label=f"{label}.claim_text", maximum=4000)
    expected_digest = digest_uri(
        {"profile_id": _CLAIM_PROFILE, "claim_text": claim_text}
    )
    if claim["claim_digest"] != expected_digest:
        raise ResponseIntegrityError(f"{label}.claim_digest mismatch for {claim_id}")

    declared = claim["verdict"]
    if declared not in _CLAIM_VERDICTS:
        raise ResponseIntegrityError(f"{label}.verdict is invalid")
    _text(claim["reason_code"], label=f"{label}.reason_code", maximum=160)

    refs = claim["observation_refs"]
    if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
        raise ResponseIntegrityError(f"{label}.observation_refs must be an array of strings")
    if len(refs) != len(set(refs)):
        raise ResponseIntegrityError(f"{label}.observation_refs must not contain duplicates")

    paths: list[str] = []
    available_paths: list[str] = []
    for value in refs:
        relative = _manifest_reference(value, role=f"response_integrity.claims[{index}]")
        paths.append(relative)
        if relative in inventory:
            available_paths.append(relative)

    comparison = claim["comparison"]
    if not isinstance(comparison, dict) or "kind" not in comparison:
        raise ResponseIntegrityError(f"{label}.comparison must be an object with kind")
    kind = comparison["kind"]

    if kind == "OUT_OF_SCOPE":
        derived = "OUT_OF_SCOPE"
    elif kind == "REFERENCE_PRESENT":
        derived = "SUPPORTED" if refs and len(available_paths) == len(refs) else "UNVERIFIABLE"
    elif kind == "JSON_POINTER_EQUALS":
        if len(refs) != 1 or len(available_paths) != 1:
            derived = "UNVERIFIABLE"
        else:
            pointer = comparison.get("pointer")
            if "expected_value" not in comparison:
                raise ResponseIntegrityError(f"{label}.comparison.expected_value is required")
            observation = _load_json(
                root / available_paths[0],
                label=f"claim observation {available_paths[0]}",
            )
            try:
                actual = _json_pointer(observation, pointer, label=f"{label}.comparison.pointer")
            except KeyError:
                derived = "UNVERIFIABLE"
            else:
                derived = (
                    "SUPPORTED"
                    if actual == comparison["expected_value"]
                    else "CONTRADICTED"
                )
    else:
        raise ResponseIntegrityError(f"{label}.comparison.kind is invalid")

    if declared != derived:
        raise ResponseIntegrityError(
            f"{label}.verdict mismatch: declared {declared}, derived {derived}"
        )
    return derived, paths


def verify_response_integrity_manifest(
    *,
    evidence_dir: Path,
    manifest_path: Path,
    transition_report_path: Path,
    response_integrity_path: Path,
    policy: str,
) -> dict[str, Any]:
    base_receipt = verify_transition_manifest(
        evidence_dir=evidence_dir,
        manifest_path=manifest_path,
        transition_report_path=transition_report_path,
        policy=policy,
    )
    root, manifest, inventory = _manifest_inventory(
        evidence_dir=evidence_dir,
        manifest_path=manifest_path,
    )
    try:
        integrity_file = response_integrity_path.resolve(strict=True)
    except OSError as error:
        raise ResponseIntegrityError(
            f"response integrity record does not exist: {response_integrity_path}"
        ) from error
    if (
        response_integrity_path.is_symlink()
        or not integrity_file.is_file()
        or not integrity_file.is_relative_to(root)
    ):
        raise ResponseIntegrityError(
            "response integrity record must be a regular file inside the evidence directory"
        )

    relative = integrity_file.relative_to(root).as_posix()
    entry = inventory.get(relative)
    if entry is None:
        raise ResponseIntegrityError(
            "response integrity record must be listed in the transition manifest"
        )
    if relative == base_receipt["transition"]["report_path"]:
        raise ResponseIntegrityError(
            "response integrity record must be distinct from the transition report"
        )

    record = _load_json(integrity_file, label="response integrity record")
    expected_keys = {
        "schema_version",
        "profile",
        "transition_id",
        "response_profile",
        "response_text",
        "response_digest",
        "claims",
        "overall_verdict",
        "verifier",
        "claim_boundary",
    }
    if set(record) != expected_keys:
        raise ResponseIntegrityError(
            f"response integrity record must contain exactly {sorted(expected_keys)}"
        )
    if record["schema_version"] != 1 or record["profile"] != _PROFILE:
        raise ResponseIntegrityError("response integrity schema/profile mismatch")
    if record["transition_id"] != base_receipt["transition"]["transition_id"]:
        raise ResponseIntegrityError("response integrity transition_id mismatch")
    if record["response_profile"] != _RESPONSE_PROFILE:
        raise ResponseIntegrityError("response integrity response_profile mismatch")

    response_text = _text(
        record["response_text"], label="response_integrity.response_text", maximum=20000
    )
    expected_response_digest = digest_uri(
        {"profile_id": _RESPONSE_PROFILE, "response_text": response_text}
    )
    if record["response_digest"] != expected_response_digest:
        raise ResponseIntegrityError("response integrity response_digest mismatch")
    if not _SHA256_URI_RE.fullmatch(record["response_digest"]):
        raise ResponseIntegrityError("response integrity response_digest is invalid")

    verifier = record["verifier"]
    if not isinstance(verifier, dict) or set(verifier) != {"id", "version"}:
        raise ResponseIntegrityError("response integrity verifier must contain id and version")
    _text(verifier["id"], label="response_integrity.verifier.id", maximum=200)
    _text(verifier["version"], label="response_integrity.verifier.version", maximum=100)
    _text(record["claim_boundary"], label="response_integrity.claim_boundary", maximum=2000)

    claims = record["claims"]
    if not isinstance(claims, list) or not claims:
        raise ResponseIntegrityError("response integrity claims must be a non-empty array")

    seen_ids: set[str] = set()
    verdicts: list[str] = []
    normalized_claims: list[dict[str, Any]] = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ResponseIntegrityError(f"response_integrity.claims[{index}] must be an object")
        claim_id = claim.get("claim_id")
        if claim_id in seen_ids:
            raise ResponseIntegrityError(f"duplicate response integrity claim_id: {claim_id}")
        seen_ids.add(claim_id)
        verdict, paths = _evaluate_claim(
            claim,
            root=root,
            inventory=inventory,
            index=index,
        )
        verdicts.append(verdict)
        normalized_claims.append(
            {
                "claim_id": claim_id,
                "verdict": verdict,
                "reason_code": claim["reason_code"],
                "observation_paths": paths,
            }
        )

    derived_overall = _derived_overall(verdicts)
    if record["overall_verdict"] not in _OVERALL_VERDICTS:
        raise ResponseIntegrityError("response integrity overall_verdict is invalid")
    if record["overall_verdict"] != derived_overall:
        raise ResponseIntegrityError(
            "response integrity overall_verdict mismatch: "
            f"declared {record['overall_verdict']}, derived {derived_overall}"
        )

    execution = (
        "OBSERVED"
        if base_receipt["references"].get("result_ref") is not None
        else "NOT_OBSERVED"
    )
    return {
        "schema_version": 1,
        "status": "VERIFIED",
        "policy": policy,
        "transition_manifest_receipt": base_receipt,
        "response_integrity": {
            "path": relative,
            "size_bytes": entry["size_bytes"],
            "sha256": entry["sha256"],
            "response_digest": record["response_digest"],
            "overall_verdict": derived_overall,
            "claims": normalized_claims,
            "verifier": dict(verifier),
        },
        "dimensions": {
            "authority": "EXTERNAL_NOT_EVALUATED",
            "execution": execution,
            "response_integrity": derived_overall,
        },
        "manifest": {
            "path": manifest.relative_to(root).as_posix(),
            "files_checked": len(inventory),
        },
        "claim_boundary": (
            "This receipt proves that the response integrity record and its referenced local "
            "observations were bound to the same exact manifest inventory and that the declared "
            "claim verdicts match the deterministic comparison rules. It does not issue or repair "
            "action authorization."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--transition-report", required=True, type=Path)
    parser.add_argument("--response-integrity", required=True, type=Path)
    parser.add_argument("--policy", choices=("verify", "require-attested"), default="verify")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = verify_response_integrity_manifest(
            evidence_dir=args.evidence_dir,
            manifest_path=args.manifest,
            transition_report_path=args.transition_report,
            response_integrity_path=args.response_integrity,
            policy=args.policy,
        )
        rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    except (OSError, TransitionManifestError, ResponseIntegrityError) as error:
        print(f"ProofQA response integrity error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
