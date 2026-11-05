"""
Listening stats from one Spotify recently-played payload.

The summary is a pure function of that JSON. It does not page, search,
or keep the play-by-play list.
"""


TOP_LIMIT = 5


class ListeningStatsError(Exception):
    def __init__(self, message, code="stats_error"):
        super().__init__(message)
        self.code = code


class ListeningStatsScopeError(ListeningStatsError):
    def __init__(self):
        super().__init__(
            "Reconnect Spotify so Stats can read your recent plays.",
            code="needs_scope",
        )


def summarize_recently_played(payload):
    """
    Reduce a GET /me/player/recently-played body to listening stats.

    total_minutes is the sum of track durations, rounded to the nearest
    minute (a half-minute rounds up). Artists are distinct by Spotify id,
    or by name when an id is missing. Top lists are the five highest play
    counts. percent is the bar width: 100 for the most-played row.
    """
    items = _items(payload)
    total_ms = 0
    artists = {}
    tracks = {}

    for item in items:
        track = item.get("track") if isinstance(item, dict) else None
        if not isinstance(track, dict):
            continue
        total_ms += _duration_ms(track)
        credited = _credited_artists(track)
        for key, name in credited:
            row = artists.get(key)
            if row is None:
                artists[key] = {"name": name, "plays": 1}
            else:
                row["plays"] += 1
        track_key, track_name, artist_label = _track_identity(track, credited)
        row = tracks.get(track_key)
        if row is None:
            tracks[track_key] = {
                "name": track_name,
                "artists": artist_label,
                "plays": 1,
            }
        else:
            row["plays"] += 1

    return {
        "total_minutes": _round_minutes(total_ms),
        "distinct_artists": len(artists),
        "top_artists": _top(list(artists.values())),
        "top_tracks": _top(list(tracks.values())),
    }


def load_listening_stats(api):
    """
    One call: GET /me/player/recently-played?limit=50.

    A 403 means the token is missing user-read-recently-played.
    """
    response = api.get_recently_played()
    status = getattr(response, "status_code", 200)
    if status == 403:
        raise ListeningStatsScopeError()
    if status >= 400:
        raise ListeningStatsError(f"Recent plays failed ({status}).")
    return summarize_recently_played(_json_object(response))


def _items(payload):
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return items


def _json_object(response):
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _duration_ms(track):
    try:
        value = int(track.get("duration_ms"))
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _round_minutes(total_ms):
    """Nearest minute. 30 seconds rounds up, so two 30s plays are 1 minute."""
    if total_ms <= 0:
        return 0
    return (total_ms + 30_000) // 60_000


def _credited_artists(track):
    seen = set()
    credited = []
    artists = track.get("artists") or []
    if not isinstance(artists, list):
        return credited
    for artist in artists:
        if not isinstance(artist, dict):
            continue
        name = str(artist.get("name") or "").strip()
        artist_id = str(artist.get("id") or "").strip()
        if artist_id:
            key = "id:" + artist_id
        elif name:
            key = "name:" + name.casefold()
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        credited.append((key, name or "Unknown artist"))
    return credited


def _track_identity(track, credited):
    track_id = str(track.get("id") or "").strip()
    uri = str(track.get("uri") or "").strip()
    name = str(track.get("name") or "").strip() or "Unknown track"
    if track_id:
        key = "id:" + track_id
    elif uri:
        key = "uri:" + uri
    else:
        key = "name:" + name.casefold()
    label = ", ".join(artist_name for _key, artist_name in credited)
    return key, name, label


def _top(rows):
    ordered = sorted(
        rows,
        key=lambda row: (-row["plays"], str(row.get("name") or "").casefold()),
    )
    chosen = ordered[:TOP_LIMIT]
    if not chosen:
        return []
    peak = chosen[0]["plays"] or 1
    ranked = []
    for row in chosen:
        public = {
            "name": row["name"],
            "plays": row["plays"],
            "percent": int(round(row["plays"] * 100 / peak)),
        }
        if "artists" in row:
            public["artists"] = row["artists"]
        ranked.append(public)
    return ranked
