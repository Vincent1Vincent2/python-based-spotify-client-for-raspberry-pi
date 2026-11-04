from django.urls import path

from . import views

urlpatterns = [
    path('library/contains/', views.contains_view, name='library_contains'),
    path('library/items/', views.items_view, name='library_items'),
]
