"""
Feel matching that stays inside two Spotify reads.

Audio features and the recommendations endpoint are gone for Development
Mode apps, so a feel is a lexicon over titles, artist names, album names,
and playlist titles the user already has. Scoring and chaining happen
locally. The network helpers in this module call the readers they are
given and do not decide how many extra requests to make.
"""
import re


class FeelError(Exception):
    def __init__(self, message, code="feel_error"):
        super().__init__(message)
        self.code = code


class FeelScopeError(FeelError):
    def __init__(self):
        super().__init__(
            "Reconnect Spotify so Feel can save private playlists.",
            code="needs_scope",
        )


BATCH_SIZE = 30
PAGE_LIMIT = 50
SEARCH_LIMIT = 10
QUERY_CHAR_LIMIT = 100

# Canonical order keeps "Sad Mad" stable no matter which button was pressed first.
EMOTION_ORDER = ("sad", "happy", "mad")

EMOTIONS = {
    "sad": {
        "label": "Sad",
        "terms": (
            "sad", "blue", "cry", "tears", "lonely", "alone", "heartbreak",
            "grief", "sorrow", "empty", "hurt", "goodbye", "miss", "rain",
        ),
        "query_terms": ("sad", "lonely", "tears", "heartbreak"),
    },
    "happy": {
        "label": "Happy",
        "terms": (
            "happy", "joy", "smile", "sunshine", "dance", "bright", "party",
            "celebrate", "laugh", "golden", "alive", "wonderful", "sunny",
        ),
        "query_terms": ("happy", "joy", "sunshine", "dance"),
    },
    "mad": {
        "label": "Mad",
        "terms": (
            "mad", "angry", "rage", "hate", "furious", "fight", "scream",
            "revenge", "burn", "war",
        ),
        "query_terms": ("angry", "rage", "hate", "furious"),
    },
}

_WORD = re.compile(r"[a-z0-9']+")
_GENERATED_PLAYLIST = re.compile(
    r"^(?:Sad|Happy|Mad)(?: (?:Sad|Happy|Mad))* (?:Radio|\d{2})$"
)
_STOP = {
    "the", "and", "for", "with", "you", "your", "that", "this", "from",
    "are", "was", "were", "have", "has", "not", "but", "its", "it's",
    "a", "an", "of", "to", "in", "on", "my", "me", "we", "our", "it",
    "just", "like", "what", "when", "all", "out",
}


def normalize_emotions(values):
    """Keep known emotions in canonical order. Drop anything else."""
    found = set()
    for value in values or []:
        key = str(value).strip().lower()
        if key in EMOTIONS:
            found.add(key)
    return [key for key in EMOTION_ORDER if key in found]


def feel_name(emotions):
    """Static label for a selection. The number that follows it is separate."""
    emotions = normalize_emotions(emotions)
    if not emotions:
        raise FeelError("Choose sad, happy, mad, or a combination.")
    return " ".join(EMOTIONS[key]["label"] for key in emotions)


def playlist_title(feel, number):
    return f"{feel} {int(number):02d}"


def radio_title(feel):
    return f"{feel} Radio"


def is_generated_playlist_name(name):
    """Playlists this feature writes must not become the next source pile."""
    return bool(_GENERATED_PLAYLIST.match(name or ""))


def _term_in(text, term):
    if " " in term:
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def term_hit_count(text, emotion):
    lowered = (text or "").lower()
    return sum(1 for term in EMOTIONS[emotion]["terms"] if _term_in(lowered, term))


def haystack(track):
    artists = " ".join(track.get("artists") or [])
    return f"{track.get('name') or ''} {artists} {track.get('album') or ''}"


def score_track(track, emotions):
    """
    Lexical feel score. A song that hits two selected emotions gets a
    bonus so Sad + Mad ranks those songs ahead of songs that are only one.
    """
    emotions = normalize_emotions(emotions)
    text = haystack(track)
    per_emotion = [term_hit_count(text, emotion) for emotion in emotions]
    total = sum(per_emotion)
    if sum(1 for value in per_emotion if value) >= 2:
        total += 3
    return total


def content_words(text):
    words = []
    for word in _WORD.findall((text or "").lower()):
        if len(word) < 3 or word in _STOP or word in words:
            continue
        words.append(word)
    return words


def _tokens(text):
    return set(content_words(text))


def similarity(left, right):
    """Shared title words, plus a bonus when the primary artists match."""
    if not left or not right:
        return 0
    overlap = len(_tokens(left.get("name")) & _tokens(right.get("name")))
    same_artist = 2 if set(left.get("artists") or []) & set(right.get("artists") or []) else 0
    return overlap * 2 + same_artist


def build_query(emotions, seed=None):
    """
    One search string, at most 100 characters (the Development Mode cap).
    Seed title words and the artist come first so the query is about the
    song that is ending, then the feel words fill whatever room is left.
    """
    emotions = normalize_emotions(emotions)
    parts = []
    if seed:
        parts.extend(content_words(seed.get("name"))[:3])
        artists = seed.get("artists") or []
        if artists and artists[0] not in parts:
            parts.append(artists[0])
    for emotion in emotions:
        for term in EMOTIONS[emotion]["query_terms"]:
            if term not in parts:
                parts.append(term)
    query = ""
    for part in parts:
        piece = f'"{part}"' if " " in part else part
        candidate = piece if not query else f"{query} OR {piece}"
        if len(candidate) > QUERY_CHAR_LIMIT:
            continue
        query = candidate
    if not query and emotions:
        query = emotions[0]
    return query[:QUERY_CHAR_LIMIT]


def coerce_track(raw):
    """A catalog track with a spotify:track URI. Local files are dropped."""
    if not isinstance(raw, dict):
        return None
    if raw.get("is_local"):
        return None
    uri = raw.get("uri") or ""
    if not uri.startswith("spotify:track:"):
        return None
    artists = []
    for artist in raw.get("artists") or []:
        if isinstance(artist, dict) and artist.get("name"):
            artists.append(artist["name"])
        elif isinstance(artist, str) and artist:
            artists.append(artist)
    album = raw.get("album")
    if isinstance(album, dict):
        album_name = album.get("name") or ""
    else:
        album_name = album or ""
    return {
        "id": raw.get("id") or uri.split(":")[-1],
        "uri": uri,
        "name": raw.get("name") or "",
        "artists": artists,
        "album": album_name,
    }


def tracks_from_paging(payload):
    """Saved-track pages and playlist item pages both wrap the track."""
    tracks = []
    seen = set()
    for item in (payload or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        nested = item.get("track")
        raw = nested if isinstance(nested, dict) else item
        track = coerce_track(raw)
        if not track or track["uri"] in seen:
            continue
        seen.add(track["uri"])
        tracks.append(track)
    return tracks


def tracks_from_search(payload):
    items = ((payload or {}).get("tracks") or {}).get("items") or []
    return tracks_from_paging({"items": items})


def choose_source_playlist(playlists, emotions):
    """
    The playlist whose title hits the selected feel hardest.
    Generated Feel playlists are ignored so the radio does not eat its own output.
    """
    emotions = normalize_emotions(emotions)
    best = None
    best_key = None
    for playlist in playlists or []:
        if not isinstance(playlist, dict):
            continue
        name = playlist.get("name") or ""
        if is_generated_playlist_name(name):
            continue
        score = sum(term_hit_count(name, emotion) for emotion in emotions)
        total = ((playlist.get("tracks") or {}).get("total") or 0)
        if score <= 0 or total <= 0:
            continue
        key = (score, total)
        if best_key is None or key > best_key:
            best_key = key
            best = playlist
    return best


def collect_corpus(emotions, read_playlists, read_playlist_tracks, read_saved_tracks):
    """
    Exactly two reads.

    1. GET /me/playlists — titles are the feel index.
    2. GET that playlist's tracks when a title matches, otherwise GET /me/tracks.
    """
    emotions = normalize_emotions(emotions)
    if not emotions:
        raise FeelError("Choose sad, happy, mad, or a combination.")
    playlist_payload = read_playlists()
    playlists = (playlist_payload or {}).get("items") or []
    chosen = choose_source_playlist(playlists, emotions)
    if chosen:
        track_payload = read_playlist_tracks(chosen.get("id"))
        source = {
            "kind": "playlist",
            "id": chosen.get("id"),
            "name": chosen.get("name") or "Playlist",
        }
        second = f"GET /playlists/{chosen.get('id')}/tracks"
    else:
        track_payload = read_saved_tracks()
        source = {"kind": "saved_tracks", "id": None, "name": "Saved songs"}
        second = "GET /me/tracks"
    tracks = tracks_from_paging(track_payload)
    return tracks, source, ["GET /me/playlists", second]


def order_for_radio(tracks, emotions, seed=None):
    """
    Walk the pile. The first song is the strongest feel match (or the
    closest to the seed). Each step picks the remaining song that shares
    the most title words or artist with the one just chosen.
    """
    emotions = normalize_emotions(emotions)
    remaining = []
    seen = set()
    for track in tracks or []:
        uri = track.get("uri")
        if not uri or uri in seen:
            continue
        seen.add(uri)
        remaining.append(track)
    if not remaining:
        return []

    def first_key(track):
        if seed:
            return (similarity(seed, track), score_track(track, emotions))
        return (score_track(track, emotions), similarity(seed, track) if seed else 0)

    remaining.sort(key=first_key, reverse=True)
    ordered = [remaining.pop(0)]
    while remaining:
        last = ordered[-1]
        best_index = 0
        best_key = None
        for index, track in enumerate(remaining):
            key = (similarity(last, track), score_track(track, emotions))
            if best_key is None or key > best_key:
                best_key = key
                best_index = index
        ordered.append(remaining.pop(best_index))
    return ordered


def refill_from_search(emotions, seed, search, exclude_uris):
    """One search. `search` is called once with the built query."""
    emotions = normalize_emotions(emotions)
    query = build_query(emotions, seed)
    payload = search(query)
    exclude = set(exclude_uris or [])
    found = []
    for track in tracks_from_search(payload):
        if track["uri"] in exclude:
            continue
        exclude.add(track["uri"])
        found.append(track)
    if seed:
        found.sort(
            key=lambda track: (similarity(seed, track), score_track(track, emotions)),
            reverse=True,
        )
    else:
        found.sort(key=lambda track: score_track(track, emotions), reverse=True)
    return found, query
