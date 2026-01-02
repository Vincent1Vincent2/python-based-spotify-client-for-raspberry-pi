#!/usr/bin/env python
"""
Generate a Django secret key.
"""
try:
    from django.core.management.utils import get_random_secret_key
    print(get_random_secret_key())
except ImportError:
    import secrets
    print(secrets.token_urlsafe(50))

