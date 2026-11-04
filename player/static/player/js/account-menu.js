(function () {
    var root = document.getElementById('accountMenu');
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';

    var switching = false;

    function setStatus(text) {
        var status = document.getElementById('accountMenuStatus');
        if (!status) return;
        status.hidden = !text;
        status.textContent = text || '';
    }

    function switchAccount(button) {
        if (switching) return;
        if (button.getAttribute('aria-current') === 'true') {
            root.open = false;
            return;
        }
        var accountId = button.getAttribute('data-account-id');
        if (!accountId) return;

        switching = true;
        button.disabled = true;
        setStatus('Switching...');

        fetch('/accounts/switch/?id=' + encodeURIComponent(accountId), {
            method: 'POST',
            headers: { 'Accept': 'application/json' }
        }).then(function (response) {
            return response.json().catch(function () {
                return {};
            }).then(function (data) {
                return { ok: response.ok, data: data };
            });
        }).then(function (result) {
            if (result.ok && result.data && result.data.status === 'switched') {
                window.location.reload();
                return;
            }
            switching = false;
            button.disabled = false;
            setStatus((result.data && result.data.error) || 'Could not switch account');
        }).catch(function () {
            switching = false;
            button.disabled = false;
            setStatus('Could not switch account');
        });
    }

    root.addEventListener('click', function (event) {
        var button = event.target.closest('button[data-account-id]');
        if (!button || !root.contains(button)) return;
        event.preventDefault();
        switchAccount(button);
    });

    document.addEventListener('click', function (event) {
        if (!root.open || root.contains(event.target)) return;
        root.open = false;
    });

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape' || !root.open) return;
        root.open = false;
        var toggle = root.querySelector('.account-menu-toggle');
        if (toggle) toggle.focus();
    });
})();
