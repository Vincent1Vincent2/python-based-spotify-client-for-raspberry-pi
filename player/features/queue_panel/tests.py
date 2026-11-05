import time
from unittest.mock import patch

from django.test import Client, TestCase

from player.features.queue_panel.views import format_duration, present_queue
from player.models import SpotifyAccount
from player.spotify_api import SpotifyAPI


def _album(name, image=None):
    album = {"name": name, "images": []}
    if image:
        album["images"] = [{"url": image, "height": 300, "width": 300}]
    return album


def _spotify_track(track_id, name, artist="Ada", album="Album", image="https://i.scdn.co/image/track"):
    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "name": name,
        "type": "track",
        "duration_ms": 180000,
        "artists": [{"name": artist}],
        "album": _album(album, image),
    }


FAKE_QUEUE = {
    "currently_playing": {
        "id": "now",
        "uri": "spotify:track:now",
        "name": "Current Song",
        "type": "track",
        "duration_ms": 181000,
        "artists": [{"name": "Ada"}, {"name": "Bea"}],
        "album": _album("Current Album", "https://i.scdn.co/image/current"),
    },
    "queue": [
        _spotify_track(
            "q1",
            "First Queued",
            artist="Cy",
            album="Queued Album",
            image="https://i.scdn.co/image/q1",
        ),
        {
            "id": "ep1",
            "uri": "spotify:episode:ep1",
            "name": "Show Notes",
            "type": "episode",
            "duration_ms": 1500000,
            "images": [{"url": "https://i.scdn.co/image/ep1"}],
            "show": {
                "name": "Night Bus",
                "images": [{"url": "https://i.scdn.co/image/show"}],
            },
        },
        _spotify_track("q2", "No Art", artist="Dee", album="Bare", image=None),
    ],
}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.content = b"" if status == 204 else b"body"

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(self.status_code)


def _account(spotify_user_id):
    return SpotifyAccount.objects.create(
        spotify_user_id=spotify_user_id,
        display_name="Queue",
        access_token="access",
        refresh_token="refresh",
        token_expires_at=time.time() + 3600,
    )


def _client_for(account):
    client = Client()
    session = client.session
    session["active_account_id"] = account.id
    session["use_web_player"] = True
    session.save()
    return client


class PresentQueueTests(TestCase):
    def test_fake_payload_keeps_the_current_item_and_queue_order(self):
        presented = present_queue(FAKE_QUEUE)
        current = presented["currently_playing"]
        self.assertEqual(current["name"], "Current Song")
        self.assertEqual(current["uri"], "spotify:track:now")
        self.assertEqual(current["subtitle"], "Ada, Bea · Current Album")
        self.assertEqual(current["image"], "https://i.scdn.co/image/current")
        self.assertEqual(current["duration_ms"], 181000)
        self.assertEqual(current["duration_label"], "3:01")
        self.assertEqual(
            [item["name"] for item in presented["queue"]],
            ["First Queued", "Show Notes", "No Art"],
        )
        self.assertEqual(
            [item["uri"] for item in presented["queue"]],
            ["spotify:track:q1", "spotify:episode:ep1", "spotify:track:q2"],
        )
        episode = presented["queue"][1]
        self.assertEqual(episode["type"], "episode")
        self.assertEqual(episode["subtitle"], "Night Bus")
        self.assertEqual(episode["image"], "https://i.scdn.co/image/ep1")
        self.assertEqual(episode["duration_label"], "25:00")
        self.assertIsNone(presented["queue"][2]["image"])
        self.assertEqual(
            set(current),
            {
                "id",
                "uri",
                "name",
                "type",
                "subtitle",
                "image",
                "duration_ms",
                "duration_label",
            },
        )

    def test_empty_queue_and_null_current_item(self):
        presented = present_queue({"currently_playing": None, "queue": []})
        self.assertIsNone(presented["currently_playing"])
        self.assertEqual(presented["queue"], [])
        self.assertEqual(present_queue({})["queue"], [])
        self.assertEqual(present_queue({"queue": None})["queue"], [])

    def test_non_items_are_skipped_and_a_long_payload_is_not_truncated(self):
        payload = {
            "currently_playing": _spotify_track("now", "Now"),
            "queue": [None, "nope", *[_spotify_track(f"q{i}", f"Song {i}") for i in range(21)]],
        }
        presented = present_queue(payload)
        self.assertEqual(
            [item["name"] for item in presented["queue"]],
            [f"Song {i}" for i in range(21)],
        )

    def test_episode_without_its_own_image_uses_the_show_image(self):
        presented = present_queue({
            "currently_playing": {
                "id": "bare",
                "uri": "spotify:episode:bare",
                "name": "Bare episode",
                "type": "episode",
                "duration_ms": 1000,
                "images": [],
                "show": {
                    "name": "Night Bus",
                    "images": [{"url": "https://i.scdn.co/image/show"}],
                },
            },
            "queue": [],
        })
        current = presented["currently_playing"]
        self.assertEqual(current["image"], "https://i.scdn.co/image/show")
        self.assertEqual(current["duration_label"], "0:01")

    def test_format_duration_uses_hours_for_a_long_episode(self):
        self.assertEqual(format_duration(3_600_000), "1:00:00")
        self.assertEqual(format_duration(None), "")
        self.assertEqual(format_duration(0), "")


class GetQueueApiTests(TestCase):
    def test_get_queue_is_a_get_of_me_player_queue(self):
        api = SpotifyAPI(access_token="token")
        with patch("player.spotify_api.requests.request") as request:
            request.return_value = FakeResponse(FAKE_QUEUE)
            response = api.get_queue()
        self.assertEqual(response.json(), FAKE_QUEUE)
        method, url = request.call_args.args[:2]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api.spotify.com/v1/me/player/queue")
        self.assertNotIn("json", request.call_args.kwargs)
        self.assertNotIn("data", request.call_args.kwargs)
        params = request.call_args.kwargs.get("params")
        self.assertTrue(params is None or "uri" not in params)


class PlaybackQueueViewTests(TestCase):
    def test_view_returns_the_fake_queue_without_changing_playback(self):
        client = _client_for(_account("queue-user"))
        with patch("player.spotify_api.SpotifyAPI.get_queue", return_value=FakeResponse(FAKE_QUEUE)) as get_queue, \
                patch("player.spotify_api.SpotifyAPI.add_to_queue") as add_to_queue, \
                patch("player.spotify_api.SpotifyAPI.next_track") as next_track, \
                patch("player.spotify_api.SpotifyAPI.start_playback") as start_playback:
            response = client.get("/playback-queue/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_queue.call_count, 1)
        self.assertEqual(add_to_queue.call_count, 0)
        self.assertEqual(next_track.call_count, 0)
        self.assertEqual(start_playback.call_count, 0)
        body = response.json()
        self.assertEqual(body["currently_playing"]["name"], "Current Song")
        self.assertEqual(body["currently_playing"]["subtitle"], "Ada, Bea · Current Album")
        self.assertEqual(
            [item["name"] for item in body["queue"]],
            ["First Queued", "Show Notes", "No Art"],
        )
        self.assertEqual(body["queue"][0]["image"], "https://i.scdn.co/image/q1")
        self.assertEqual(body["queue"][1]["subtitle"], "Night Bus")

    def test_no_content_is_an_empty_queue(self):
        client = _client_for(_account("queue-empty"))
        with patch("player.spotify_api.SpotifyAPI.get_queue", return_value=FakeResponse(status=204)):
            response = client.get("/playback-queue/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["currently_playing"])
        self.assertEqual(response.json()["queue"], [])

    def test_no_active_device_is_reported(self):
        client = _client_for(_account("queue-idle"))
        spotify = FakeResponse(
            {"error": {"status": 404, "message": "No active device found"}},
            status=404,
        )
        with patch("player.spotify_api.SpotifyAPI.get_queue", return_value=spotify):
            response = client.get("/playback-queue/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "No active device found")

    def test_unreadable_queue_is_an_error(self):
        client = _client_for(_account("queue-bad"))
        with patch(
            "player.spotify_api.SpotifyAPI.get_queue",
            return_value=FakeResponse(ValueError("not json"), status=200),
        ):
            response = client.get("/playback-queue/")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "Queue response was not readable")

    def test_queue_read_requires_an_account(self):
        response = Client().get("/playback-queue/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_expired")

    def test_playback_queue_rejects_writes(self):
        response = Client().post("/playback-queue/")
        self.assertEqual(response.status_code, 405)

    def test_existing_add_to_queue_endpoint_stays(self):
        missing = Client().post("/queue/")
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["error"], "Track ID required")
        reading = Client().get("/queue/")
        self.assertEqual(reading.status_code, 405)


class QueuePanelPageTests(TestCase):
    def test_player_page_includes_the_queue_tab(self):
        client = _client_for(_account("queue-page"))
        with patch("player.spotify_api.SpotifyAPI.get_devices", return_value=FakeResponse({"devices": []})), \
                patch("player.spotify_api.SpotifyAPI.get_current_playback", return_value=FakeResponse({}, status=204)), \
                patch("player.spotify_api.SpotifyAPI.get_queue") as get_queue:
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(get_queue.call_count, 0)
        body = page.content.decode()
        start = body.index('id="content-queue"')
        panel = body[start:body.index('id="playlistDetailView"')]
        self.assertIn('id="tab-queue"', body)
        self.assertIn(">Queue</button>", body)
        self.assertIn("New items go to the end of the queue.", panel)
        self.assertIn("cannot remove a queued item", panel)
        self.assertIn("insert one at the front", panel)
        self.assertIn("about 20", panel)
        self.assertIn("fetch('/playback-queue/')", panel)
        self.assertNotIn("Play next", panel)
        self.assertNotIn("play next", panel.lower())
        self.assertNotIn("Remove from queue", panel)
        self.assertNotIn("add_to_queue", panel)
        self.assertNotIn("method: 'POST'", panel)
        self.assertNotIn('method: "POST"', panel)
