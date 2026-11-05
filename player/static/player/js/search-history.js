// Recent searches. Cap and dedupe match player/features/search_history/history.py:
// newest first, 8 distinct queries, a repeat moves to the front, blanks ignored.
(function () {
    var STORAGE_KEY = 'spotipi.searchHistory';
    var LIMIT = 8;
    var memory = null;

    function rememberQuery(history, query) {
        var previous = [];
        var source = Array.isArray(history) ? history : [];
        var index;
        for (index = 0; index < source.length; index += 1) {
            var item = source[index];
            if (typeof item !== 'string') {
                continue;
            }
            var text = item.trim();
            if (!text || previous.indexOf(text) !== -1) {
                continue;
            }
            previous.push(text);
        }
        if (typeof query !== 'string') {
            return previous.slice(0, LIMIT);
        }
        var queryText = query.trim();
        if (!queryText) {
            return previous.slice(0, LIMIT);
        }
        previous = previous.filter(function (entry) {
            return entry !== queryText;
        });
        return [queryText].concat(previous).slice(0, LIMIT);
    }

    function readHistory() {
        if (memory !== null) {
            return memory.slice();
        }
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            memory = rememberQuery(raw ? JSON.parse(raw) : [], '');
        } catch (error) {
            memory = [];
        }
        return memory.slice();
    }

    function writeHistory(history) {
        memory = history.slice();
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(memory));
        } catch (error) {
            // Keep the in-memory list when storage is blocked.
        }
    }

    function runSavedQuery(query) {
        var input = document.getElementById('searchInput');
        if (input) {
            input.value = query;
        }
        if (typeof window.searchTracks === 'function') {
            window.searchTracks();
            return;
        }
        if (typeof window.performSearch === 'function') {
            window.performSearch(query);
        }
    }

    function mountElement() {
        var existing = document.getElementById('searchHistory');
        if (existing) {
            return existing;
        }
        var box = document.querySelector('.search-box');
        if (!box || !box.parentNode) {
            return null;
        }
        var created = document.createElement('div');
        created.id = 'searchHistory';
        created.className = 'search-history';
        created.hidden = true;
        box.parentNode.insertBefore(created, box.nextSibling);
        return created;
    }

    function render() {
        var mount = mountElement();
        if (!mount) {
            return;
        }
        var history = readHistory();
        mount.replaceChildren();
        if (!history.length) {
            mount.hidden = true;
            return;
        }
        mount.hidden = false;
        mount.className = 'search-history';
        mount.setAttribute('aria-label', 'Recent searches');

        var list = document.createElement('div');
        list.className = 'search-history-list';
        history.forEach(function (query) {
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'search-history-item';
            button.textContent = query;
            button.title = query;
            button.addEventListener('click', function () {
                runSavedQuery(query);
            });
            list.appendChild(button);
        });

        var clearButton = document.createElement('button');
        clearButton.type = 'button';
        clearButton.className = 'search-history-clear';
        clearButton.id = 'searchHistoryClear';
        clearButton.textContent = 'Clear';
        clearButton.addEventListener('click', function () {
            writeHistory([]);
            render();
        });

        mount.appendChild(list);
        mount.appendChild(clearButton);
    }

    window.recordSearchQuery = function (query) {
        writeHistory(rememberQuery(readHistory(), query));
        render();
    };

    function boot() {
        render();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
