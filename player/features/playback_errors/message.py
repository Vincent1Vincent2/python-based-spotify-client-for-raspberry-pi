"""User-facing text for a playback command response."""

NEEDS_SCOPE_MESSAGE = "Reconnect Spotify to control playback."


def playback_error_message(body):
    """Return the string to show for a playback response body.

    A string ``error`` is shown as written, without surrounding
    whitespace. A Spotify error object contributes its ``message``.
    ``needs_scope`` uses that text when it is present, and otherwise
    asks the listener to reconnect. A body with no error returns "".
    """
    if not isinstance(body, dict):
        return ""
    text = _error_text(body.get("error"))
    if body.get("code") == "needs_scope":
        return text or NEEDS_SCOPE_MESSAGE
    return text


def _error_text(error):
    if isinstance(error, str):
        return error.strip()
    if isinstance(error, dict):
        return _error_text(error.get("message"))
    return ""
