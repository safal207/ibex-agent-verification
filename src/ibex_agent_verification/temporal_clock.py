"""UTC timestamp helpers used by temporal verification."""

from datetime import datetime, timezone


def parse_utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be a UTC timestamp ending in Z")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid UTC timestamp") from exc
    if result.tzinfo != timezone.utc:
        raise ValueError(f"{label} must be UTC")
    return result


def format_utc(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    precision = "microseconds" if value.microsecond else "seconds"
    return value.isoformat(timespec=precision).replace("+00:00", "Z")
