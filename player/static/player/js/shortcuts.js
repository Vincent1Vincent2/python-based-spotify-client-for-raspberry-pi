/*
 * Keyboard shortcuts for the player page.
 * Does not call Spotify. Playback goes through togglePlayback, nextTrack,
 * and previousTrack when those page functions exist.
 *
 * Mirrors player/features/keyboard_shortcuts/keys.py
 * action_for_key(key, shift, ctrl, alt, meta):
 *   ctrl or alt or meta -> no action
 *   shift and key "/" -> show_help
 *   otherwise KEY_ACTIONS[key]
 * is_typing_target: input, textarea, or contenteditable -> ignore,
 *   and do not preventDefault.
 *
 * KEY_MAP_START
 * " " -> toggle_playback
 * "k" -> toggle_playback
 * "K" -> toggle_playback
 * "ArrowRight" -> next_track
 * "ArrowLeft" -> previous_track
 * "/" -> focus_search
 * "?" -> show_help
 * KEY_MAP_END
 */
(function () {
    "use strict";

    var KEY_ACTIONS = {
        " ": "toggle_playback",
        "k": "toggle_playback",
        "K": "toggle_playback",
        "ArrowRight": "next_track",
        "ArrowLeft": "previous_track",
        "/": "focus_search",
        "?": "show_help"
    };

    var HELP_ROWS = [
        { keys: ["Space"], label: "Play or pause" },
        { keys: ["K"], label: "Play or pause" },
        { keys: ["\u2192"], label: "Next track" },
        { keys: ["\u2190"], label: "Previous track" },
        { keys: ["/"], label: "Focus search" },
        { keys: ["Shift", "/"], label: "Show or hide this help" }
    ];

    var HELP_CSS = [
        ".shortcut-help {",
        "  position: fixed;",
        "  inset: 0;",
        "  z-index: 11000;",
        "  display: flex;",
        "  align-items: center;",
        "  justify-content: center;",
        "  padding: 20px;",
        "  background: rgba(26, 26, 26, 0.45);",
        "}",
        ".shortcut-help[hidden] { display: none; }",
        ".shortcut-help-panel {",
        "  width: 100%;",
        "  max-width: 360px;",
        "  background: #fff;",
        "  color: #1a1a1a;",
        "  border: 2px solid #1a1a1a;",
        "  padding: 16px 18px 18px;",
        "}",
        ".shortcut-help-panel h2 {",
        "  margin: 0 0 12px;",
        "  font-size: 1.05rem;",
        "  font-weight: 600;",
        "}",
        ".shortcut-help-list { list-style: none; margin: 0; padding: 0; }",
        ".shortcut-help-list li {",
        "  display: flex;",
        "  justify-content: space-between;",
        "  align-items: baseline;",
        "  gap: 12px;",
        "  padding: 8px 0;",
        "  border-top: 2px solid #1a1a1a;",
        "  font-size: 0.95rem;",
        "}",
        ".shortcut-help-keys {",
        "  display: inline-flex;",
        "  align-items: center;",
        "  gap: 6px;",
        "  white-space: nowrap;",
        "}",
        ".shortcut-help kbd {",
        "  display: inline-block;",
        "  min-width: 1.6em;",
        "  padding: 2px 6px;",
        "  border: 2px solid #1a1a1a;",
        "  background: #f5f5f5;",
        "  font-family: inherit;",
        "  font-size: 0.85rem;",
        "  line-height: 1.3;",
        "  text-align: center;",
        "}",
        ".shortcut-help-label { text-align: right; }",
        ".shortcut-help-note { margin: 12px 0 0; font-size: 0.8rem; }",
        ".shortcut-help-close { margin-top: 14px; padding: 8px 14px; }"
    ].join("\n");

    function actionForKey(key, shift, ctrl, alt, meta) {
        if (typeof key !== "string" || ctrl || alt || meta) {
            return null;
        }
        if (shift && key === "/") {
            return "show_help";
        }
        if (Object.prototype.hasOwnProperty.call(KEY_ACTIONS, key)) {
            return KEY_ACTIONS[key];
        }
        return null;
    }

    function isTypingTarget(target) {
        var element = target;
        if (element && element.nodeType === 3) {
            element = element.parentElement;
        }
        if (!element || element.nodeType !== 1) {
            return false;
        }
        if (element.isContentEditable) {
            return true;
        }
        var tag = element.tagName;
        return tag === "INPUT" || tag === "TEXTAREA";
    }

    function focusSearch() {
        var input = document.getElementById("searchInput");
        if (input && typeof input.focus === "function") {
            input.focus();
        }
    }

    function ensureHelpStyle() {
        if (document.getElementById("shortcutHelpStyle")) {
            return;
        }
        var style = document.createElement("style");
        style.id = "shortcutHelpStyle";
        style.textContent = HELP_CSS;
        document.head.appendChild(style);
    }

    function appendKeys(parent, keys) {
        keys.forEach(function (key, index) {
            if (index > 0) {
                var plus = document.createElement("span");
                plus.textContent = "+";
                parent.appendChild(plus);
            }
            var kbd = document.createElement("kbd");
            kbd.textContent = key;
            parent.appendChild(kbd);
        });
    }

    function ensureHelp() {
        var existing = document.getElementById("shortcutHelp");
        if (existing) {
            return existing;
        }
        ensureHelpStyle();

        var overlay = document.createElement("div");
        overlay.id = "shortcutHelp";
        overlay.className = "shortcut-help";
        overlay.setAttribute("hidden", "");
        overlay.setAttribute("aria-hidden", "true");

        var panel = document.createElement("div");
        panel.className = "shortcut-help-panel";
        panel.setAttribute("role", "dialog");
        panel.setAttribute("aria-modal", "true");
        panel.setAttribute("aria-labelledby", "shortcutHelpTitle");

        var title = document.createElement("h2");
        title.id = "shortcutHelpTitle";
        title.textContent = "Keyboard shortcuts";
        panel.appendChild(title);

        var list = document.createElement("ul");
        list.className = "shortcut-help-list";
        HELP_ROWS.forEach(function (row) {
            var item = document.createElement("li");
            var keys = document.createElement("span");
            keys.className = "shortcut-help-keys";
            appendKeys(keys, row.keys);
            var label = document.createElement("span");
            label.className = "shortcut-help-label";
            label.textContent = row.label;
            item.appendChild(keys);
            item.appendChild(label);
            list.appendChild(item);
        });
        panel.appendChild(list);

        var note = document.createElement("p");
        note.className = "shortcut-help-note";
        note.textContent = "Shortcuts stay off while a text field is focused. Press Shift and / again to close.";
        panel.appendChild(note);

        var close = document.createElement("button");
        close.type = "button";
        close.className = "btn shortcut-help-close";
        close.textContent = "Close";
        close.addEventListener("click", function () {
            setHelpOpen(false);
        });
        panel.appendChild(close);

        overlay.appendChild(panel);
        overlay.addEventListener("click", function (event) {
            if (event.target === overlay) {
                setHelpOpen(false);
            }
        });
        document.body.appendChild(overlay);
        return overlay;
    }

    function setHelpOpen(open) {
        var overlay = ensureHelp();
        if (open) {
            overlay.removeAttribute("hidden");
            overlay.setAttribute("aria-hidden", "false");
        } else {
            overlay.setAttribute("hidden", "");
            overlay.setAttribute("aria-hidden", "true");
        }
    }

    function helpIsOpen() {
        var overlay = document.getElementById("shortcutHelp");
        return !!(overlay && !overlay.hasAttribute("hidden"));
    }

    function toggleHelp() {
        setHelpOpen(!helpIsOpen());
    }

    var ACTIONS = {
        toggle_playback: function () {
            if (typeof togglePlayback === "function") {
                togglePlayback();
            }
        },
        next_track: function () {
            if (typeof nextTrack === "function") {
                nextTrack();
            }
        },
        previous_track: function () {
            if (typeof previousTrack === "function") {
                previousTrack();
            }
        },
        focus_search: focusSearch,
        show_help: toggleHelp
    };

    function onKeyDown(event) {
        if (event.repeat || event.isComposing) {
            return;
        }
        if (isTypingTarget(event.target)) {
            return;
        }
        var action = actionForKey(
            event.key,
            event.shiftKey,
            event.ctrlKey,
            event.altKey,
            event.metaKey
        );
        if (!action || typeof ACTIONS[action] !== "function") {
            return;
        }
        event.preventDefault();
        ACTIONS[action]();
    }

    document.addEventListener("keydown", onKeyDown);
})();
