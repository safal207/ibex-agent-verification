#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts import proofqa_gate_v3 as core
    from scripts import proofqa_gate_v4 as transition_gate
except ImportError:  # Direct execution from the scripts directory.
    import proofqa_gate_v3 as core
    import proofqa_gate_v4 as transition_gate


class ProofQAGateV5Error(ValueError):
    """Raised when transition-manifest policy or receipt evidence is invalid."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_KEYS = {
    "intent_ref",
    "action_ref",
    "result_ref",
    "verification_ref",
}


def _manifest_policy(environment: Mapping[str, str]) -> str:
    return core._require_choice(
        environment.get("PROOFQA_TRANSITION_MANIFEST_POLICY", "ignore"),
        name="transition-manifest-policy",
        choices={"ignore", "verify", "require-attested"},
    )


def _required_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProofQAGateV5Error(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return value


def _required_text(value: Any, *, label: str, maximum: int = 500) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or "\n" in value
        or "\r" in value
    ):
        raise ProofQAGateV5Error(
            f"{label} must be a single-line non-empty string of at most {maximum} characters"
        )
    return value.strip()


def _non_negative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProofQAGateV5Error(f"{label} must be a non-negative integer")
    return value


def validate_manifest_receipt(
    *,
    receipt: dict[str, Any],
    expected_policy: str,
    transition: dict[str, Any],
    transition_path: Path,
) -> dict[str, Any]:
    if receipt.get("schema_version") != 1:
        raise ProofQAGateV5Error("transition manifest receipt schema_version must equal 1")
    if receipt.get("status") != "VERIFIED":
        raise ProofQAGateV5Error("transition manifest receipt status must equal VERIFIED")
    if receipt.get("policy") != expected_policy:
        raise ProofQAGateV5Error(
            "transition manifest receipt policy does not match transition-manifest-policy"
        )

    receipt_transition = receipt.get("transition")
    if not isinstance(receipt_transition, dict):
        raise ProofQAGateV5Error("transition manifest receipt transition must be an object")
    for field in ("transition_id", "status", "phase"):
        if receipt_transition.get(field) != transition[field]:
            raise ProofQAGateV5Error(
                f"transition manifest receipt {field} does not match transition report"
            )
    report_path = _required_text(
        receipt_transition.get("report_path"),
        label="transition manifest receipt report_path",
    )
    report_size = _non_negative_int(
        receipt_transition.get("report_size_bytes"),
        label="transition manifest receipt report_size_bytes",
    )
    report_sha = _required_sha(
        receipt_transition.get("report_sha256"),
        label="transition manifest receipt report_sha256",
    )
    actual_size = transition_path.stat().st_size
    actual_sha = core._sha256(transition_path)
    if report_size != actual_size or report_sha != actual_sha:
        raise ProofQAGateV5Error(
            "transition manifest receipt no longer matches the consumed transition report bytes"
        )

    manifest = receipt.get("manifest")
    if not isinstance(manifest, dict):
        raise ProofQAGateV5Error("transition manifest receipt manifest must be an object")
    manifest_path = _required_text(
        manifest.get("path"),
        label="transition manifest receipt manifest.path",
    )
    manifest_sha = _required_sha(
        manifest.get("sha256"),
        label="transition manifest receipt manifest.sha256",
    )
    files_checked = _non_negative_int(
        manifest.get("files_checked"),
        label="transition manifest receipt manifest.files_checked",
    )
    if files_checked == 0:
        raise ProofQAGateV5Error(
            "transition manifest receipt must verify at least one file"
        )

    references = receipt.get("references")
    if not isinstance(references, dict) or set(references) != _REFERENCE_KEYS:
        raise ProofQAGateV5Error(
            "transition manifest receipt references must contain exactly all four evidence roles"
        )
    normalized_references: dict[str, dict[str, Any] | None] = {}
    observed_paths: set[str] = set()
    for role in sorted(_REFERENCE_KEYS):
        entry = references[role]
        if entry is None:
            normalized_references[role] = None
            continue
        if not isinstance(entry, dict) or set(entry) != {
            "path",
            "size_bytes",
            "sha256",
        }:
            raise ProofQAGateV5Error(
                f"transition manifest receipt references.{role} must contain exactly path, size_bytes, and sha256"
            )
        path = _required_text(
            entry.get("path"),
            label=f"transition manifest receipt references.{role}.path",
        )
        if path in observed_paths:
            raise ProofQAGateV5Error(
                "transition manifest receipt evidence paths must be distinct"
            )
        observed_paths.add(path)
        normalized_references[role] = {
            "path": path,
            "size_bytes": _non_negative_int(
                entry.get("size_bytes"),
                label=f"transition manifest receipt references.{role}.size_bytes",
            ),
            "sha256": _required_sha(
                entry.get("sha256"),
                label=f"transition manifest receipt references.{role}.sha256",
            ),
        }

    attestation = receipt.get("attestation")
    if not isinstance(attestation, dict):
        raise ProofQAGateV5Error(
            "transition manifest receipt attestation must be an object"
        )
    if expected_policy == "verify":
        if attestation != {"required": False, "status": "NOT_REQUIRED"}:
            raise ProofQAGateV5Error(
                "verify policy requires attestation status NOT_REQUIRED"
            )
        normalized_attestation = dict(attestation)
    else:
        if attestation.get("required") is not True or attestation.get("status") != "VERIFIED":
            raise ProofQAGateV5Error(
                "require-attested policy requires VERIFIED attestation receipt"
            )
        normalized_attestation = {
            "required": True,
            "status": "VERIFIED",
            "repository": _required_text(
                attestation.get("repository"),
                label="transition manifest attestation repository",
                maximum=200,
            ),
            "signer_workflow": _required_text(
                attestation.get("signer_workflow"),
                label="transition manifest attestation signer_workflow",
                maximum=300,
            ),
            "deny_self_hosted_runners": attestation.get(
                "deny_self_hosted_runners"
            ),
            "bundle_path": _required_text(
                attestation.get("bundle_path"),
                label="transition manifest attestation bundle_path",
            ),
            "bundle_sha256": _required_sha(
                attestation.get("bundle_sha256"),
                label="transition manifest attestation bundle_sha256",
            ),
            "online_report_sha256": _required_sha(
                attestation.get("online_report_sha256"),
                label="transition manifest online_report_sha256",
            ),
            "bundled_report_sha256": _required_sha(
                attestation.get("bundled_report_sha256"),
                label="transition manifest bundled_report_sha256",
            ),
        }
        if normalized_attestation["deny_self_hosted_runners"] is not True:
            raise ProofQAGateV5Error(
                "attested transition manifest must deny self-hosted runners"
            )

    return {
        "status": "VERIFIED",
        "policy": expected_policy,
        "transition_report_path": report_path,
        "transition_report_sha256": report_sha,
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha,
        "files_checked": files_checked,
        "references": normalized_references,
        "attestation": normalized_attestation,
    }


def build_report(
    *,
    summary_path: Path,
    summary: dict[str, Any],
    transition_path: Path | None,
    policy: transition_gate.GatePolicyV4,
    evaluation: dict[str, Any],
    manifest_policy: str,
    manifest_receipt_path: Path | None,
    manifest_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    report = transition_gate.build_report(
        summary_path=summary_path,
        summary=summary,
        transition_path=transition_path,
        policy=policy,
        evaluation=evaluation,
    )
    report["schema_version"] = 4
    report["policy"]["transition_manifest_policy"] = manifest_policy
    report["source"].update(
        {
            "transition_manifest_receipt_path": None,
            "transition_manifest_receipt_sha256": None,
            "transition_manifest_path": None,
            "transition_manifest_sha256": None,
        }
    )
    report["transition_manifest"] = manifest_receipt
    if manifest_receipt_path is not None and manifest_receipt is not None:
        report["source"].update(
            {
                "transition_manifest_receipt_path": str(manifest_receipt_path),
                "transition_manifest_receipt_sha256": core._sha256(
                    manifest_receipt_path
                ),
                "transition_manifest_path": manifest_receipt["manifest_path"],
                "transition_manifest_sha256": manifest_receipt["manifest_sha256"],
            }
        )
    report["claim_boundary"] = (
        "The gate applies configured correctness, reliability, time, transition, and "
        "transition-manifest policies to one scorecard. When enabled, the manifest receipt "
        "binds the consumed transition report and every non-null evidence reference to exact "
        "local bytes. Cryptographic signer identity is claimed only for require-attested with "
        "a VERIFIED attestation receipt. Stable quality and latency still require repeated, "
        "versioned evidence."
    )
    return report


def render_markdown(report: dict[str, Any]) -> str:
    rendered = transition_gate.render_markdown(report)
    manifest = report["transition_manifest"]
    lines = [rendered, "", "### Transition evidence manifest", ""]
    if manifest is None:
        lines.append("- Manifest binding: `disabled`")
    else:
        lines.extend(
            [
                f"- Policy: `{manifest['policy']}`",
                f"- Manifest: `{manifest['manifest_path']}`",
                f"- Manifest SHA-256: `{manifest['manifest_sha256']}`",
                f"- Files checked: `{manifest['files_checked']}`",
                f"- Attestation: `{manifest['attestation']['status']}`",
            ]
        )
        for role, entry in manifest["references"].items():
            if entry is not None:
                lines.append(
                    f"- `{role}` → `{entry['path']}` / `{entry['sha256']}`"
                )
    lines.append("")
    return "\n".join(lines)


def _write_outputs(path: Path, report: dict[str, Any], report_path: Path) -> None:
    transition_gate._write_outputs(path, report, report_path)
    manifest = report["transition_manifest"]
    values = {
        "transition-manifest-status": (
            manifest["status"] if manifest is not None else "n/a"
        ),
        "transition-manifest-sha256": (
            manifest["manifest_sha256"] if manifest is not None else "n/a"
        ),
        "transition-manifest-receipt-sha256": (
            report["source"]["transition_manifest_receipt_sha256"] or "n/a"
        ),
        "transition-attestation-status": (
            manifest["attestation"]["status"] if manifest is not None else "n/a"
        ),
    }
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def run(environment: Mapping[str, str]) -> int:
    summary_raw = environment.get("PROOFQA_SUMMARY_PATH", "").strip()
    if not summary_raw:
        raise ProofQAGateV5Error("summary-path is required")
    report_raw = environment.get(
        "PROOFQA_REPORT_PATH", "proofqa-gate-report.json"
    ).strip()
    if not report_raw:
        raise ProofQAGateV5Error("report-path must not be empty")

    summary_path = Path(summary_raw)
    report_path = Path(report_raw)
    if report_path.is_symlink() or report_path.is_dir():
        raise ProofQAGateV5Error(
            f"report-path must be a writable regular-file path: {report_path}"
        )

    policy = transition_gate.policy_from_environment(environment)
    manifest_policy = _manifest_policy(environment)
    transition_raw = environment.get("PROOFQA_TRANSITION_REPORT_PATH", "").strip()
    transition_path = Path(transition_raw) if transition_raw else None
    if policy.transition_policy != "ignore" and transition_path is None:
        raise ProofQAGateV5Error(
            f"transition-report-path is required when transition-policy={policy.transition_policy}"
        )
    if policy.transition_policy == "ignore" and manifest_policy != "ignore":
        raise ProofQAGateV5Error(
            "transition-manifest-policy must be ignore when transition-policy is ignore"
        )

    summary = core._load_json_object(summary_path, label="ProofQA summary")
    transition: dict[str, Any] | None = None
    if transition_path is not None and policy.transition_policy != "ignore":
        raw_transition = core._load_json_object(
            transition_path,
            label="ProofQA transition report",
        )
        transition = transition_gate.validate_transition_report(raw_transition)

    receipt_raw = environment.get(
        "PROOFQA_TRANSITION_MANIFEST_RECEIPT_PATH", ""
    ).strip()
    receipt_path = Path(receipt_raw) if receipt_raw else None
    manifest_receipt: dict[str, Any] | None = None
    if manifest_policy != "ignore":
        if transition is None or transition_path is None:
            raise ProofQAGateV5Error(
                "transition manifest verification requires an enabled transition report"
            )
        if receipt_path is None:
            raise ProofQAGateV5Error(
                "transition-manifest-receipt-path is required when transition-manifest-policy is enabled"
            )
        raw_receipt = core._load_json_object(
            receipt_path,
            label="ProofQA transition manifest receipt",
        )
        manifest_receipt = validate_manifest_receipt(
            receipt=raw_receipt,
            expected_policy=manifest_policy,
            transition=transition,
            transition_path=transition_path,
        )

    summary_resolved = summary_path.resolve(strict=True)
    report_resolved = report_path.resolve(strict=False)
    protected_sources = [summary_resolved]
    if transition_path is not None and policy.transition_policy != "ignore":
        protected_sources.append(transition_path.resolve(strict=True))
    if receipt_path is not None and manifest_policy != "ignore":
        protected_sources.append(receipt_path.resolve(strict=True))
    for protected in protected_sources:
        same_existing_file = report_path.exists() and os.path.samefile(
            protected, report_path
        )
        if report_resolved == protected or same_existing_file:
            raise ProofQAGateV5Error(
                "report-path must differ from every consumed source report"
            )

    evaluation = transition_gate.evaluate_gate(
        summary=summary,
        policy=policy,
        transition=transition,
    )
    report = build_report(
        summary_path=summary_path,
        summary=summary,
        transition_path=(
            transition_path if policy.transition_policy != "ignore" else None
        ),
        policy=policy,
        evaluation=evaluation,
        manifest_policy=manifest_policy,
        manifest_receipt_path=(receipt_path if manifest_policy != "ignore" else None),
        manifest_receipt=manifest_receipt,
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    markdown = render_markdown(report)
    print(markdown)

    step_summary = environment.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with Path(step_summary).open("a", encoding="utf-8", newline="\n") as output:
            output.write(markdown)

    github_output = environment.get("GITHUB_OUTPUT")
    if github_output:
        _write_outputs(Path(github_output), report, report_path)

    annotation = "error" if report["decision"] == "BLOCK" else "warning"
    if report["decision"] != "PASS":
        messages = "; ".join(
            finding["message"]
            for finding in report["findings"]
            if finding["status"] != "PASS"
        )
        print(
            f"::{annotation} title=ProofQA {report['decision']}::"
            f"{core._escape_workflow_command(messages)}"
        )
    return 1 if report["should_fail"] else 0


def main() -> int:
    try:
        return run(os.environ)
    except (
        OSError,
        core.ProofQAGateV3Error,
        transition_gate.ProofQAGateV4Error,
        ProofQAGateV5Error,
    ) as error:
        message = core._escape_workflow_command(str(error))
        print(f"::error title=ProofQA configuration error::{message}")
        print(f"ProofQA gate error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
