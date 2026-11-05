import time
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase

from player.features.listening_stats.stats import (
    ListeningStatsScopeError,
    load_listening_stats,
    summarize_recently_played,
)
from player.models import SpotifyAccount
from player.spotify_api import SpotifyAPI
from player.views import SPOTIFY_SCOPE


EXISTING_SCOPES = (
    "user-modify-playback-state",
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-read-playback-position",
    "streaming",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "user-library-read",
)

EMPTY_STATS = {
    "total_minutes": 0,
    "distinct_artists": 0,
    "top_artists": [],
    "top_tracks": [],
}


def _play(track_id, name, artists, duration_ms):
    return {
        "played_at": "2026-01-01T00:00:00.000Z",
        "track": {
            "id": track_id,
            "uri": f"spotify:track:{track_id}",
            "name": name,
            "duration_ms": duration_ms,
            "artists": [
                {"id": artist_id, "name": artist_name}
                for artist_id, artist_name in artists
            ],
        },
    }


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload


class FakeAPI:
    def __init__(self, payload=None, status=200):
        self.payload = {"items": []} if payload is None else payload
        self.status = status
        self.calls = 0

    def get_recently_played(self):
        self.calls += 1
        return FakeResponse(self.payload, self.status)


class SummarizeRecentlyPlayedTests(SimpleTestCase):
    def test_empty_list(self):
        self.assertEqual(summarize_recently_played({"items": []}), EMPTY_STATS)
        self.assertEqual(summarize_recently_played({}), EMPTY_STATS)
        self.assertEqual(summarize_recently_played(None), EMPTY_STATS)
        skipped = summarize_recently_played({"items": [{"track": None}, "nope"]})
        self.assertEqual(skipped, EMPTY_STATS)

    def test_repeated_artist(self):
        payload = {
            "items": [
                _play("t1", "Alpha", [("ada", "Ada")], 60_000),
                _play("t2", "Beta", [("ada", "Ada"), ("bea", "Bea")], 60_000),
                _play("t1", "Alpha", [("ada", "Ada")], 60_000),
            ],
            "next": "https://api.spotify.com/v1/me/player/recently-played?before=1",
        }
        stats = summarize_recently_played(payload)
        self.assertEqual(stats["distinct_artists"], 2)
        self.assertEqual(stats["top_artists"], [
            {"name": "Ada", "plays": 3, "percent": 100},
            {"name": "Bea", "plays": 1, "percent": 33},
        ])
        self.assertEqual(stats["top_tracks"], [
            {"name": "Alpha", "artists": "Ada", "plays": 2, "percent": 100},
            {"name": "Beta", "artists": "Ada, Bea", "plays": 1, "percent": 50},
        ])
        self.assertNotIn("items", stats)

    def test_minute_rounding(self):
        one_and_a_half = summarize_recently_played(
            {"items": [_play("t1", "Alpha", [("ada", "Ada")], 90_000)]}
        )
        self.assertEqual(one_and_a_half["total_minutes"], 2)

        just_under_half = summarize_recently_played(
            {"items": [_play("t1", "Alpha", [("ada", "Ada")], 29_999)]}
        )
        self.assertEqual(just_under_half["total_minutes"], 0)

        # Durations are summed first. Two 30-second plays are one minute,
        # not two rounded minutes and not zero.
        two_halves = summarize_recently_played({
            "items": [
                _play("t1", "Alpha", [("ada", "Ada")], 30_000),
                _play("t2", "Beta", [("bea", "Bea")], 30_000),
            ]
        })
        self.assertEqual(two_halves["total_minutes"], 1)

    def test_top_lists_keep_five(self):
        items = [
            _play(f"t{index}", f"Song {index}", [(f"a{index}", name)], 60_000)
            for index, name in enumerate(
                ["Nora", "Ada", "Bea", "Cara", "Eve", "Mia"],
                start=1,
            )
        ]
        # Plays: Nora 6, Ada 5, Bea 4, Cara 3, Eve 2, Mia 1.
        for extra, track_id, name, artist_id, artist_name in (
            (5, "t1", "Song 1", "a1", "Nora"),
            (4, "t2", "Song 2", "a2", "Ada"),
            (3, "t3", "Song 3", "a3", "Bea"),
            (2, "t4", "Song 4", "a4", "Cara"),
            (1, "t5", "Song 5", "a5", "Eve"),
        ):
            items.extend([
                _play(track_id, name, [(artist_id, artist_name)], 60_000)
                for _ in range(extra)
            ])
        stats = summarize_recently_played({"items": items})
        self.assertEqual(
            [row["name"] for row in stats["top_artists"]],
            ["Nora", "Ada", "Bea", "Cara", "Eve"],
        )
        self.assertEqual(stats["distinct_artists"], 6)
        self.assertEqual(
            [row["percent"] for row in stats["top_artists"]],
            [100, 83, 67, 50, 33],
        )


class LoadListeningStatsTests(SimpleTestCase):
    def test_one_recently_played_call(self):
        api = FakeAPI(payload={
            "items": [_play("t1", "Alpha", [("ada", "Ada")], 60_000)],
            "next": "https://api.spotify.com/v1/me/player/recently-played?before=1",
        })
        stats = load_listening_stats(api)
        self.assertEqual(api.calls, 1)
        self.assertEqual(stats["total_minutes"], 1)
        self.assertEqual(stats["distinct_artists"], 1)

    def test_forbidden_raises_needs_scope(self):
        api = FakeAPI(status=403)
        with self.assertRaises(ListeningStatsScopeError) as caught:
            load_listening_stats(api)
        self.assertEqual(caught.exception.code, "needs_scope")
        self.assertEqual(api.calls, 1)

    def test_spotify_client_requests_one_page_of_fifty(self):
        api = SpotifyAPI(access_token="token")
        with patch("player.spotify_api.requests.request") as request:
            request.return_value = FakeResponse({"items": []})
            api.get_recently_played()
        request.assert_called_once()
        method, url = request.call_args.args
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api.spotify.com/v1/me/player/recently-played")
        self.assertEqual(request.call_args.kwargs["params"], {"limit": 50})


class ListeningStatsScopeTests(SimpleTestCase):
    def test_scope_adds_recently_played_and_keeps_the_rest(self):
        scopes = SPOTIFY_SCOPE.split()
        self.assertEqual(
            set(scopes),
            set(EXISTING_SCOPES) | {"user-read-recently-played"},
        )
        self.assertEqual(len(scopes), len(set(scopes)))
        self.assertEqual(scopes[-1], "user-read-recently-played")


def _account(spotify_user_id):
    return SpotifyAccount.objects.create(
        spotify_user_id=spotify_user_id,
        display_name="Listener",
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


class ListeningStatsViewTests(TestCase):
    def test_stats_reads_recently_played_once(self):
        client = _client_for(_account("stats-user"))
        payload = {"items": [_play("t1", "Alpha", [("ada", "Ada")], 120_000)]}
        with patch.object(SpotifyAPI, "get_recently_played", return_value=FakeResponse(payload)) as read:
            response = client.get("/stats/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(read.call_count, 1)
        body = response.json()
        self.assertEqual(body["total_minutes"], 2)
        self.assertEqual(body["distinct_artists"], 1)
        self.assertEqual(body["top_artists"][0]["name"], "Ada")
        self.assertNotIn("items", body)
        self.assertNotIn("played_at", response.content.decode())

    def test_forbidden_returns_needs_scope(self):
        client = _client_for(_account("stats-forbidden"))
        with patch.object(SpotifyAPI, "get_recently_played", return_value=FakeResponse({}, 403)):
            response = client.get("/stats/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "needs_scope")

    def test_missing_session_is_unauthorized(self):
        response = Client().get("/stats/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_expired")

    def test_player_page_has_stats_tab(self):
        client = _client_for(_account("stats-page"))
        with patch("player.spotify_api.SpotifyAPI.get_devices", return_value=FakeResponse({"devices": []})), \
                patch("player.spotify_api.SpotifyAPI.get_current_playback", return_value=FakeResponse({}, status=204)):
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('id="tab-stats"', body)
        self.assertIn(">Stats</button>", body)
        self.assertIn('id="content-stats"', body)
        self.assertIn("/stats/", body)
        self.assertIn("/login/?auth=1", body)
        self.assertIn("stats-bar", body)
        self.assertIn("width:", body)
        self.assertIn("Feel radio", body)

    def test_logged_in_auth_link_starts_oauth_with_the_new_scope(self):
        client = _client_for(_account("stats-reauth"))
        home = client.get("/login/")
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home["Location"], "/")
        reconnect = client.get("/login/?auth=1")
        self.assertEqual(reconnect.status_code, 302)
        location = reconnect["Location"]
        self.assertIn("https://accounts.spotify.com/authorize?", location)
        self.assertIn("user-read-recently-played", location)
        for scope in EXISTING_SCOPES:
            self.assertIn(scope, location)
