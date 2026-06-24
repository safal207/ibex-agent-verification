from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .ibex_trace import IbexTraceParseResult, IbexTraceRecord, load_ibex_trace
from .models import TraceValidationError

_CONDITIONAL_BRANCHES = frozenset({"beq", "bne", "blt", "bge", "bltu", "bgeu"})
_DIRECT_JUMPS = frozenset({"j", "jal"})
_INDIRECT_JUMPS = frozenset({"jr", "jalr"})
_RETURNS = frozenset({"ret", "mret", "dret"})


def _normalized_mnemonic(record: IbexTraceRecord) -> str | None:
    if record.mnemonic is None:
        return None
    return record.mnemonic.lower().removeprefix("c.")


def _redirect_kind(mnemonic: str | None) -> str | None:
    if mnemonic in _CONDITIONAL_BRANCHES:
        return "conditional_branch"
    if mnemonic in _DIRECT_JUMPS:
        return "direct_jump"
    if mnemonic in _INDIRECT_JUMPS:
        return "indirect_jump"
    if mnemonic in _RETURNS:
        return "return"
    return None


@dataclass(frozen=True)
class ControlFlowRedirect:
    transition_step: int
    cycle_start: int
    cycle_end: int
    expected_cycles: int
    actual_cycles: int
    delay_cycles: int
    from_pc: int
    sequential_pc: int
    target_pc: int
    instruction_width_bits: int
    mnemonic: str
    redirect_kind: str
    source_line: int
    target_source_line: int

    @property
    def is_delayed(self) -> bool:
        return self.delay_cycles > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_step": self.transition_step,
            "status": "DELAY_ANOMALY" if self.is_delayed else "ON_TIME_REDIRECT",
            "primary_cause": "BRANCH_REDIRECT",
            "cycle_start": self.cycle_start,
            "cycle_end": self.cycle_end,
            "expected_cycles": self.expected_cycles,
            "actual_cycles": self.actual_cycles,
            "delay_cycles": self.delay_cycles,
            "from_pc": self.from_pc,
            "sequential_pc": self.sequential_pc,
            "target_pc": self.target_pc,
            "instruction_width_bits": self.instruction_width_bits,
            "mnemonic": self.mnemonic,
            "redirect_kind": self.redirect_kind,
            "source_line": self.source_line,
            "target_source_line": self.target_source_line,
            "pipeline_flush_confirmed": False,
            "evidence": [
                f"mnemonic={self.mnemonic}",
                f"redirect_kind={self.redirect_kind}",
                f"from_pc=0x{self.from_pc:08x}",
                f"sequential_pc=0x{self.sequential_pc:08x}",
                f"target_pc=0x{self.target_pc:08x}",
                f"cycle_gap={self.actual_cycles}",
            ],
        }


@dataclass(frozen=True)
class ControlFlowAnalysis:
    source_sha256: str
    instructions: int
    transitions: int
    redirects: tuple[ControlFlowRedirect, ...]

    def summary(self) -> dict[str, Any]:
        delayed = sum(item.is_delayed for item in self.redirects)
        by_kind: dict[str, int] = {}
        for item in self.redirects:
            by_kind[item.redirect_kind] = by_kind.get(item.redirect_kind, 0) + 1
        return {
            "status": "REDIRECTS_FOUND" if self.redirects else "NO_REDIRECTS_FOUND",
            "source_sha256": self.source_sha256,
            "instructions": self.instructions,
            "transitions": self.transitions,
            "redirects": len(self.redirects),
            "delayed_redirects": delayed,
            "redirects_by_kind": dict(sorted(by_kind.items())),
            "pipeline_flush_claims": 0,
            "causal_boundary": (
                "A non-sequential PC after a recognized control-flow instruction "
                "proves a redirect. It does not by itself prove a branch mispredict "
                "or pipeline flush."
            ),
        }


def extract_control_flow_redirects(
    records: Sequence[IbexTraceRecord], *, expected_cycles: int = 1
) -> tuple[ControlFlowRedirect, ...]:
    if (
        isinstance(expected_cycles, bool)
        or not isinstance(expected_cycles, int)
        or expected_cycles < 0
    ):
        raise TraceValidationError("expected_cycles must be a non-negative integer")

    redirects: list[ControlFlowRedirect] = []
    for transition_step, (previous, current) in enumerate(
        zip(records, records[1:]), start=1
    ):
        width_bytes = previous.instruction_width_bits // 8
        sequential_pc = (previous.pc + width_bytes) & 0xFFFFFFFF
        if current.pc == sequential_pc:
            continue

        mnemonic = _normalized_mnemonic(previous)
        kind = _redirect_kind(mnemonic)
        if mnemonic is None or kind is None:
            continue

        actual_cycles = current.cycle - previous.cycle
        redirects.append(
            ControlFlowRedirect(
                transition_step=transition_step,
                cycle_start=previous.cycle,
                cycle_end=current.cycle,
                expected_cycles=expected_cycles,
                actual_cycles=actual_cycles,
                delay_cycles=max(0, actual_cycles - expected_cycles),
                from_pc=previous.pc,
                sequential_pc=sequential_pc,
                target_pc=current.pc,
                instruction_width_bits=previous.instruction_width_bits,
                mnemonic=mnemonic,
                redirect_kind=kind,
                source_line=previous.line_number,
                target_source_line=current.line_number,
            )
        )
    return tuple(redirects)


def analyze_control_flow(
    parsed: IbexTraceParseResult, *, expected_cycles: int = 1
) -> ControlFlowAnalysis:
    return ControlFlowAnalysis(
        source_sha256=parsed.source_sha256,
        instructions=len(parsed.records),
        transitions=max(0, len(parsed.records) - 1),
        redirects=extract_control_flow_redirects(
            parsed.records, expected_cycles=expected_cycles
        ),
    )


def write_redirect_jsonl(
    redirects: Iterable[ControlFlowRedirect], path: str | Path
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for redirect in redirects:
            handle.write(json.dumps(redirect.to_dict(), sort_keys=True))
            handle.write("\n")


def write_report(analysis: ControlFlowAnalysis, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(analysis.summary(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract evidence-backed control-flow redirects from an official "
            "Ibex instruction trace."
        )
    )
    parser.add_argument("--input", required=True, help="Ibex trace_core_*.log path")
    parser.add_argument("--output", required=True, help="Redirect JSONL output path")
    parser.add_argument("--report", required=True, help="Summary JSON output path")
    parser.add_argument(
        "--expected-cycles",
        type=int,
        default=1,
        help="Baseline cycles between retired instructions (default: 1)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    parsed = load_ibex_trace(args.input)
    analysis = analyze_control_flow(parsed, expected_cycles=args.expected_cycles)
    write_redirect_jsonl(analysis.redirects, args.output)
    write_report(analysis, args.report)
    print(json.dumps(analysis.summary(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
