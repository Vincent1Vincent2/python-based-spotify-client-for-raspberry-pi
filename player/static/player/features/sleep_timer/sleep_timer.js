(function () {
    const root = document.getElementById('sleep-timer');
    if (!root) {
        return;
    }

    const remainingEl = document.getElementById('sleep-timer-remaining');
    const cancelBtn = document.getElementById('sleep-timer-cancel');
    const MINUTE_MS = 60 * 1000;
    let timerId = null;
    let alarmId = null;
    let deadline = null;
    let mode = null;
    let finished = false;

    function formatRemaining(ms) {
        const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        return minutes + ':' + String(seconds).padStart(2, '0');
    }

    // End of track reads the progress bar already on the page. It does not
    // ask Spotify for another playback position.
    function trackRemainingMs() {
        try {
            if (typeof progressDurationMs === 'undefined' || typeof progressCurrentMs === 'undefined') {
                return null;
            }
        } catch (error) {
            return null;
        }
        const duration = Number(progressDurationMs);
        const current = Number(progressCurrentMs);
        if (!Number.isFinite(duration) || duration <= 0) {
            return null;
        }
        const position = Number.isFinite(current) ? current : 0;
        return Math.max(0, duration - position);
    }

    function remainingMs() {
        if (mode === 'end') {
            return trackRemainingMs();
        }
        if (deadline === null) {
            return null;
        }
        return Math.max(0, deadline - Date.now());
    }

    function setPressed(button) {
        const choices = root.querySelectorAll('.sleep-timer-choice');
        for (let i = 0; i < choices.length; i++) {
            const on = choices[i] === button;
            choices[i].classList.toggle('is-on', on);
            choices[i].setAttribute('aria-pressed', on ? 'true' : 'false');
        }
    }

    function showRemaining(text) {
        if (!remainingEl) {
            return;
        }
        remainingEl.hidden = false;
        remainingEl.textContent = text;
    }

    function clearTimer() {
        if (timerId !== null) {
            clearInterval(timerId);
            timerId = null;
        }
        if (alarmId !== null) {
            clearTimeout(alarmId);
            alarmId = null;
        }
        deadline = null;
        mode = null;
        finished = false;
        setPressed(null);
        root.classList.remove('is-active');
        if (cancelBtn) {
            cancelBtn.hidden = true;
        }
        if (remainingEl) {
            remainingEl.textContent = '';
            remainingEl.hidden = true;
        }
    }

    function pausePlayback() {
        // Same split as the play button: the Web Playback SDK when that
        // device is selected, otherwise the existing POST /pause/ route.
        if (typeof useWebPlayer !== 'undefined' && useWebPlayer && typeof player !== 'undefined' && player && typeof player.pause === 'function') {
            Promise.resolve(player.pause()).catch(function () {});
            return;
        }
        fetch('/pause/', { method: 'POST' })
            .then(function (response) { return response.json(); })
            .then(function (data) {
                if (data && data.status && typeof isPlaying !== 'undefined') {
                    isPlaying = false;
                    if (typeof updatePlayButton === 'function') {
                        updatePlayButton();
                    }
                }
            })
            .catch(function () {});
    }

    function finish() {
        if (finished) {
            return;
        }
        finished = true;
        if (timerId !== null) {
            clearInterval(timerId);
            timerId = null;
        }
        if (alarmId !== null) {
            clearTimeout(alarmId);
            alarmId = null;
        }
        deadline = null;
        mode = null;
        setPressed(null);
        root.classList.remove('is-active');
        if (cancelBtn) {
            cancelBtn.hidden = true;
        }
        showRemaining(formatRemaining(0));
        pausePlayback();
    }

    function tick() {
        const left = remainingMs();
        if (left === null) {
            clearTimer();
            return;
        }
        if (left <= 0) {
            finish();
            return;
        }
        showRemaining(formatRemaining(left));
    }

    function start(nextMode, button, durationMs) {
        clearTimer();
        mode = nextMode;
        if (nextMode === 'minutes') {
            deadline = Date.now() + durationMs;
        }
        setPressed(button);
        root.classList.add('is-active');
        if (cancelBtn) {
            cancelBtn.hidden = false;
        }
        tick();
        if (mode === null) {
            return;
        }
        timerId = setInterval(tick, 250);
        if (nextMode === 'minutes') {
            alarmId = setTimeout(finish, durationMs);
        }
    }

    root.addEventListener('click', function (event) {
        const choice = event.target.closest('.sleep-timer-choice');
        if (!choice || !root.contains(choice)) {
            return;
        }
        if (choice.hasAttribute('data-sleep-end')) {
            const left = trackRemainingMs();
            if (left === null) {
                clearTimer();
                showRemaining('No track playing');
                return;
            }
            start('end', choice, left);
            return;
        }
        const minutes = Number(choice.getAttribute('data-sleep-minutes'));
        if (!Number.isFinite(minutes) || minutes <= 0) {
            return;
        }
        start('minutes', choice, minutes * MINUTE_MS);
    });

    if (cancelBtn) {
        cancelBtn.addEventListener('click', function (event) {
            event.stopPropagation();
            clearTimer();
        });
    }
})();
