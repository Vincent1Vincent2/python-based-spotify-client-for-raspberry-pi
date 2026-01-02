"""
ASGI config for spotify_client project.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spotify_client.settings')

application = get_asgi_application()

