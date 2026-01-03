from django.urls import path
from . import views

urlpatterns = [
    path('', views.setup_view, name='setup'),
    path('done/', views.setup_done_view, name='done'),
]

