(function () {
    if (!navigator.mediaSession) {
        return;
    }

    var session = navigator.mediaSession;
    var metadataQueued = false;

    function text(selector) {
        var root = document.getElementById('trackInfo');
        var node = root && root.querySelector(selector);
        return node ? node.textContent.trim() : '';
    }

    function artwork() {
        var root = document.getElementById('trackInfo');
        var image = root && root.querySelector('img');
        var src = image ? image.getAttribute('src') : '';
        if (!src) {
            return [];
        }
        return [{ src: src }];
    }

    function publishMetadata() {
        if (typeof MediaMetadata !== 'function') {
            return;
        }
        try {
            session.metadata = new MediaMetadata({
                title: text('.track-name'),
                artist: text('.track-artist'),
                album: text('.track-album'),
                artwork: artwork()
            });
        } catch (error) {
            // Ignore artwork the browser will not accept.
        }
    }

    function queueMetadata() {
        if (metadataQueued) {
            return;
        }
        metadataQueued = true;
        Promise.resolve().then(function () {
            metadataQueued = false;
            publishMetadata();
        });
    }

    function publishPlaybackState() {
        var button = document.getElementById('playBtn');
        var label = button ? button.textContent : '';
        try {
            session.playbackState = label.indexOf('Pause') !== -1 ? 'playing' : 'paused';
        } catch (error) {
            // playbackState is not writable in this browser.
        }
    }

    function callExisting(name) {
        var fn = window[name];
        if (typeof fn === 'function') {
            fn();
        }
    }

    function onAction(action, handler) {
        try {
            session.setActionHandler(action, handler);
        } catch (error) {
            // Some browsers reject actions they do not implement.
        }
    }

    onAction('play', function () {
        callExisting('togglePlayback');
    });
    onAction('pause', function () {
        callExisting('togglePlayback');
    });
    onAction('previoustrack', function () {
        callExisting('previousTrack');
    });
    onAction('nexttrack', function () {
        callExisting('nextTrack');
    });

    function seekBy(deltaMs) {
        if (typeof sendSeek !== 'function') {
            return;
        }
        var current = typeof progressCurrentMs === 'number' ? progressCurrentMs : 0;
        var duration = typeof progressDurationMs === 'number' ? progressDurationMs : 0;
        var position = Math.max(0, Math.min(duration, current + deltaMs));
        if (typeof progressCurrentMs !== 'undefined') {
            progressCurrentMs = position;
        }
        if (typeof renderProgressBar === 'function') {
            renderProgressBar();
        }
        sendSeek(position);
    }

    onAction('seekbackward', function () {
        seekBy(-15000);
    });
    onAction('seekforward', function () {
        seekBy(15000);
    });

    function watch() {
        publishMetadata();
        publishPlaybackState();

        var root = document.getElementById('trackInfo');
        if (root && typeof MutationObserver === 'function') {
            new MutationObserver(queueMetadata).observe(root, {
                subtree: true,
                childList: true,
                characterData: true,
                attributes: true
            });
        }

        var playButton = document.getElementById('playBtn');
        if (playButton && typeof MutationObserver === 'function') {
            new MutationObserver(publishPlaybackState).observe(playButton, {
                subtree: true,
                childList: true,
                characterData: true
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', watch);
    } else {
        watch();
    }
})();
