"""
URL configuration for spotify_client project.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('setup/', include('wizard.urls')),  # Wizard must come before player URLs - matches /setup/ and /setup/done/
    path('', include('player.urls')),  # Player URLs last - matches everything else
]

