"""Trace ID generation for HoneyBadge audit logging."""

from datetime import datetime
from typing import Optional
import uuid


def generate_trace_id(prefix: Optional[str] = "TRC") -> str:
    """
    Generate a unique trace ID for audit logging.

    Format: {PREFIX}-{YYYYMMDD}-{HHMMSS}-{UUID4_LAST8}

    Example: TRC-20260404-143022-a1b2c3d4

    Args:
        prefix: Optional prefix for the trace ID (default: "TRC")

    Returns:
        A unique trace ID string
    """
    now = datetime.now()
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    uuid_part = uuid.uuid4().hex[-8:]

    return f"{prefix}-{date_part}-{time_part}-{uuid_part}"


def parse_trace_id(trace_id: str) -> dict:
    """
    Parse a trace ID into its components.

    Args:
        trace_id: A trace ID string

    Returns:
        A dict with prefix, date, time, and uuid components

    Raises:
        ValueError: If the trace ID format is invalid
    """
    parts = trace_id.split("-")
    if len(parts) != 4:
        raise ValueError(f"Invalid trace ID format: {trace_id}")

    return {
        "prefix": parts[0],
        "date": parts[1],
        "time": parts[2],
        "uuid": parts[3],
    }


def is_valid_trace_id(trace_id: str) -> bool:
    """
    Check if a trace ID has valid format.

    Args:
        trace_id: A trace ID string

    Returns:
        True if valid, False otherwise
    """
    try:
        parts = trace_id.split("-")
        if len(parts) != 4:
            return False
        if len(parts[0]) == 0 or len(parts[0]) > 10:
            return False
        if len(parts[1]) != 8 or not parts[1].isdigit():
            return False
        if len(parts[2]) != 6 or not parts[2].isdigit():
            return False
        if len(parts[3]) != 8 or not parts[3].isalnum():
            return False
        return True
    except Exception:
        return False
