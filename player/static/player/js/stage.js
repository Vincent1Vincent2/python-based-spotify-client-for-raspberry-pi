/*
 * Now Playing stage.
 * Reads the artwork, title, artists, album, and device name already
 * painted by the player. Does not call Spotify.
 */
(function () {
    var toggle = document.getElementById('stageToggle');
    var stage = document.getElementById('nowPlayingStage');
    if (!toggle || !stage) {
        return;
    }

    var art = document.getElementById('stageArt');
    var titleEl = document.getElementById('stageTitle');
    var artistsEl = document.getElementById('stageArtists');
    var albumEl = document.getElementById('stageAlbum');
    var deviceEl = document.getElementById('stageDevice');
    var statusEl = document.getElementById('stageStatus');
    var closeBtn = document.getElementById('stageClose');

    function clean(node) {
        if (!node) {
            return '';
        }
        return node.textContent.replace(/\s+/g, ' ').trim();
    }

    function readNowPlaying() {
        var info = document.getElementById('trackInfo');
        var image = info ? info.querySelector('img') : null;
        var src = image ? (image.getAttribute('src') || '') : '';
        var activeDevice = document.querySelector('.device-item.active .device-name');
        var playerStatus = document.getElementById('playerStatus');
        var device = clean(activeDevice);
        if (!device) {
            device = clean(playerStatus);
        }
        return {
            src: src,
            alt: image ? (image.getAttribute('alt') || 'Artwork') : 'Artwork',
            title: (info && clean(info.querySelector('.track-name'))) || 'No track playing',
            artists: info ? clean(info.querySelector('.track-artist')) : '',
            album: info ? clean(info.querySelector('.track-album')) : '',
            device: device,
            status: clean(playerStatus)
        };
    }

    function render() {
        var now = readNowPlaying();
        if (art) {
            if (now.src) {
                art.src = now.src;
                art.alt = now.alt;
                art.hidden = false;
            } else {
                art.removeAttribute('src');
                art.alt = '';
                art.hidden = true;
            }
        }
        if (titleEl) {
            titleEl.textContent = now.title;
        }
        if (artistsEl) {
            artistsEl.textContent = now.artists;
        }
        if (albumEl) {
            albumEl.textContent = now.album;
        }
        if (deviceEl) {
            deviceEl.textContent = now.device;
        }
        if (statusEl) {
            statusEl.textContent = now.status && now.status !== now.device ? now.status : '';
        }
    }

    function openStage() {
        render();
        stage.hidden = false;
        stage.setAttribute('aria-hidden', 'false');
        toggle.setAttribute('aria-pressed', 'true');
        document.body.classList.add('stage-open');
        if (closeBtn) {
            closeBtn.focus();
        }
    }

    function closeStage() {
        if (stage.hidden) {
            return;
        }
        stage.hidden = true;
        stage.setAttribute('aria-hidden', 'true');
        toggle.setAttribute('aria-pressed', 'false');
        document.body.classList.remove('stage-open');
        toggle.focus();
    }

    toggle.addEventListener('click', function () {
        if (stage.hidden) {
            openStage();
        } else {
            closeStage();
        }
    });

    if (closeBtn) {
        closeBtn.addEventListener('click', closeStage);
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !stage.hidden) {
            event.preventDefault();
            closeStage();
        }
    });

    var observer = new MutationObserver(function () {
        if (!stage.hidden) {
            render();
        }
    });
    var trackInfo = document.getElementById('trackInfo');
    var playerStatus = document.getElementById('playerStatus');
    var deviceList = document.getElementById('deviceList');
    if (trackInfo) {
        observer.observe(trackInfo, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true,
            attributeFilter: ['src', 'alt']
        });
    }
    if (playerStatus) {
        observer.observe(playerStatus, {
            childList: true,
            subtree: true,
            characterData: true
        });
    }
    if (deviceList) {
        observer.observe(deviceList, {
            attributes: true,
            subtree: true,
            attributeFilter: ['class']
        });
    }
})();
