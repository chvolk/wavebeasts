from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("signup/", views.signup, name="signup"),
    path("me/", views.dashboard, name="dashboard"),
    path("nodes/new", views.node_create, name="node_create"),
    path("nodes/<int:node_id>/boost", views.node_boost, name="node_boost"),
    path("beast/<int:beast_id>/catch", views.catch, name="catch"),
    path("sprite/<int:beast_id>.png", views.sprite, name="sprite"),
    path("api/snapshot", views.api_snapshot, name="api_snapshot"),
]
