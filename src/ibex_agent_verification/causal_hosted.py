from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from .causal_vcd import (
    CycleSnapshot,
    DEFAULT_SIGNAL_SPECS,
    _iter_vcd_lines,
    _load_jsonl_dicts,
    _parse_var,
    enrich_timing_rows,
    load_vcd_cycle_snapshots,
    resolve_signals,
    write_jsonl,
)
from .models import TraceValidationError


def _resolved_code_groups(path: str | Path) -> list[tuple[str, ...]]:
    scope: list[str] = []
    declarations = []
    for raw_line in _iter_vcd_lines(Path(path)):
        line = raw_line.strip()
        if line.startswith("$scope "):
            parts = line.split()
            if len(parts) >= 4:
                scope.append(parts[2])
        elif line.startswith("$upscope"):
            if scope:
                scope.pop()
        elif line.startswith("$var "):
            signal = _parse_var(line, scope)
            if signal is not None:
                declarations.append(signal)
        elif line.startswith("$enddefinitions"):
            break

    resolved, _ = resolve_signals(declarations, DEFAULT_SIGNAL_SPECS)
    by_code: dict[str, list[str]] = {}
    for alias, signal in resolved.items():
        by_code.setdefault(signal.code, []).append(alias)
    return [tuple(aliases) for aliases in by_code.values() if len(aliases) > 1]


def _restore_equivalent_signal_aliases(
    snapshots: list[CycleSnapshot], code_groups: list[tuple[str, ...]]
) -> list[CycleSnapshot]:
    data_pending = False
    instruction_pending = False
    restored: list[CycleSnapshot] = []

    for snapshot in snapshots:
        values = dict(snapshot.values)
        for aliases in code_groups:
            observed = [values.get(alias) for alias in aliases]
            value = next((item for item in observed if item is not None), None)
            if value is not None:
                for alias in aliases:
                    values[alias] = value

        data_req = values.get("data_req") == 1
        data_gnt = values.get("data_gnt") == 1
        data_rvalid = values.get("data_rvalid") == 1
        data_grant_wait = data_req and not data_gnt
        if data_req and data_gnt:
            data_pending = True
        if data_rvalid:
            data_pending = False
        data_wait = data_pending and not data_rvalid

        instr_req = values.get("instr_req") == 1
        instr_gnt = values.get("instr_gnt") == 1
        instr_rvalid = values.get("instr_rvalid") == 1
        instruction_grant_wait = instr_req and not instr_gnt
        if instr_req and instr_gnt:
            instruction_pending = True
        if instr_rvalid:
            instruction_pending = False
        instruction_wait = instruction_pending and not instr_rvalid

        restored.append(
            replace(
                snapshot,
                values=values,
                data_wait=data_wait,
                data_grant_wait=data_grant_wait,
                instruction_wait=instruction_wait,
                instruction_grant_wait=instruction_grant_wait,
            )
        )
    return restored


def _required_time(row: dict[str, Any], index: int) -> int:
    value = row.get("simulation_time")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TraceValidationError(
            f"metadata[{index}].simulation_time must be a non-negative integer"
        )
    return value


def infer_retirement_time_offset(
    metadata_rows: list[dict[str, Any]], snapshots: list[CycleSnapshot]
) -> tuple[int, int, float]:
    retirement_times = [
        _required_time(row, index) for index, row in enumerate(metadata_rows)
    ]
    valid_times = {
        snapshot.time
        for snapshot in snapshots
        if snapshot.values.get("rvfi_valid") == 1
    }
    if not valid_times:
        raise TraceValidationError("waveform contains no rvfi_valid retirement edges")

    scores = [
        (
            sum((time + offset) in valid_times for time in retirement_times),
            offset,
        )
        for offset in range(-4, 5)
    ]
    matched, offset = max(scores, key=lambda item: (item[0], -abs(item[1]), -item[1]))
    ratio = matched / len(retirement_times)
    if ratio < 0.95:
        raise TraceValidationError(
            "retirement/VCD rvfi_valid alignment is below 95% "
            f"({matched}/{len(retirement_times)}; best offset={offset})"
        )
    return offset, matched, ratio


def enrich_hosted_waveform(
    timing_rows: list[dict[str, Any]],
    metadata_rows: list[dict[str, Any]],
    snapshots: list[CycleSnapshot],
    *,
    waveform_source: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    offset, matched, ratio = infer_retirement_time_offset(metadata_rows, snapshots)
    adjusted_metadata = []
    for index, row in enumerate(metadata_rows):
        adjusted = dict(row)
        adjusted["simulation_time"] = _required_time(row, index) + offset
        adjusted_metadata.append(adjusted)

    enriched, report = enrich_timing_rows(
        timing_rows,
        adjusted_metadata,
        snapshots,
        waveform_source=waveform_source,
    )
    for index, row in enumerate(enriched):
        evidence = row["signals"]["waveform_evidence"]
        evidence["trace_time_start"] = _required_time(metadata_rows[index], index)
        evidence["trace_time_end"] = _required_time(metadata_rows[index + 1], index + 1)
        evidence["waveform_time_offset"] = offset
        if "time_start_exclusive" in evidence:
            evidence["waveform_time_start_exclusive"] = evidence.pop(
                "time_start_exclusive"
            )
        if "time_end_inclusive" in evidence:
            evidence["waveform_time_end_inclusive"] = evidence.pop(
                "time_end_inclusive"
            )

    report["matched_retirement_times"] = matched
    report["alignment_ratio"] = round(ratio, 6)
    report["retirement_time_offset"] = offset
    return enriched, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enrich Ibex timing with hosted FST/VCD causal evidence."
    )
    parser.add_argument("--vcd", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--timing", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--waveform-source", default="sim.fst")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        snapshots, signal_names, missing_optional = load_vcd_cycle_snapshots(args.vcd)
        code_groups = _resolved_code_groups(args.vcd)
        snapshots = _restore_equivalent_signal_aliases(snapshots, code_groups)
        timing_rows = _load_jsonl_dicts(args.timing, "timing")
        metadata_rows = _load_jsonl_dicts(args.metadata, "metadata")
        enriched, report = enrich_hosted_waveform(
            timing_rows,
            metadata_rows,
            snapshots,
            waveform_source=args.waveform_source,
        )
        report["resolved_signals"] = signal_names
        report["missing_optional_signals"] = missing_optional
        report["equivalent_signal_alias_groups"] = [list(group) for group in code_groups]
        write_jsonl(enriched, args.output)
        rendered = json.dumps(report, indent=2, sort_keys=True)
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except TraceValidationError as exc:
        print(
            json.dumps({"status": "INVALID_INPUT", "error": str(exc)}, indent=2),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
