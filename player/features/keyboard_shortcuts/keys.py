"""Map keyboard events to player actions.

``player/static/player/js/shortcuts.js`` mirrors ``KEY_ACTIONS`` and
``action_for_key``. The browser script calls playback helpers that
already live on the page. This module does not talk to Spotify.
"""

TOGGLE_PLAYBACK = "toggle_playback"
NEXT_TRACK = "next_track"
PREVIOUS_TRACK = "previous_track"
FOCUS_SEARCH = "focus_search"
SHOW_HELP = "show_help"

# KeyboardEvent.key values. Shift+/ arrives as "?" on a US layout and is
# also accepted as "/" while shift is held (see action_for_key).
KEY_ACTIONS = {
    " ": TOGGLE_PLAYBACK,
    "k": TOGGLE_PLAYBACK,
    "K": TOGGLE_PLAYBACK,
    "ArrowRight": NEXT_TRACK,
    "ArrowLeft": PREVIOUS_TRACK,
    "/": FOCUS_SEARCH,
    "?": SHOW_HELP,
}

_TYPING_TAGS = frozenset({"input", "textarea"})


def action_for_key(key, shift=False, ctrl=False, alt=False, meta=False):
    """Return the action name for a key, or None when nothing is bound.

    ``key`` is ``KeyboardEvent.key``. The flags are ``shiftKey``,
    ``ctrlKey``, ``altKey``, and ``metaKey``. Ctrl, Alt, and Meta chords
    are left to the browser. Shift+/ opens help whether the event key is
    ``"/"`` or ``"?"``.
    """
    if not isinstance(key, str) or ctrl or alt or meta:
        return None
    if shift and key == "/":
        return SHOW_HELP
    return KEY_ACTIONS.get(key)


def is_typing_target(tag_name="", content_editable=False):
    """True when a key event should be left alone.

    ``tag_name`` is the event target's tag, in any case.
    ``content_editable`` is the target's ``isContentEditable`` flag.
    Typing targets do not prevent the browser default.
    """
    if content_editable is True:
        return True
    if not isinstance(tag_name, str):
        return False
    return tag_name.lower() in _TYPING_TAGS
