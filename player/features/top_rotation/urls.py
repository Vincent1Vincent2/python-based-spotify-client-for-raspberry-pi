from django.urls import path

from . import views

urlpatterns = [
    path("rotation/tracks/", views.top_tracks, name="rotation_tracks"),
    path("rotation/artists/", views.top_artists, name="rotation_artists"),
]
