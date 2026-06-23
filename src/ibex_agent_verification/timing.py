from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import TraceValidationError


def _as_non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TraceValidationError(f"{field} must be a non-negative integer")
    if value < 0:
        raise TraceValidationError(f"{field} must be a non-negative integer")
    return value


def _signal_bool(signals: dict[str, Any], key: str) -> bool:
    return signals.get(key) is True


def _positive_signal(signals: dict[str, Any], key: str) -> int:
    value = signals.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value > 0:
        return value
    return 0


@dataclass(frozen=True)
class TimingSample:
    step: int
    cycle_start: int
    cycle_end: int
    expected_cycles: int
    signals: dict[str, Any]

    @classmethod
    def from_raw(cls, raw: Any) -> "TimingSample":
        if not isinstance(raw, dict):
            raise TraceValidationError("timing line must be a JSON object")
        missing = {"step", "cycle_start", "cycle_end", "expected_cycles"} - raw.keys()
        if missing:
            raise TraceValidationError(
                f"missing required fields: {', '.join(sorted(missing))}"
            )
        step = _as_non_negative_int(raw["step"], "step")
        cycle_start = _as_non_negative_int(raw["cycle_start"], "cycle_start")
        cycle_end = _as_non_negative_int(raw["cycle_end"], "cycle_end")
        expected_cycles = _as_non_negative_int(raw["expected_cycles"], "expected_cycles")
        if cycle_end < cycle_start:
            raise TraceValidationError(
                "cycle_end must be greater than or equal to cycle_start"
            )
        signals = raw.get("signals", {})
        if not isinstance(signals, dict):
            raise TraceValidationError("signals must be an object")
        return cls(
            step=step,
            cycle_start=cycle_start,
            cycle_end=cycle_end,
            expected_cycles=expected_cycles,
            signals=signals,
        )

    @property
    def actual_cycles(self) -> int:
        return self.cycle_end - self.cycle_start

    @property
    def delta_cycles(self) -> int:
        return self.actual_cycles - self.expected_cycles


@dataclass(frozen=True)
class CauseCandidate:
    cause: str
    confidence: float
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cause": self.cause,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class TimingFinding:
    step: int
    status: str
    cycle_start: int
    cycle_end: int
    expected_cycles: int
    actual_cycles: int
    delta_cycles: int
    primary_cause: str | None
    confidence: float
    evidence: tuple[str, ...]
    candidates: tuple[CauseCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "cycle_start": self.cycle_start,
            "cycle_end": self.cycle_end,
            "expected_cycles": self.expected_cycles,
            "actual_cycles": self.actual_cycles,
            "delta_cycles": self.delta_cycles,
            "primary_cause": self.primary_cause,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class TimingAnalysis:
    status: str
    samples: int
    anomalies: int
    findings: tuple[TimingFinding, ...]

    @property
    def has_anomalies(self) -> bool:
        return self.anomalies > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "samples": self.samples,
            "anomalies": self.anomalies,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def load_timing_jsonl(path: str | Path) -> list[TimingSample]:
    source = Path(path)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TraceValidationError(f"cannot read timing trace {source}: {exc}") from exc

    samples: list[TimingSample] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            sample = TimingSample.from_raw(json.loads(line))
        except (json.JSONDecodeError, TraceValidationError) as exc:
            raise TraceValidationError(f"{source}:{line_number}: {exc}") from exc
        if samples and sample.step <= samples[-1].step:
            raise TraceValidationError(
                f"{source}:{line_number}: step must increase strictly "
                f"({sample.step} after {samples[-1].step})"
            )
        samples.append(sample)
    return samples


def _candidate_scores(sample: TimingSample) -> list[CauseCandidate]:
    signals = sample.signals
    scores: list[tuple[str, float, list[str]]] = []

    memory_score = 0.0
    memory_evidence: list[str] = []
    wait_cycles = _positive_signal(signals, "memory_wait_cycles")
    if wait_cycles:
        memory_score += 0.55
        memory_evidence.append(f"memory_wait_cycles={wait_cycles}")
    if _signal_bool(signals, "data_req"):
        memory_score += 0.15
        memory_evidence.append("data_req=true")
    if signals.get("data_ready") is False:
        memory_score += 0.15
        memory_evidence.append("data_ready=false")
    if _signal_bool(signals, "pipeline_stall"):
        memory_score += 0.10
        memory_evidence.append("pipeline_stall=true")
    if memory_score:
        scores.append(("MEMORY_WAIT", memory_score, memory_evidence))

    branch_score = 0.0
    branch_evidence: list[str] = []
    if _signal_bool(signals, "branch_mispredict"):
        branch_score += 0.75
        branch_evidence.append("branch_mispredict=true")
    if _signal_bool(signals, "pipeline_flush"):
        branch_score += 0.15
        branch_evidence.append("pipeline_flush=true")
    recovery_cycles = _positive_signal(signals, "branch_recovery_cycles")
    if recovery_cycles:
        branch_score += 0.10
        branch_evidence.append(f"branch_recovery_cycles={recovery_cycles}")
    if branch_score:
        scores.append(("BRANCH_RECOVERY", branch_score, branch_evidence))

    hazard_score = 0.0
    hazard_evidence: list[str] = []
    if _signal_bool(signals, "pipeline_hazard"):
        hazard_score += 0.70
        hazard_evidence.append("pipeline_hazard=true")
    hazard_cycles = _positive_signal(signals, "hazard_cycles")
    if hazard_cycles:
        hazard_score += 0.20
        hazard_evidence.append(f"hazard_cycles={hazard_cycles}")
    if _signal_bool(signals, "pipeline_stall"):
        hazard_score += 0.10
        hazard_evidence.append("pipeline_stall=true")
    if hazard_score:
        scores.append(("PIPELINE_HAZARD", hazard_score, hazard_evidence))

    bus_score = 0.0
    bus_evidence: list[str] = []
    bus_wait = _positive_signal(signals, "bus_wait_cycles")
    if bus_wait:
        bus_score += 0.65
        bus_evidence.append(f"bus_wait_cycles={bus_wait}")
    if signals.get("bus_grant") is False:
        bus_score += 0.25
        bus_evidence.append("bus_grant=false")
    if bus_score:
        scores.append(("BUS_CONTENTION", bus_score, bus_evidence))

    if _signal_bool(signals, "interrupt"):
        scores.append(("INTERRUPT_SERVICE", 0.85, ["interrupt=true"]))

    long_score = 0.0
    long_evidence: list[str] = []
    instruction_class = signals.get("instruction_class")
    if isinstance(instruction_class, str) and instruction_class.lower() in {
        "mul",
        "div",
        "rem",
    }:
        long_score += 0.45
        long_evidence.append(f"instruction_class={instruction_class.lower()}")
    unit_wait = _positive_signal(signals, "execution_unit_wait_cycles")
    if unit_wait:
        long_score += 0.45
        long_evidence.append(f"execution_unit_wait_cycles={unit_wait}")
    if _signal_bool(signals, "execution_unit_busy"):
        long_score += 0.10
        long_evidence.append("execution_unit_busy=true")
    if long_score:
        scores.append(("LONG_LATENCY_EXECUTION", long_score, long_evidence))

    if _signal_bool(signals, "clock_domain_wait"):
        scores.append(
            ("CLOCK_DOMAIN_CROSSING", 0.85, ["clock_domain_wait=true"])
        )

    candidates = [
        CauseCandidate(
            cause=cause,
            confidence=round(min(score, 0.99), 2),
            evidence=tuple(evidence),
        )
        for cause, score, evidence in scores
    ]
    candidates.sort(key=lambda item: (-item.confidence, item.cause))
    return candidates


def analyze_sample(sample: TimingSample) -> TimingFinding:
    if sample.delta_cycles == 0:
        return TimingFinding(
            step=sample.step,
            status="ON_TIME",
            cycle_start=sample.cycle_start,
            cycle_end=sample.cycle_end,
            expected_cycles=sample.expected_cycles,
            actual_cycles=sample.actual_cycles,
            delta_cycles=0,
            primary_cause=None,
            confidence=1.0,
            evidence=(),
            candidates=(),
        )

    if sample.delta_cycles < 0:
        return TimingFinding(
            step=sample.step,
            status="FASTER_THAN_EXPECTED",
            cycle_start=sample.cycle_start,
            cycle_end=sample.cycle_end,
            expected_cycles=sample.expected_cycles,
            actual_cycles=sample.actual_cycles,
            delta_cycles=sample.delta_cycles,
            primary_cause=None,
            confidence=0.0,
            evidence=(
                "The sample completed faster than the supplied baseline; "
                "this module does not infer a cause for speedups.",
            ),
            candidates=(),
        )

    candidates = tuple(_candidate_scores(sample))
    if candidates:
        primary = candidates[0]
        return TimingFinding(
            step=sample.step,
            status="DELAY_ANOMALY",
            cycle_start=sample.cycle_start,
            cycle_end=sample.cycle_end,
            expected_cycles=sample.expected_cycles,
            actual_cycles=sample.actual_cycles,
            delta_cycles=sample.delta_cycles,
            primary_cause=primary.cause,
            confidence=primary.confidence,
            evidence=primary.evidence,
            candidates=candidates,
        )

    return TimingFinding(
        step=sample.step,
        status="DELAY_ANOMALY",
        cycle_start=sample.cycle_start,
        cycle_end=sample.cycle_end,
        expected_cycles=sample.expected_cycles,
        actual_cycles=sample.actual_cycles,
        delta_cycles=sample.delta_cycles,
        primary_cause="UNKNOWN",
        confidence=0.0,
        evidence=("No supported causal signal was present.",),
        candidates=(),
    )


def analyze_timing(samples: list[TimingSample]) -> TimingAnalysis:
    findings = tuple(analyze_sample(sample) for sample in samples)
    anomalies = sum(finding.status != "ON_TIME" for finding in findings)
    return TimingAnalysis(
        status="ANOMALY_DETECTED" if anomalies else "ON_TIME",
        samples=len(samples),
        anomalies=anomalies,
        findings=findings,
    )
