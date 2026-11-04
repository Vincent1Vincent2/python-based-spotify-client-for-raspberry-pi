from django.urls import path

from . import views

urlpatterns = [
    path("save/", views.save_track_view, name="track_actions_save"),
    path("playlist/", views.add_to_playlist_view, name="track_actions_playlist"),
]
