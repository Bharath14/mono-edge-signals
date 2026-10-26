"""Cleaning rules: raw message in, typed row plus any rejects out.

Rules
-----
Whole message refused (goes to rejected_readings only):
  * not a JSON object
  * missing or empty mill_id
  * timestamp missing or unparseable
  * every signal is NULL or invalid (nothing usable left)

Single field handled (the row is still kept, the field becomes NULL):
  * value is None                -> NULL, not logged (a missing reading is normal)
  * value is numeric text        -> converted to a number, not logged
  * value is non-numeric text    -> NULL, logged as non_numeric
  * value is NaN or infinite     -> NULL, logged as non_finite
  * value outside VALID_RANGES   -> NULL, logged as out_of_range (covers the
                                    -9999 PLC error value)
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config as c


@dataclass
class CleanResult:
    row: tuple | None = None  # (mill_id, ts, speed, current, torque, force, vib, temp)
    rejects: list = field(default_factory=list)


def parse_timestamp(value):
    """Parse an ISO 8601 string to an aware UTC datetime, or return None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        ts = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _identity(msg):
    """Best effort mill_id and timestamp text, for logging rejects."""
    if isinstance(msg, dict):
        mill = msg.get("mill_id")
        ts = msg.get("timestamp")
        return (
            mill if isinstance(mill, str) else "",
            ts if isinstance(ts, str) else ("" if ts is None else str(ts)),
        )
    return "", ""


def _reject(msg, reason):
    mill, ts_text = _identity(msg)
    return {"mill_id": mill, "ts_text": ts_text, "payload": msg, "reason": reason}


def clean_message(msg):
    if not isinstance(msg, dict):
        return CleanResult(rejects=[_reject(msg, "not_an_object")])

    mill_id = msg.get("mill_id")
    if not isinstance(mill_id, str) or not mill_id.strip():
        return CleanResult(rejects=[_reject(msg, "missing_mill_id")])

    ts = parse_timestamp(msg.get("timestamp"))
    if ts is None:
        return CleanResult(rejects=[_reject(msg, "bad_timestamp")])

    values = []
    rejects = []
    for sig in c.SIGNALS:
        raw = msg.get(sig)
        value = None
        if raw is None:
            pass
        elif isinstance(raw, bool):
            rejects.append(_reject(msg, f"non_numeric:{sig}"))
        elif isinstance(raw, (int, float)):
            value = float(raw)
        elif isinstance(raw, str):
            try:
                value = float(raw.strip())
            except ValueError:
                rejects.append(_reject(msg, f"non_numeric:{sig}"))
        else:
            rejects.append(_reject(msg, f"non_numeric:{sig}"))

        if value is not None:
            if not math.isfinite(value):
                rejects.append(_reject(msg, f"non_finite:{sig}"))
                value = None
            else:
                low, high = c.VALID_RANGES[sig]
                if not (low <= value <= high):
                    rejects.append(_reject(msg, f"out_of_range:{sig}"))
                    value = None
        values.append(value)

    if all(v is None for v in values):
        rejects.append(_reject(msg, "no_valid_signals"))
        return CleanResult(rejects=rejects)

    return CleanResult(row=(mill_id.strip(), ts, *values), rejects=rejects)
