"""
Books shelf.

The saved list is one Spotify read: GET /me/audiobooks?limit=50.
Opening a book is the next click: GET /audiobooks/{id} and
GET /audiobooks/{id}/chapters?limit=50.
Save and remove use PUT and DELETE /me/library?uris=spotify:audiobook:{id}.
A chapter link is passed to start_playback. That includes spotify:chapter;
when Spotify rejects it, the message is returned for the Books tab.
"""
import re

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_spotify_api


LIST_LIMIT = 50
CHAPTER_LIMIT = 50
_SPOTIFY_ID = re.compile(r"^[0-9A-Za-z]+$")
_PLAY_URI = re.compile(r"^spotify:(episode|track|chapter):[0-9A-Za-z]+$")


class AudiobookError(Exception):
    def __init__(self, message, code="audiobook_error", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


class AudiobookScopeError(AudiobookError):
    def __init__(self, message="Reconnect Spotify to use your audiobook library."):
        super().__init__(message, code="needs_scope", status=403)


def parse_audiobook(item):
    """One saved or catalog audiobook. Null and id-less rows are dropped."""
    if not isinstance(item, dict):
        return None
    nested = item.get("audiobook")
    if isinstance(nested, dict) and str(nested.get("id") or "").strip():
        item = nested
    audiobook_id = str(item.get("id") or "").strip()
    if not audiobook_id:
        return None
    uri = str(item.get("uri") or "").strip() or f"spotify:audiobook:{audiobook_id}"
    return {
        "id": audiobook_id,
        "name": str(item.get("name") or "").strip() or "Audiobook",
        "uri": uri,
        "authors": _names(item.get("authors")),
        "narrators": _names(item.get("narrators")),
        "publisher": str(item.get("publisher") or "").strip(),
        "description": str(item.get("description") or "").strip(),
        "image": _image(item.get("images")),
        "total_chapters": max(0, _int(item.get("total_chapters"), 0)),
        "explicit": bool(item.get("explicit")),
        "edition": str(item.get("edition") or "").strip(),
        "languages": _strings(item.get("languages")),
    }


def parse_saved_audiobooks(payload):
    """Paging object from GET /me/audiobooks. Does not follow next."""
    if not isinstance(payload, dict):
        payload = {}
    audiobooks = []
    for item in _items(payload):
        book = parse_audiobook(item)
        if book:
            audiobooks.append(book)
    return {
        "audiobooks": audiobooks,
        "total": _int(payload.get("total"), len(audiobooks)),
        "limit": _int(payload.get("limit"), LIST_LIMIT),
    }


def parse_chapter(item):
    """One chapter from GET /audiobooks/{id}/chapters. The uri is kept as-is."""
    if not isinstance(item, dict):
        return None
    chapter_id = str(item.get("id") or "").strip()
    uri = str(item.get("uri") or "").strip()
    if not chapter_id and not uri:
        return None
    number = item.get("chapter_number")
    chapter_number = None if number is None or number == "" else _optional_int(number)
    is_playable = item.get("is_playable")
    if not isinstance(is_playable, bool):
        is_playable = None
    return {
        "id": chapter_id,
        "name": str(item.get("name") or "").strip() or "Chapter",
        "uri": uri,
        "chapter_number": chapter_number,
        "duration_ms": max(0, _int(item.get("duration_ms"), 0)),
        "description": str(item.get("description") or "").strip(),
        "explicit": bool(item.get("explicit")),
        "image": _image(item.get("images")),
        "is_playable": is_playable,
        "type": str(item.get("type") or "").strip(),
    }


def parse_chapters(payload):
    """Paging object of chapters. Does not follow next."""
    if not isinstance(payload, dict):
        payload = {}
    chapters = []
    for item in _items(payload):
        chapter = parse_chapter(item)
        if chapter:
            chapters.append(chapter)
    return {
        "chapters": chapters,
        "total": _int(payload.get("total"), len(chapters)),
        "limit": _int(payload.get("limit"), CHAPTER_LIMIT),
    }


def load_saved_audiobooks(api):
    """One call: GET /me/audiobooks?limit=50."""
    response = api.get("me/audiobooks", params={"limit": LIST_LIMIT})
    _raise_for_spotify(response)
    return parse_saved_audiobooks(_json_object(response))


def load_audiobook(api, audiobook_id):
    """
    Two calls for one book: the audiobook, then its chapters.
    Embedded chapter stubs on the audiobook are not used.
    """
    audiobook_id = _require_id(audiobook_id)
    book_response = api.get(f"audiobooks/{audiobook_id}")
    _raise_for_spotify(book_response)
    book = parse_audiobook(_json_object(book_response))
    if not book:
        raise AudiobookError(
            "Spotify returned an unreadable audiobook.",
            code="bad_response",
            status=502,
        )
    chapters_response = api.get(
        f"audiobooks/{audiobook_id}/chapters",
        params={"limit": CHAPTER_LIMIT},
    )
    _raise_for_spotify(chapters_response)
    parsed = parse_chapters(_json_object(chapters_response))
    book["chapters"] = parsed["chapters"]
    book["chapters_total"] = parsed["total"]
    return book


def play_chapter(api, uri, device_id=None):
    """
    Play a chapter link with start_playback.

    spotify:episode and spotify:track are played as themselves.
    spotify:chapter is still passed through. Spotify's rejection is raised
    with the message Spotify returned.
    """
    playable = (uri or "").strip()
    if not _PLAY_URI.match(playable):
        raise AudiobookError(
            "This chapter needs a Spotify episode, track, or chapter link.",
            code="bad_uri",
            status=400,
        )
    if device_id is not None:
        device_id = str(device_id).strip() or None
    response = api.start_playback(device_id=device_id, uris=[playable])
    _raise_for_spotify(response, playback=True)
    return {"status": "playing", "uri": playable}


def save_audiobook(api, audiobook_id):
    """PUT /me/library?uris=spotify:audiobook:{id}."""
    audiobook_id = _require_id(audiobook_id)
    uri = f"spotify:audiobook:{audiobook_id}"
    response = api.put("me/library", params={"uris": uri})
    _raise_for_spotify(response)
    return {"status": "saved", "id": audiobook_id, "uri": uri}


def remove_audiobook(api, audiobook_id):
    """DELETE /me/library?uris=spotify:audiobook:{id}."""
    audiobook_id = _require_id(audiobook_id)
    uri = f"spotify:audiobook:{audiobook_id}"
    response = api.delete("me/library", params={"uris": uri})
    _raise_for_spotify(response)
    return {"status": "removed", "id": audiobook_id, "uri": uri}


def _require_id(value):
    audiobook_id = (value or "").strip()
    if not _SPOTIFY_ID.match(audiobook_id):
        raise AudiobookError("Audiobook id is required.", code="bad_id", status=400)
    return audiobook_id


def _raise_for_spotify(response, playback=False):
    status = getattr(response, "status_code", 200) or 200
    if status < 400:
        return
    message = _spotify_message(response)
    if status == 403:
        if not message or message.startswith("Spotify API error"):
            message = "Reconnect Spotify to use your audiobook library."
        raise AudiobookScopeError(message)
    code = "playback_error" if playback else "spotify_error"
    http_status = status if status < 500 else 502
    raise AudiobookError(message, code=code, status=http_status)


def _spotify_message(response):
    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error.strip():
            return error.strip()
    text = getattr(response, "text", "") or ""
    if text and not text.lstrip().startswith("<"):
        stripped = text.strip()
        if stripped:
            return stripped
    return f"Spotify API error: {getattr(response, 'status_code', '')}"


def _json_object(response):
    try:
        body = response.json()
    except Exception as exc:
        raise AudiobookError(
            "Spotify returned an unreadable response.",
            code="bad_response",
            status=502,
        ) from exc
    if not isinstance(body, dict):
        raise AudiobookError(
            "Spotify returned an unreadable response.",
            code="bad_response",
            status=502,
        )
    return body


def _items(payload):
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return items


def _names(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    names = []
    for entry in value:
        if isinstance(entry, str):
            text = entry.strip()
        elif isinstance(entry, dict):
            text = str(entry.get("name") or "").strip()
        else:
            continue
        if text:
            names.append(text)
    return names


def _strings(value):
    if not isinstance(value, list):
        return []
    texts = []
    for entry in value:
        text = str(entry or "").strip()
        if text:
            texts.append(text)
    return texts


def _image(value):
    if not isinstance(value, list) or not value:
        return None
    first = value[0]
    if isinstance(first, str):
        return first or None
    if isinstance(first, dict):
        return first.get("url") or None
    return None


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _api(request):
    api = get_spotify_api(request)
    if not api:
        return None, JsonResponse(
            {"error": "Not authenticated", "code": "token_expired"},
            status=401,
        )
    return api, None


def _device_id(request):
    """Same device choice as play track: web player id from the page, else the session."""
    device_id = None
    if request.session.get("use_web_player", True):
        device_id = (request.GET.get("device_id") or "").strip() or None
    if not device_id:
        device_id = request.session.get("selected_device_id") or None
    return device_id


def _error(exc):
    return JsonResponse({"error": str(exc), "code": exc.code}, status=exc.status)


def _call(request, action):
    api, error = _api(request)
    if error:
        return error
    try:
        return JsonResponse(action(api))
    except AudiobookError as exc:
        return _error(exc)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_http_methods(["GET"])
def saved_audiobooks(request):
    """Saved audiobooks. One Spotify read."""
    return _call(request, load_saved_audiobooks)


@require_http_methods(["GET"])
def audiobook_detail(request):
    """One audiobook and its chapters. Two Spotify reads."""
    audiobook_id = request.GET.get("id", "")
    return _call(request, lambda api: load_audiobook(api, audiobook_id))


@csrf_exempt
@require_http_methods(["POST"])
def play_audiobook_chapter(request):
    """start_playback for a chapter uri. Spotify's error is returned as-is."""
    uri = request.GET.get("uri", "")
    device_id = _device_id(request)
    return _call(request, lambda api: play_chapter(api, uri, device_id=device_id))


@csrf_exempt
@require_http_methods(["POST"])
def save_audiobook_view(request):
    """Save one audiobook with PUT /me/library."""
    audiobook_id = request.GET.get("id", "")
    return _call(request, lambda api: save_audiobook(api, audiobook_id))


@csrf_exempt
@require_http_methods(["POST"])
def remove_audiobook_view(request):
    """Remove one audiobook with DELETE /me/library."""
    audiobook_id = request.GET.get("id", "")
    return _call(request, lambda api: remove_audiobook(api, audiobook_id))
