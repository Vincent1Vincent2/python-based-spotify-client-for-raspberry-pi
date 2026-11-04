(function () {
    var BANNER_ID = 'spotipi-scope-banner';

    function messageFrom(data) {
        if (data && typeof data.error === 'string' && data.error.trim()) {
            return data.error.trim();
        }
        return 'Reconnect Spotify to continue.';
    }

    function bannerIsVisible() {
        var banner = document.getElementById(BANNER_ID);
        if (!banner) return false;
        var style = window.getComputedStyle(banner);
        return style.display !== 'none' && style.visibility !== 'hidden';
    }

    function showScopeBanner(data) {
        if (bannerIsVisible()) return;

        var banner = document.createElement('div');
        banner.id = BANNER_ID;
        banner.className = 'scope-banner';
        banner.setAttribute('role', 'status');

        var message = document.createElement('span');
        message.className = 'scope-banner-message';
        message.textContent = messageFrom(data);

        var link = document.createElement('a');
        link.href = '/login/?auth=1';
        link.textContent = 'Reconnect Spotify';

        banner.appendChild(message);
        banner.appendChild(document.createTextNode(' '));
        banner.appendChild(link);

        var parent = document.body || document.documentElement;
        parent.insertBefore(banner, parent.firstChild);
    }

    window.spotipiNoteAuth = function (data) {
        if (!data || data.code !== 'needs_scope') return;
        window.dispatchEvent(new CustomEvent('spotipi:needs-scope', { detail: data }));
    };

    window.addEventListener('spotipi:needs-scope', function (event) {
        showScopeBanner(event.detail || {});
    });
})();
