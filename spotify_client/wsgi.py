"""
WSGI config for spotify_client project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spotify_client.settings')

application = get_wsgi_application()

