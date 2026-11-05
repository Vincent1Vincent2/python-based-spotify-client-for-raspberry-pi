from django.urls import path

from . import views

urlpatterns = [
    path("recently-played/", views.recently_played_view, name="recently_played"),
    path(
        "recently-played/play/",
        views.play_recently_played_view,
        name="play_recently_played",
    ),
]
