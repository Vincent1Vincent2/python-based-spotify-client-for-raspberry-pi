"""Clamp a 15-second seek so it stays inside the current track.

The player buttons apply this same clamp, then POST the result to /seek/.
They do not read Spotify again to find the playhead.
"""

NUDGE_MS = 15000


def nudge_position(current_ms, duration_ms, delta_ms):
    """Return current_ms + delta_ms, clamped to 0 and to duration_ms."""
    duration = duration_ms if duration_ms > 0 else 0
    target = current_ms + delta_ms
    if target < 0:
        return 0
    if target > duration:
        return duration
    return target
