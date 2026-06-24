from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from .models import TraceValidationError


@dataclass(frozen=True)
class SignalSpec:
    alias: str
    suffixes: tuple[str, ...]
    required: bool = True


DEFAULT_SIGNAL_SPECS: tuple[SignalSpec, ...] = (
    SignalSpec(
        "clock",
        ("TOP.ibex_simple_system.clk_sys", "ibex_simple_system.clk_sys"),
    ),
    SignalSpec("rvfi_valid", ("ibex_simple_system.u_top.rvfi_valid",)),
    SignalSpec("rvfi_intr", ("ibex_simple_system.u_top.rvfi_intr",)),
    SignalSpec("rvfi_trap", ("ibex_simple_system.u_top.rvfi_trap",)),
    SignalSpec(
        "instr_req",
        (
            "ibex_simple_system.u_top.instr_req_o",
            "ibex_simple_system.instr_req",
        ),
    ),
    SignalSpec(
        "instr_gnt",
        (
            "ibex_simple_system.u_top.instr_gnt_i",
            "ibex_simple_system.instr_gnt",
        ),
    ),
    SignalSpec(
        "instr_rvalid",
        (
            "ibex_simple_system.u_top.instr_rvalid_i",
            "ibex_simple_system.instr_rvalid",
        ),
    ),
    SignalSpec("data_req", ("ibex_simple_system.u_top.data_req_o",)),
    SignalSpec("data_gnt", ("ibex_simple_system.u_top.data_gnt_i",)),
    SignalSpec("data_rvalid", ("ibex_simple_system.u_top.data_rvalid_i",)),
    SignalSpec("timer_irq", ("ibex_simple_system.timer_irq",), required=False),
)


@dataclass(frozen=True)
class VcdSignal:
    code: str
    width: int
    full_name: str


@dataclass(frozen=True)
class CycleSnapshot:
    time: int
    values: dict[str, int | None]
    data_wait: bool
    data_grant_wait: bool
    instruction_wait: bool
    instruction_grant_wait: bool


def _clean_reference(parts: list[str]) -> str:
    reference = "".join(parts).strip()
    if reference.startswith("\\"):
        reference = reference[1:]
    return reference


def _parse_var(line: str, scope: list[str]) -> VcdSignal | None:
    parts = line.split()
    if len(parts) < 6 or parts[0] != "$var" or parts[-1] != "$end":
        return None
    try:
        width = int(parts[2], 10)
    except ValueError as exc:
        raise TraceValidationError(f"invalid VCD variable width in {line!r}") from exc
    code = parts[3]
    reference = _clean_reference(parts[4:-1])
    full_name = ".".join([*scope, reference])
    return VcdSignal(code=code, width=width, full_name=full_name)


def _matches_suffix(full_name: str, suffix: str) -> bool:
    return full_name == suffix or full_name.endswith("." + suffix)


def resolve_signals(
    signals: Iterable[VcdSignal],
    specs: tuple[SignalSpec, ...] = DEFAULT_SIGNAL_SPECS,
) -> tuple[dict[str, VcdSignal], list[str]]:
    materialized = list(signals)
    resolved: dict[str, VcdSignal] = {}
    missing_optional: list[str] = []

    for spec in specs:
        chosen: VcdSignal | None = None
        for suffix in spec.suffixes:
            candidates = [
                signal
                for signal in materialized
                if signal.width == 1 and _matches_suffix(signal.full_name, suffix)
            ]
            if len(candidates) > 1:
                names = ", ".join(sorted(item.full_name for item in candidates))
                raise TraceValidationError(
                    f"VCD signal {spec.alias!r} is ambiguous for suffix "
                    f"{suffix!r}: {names}"
                )
            if candidates:
                chosen = candidates[0]
                break
        if chosen is None:
            if spec.required:
                expected = ", ".join(spec.suffixes)
                raise TraceValidationError(
                    f"required VCD signal {spec.alias!r} was not found; "
                    f"expected one of: {expected}"
                )
            missing_optional.append(spec.alias)
        else:
            resolved[spec.alias] = chosen

    return resolved, missing_optional


def _iter_vcd_lines(path: Path) -> Iterator[str]:
    try:
        with path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
            yield from handle
    except (OSError, UnicodeError) as exc:
        raise TraceValidationError(f"cannot read VCD {path}: {exc}") from exc


def _parse_scalar_value(line: str) -> tuple[str, int | None] | None:
    if not line:
        return None
    marker = line[0]
    if marker in "01xXzZ":
        value: int | None
        if marker == "0":
            value = 0
        elif marker == "1":
            value = 1
        else:
            value = None
        return line[1:].strip(), value
    if marker in "bB":
        parts = line.split()
        if len(parts) != 2:
            return None
        bits = parts[0][1:]
        if len(bits) != 1:
            return None
        if bits == "0":
            value = 0
        elif bits == "1":
            value = 1
        else:
            value = None
        return parts[1], value
    return None


def load_vcd_cycle_snapshots(
    path: str | Path,
    specs: tuple[SignalSpec, ...] = DEFAULT_SIGNAL_SPECS,
) -> tuple[list[CycleSnapshot], dict[str, str], list[str]]:
    source = Path(path)
    lines = _iter_vcd_lines(source)
    scope: list[str] = []
    declarations: list[VcdSignal] = []

    for raw_line in lines:
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

    resolved, missing_optional = resolve_signals(declarations, specs)
    code_to_alias = {signal.code: alias for alias, signal in resolved.items()}
    signal_names = {alias: signal.full_name for alias, signal in resolved.items()}

    values: dict[str, int | None] = {alias: None for alias in resolved}
    snapshots: list[CycleSnapshot] = []
    current_time: int | None = None
    changes: dict[str, int | None] = {}
    data_pending = False
    instruction_pending = False

    def finalize_timestamp() -> None:
        nonlocal data_pending, instruction_pending
        if current_time is None:
            return
        previous_clock = values.get("clock")
        values.update(changes)
        current_clock = values.get("clock")
        if previous_clock == 1 or current_clock != 1:
            return

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

        snapshots.append(
            CycleSnapshot(
                time=current_time,
                values=dict(values),
                data_wait=data_wait,
                data_grant_wait=data_grant_wait,
                instruction_wait=instruction_wait,
                instruction_grant_wait=instruction_grant_wait,
            )
        )

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("$"):
            continue
        if line.startswith("#"):
            finalize_timestamp()
            try:
                current_time = int(line[1:], 10)
            except ValueError as exc:
                raise TraceValidationError(f"invalid VCD timestamp: {line!r}") from exc
            changes = {}
            continue
        parsed = _parse_scalar_value(line)
        if parsed is None:
            continue
        code, value = parsed
        alias = code_to_alias.get(code)
        if alias is not None:
            changes[alias] = value

    finalize_timestamp()
    if not snapshots:
        raise TraceValidationError(f"VCD {source} contained no rising clock snapshots")
    return snapshots, signal_names, missing_optional


def _load_jsonl_dicts(path: str | Path, kind: str) -> list[dict[str, Any]]:
    source = Path(path)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TraceValidationError(f"cannot read {kind} JSONL {source}: {exc}") from exc

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceValidationError(
                f"{source}:{line_number}: invalid JSON: {exc.msg}"
            ) from exc
        if not isinstance(row, dict):
            raise TraceValidationError(f"{source}:{line_number}: row must be an object")
        rows.append(row)
    return rows


def _required_int(row: dict[str, Any], key: str, context: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TraceValidationError(f"{context}.{key} must be a non-negative integer")
    return value


def enrich_timing_rows(
    timing_rows: list[dict[str, Any]],
    metadata_rows: list[dict[str, Any]],
    snapshots: list[CycleSnapshot],
    *,
    waveform_source: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(metadata_rows) < 2:
        raise TraceValidationError("metadata must contain at least two retired instructions")
    if len(timing_rows) != len(metadata_rows) - 1:
        raise TraceValidationError(
            "timing row count must equal metadata row count minus one "
            f"({len(timing_rows)} versus {len(metadata_rows) - 1})"
        )

    snapshot_times = {snapshot.time for snapshot in snapshots}
    retirement_times = [
        _required_int(row, "simulation_time", f"metadata[{index}]")
        for index, row in enumerate(metadata_rows)
    ]
    matched_retirements = sum(time in snapshot_times for time in retirement_times)
    alignment_ratio = matched_retirements / len(retirement_times)
    if alignment_ratio < 0.95:
        raise TraceValidationError(
            "retirement/VCD time alignment is below 95% "
            f"({matched_retirements}/{len(retirement_times)})"
        )

    enriched: list[dict[str, Any]] = []
    memory_wait_samples = 0
    instruction_wait_samples = 0
    interrupt_samples = 0
    trap_samples = 0
    snapshot_index = 0

    for index, timing in enumerate(timing_rows):
        context = f"timing[{index}]"
        step = _required_int(timing, "step", context)
        if step != index + 1:
            raise TraceValidationError(
                f"{context}.step must equal {index + 1} for metadata alignment"
            )
        start_meta = metadata_rows[index]
        end_meta = metadata_rows[index + 1]
        start_time = _required_int(
            start_meta, "simulation_time", f"metadata[{index}]"
        )
        end_time = _required_int(
            end_meta, "simulation_time", f"metadata[{index + 1}]"
        )
        start_cycle = _required_int(start_meta, "cycle", f"metadata[{index}]")
        end_cycle = _required_int(end_meta, "cycle", f"metadata[{index + 1}]")
        if timing.get("cycle_start") != start_cycle or timing.get("cycle_end") != end_cycle:
            raise TraceValidationError(
                f"{context} cycle bounds do not match metadata "
                f"({timing.get('cycle_start')}..{timing.get('cycle_end')} versus "
                f"{start_cycle}..{end_cycle})"
            )

        while (
            snapshot_index < len(snapshots)
            and snapshots[snapshot_index].time <= start_time
        ):
            snapshot_index += 1
        interval: list[CycleSnapshot] = []
        cursor = snapshot_index
        while cursor < len(snapshots) and snapshots[cursor].time <= end_time:
            interval.append(snapshots[cursor])
            cursor += 1
        snapshot_index = cursor

        signals = timing.get("signals", {})
        if not isinstance(signals, dict):
            raise TraceValidationError(f"{context}.signals must be an object")
        signals = dict(signals)

        memory_wait_cycles = sum(item.data_wait for item in interval)
        bus_wait_cycles = sum(item.data_grant_wait for item in interval)
        instruction_wait_cycles = sum(item.instruction_wait for item in interval)
        instruction_grant_wait_cycles = sum(
            item.instruction_grant_wait for item in interval
        )
        data_req = any(item.values.get("data_req") == 1 for item in interval)
        instr_req = any(item.values.get("instr_req") == 1 for item in interval)
        interrupt = any(
            item.values.get("rvfi_valid") == 1
            and item.values.get("rvfi_intr") == 1
            for item in interval
        )
        trap = any(
            item.values.get("rvfi_valid") == 1
            and item.values.get("rvfi_trap") == 1
            for item in interval
        )

        if data_req:
            signals["data_req"] = True
        if memory_wait_cycles:
            signals["memory_wait_cycles"] = memory_wait_cycles
            signals["data_ready"] = False
            memory_wait_samples += 1
        if bus_wait_cycles:
            signals["bus_wait_cycles"] = bus_wait_cycles
            signals["bus_grant"] = False
        if instr_req:
            signals["instr_req"] = True
        if instruction_wait_cycles:
            signals["instruction_wait_cycles"] = instruction_wait_cycles
            signals["instr_ready"] = False
            instruction_wait_samples += 1
        if instruction_grant_wait_cycles:
            signals["instruction_grant_wait_cycles"] = instruction_grant_wait_cycles
            signals["instr_grant"] = False
        if interrupt:
            signals["interrupt"] = True
            interrupt_samples += 1
        if trap:
            signals["rvfi_trap"] = True
            trap_samples += 1

        signals["waveform_evidence"] = {
            "source": waveform_source,
            "time_start_exclusive": start_time,
            "time_end_inclusive": end_time,
            "rising_edge_snapshots": len(interval),
        }

        row = dict(timing)
        row["signals"] = signals
        enriched.append(row)

    report = {
        "status": "ENRICHED",
        "timing_samples": len(enriched),
        "clock_snapshots": len(snapshots),
        "first_snapshot_time": snapshots[0].time,
        "last_snapshot_time": snapshots[-1].time,
        "retirement_times": len(retirement_times),
        "matched_retirement_times": matched_retirements,
        "alignment_ratio": round(alignment_ratio, 6),
        "samples_with_memory_wait": memory_wait_samples,
        "samples_with_instruction_wait": instruction_wait_samples,
        "samples_with_interrupt": interrupt_samples,
        "samples_with_trap": trap_samples,
    }
    return enriched, report


def write_jsonl(rows: Iterable[dict[str, Any]], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enrich Ibex timing JSONL with causal evidence from a VCD waveform."
    )
    parser.add_argument("--vcd", required=True, help="VCD converted from the hosted FST")
    parser.add_argument("--metadata", required=True, help="Ibex metadata JSONL")
    parser.add_argument("--timing", required=True, help="baseline timing JSONL")
    parser.add_argument("--output", required=True, help="enriched timing JSONL")
    parser.add_argument("--report", required=True, help="causal extraction report JSON")
    parser.add_argument(
        "--waveform-source",
        default="sim.fst",
        help="source waveform label stored in evidence references",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        snapshots, signal_names, missing_optional = load_vcd_cycle_snapshots(args.vcd)
        timing_rows = _load_jsonl_dicts(args.timing, "timing")
        metadata_rows = _load_jsonl_dicts(args.metadata, "metadata")
        enriched, report = enrich_timing_rows(
            timing_rows,
            metadata_rows,
            snapshots,
            waveform_source=args.waveform_source,
        )
        report["resolved_signals"] = signal_names
        report["missing_optional_signals"] = missing_optional
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
