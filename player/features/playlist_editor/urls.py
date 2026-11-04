from django.urls import path

from . import views

urlpatterns = [
    path("playlists/", views.playlists_view, name="playlist_editor_playlists"),
    path("create/", views.create_view, name="playlist_editor_create"),
    path("<str:playlist_id>/", views.detail_view, name="playlist_editor_detail"),
    path("<str:playlist_id>/details/", views.update_view, name="playlist_editor_update"),
    path("<str:playlist_id>/library/", views.remove_library_view, name="playlist_editor_remove_library"),
    path("<str:playlist_id>/items/add/", views.add_view, name="playlist_editor_add"),
    path("<str:playlist_id>/items/remove/", views.remove_item_view, name="playlist_editor_remove_item"),
    path("<str:playlist_id>/items/move/", views.move_view, name="playlist_editor_move"),
]
