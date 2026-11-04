"""Private playlist editing. Tests live in tests.py."""


def load_tests(loader, tests, pattern):
    """So `manage.py test player.features.playlist_editor` finds tests.py."""
    from . import tests as editor_tests

    return loader.loadTestsFromModule(editor_tests, pattern=pattern)
