from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import RegisterWrite, TraceEvent, TraceValidationError

_TRACE_RE = re.compile(
    r"^\s*(?P<time>\d+)\s+(?P<cycle>\d+)\s+"
    r"(?P<pc>[0-9a-fA-F]{8})\s+"
    r"(?P<instruction>(?:[0-9a-fA-F]{4}|[0-9a-fA-F]{8}))"
    r"(?:\s+(?P<body>.*?))?\s*$"
)
_ACCESS_START_RE = re.compile(
    r"(?:^|\s)(?:x(?:[0-9]|[12][0-9]|3[01])[=:]0x[0-9a-fA-F]+|"
    r"PA:0x[0-9a-fA-F]+|store:0x[0-9a-fA-F]+|"
    r"load:0x[0-9a-fA-F]+|expand_insn:)"
)
_REGISTER_ACCESS_RE = re.compile(
    r"(?<!\S)(?P<register>x(?:[0-9]|[12][0-9]|3[01]))"
    r"(?P<operator>[=:])0x(?P<value>[0-9a-fA-F]+)"
)
_MEMORY_ADDRESS_RE = re.compile(r"(?<!\S)PA:0x(?P<value>[0-9a-fA-F]+)")
_STORE_RE = re.compile(r"(?<!\S)store:0x(?P<value>[0-9a-fA-F]+)")
_LOAD_RE = re.compile(r"(?<!\S)load:0x(?P<value>[0-9a-fA-F]+)")
_HEADER_RE = re.compile(r"^\s*Time\s+Cycle\s+PC\s+Instr\b", re.IGNORECASE)


@dataclass(frozen=True)
class RegisterRead:
    name: str
    value: int

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True)
class IbexTraceRecord:
    simulation_time: int
    cycle: int
    pc: int
    instruction: int
    instruction_width_bits: int
    decoded: str
    mnemonic: str | None
    register_reads: tuple[RegisterRead, ...]
    register_write: RegisterWrite | None
    memory: dict[str, int] | None
    raw_line: str
    line_number: int

    def to_trace_event(self, step: int) -> TraceEvent:
        return TraceEvent(
            step=step,
            pc=self.pc,
            instruction=self.instruction,
            register_write=self.register_write,
            memory=self.memory,
            trap=None,
        )

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "simulation_time": self.simulation_time,
            "cycle": self.cycle,
            "pc": self.pc,
            "instruction": self.instruction,
            "instruction_width_bits": self.instruction_width_bits,
            "decoded": self.decoded,
            "mnemonic": self.mnemonic,
            "register_reads": [item.to_dict() for item in self.register_reads],
            "register_write": (
                None
                if self.register_write is None
                else {
                    "name": self.register_write.name,
                    "value": self.register_write.value,
                }
            ),
            "memory": self.memory,
            "source_line": self.line_number,
        }


@dataclass(frozen=True)
class IbexTraceParseResult:
    records: tuple[IbexTraceRecord, ...]
    source_sha256: str
    source_lines: int
    header_lines: int

    def summary(self) -> dict[str, Any]:
        first_cycle = self.records[0].cycle if self.records else None
        last_cycle = self.records[-1].cycle if self.records else None
        return {
            "status": "PARSED",
            "instructions": len(self.records),
            "source_lines": self.source_lines,
            "header_lines": self.header_lines,
            "source_sha256": self.source_sha256,
            "first_cycle": first_cycle,
            "last_cycle": last_cycle,
        }


def _parse_hex(match: re.Match[str] | None) -> int | None:
    if match is None:
        return None
    return int(match.group("value"), 16)


def parse_ibex_trace_line(line: str, line_number: int) -> IbexTraceRecord:
    match = _TRACE_RE.match(line)
    if match is None:
        raise TraceValidationError(
            f"line {line_number}: unsupported Ibex tracer line: {line.rstrip()!r}"
        )

    body = (match.group("body") or "").strip()
    access_start = _ACCESS_START_RE.search(body)
    if access_start is None:
        decoded = body
        access_text = ""
    else:
        decoded = body[: access_start.start()].strip()
        access_text = body[access_start.start() :].strip()

    register_reads: list[RegisterRead] = []
    register_writes: list[RegisterWrite] = []
    for register_match in _REGISTER_ACCESS_RE.finditer(access_text):
        name = register_match.group("register")
        value = int(register_match.group("value"), 16)
        if register_match.group("operator") == ":":
            register_reads.append(RegisterRead(name=name, value=value))
        elif name != "x0":
            register_writes.append(RegisterWrite(name=name, value=value))

    if len(register_writes) > 1:
        raise TraceValidationError(
            f"line {line_number}: multiple architectural register writes are unsupported"
        )

    address = _parse_hex(_MEMORY_ADDRESS_RE.search(access_text))
    store_value = _parse_hex(_STORE_RE.search(access_text))
    load_value = _parse_hex(_LOAD_RE.search(access_text))
    if address is None and (store_value is not None or load_value is not None):
        raise TraceValidationError(
            f"line {line_number}: memory value is present without a physical address"
        )

    memory = None
    if address is not None:
        memory = {"address": address}
        if load_value is not None:
            memory["read_value"] = load_value
        if store_value is not None:
            memory["write_value"] = store_value

    instruction_text = match.group("instruction")
    mnemonic = decoded.split(maxsplit=1)[0] if decoded else None
    return IbexTraceRecord(
        simulation_time=int(match.group("time"), 10),
        cycle=int(match.group("cycle"), 10),
        pc=int(match.group("pc"), 16),
        instruction=int(instruction_text, 16),
        instruction_width_bits=len(instruction_text) * 4,
        decoded=decoded,
        mnemonic=mnemonic,
        register_reads=tuple(register_reads),
        register_write=register_writes[0] if register_writes else None,
        memory=memory,
        raw_line=line.rstrip("\n"),
        line_number=line_number,
    )


def parse_ibex_trace_lines(
    lines: Iterable[str], *, source: str = "<memory>"
) -> IbexTraceParseResult:
    materialized = list(lines)
    records: list[IbexTraceRecord] = []
    header_lines = 0

    for line_number, line in enumerate(materialized, start=1):
        if not line.strip():
            continue
        if _HEADER_RE.match(line):
            header_lines += 1
            continue
        try:
            record = parse_ibex_trace_line(line, line_number)
        except TraceValidationError as exc:
            raise TraceValidationError(f"{source}:{exc}") from exc
        if records and record.cycle <= records[-1].cycle:
            raise TraceValidationError(
                f"{source}:line {line_number}: cycle must increase strictly "
                f"({record.cycle} after {records[-1].cycle})"
            )
        records.append(record)

    if not records:
        raise TraceValidationError(f"{source}: no Ibex instructions found")

    raw_bytes = "".join(materialized).encode("utf-8")
    return IbexTraceParseResult(
        records=tuple(records),
        source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        source_lines=len(materialized),
        header_lines=header_lines,
    )


def load_ibex_trace(path: str | Path) -> IbexTraceParseResult:
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8", newline="") as handle:
            return parse_ibex_trace_lines(handle, source=str(source))
    except OSError as exc:
        raise TraceValidationError(f"cannot read Ibex trace {source}: {exc}") from exc


def _write_jsonl(rows: Iterable[dict[str, Any]], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def write_architectural_jsonl(
    result: IbexTraceParseResult, path: str | Path
) -> None:
    _write_jsonl(
        (
            record.to_trace_event(step).normalized()
            for step, record in enumerate(result.records)
        ),
        path,
    )


def write_metadata_jsonl(result: IbexTraceParseResult, path: str | Path) -> None:
    _write_jsonl((record.to_metadata_dict() for record in result.records), path)


def records_to_timing_dicts(
    records: tuple[IbexTraceRecord, ...], *, expected_cycles: int = 1
) -> list[dict[str, Any]]:
    if isinstance(expected_cycles, bool) or expected_cycles < 0:
        raise TraceValidationError("expected_cycles must be a non-negative integer")

    samples: list[dict[str, Any]] = []
    for step, (previous, current) in enumerate(
        zip(records, records[1:]), start=1
    ):
        signals: dict[str, Any] = {
            "retired_mnemonic": current.mnemonic,
            "instruction_width_bits": current.instruction_width_bits,
        }
        if current.memory is not None:
            signals["memory_access"] = True
        if current.mnemonic is not None:
            base_mnemonic = current.mnemonic.removeprefix("c.")
            if base_mnemonic in {"mul", "div", "divu", "rem", "remu"}:
                if base_mnemonic == "mul":
                    signals["instruction_class"] = "mul"
                elif base_mnemonic.startswith("div"):
                    signals["instruction_class"] = "div"
                else:
                    signals["instruction_class"] = "rem"
        samples.append(
            {
                "step": step,
                "cycle_start": previous.cycle,
                "cycle_end": current.cycle,
                "expected_cycles": expected_cycles,
                "signals": signals,
            }
        )
    return samples


def write_timing_jsonl(
    result: IbexTraceParseResult,
    path: str | Path,
    *,
    expected_cycles: int = 1,
) -> None:
    _write_jsonl(
        records_to_timing_dicts(
            result.records, expected_cycles=expected_cycles
        ),
        path,
    )
