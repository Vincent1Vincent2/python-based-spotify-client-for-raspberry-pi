"""Save a track, add it to a playlist, or open its album from the track menu."""


def load_tests(loader, tests, pattern):
    """Let `manage.py test player.features.track_actions` find tests.py."""
    from . import tests as feature_tests

    tests.addTests(loader.loadTestsFromModule(feature_tests))
    return tests
