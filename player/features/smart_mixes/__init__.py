"""Smart mixes: filter saved songs locally and save a private playlist."""


def load_tests(loader, tests, pattern):
    """`manage.py test player.features.smart_mixes` loads tests.py."""
    tests.addTests(loader.loadTestsFromName("player.features.smart_mixes.tests"))
    return tests
