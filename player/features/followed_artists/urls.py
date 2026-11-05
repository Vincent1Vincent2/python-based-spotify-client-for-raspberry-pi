from django.urls import path

from . import views

urlpatterns = [
    path("", views.followed_artists_view, name="followed_artists"),
]
