import time
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase

from player.features.followed_artists import (
    LOGIN_PATH,
    SCOPE,
    NeedsScope,
    artists_from_payload,
    load_followed_artists,
)
from player.models import SpotifyAccount
from player.views import SPOTIFY_SCOPE


PAYLOAD = {
    "artists": {
        "href": "https://api.spotify.com/v1/me/following?type=artist&limit=50",
        "limit": 50,
        "next": "https://api.spotify.com/v1/me/following?type=artist&after=bea&limit=50",
        "cursors": {"after": "bea"},
        "total": 80,
        "items": [
            {
                "id": "ada",
                "name": "Ada",
                "images": [
                    {"url": "https://i.scdn.co/image/ada", "height": 640, "width": 640},
                    {"url": "https://i.scdn.co/image/ada-small", "height": 64, "width": 64},
                ],
                "uri": "spotify:artist:ada",
                "genres": ["jazz"],
                "followers": {"total": 12},
                "type": "artist",
            },
            None,
            {"id": "", "name": "Missing"},
            {
                "id": "bea",
                "name": "Bea",
                "images": [],
                "uri": "spotify:artist:bea",
                "type": "artist",
            },
        ],
    },
    "items": [
        {"id": "not-an-artist", "name": "Wrong list"},
    ],
}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(self.status_code)


class FakeAPI:
    def __init__(self, payload=None, status=200):
        self.payload = PAYLOAD if payload is None else payload
        self.status = status
        self.gets = []

    def get(self, endpoint, params=None, **kwargs):
        self.gets.append((endpoint, params))
        return FakeResponse(self.payload, self.status)


class FollowedArtistsPayloadTests(SimpleTestCase):
    def test_one_call_parses_artists_items(self):
        api = FakeAPI(PAYLOAD)
        artists = load_followed_artists(api)

        self.assertEqual(
            [(artist["id"], artist["name"], artist["image"]) for artist in artists],
            [
                ("ada", "Ada", "https://i.scdn.co/image/ada"),
                ("bea", "Bea", ""),
            ],
        )
        self.assertEqual(artists[0]["url"], "/features/artist-pages/?id=ada")
        self.assertEqual(api.gets, [("me/following", {"type": "artist", "limit": 50})])
        self.assertEqual(len(api.gets), 1)
        self.assertNotIn("related-artists", api.gets[0][0])
        self.assertNotIn("top-tracks", api.gets[0][0])

    def test_artists_from_payload_reads_artists_items(self):
        artists = artists_from_payload(PAYLOAD)
        self.assertEqual([artist["name"] for artist in artists], ["Ada", "Bea"])
        self.assertEqual(artists[0]["image"], "https://i.scdn.co/image/ada")

    def test_empty_artists_items_is_an_empty_list(self):
        api = FakeAPI({"artists": {"items": [], "total": 0, "next": None}})
        artists = load_followed_artists(api)
        self.assertEqual(artists, [])
        self.assertEqual(api.gets, [("me/following", {"type": "artist", "limit": 50})])

    def test_missing_artists_object_is_an_empty_list(self):
        self.assertEqual(artists_from_payload({}), [])
        self.assertEqual(artists_from_payload({"items": [{"id": "nope", "name": "Nope"}]}), [])
        self.assertEqual(artists_from_payload({"artists": {}}), [])
        self.assertEqual(artists_from_payload(None), [])

    def test_forbidden_read_needs_the_follow_scope(self):
        api = FakeAPI(status=403)
        with self.assertRaises(NeedsScope) as caught:
            load_followed_artists(api)
        self.assertEqual(caught.exception.code, "needs_scope")
        self.assertEqual(caught.exception.login, LOGIN_PATH)
        self.assertEqual(len(api.gets), 1)


class FollowedArtistsViewTests(TestCase):
    def test_get_returns_artists_from_one_read(self):
        api = FakeAPI(PAYLOAD)
        with patch(
            "player.features.followed_artists.views.get_spotify_api",
            return_value=api,
        ):
            response = Client().get("/features/followed-artists/")

        self.assertEqual(response.status_code, 200)
        artists = response.json()["artists"]
        self.assertEqual(len(artists), 2)
        self.assertEqual(artists[0]["name"], "Ada")
        self.assertEqual(artists[0]["image"], "https://i.scdn.co/image/ada")
        self.assertEqual(artists[0]["url"], "/features/artist-pages/?id=ada")
        self.assertEqual(artists[1]["name"], "Bea")
        self.assertEqual(artists[1]["image"], "")
        self.assertEqual(api.gets, [("me/following", {"type": "artist", "limit": 50})])

    def test_empty_list(self):
        api = FakeAPI({"artists": {"items": []}})
        with patch(
            "player.features.followed_artists.views.get_spotify_api",
            return_value=api,
        ):
            response = Client().get("/features/followed-artists/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["artists"], [])
        self.assertEqual(len(api.gets), 1)

    def test_forbidden_read_returns_needs_scope_and_login(self):
        api = FakeAPI(status=403)
        with patch(
            "player.features.followed_artists.views.get_spotify_api",
            return_value=api,
        ):
            response = Client().get("/features/followed-artists/")

        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body["code"], "needs_scope")
        self.assertEqual(body["login"], "/login/?auth=1")
        self.assertEqual(api.gets, [("me/following", {"type": "artist", "limit": 50})])

    def test_signed_out_list_is_unauthorized(self):
        response = Client().get("/features/followed-artists/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_expired")


class FollowedArtistsScopeTests(SimpleTestCase):
    def test_scope_adds_follow_read_without_removing_existing(self):
        scopes = SPOTIFY_SCOPE.split()
        existing = [
            "user-modify-playback-state",
            "user-read-playback-state",
            "user-read-currently-playing",
            "user-read-playback-position",
            "streaming",
            "playlist-read-private",
            "playlist-read-collaborative",
            "playlist-modify-private",
            "user-library-read",
        ]
        self.assertIn(SCOPE, scopes)
        self.assertEqual(scopes.count(SCOPE), 1)
        for scope in existing:
            self.assertIn(scope, scopes)
        self.assertGreaterEqual(len(scopes), len(existing) + 1)


class FollowedArtistsPageTests(TestCase):
    def _account(self):
        return SpotifyAccount.objects.create(
            spotify_user_id="follow-user",
            display_name="Follow",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=time.time() + 3600,
        )

    def _signed_in(self):
        account = self._account()
        client = Client()
        session = client.session
        session["active_account_id"] = account.id
        session["use_web_player"] = True
        session.save()
        return client

    def test_player_page_has_a_following_tab(self):
        client = self._signed_in()
        with patch(
            "player.spotify_api.SpotifyAPI.get_devices",
            return_value=FakeResponse({"devices": []}),
        ), patch(
            "player.spotify_api.SpotifyAPI.get_current_playback",
            return_value=FakeResponse({}, status=204),
        ):
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn('id="tab-following"', body)
        self.assertIn(">Following</button>", body)
        self.assertIn('id="content-following"', body)
        self.assertIn("loadFollowing", body)
        self.assertIn("/features/followed-artists/", body)
        self.assertIn("/features/artist-pages/?id=", body)
        self.assertIn("Reconnect Spotify to show artists you follow.", body)
        self.assertIn('href="/login/?auth=1"', body)
        self.assertIn("No followed artists.", body)

    def test_signed_in_login_without_auth_stays_on_the_player(self):
        response = self._signed_in().get("/login/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")

    def test_signed_in_auth_query_reauthorizes_with_the_new_scope(self):
        response = self._signed_in().get("/login/?auth=1")
        self.assertEqual(response.status_code, 302)
        location = response["Location"]
        self.assertIn("https://accounts.spotify.com/authorize", location)
        self.assertIn("user-follow-read", location)
        self.assertIn("playlist-modify-private", location)
        self.assertIn("user-library-read", location)
        self.assertIn("user-modify-playback-state", location)
