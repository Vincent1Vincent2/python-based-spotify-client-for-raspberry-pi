"""Status text for device-transfer responses."""


def status_text(response):
    """Choose the status string from a transfer response dict.

    An error is the status even when a success message is also present.
    A body with neither, including an empty object, has nothing to show.
    """
    if not isinstance(response, dict):
        return ""
    error = response.get("error")
    if isinstance(error, str) and error:
        return error
    message = response.get("message")
    if isinstance(message, str) and message:
        return message
    return ""
