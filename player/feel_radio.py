"""
Feel radio.

Two Spotify reads build the first pile (see feel.collect_corpus). Each
later block spends at most one search, and only when the local pile
cannot fill another 30. Playback itself is a private "{Feel} Radio"
playlist that grows by one add-items call, so the queue endpoint is
never called once per song. Every completed block of 30 is also saved
under the static feel name plus a number: "Sad Mad 01", "Sad Mad 02".
"""
import logging

from django.db import transaction

from .feel import (
    BATCH_SIZE,
    PAGE_LIMIT,
    SEARCH_LIMIT,
    FeelError,
    FeelScopeError,
    collect_corpus,
    feel_name,
    normalize_emotions,
    order_for_radio,
    playlist_title,
    radio_title,
    refill_from_search,
)
from .models import FeelRadio

logger = logging.getLogger(__name__)


def _payload(response, action):
    status = getattr(response, "status_code", 200)
    if status == 403:
        raise FeelScopeError()
    if status >= 400:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    detail = error.get("message") or ""
                elif isinstance(error, str):
                    detail = error
        except Exception:
            detail = ""
        message = f"{action} failed ({status})"
        if detail:
            message = f"{message}: {detail}"
        raise FeelError(message)
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _public_track(track):
    return {
        "id": track.get("id"),
        "uri": track.get("uri"),
        "name": track.get("name") or "",
        "artists": list(track.get("artists") or []),
        "album": track.get("album") or "",
    }


def radio_state(radio, tracks=None, reads=None, extended=False, message=""):
    return {
        "active": radio.active,
        "continue_forever": radio.continue_forever,
        "emotions": list(radio.emotions or []),
        "feel_name": radio.feel_name,
        "radio_name": radio.live_playlist_name,
        "radio_id": radio.live_playlist_id,
        "snapshots": list(radio.snapshots or [])[-8:],
        "tracks": [_public_track(track) for track in (tracks if tracks is not None else radio.latest_batch or [])],
        "pool_remaining": len(radio.pool or []),
        "reads": list(reads if reads is not None else radio.last_reads or []),
        "source_name": radio.source_name,
        "tail_uri": radio.tail_uri,
        "query": radio.last_query,
        "extended": extended,
        "extend_blocked": radio.extend_blocked,
        "message": message,
    }


def _create_playlist(api, name, description):
    response = api.create_playlist(name, description=description[:300], public=False)
    data = _payload(response, "Create playlist")
    playlist_id = data.get("id")
    if not playlist_id:
        raise FeelError("Spotify did not return a playlist id.")
    return playlist_id


def _add_items(api, playlist_id, tracks):
    uris = [track["uri"] for track in tracks if track.get("uri")]
    if not uris:
        return
    response = api.add_playlist_items(playlist_id, uris)
    _payload(response, "Add songs")


def _description(feel, source_name, reads, opener):
    read_text = ", ".join(reads) if reads else "local pile"
    text = f"{feel}. Chained from {source_name or 'your library'}."
    if opener and opener.get("name"):
        text += f" Opens with {opener['name']}."
    text += f" Spotify reads: {read_text}."
    return text[:300]


def _bump_counter(radio):
    counters = dict(radio.counters or {})
    number = int(counters.get(radio.feel_name, 0)) + 1
    counters[radio.feel_name] = number
    radio.counters = counters
    return number


def _cut_snapshots(api, radio, reads):
    """Save each completed block of 30 under the static feel name."""
    made = []
    pending = list(radio.unsnapshotted or [])
    while len(pending) >= BATCH_SIZE:
        chunk = pending[:BATCH_SIZE]
        pending = pending[BATCH_SIZE:]
        number = _bump_counter(radio)
        name = playlist_title(radio.feel_name, number)
        playlist_id = _create_playlist(
            api,
            name,
            _description(radio.feel_name, radio.source_name, reads, chunk[0]),
        )
        _add_items(api, playlist_id, chunk)
        made.append({"name": name, "id": playlist_id, "count": len(chunk)})
    radio.unsnapshotted = pending
    if made:
        radio.snapshots = (list(radio.snapshots or []) + made)[-24:]
    return made


def _exclude_uris(radio):
    uris = []
    for bucket in (radio.pool, radio.queued_tracks, radio.unsnapshotted):
        for track in bucket or []:
            if track.get("uri"):
                uris.append(track["uri"])
    return uris


def _read_corpus(api, emotions):
    def read_playlists():
        return _payload(
            api.get_user_playlists(limit=PAGE_LIMIT, offset=0),
            "Read playlists",
        )

    def read_playlist_tracks(playlist_id):
        return _payload(
            api.get_playlist_tracks(playlist_id, limit=PAGE_LIMIT, offset=0),
            "Read playlist songs",
        )

    def read_saved_tracks():
        return _payload(
            api.get_user_saved_tracks(limit=PAGE_LIMIT, offset=0),
            "Read saved songs",
        )

    return collect_corpus(emotions, read_playlists, read_playlist_tracks, read_saved_tracks)


def start_feel_radio(api, account, emotions, device_id, continue_forever=True):
    emotions = normalize_emotions(emotions)
    feel = feel_name(emotions)
    tracks, source, reads = _read_corpus(api, emotions)
    ordered = order_for_radio(tracks, emotions)
    if not ordered:
        raise FeelError(
            "No songs came back from your playlists or saved library.",
            code="empty_library",
        )
    batch = ordered[:BATCH_SIZE]
    pool = ordered[BATCH_SIZE:]

    radio, _created = FeelRadio.objects.get_or_create(account=account)
    radio.active = True
    radio.continue_forever = bool(continue_forever)
    radio.emotions = emotions
    radio.feel_name = feel
    radio.pool = pool
    radio.unsnapshotted = list(batch)
    radio.queued_tracks = list(batch)
    radio.latest_batch = list(batch)
    radio.extend_blocked = False
    radio.last_extend_uri = ""
    radio.last_query = ""
    radio.source_name = source["name"]
    radio.last_reads = reads
    radio.live_playlist_name = radio_title(feel)

    radio.live_playlist_id = _create_playlist(
        api,
        radio.live_playlist_name,
        _description(feel, source["name"], reads, batch[0]),
    )
    _add_items(api, radio.live_playlist_id, batch)
    try:
        snapshots = _cut_snapshots(api, radio, reads)
    except FeelError:
        logger.warning("feel radio: numbered playlist was not saved", exc_info=True)
        snapshots = []

    try:
        _payload(api.set_shuffle(False, device_id=device_id), "Shuffle")
    except FeelError:
        logger.warning("feel radio: shuffle off failed", exc_info=True)

    play_message = ""
    play = api.start_playback(
        device_id=device_id,
        context_uri=f"spotify:playlist:{radio.live_playlist_id}",
    )
    if getattr(play, "status_code", 200) >= 400:
        play_message = "The playlist is saved. Playback did not start on this device."
        logger.warning("feel radio: start_playback status %s", play.status_code)

    radio.save()
    message = play_message
    if len(batch) < BATCH_SIZE:
        short = (
            f"Playing {len(batch)} songs from {source['name']}. "
            f"{playlist_title(feel, (radio.counters or {}).get(feel, 0) + 1)} "
            "is saved once 30 songs have been chained."
        )
        message = f"{message} {short}".strip()
    elif snapshots:
        message = f"{message} Saved {snapshots[-1]['name']}.".strip()
    return radio_state(radio, tracks=batch, reads=reads, extended=False, message=message)


def _claim_extension(account, uri, remaining_ms, ended):
    """Mark this track so the playback poll cannot extend twice."""
    with transaction.atomic():
        radio = (
            FeelRadio.objects.select_for_update()
            .filter(account=account, active=True)
            .first()
        )
        if not radio or not radio.continue_forever or radio.extend_blocked:
            return None, radio_state(radio, extended=False) if radio else {
                "active": False, "extended": False, "tail_uri": "",
            }
        marker = uri or "ended"
        near_end = (
            bool(uri)
            and uri == radio.tail_uri
            and remaining_ms is not None
            and remaining_ms <= 20000
        )
        if ended and radio.last_extend_uri and radio.last_extend_uri == radio.tail_uri:
            return None, radio_state(radio, extended=False)
        if not (bool(ended) or near_end) or radio.last_extend_uri == marker:
            return None, radio_state(radio, extended=False)
        radio.last_extend_uri = marker
        radio.save(update_fields=["last_extend_uri"])
        return radio, None


def _release_extension(radio_id):
    FeelRadio.objects.filter(pk=radio_id).update(last_extend_uri="")


def advance_feel_radio(api, account, device_id, uri, remaining_ms, ended):
    """
    Called from the playback poll. Spotify is contacted only when the
    track that is playing is the last one we queued and it is inside
    the last 20 seconds, or playback has already run out.
    A full local pile costs zero reads. A short pile costs one search.
    """
    radio, idle = _claim_extension(account, uri, remaining_ms, ended)
    if radio is None:
        return idle

    emotions = list(radio.emotions or [])
    pool = list(radio.pool or [])
    seed = radio.queued_tracks[-1] if radio.queued_tracks else None
    live_id = radio.live_playlist_id
    exclude = _exclude_uris(radio)
    if not live_id:
        _release_extension(radio.pk)
        raise FeelError("Feel radio has no playlist to extend.")

    reads = []
    query = ""
    try:
        if len(pool) < BATCH_SIZE:
            found, query = refill_from_search(
                emotions,
                seed,
                lambda built: _payload(
                    api.search(q=built, type="track", limit=SEARCH_LIMIT),
                    "Search",
                ),
                exclude,
            )
            pool = pool + found
            reads = ["GET /search"]
        addition = pool[:BATCH_SIZE]
        pool = pool[BATCH_SIZE:]
        if not addition:
            radio.pool = pool
            radio.extend_blocked = True
            radio.last_query = query
            radio.last_reads = reads
            radio.save(update_fields=["pool", "extend_blocked", "last_query", "last_reads"])
            return radio_state(
                radio,
                reads=reads,
                extended=False,
                message="Nothing further matched this feel.",
            )
        _add_items(api, live_id, addition)
    except FeelError:
        _release_extension(radio.pk)
        raise

    play_message = ""
    if ended:
        resume = api.start_playback(
            device_id=device_id,
            context_uri=f"spotify:playlist:{live_id}",
            offset={"uri": addition[0]["uri"]},
        )
        if getattr(resume, "status_code", 200) >= 400:
            play_message = "Added songs, but playback did not resume."

    radio.pool = pool
    radio.unsnapshotted = list(radio.unsnapshotted or []) + addition
    radio.queued_tracks = (list(radio.queued_tracks or []) + addition)[-60:]
    radio.latest_batch = addition
    radio.last_query = query
    radio.last_reads = reads
    radio.extend_blocked = False
    try:
        snapshots = _cut_snapshots(api, radio, reads or ["local pile"])
    except FeelError:
        logger.warning("feel radio: numbered playlist was not saved", exc_info=True)
        snapshots = []
    radio.save()

    message = play_message
    if snapshots:
        message = f"{message} Saved {snapshots[-1]['name']}.".strip()
    elif query:
        message = f"{message} One search kept the radio going.".strip()
    return radio_state(radio, tracks=addition, reads=reads, extended=True, message=message)


def stop_feel_radio(account):
    radio = FeelRadio.objects.filter(account=account).first()
    if not radio:
        return {"active": False, "extended": False, "tail_uri": ""}
    radio.active = False
    radio.save(update_fields=["active"])
    return radio_state(radio, extended=False, message="Feel radio stopped. The playlists stay in your library.")


def feel_status(account):
    radio = FeelRadio.objects.filter(account=account).first()
    if not radio:
        return {"active": False, "extended": False, "tail_uri": "", "tracks": [], "snapshots": []}
    return radio_state(radio)
