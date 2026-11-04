"""Sleep timer choices shown on the player."""

MINUTE_CHOICES = (15, 30, 45, 60)
END_OF_TRACK = "end_of_track"
END_OF_TRACK_LABEL = "End of track"


def minute_choices():
    """Return the selectable sleep-timer lengths, in minutes."""
    return MINUTE_CHOICES


def timer_options():
    """Return the minute buttons, then End of track, for the player UI."""
    options = [
        {
            "kind": "minutes",
            "minutes": minutes,
            "label": f"{minutes} minutes",
        }
        for minutes in MINUTE_CHOICES
    ]
    options.append({
        "kind": END_OF_TRACK,
        "minutes": None,
        "label": END_OF_TRACK_LABEL,
    })
    return options
