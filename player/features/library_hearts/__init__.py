def load_tests(loader, tests, pattern):
    """Let `manage.py test player.features.library_hearts` find tests.py."""
    from . import tests as library_heart_tests
    return loader.loadTestsFromModule(library_heart_tests)
