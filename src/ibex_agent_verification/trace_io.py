from __future__ import annotations

import json
from pathlib import Path

from .models import TraceEvent, TraceValidationError


def load_jsonl(path: str | Path) -> list[TraceEvent]:
    source = Path(path)
    events: list[TraceEvent] = []
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TraceValidationError(f"cannot read trace {source}: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            event = TraceEvent.from_raw(raw)
        except (json.JSONDecodeError, TraceValidationError) as exc:
            raise TraceValidationError(f"{source}:{line_number}: {exc}") from exc
        if events and event.step <= events[-1].step:
            raise TraceValidationError(
                f"{source}:{line_number}: step must increase strictly "
                f"({event.step} after {events[-1].step})"
            )
        events.append(event)
    return events
