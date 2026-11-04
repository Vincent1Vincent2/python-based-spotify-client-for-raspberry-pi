"""Read the Spotify playback queue for the Queue tab.

GET /me/player/queue returns the current item and the upcoming queue.
Adding a song stays on the existing POST /queue/ endpoint, which appends.
The public Web API cannot remove one queued item, reorder the queue, or
insert at the front, so this module only reads.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from player.spotify_api import get_spotify_api


def format_duration(duration_ms):
    """mm:ss, or h:mm:ss when the item is longer than an hour."""
    try:
        total_seconds = int(duration_ms) // 1000
    except (TypeError, ValueError):
        return ""
    if total_seconds <= 0:
        return ""
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def present_item(item):
    """Slim a track or episode to the fields the queue panel shows."""
    if not isinstance(item, dict):
        return None
    kind = item.get("type") or "unknown"
    if kind == "episode":
        show = item.get("show") if isinstance(item.get("show"), dict) else {}
        subtitle = show.get("name") or ""
        image = _image_url(item.get("images")) or _image_url(show.get("images"))
    else:
        album = item.get("album") if isinstance(item.get("album"), dict) else {}
        artists = _names(item.get("artists"))
        album_name = album.get("name") or ""
        subtitle_parts = []
        if artists:
            subtitle_parts.append(", ".join(artists))
        if album_name:
            subtitle_parts.append(album_name)
        subtitle = " · ".join(subtitle_parts)
        image = _image_url(album.get("images")) or _image_url(item.get("images"))
    return {
        "id": item.get("id"),
        "uri": item.get("uri"),
        "name": item.get("name") or "Unknown",
        "type": kind,
        "subtitle": subtitle,
        "image": image,
        "duration_ms": _duration_ms(item.get("duration_ms")),
        "duration_label": format_duration(item.get("duration_ms")),
    }


def present_queue(payload):
    """Keep Spotify's order. Do not drop, reorder, or page the payload."""
    if not isinstance(payload, dict):
        payload = {}
    raw_queue = payload.get("queue")
    if not isinstance(raw_queue, list):
        raw_queue = []
    queue = []
    for item in raw_queue:
        presented = present_item(item)
        if presented:
            queue.append(presented)
    return {
        "currently_playing": present_item(payload.get("currently_playing")),
        "queue": queue,
    }


def _names(artists):
    if not isinstance(artists, list):
        return []
    names = []
    for artist in artists:
        if isinstance(artist, dict) and artist.get("name"):
            names.append(artist["name"])
    return names


def _image_url(images):
    if not isinstance(images, list):
        return None
    for image in images:
        if isinstance(image, dict) and image.get("url"):
            return image["url"]
    return None


def _duration_ms(value):
    try:
        duration = int(value)
    except (TypeError, ValueError):
        return 0
    return duration if duration > 0 else 0


def _spotify_error_message(response, status):
    message = f"Spotify API error: {status}"
    try:
        body = response.json()
    except Exception:
        return message
    if not isinstance(body, dict):
        return message
    error = body.get("error")
    if isinstance(error, dict) and error.get("message"):
        return error["message"]
    if isinstance(error, str) and error:
        return error
    return message


@require_http_methods(["GET"])
def playback_queue(request):
    """GET the current item and the queue. Does not add or skip."""
    api = get_spotify_api(request)
    if not api:
        return JsonResponse(
            {"error": "Not authenticated", "code": "token_expired"},
            status=401,
        )
    try:
        response = api.get_queue()
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    status = getattr(response, "status_code", 200)
    if status == 204:
        return JsonResponse(present_queue(None))

    if status != 200:
        http_status = status if 400 <= status < 600 else 502
        return JsonResponse(
            {"error": _spotify_error_message(response, status)},
            status=http_status,
        )

    try:
        payload = response.json()
    except Exception:
        return JsonResponse({"error": "Queue response was not readable"}, status=502)
    return JsonResponse(present_queue(payload))
