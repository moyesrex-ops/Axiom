from __future__ import annotations

import re


_DURATION_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ms|s|m|h)", re.IGNORECASE)
_CLOCK_RE = re.compile(r"^(?P<parts>\d{1,2}:\d{2}(?::\d{2})?)$")


def parse_duration_seconds(value: object) -> float | None:
    text = str(value or "").strip().lower()
    if not text:
        return None

    clock_match = _CLOCK_RE.match(text)
    if clock_match:
        parts = [int(part) for part in clock_match.group("parts").split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            return float((minutes * 60) + seconds)
        hours, minutes, seconds = parts
        return float((hours * 3600) + (minutes * 60) + seconds)

    total = 0.0
    matches = list(_DURATION_RE.finditer(text))
    if matches:
        for match in matches:
            amount = float(match.group("value"))
            unit = match.group("unit").lower()
            if unit == "ms":
                total += amount / 1000.0
            elif unit == "s":
                total += amount
            elif unit == "m":
                total += amount * 60.0
            elif unit == "h":
                total += amount * 3600.0
        return total

    try:
        return float(text)
    except ValueError:
        return None


def compute_rotation_deadline(
    time_left: object,
    *,
    now: float,
    lead_seconds: float,
    fallback_seconds: float = 2.0,
) -> float:
    seconds_left = parse_duration_seconds(time_left)
    if seconds_left is None:
        return now + max(float(fallback_seconds), 0.0)
    return now + max(float(seconds_left) - max(float(lead_seconds), 0.0), 0.0)


def should_rotate_now(
    *,
    now: float,
    deadline: float,
    is_speaking: bool,
    playback_backlog: int,
    tool_calls_in_flight: int,
    has_partial_turn: bool,
    last_user_audio_at: float,
    idle_window_seconds: float,
) -> bool:
    if deadline > 0.0 and now >= deadline:
        return True
    if is_speaking or playback_backlog > 0 or tool_calls_in_flight > 0 or has_partial_turn:
        return False
    if last_user_audio_at <= 0.0:
        return True
    return (now - last_user_audio_at) >= max(float(idle_window_seconds), 0.0)
