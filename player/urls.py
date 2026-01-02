from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('callback/', views.callback, name='callback'),
    path('token/', views.token, name='token'),
    path('search/', views.search, name='search'),
    path('devices/', views.devices, name='devices'),
    path('transfer/', views.transfer_device, name='transfer'),
    path('select-web-player/', views.select_web_player, name='select_web_player'),
    path('play/', views.play, name='play'),
    path('pause/', views.pause, name='pause'),
    path('next/', views.next_track, name='next'),
    path('previous/', views.previous_track, name='previous'),
    path('queue/', views.queue_track, name='queue'),
    path('playlists/', views.playlists, name='playlists'),
    path('playlist-detail/', views.playlist_detail, name='playlist_detail'),
    path('play-playlist/', views.play_playlist, name='play_playlist'),
    path('albums/', views.albums, name='albums'),
    path('album-detail/', views.album_detail, name='album_detail'),
    path('play-album/', views.play_album, name='play_album'),
    path('saved-tracks/', views.saved_tracks, name='saved_tracks'),
    path('discover/', views.discover, name='discover'),
]

