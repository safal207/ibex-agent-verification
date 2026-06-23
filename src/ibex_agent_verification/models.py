from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


class TraceValidationError(ValueError):
    """Raised when a trace event does not satisfy the public contract."""


def parse_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise TraceValidationError(f"{field} must be an integer or hex string, not bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().lower().replace("_", "")
        try:
            return int(text, 0)
        except ValueError as exc:
            raise TraceValidationError(f"{field} is not a valid integer: {value!r}") from exc
    raise TraceValidationError(f"{field} must be an integer or string")


@dataclass(frozen=True)
class RegisterWrite:
    name: str
    value: int

    @classmethod
    def from_raw(cls, raw: Any) -> "RegisterWrite | None":
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise TraceValidationError("register_write must be an object or null")
        name = raw.get("name")
        if not isinstance(name, str) or not name.startswith("x") or not name[1:].isdigit():
            raise TraceValidationError("register_write.name must look like x0..x31")
        index = int(name[1:])
        if not 0 <= index <= 31:
            raise TraceValidationError("register_write.name must be in x0..x31")
        return cls(name=name, value=parse_int(raw.get("value"), "register_write.value"))


@dataclass(frozen=True)
class TraceEvent:
    step: int
    pc: int
    instruction: int
    register_write: RegisterWrite | None
    memory: Any
    trap: Any

    @classmethod
    def from_raw(cls, raw: Any) -> "TraceEvent":
        if not isinstance(raw, dict):
            raise TraceValidationError("trace line must be a JSON object")
        missing = {"step", "pc", "instruction"} - raw.keys()
        if missing:
            raise TraceValidationError(f"missing required fields: {', '.join(sorted(missing))}")
        step = parse_int(raw["step"], "step")
        if step < 0:
            raise TraceValidationError("step must be non-negative")
        return cls(
            step=step,
            pc=parse_int(raw["pc"], "pc"),
            instruction=parse_int(raw["instruction"], "instruction"),
            register_write=RegisterWrite.from_raw(raw.get("register_write")),
            memory=raw.get("memory"),
            trap=raw.get("trap"),
        )

    def normalized(self) -> dict[str, Any]:
        data = asdict(self)
        return data
