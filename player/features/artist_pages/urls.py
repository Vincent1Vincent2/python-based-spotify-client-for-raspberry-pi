from django.urls import path

from . import views

app_name = 'artist_pages'

urlpatterns = [
    path('', views.artist_page, name='artist_page'),
    path('follow/', views.artist_follow, name='artist_follow'),
    path('<str:artist_id>/', views.artist_page, name='artist_detail'),
]
