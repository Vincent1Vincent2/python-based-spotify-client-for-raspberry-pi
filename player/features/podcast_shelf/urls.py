from django.urls import path

from . import views

urlpatterns = [
    path('shows/', views.shows, name='shows'),
    path('shows/detail/', views.show_detail_view, name='show_detail'),
    path('shows/save/', views.save_show_view, name='save_show'),
    path('shows/remove/', views.remove_show_view, name='remove_show'),
    path('shows/play-episode/', views.play_episode_view, name='play_episode'),
]
