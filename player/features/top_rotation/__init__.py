"""Heavy rotation: top tracks and top artists, one Spotify read each."""


def load_tests(loader, tests, pattern):
    """Expose feature tests at ``player.features.top_rotation``."""
    from . import tests as rotation_tests

    tests.addTests(loader.loadTestsFromModule(rotation_tests, pattern=pattern))
    return tests
