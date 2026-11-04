from django.db import models


class SpotifyAccount(models.Model):
    """
    A Spotify account linked on this device. A kiosk can have several
    linked (e.g. different household members' accounts) - only one is
    "active" at a time, tracked by id in the Django session
    (request.session['active_account_id']), not on this model, since
    "active" is a property of the current kiosk session rather than
    the account itself.

    Tokens live here instead of only in the session so switching
    accounts doesn't require re-authenticating with Spotify every
    time - only the very first link for a given account does.
    """
    spotify_user_id = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    avatar_url = models.URLField(blank=True, max_length=1000)

    access_token = models.TextField()
    refresh_token = models.TextField()
    # Unix timestamp (matches the expires_at convention already used
    # in spotify_api.py's token_info dicts), not a DateTimeField, so
    # the refresh-check logic can stay identical to what it was
    # before this model existed.
    token_expires_at = models.FloatField()

    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_used_at']

    def __str__(self):
        return self.display_name or self.spotify_user_id

    def to_token_info(self):
        """Shape-compatible with the token_info dicts SpotifyAPI already
        works with, so existing refresh/expiry logic doesn't need to
        change - it just reads/writes through this instead of the
        session directly."""
        return {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'expires_at': self.token_expires_at,
        }

    def update_from_token_info(self, token_info):
        self.access_token = token_info['access_token']
        if token_info.get('refresh_token'):
            self.refresh_token = token_info['refresh_token']
        self.token_expires_at = token_info['expires_at']


class FeelRadio(models.Model):
    """
    One feel-radio session per linked account. The pile of candidate
    songs lives here so continuing playback does not re-read Spotify
    until the pile runs short.
    """
    account = models.OneToOneField(
        SpotifyAccount,
        on_delete=models.CASCADE,
        related_name="feel_radio",
    )
    active = models.BooleanField(default=False)
    continue_forever = models.BooleanField(default=True)
    emotions = models.JSONField(default=list)
    feel_name = models.CharField(max_length=40, blank=True)
    # {"Sad Mad": 4} — next snapshot uses the stored number plus one.
    counters = models.JSONField(default=dict)
    pool = models.JSONField(default=list)
    queued_tracks = models.JSONField(default=list)
    unsnapshotted = models.JSONField(default=list)
    latest_batch = models.JSONField(default=list)
    live_playlist_id = models.CharField(max_length=64, blank=True)
    live_playlist_name = models.CharField(max_length=120, blank=True)
    snapshots = models.JSONField(default=list)
    last_extend_uri = models.CharField(max_length=128, blank=True)
    extend_blocked = models.BooleanField(default=False)
    source_name = models.CharField(max_length=200, blank=True)
    last_reads = models.JSONField(default=list)
    last_query = models.CharField(max_length=120, blank=True)

    @property
    def tail_uri(self):
        tracks = self.queued_tracks or []
        if not tracks:
            return ""
        return tracks[-1].get("uri") or ""