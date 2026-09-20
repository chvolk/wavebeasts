from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("download/", views.download, name="download"),
    path("signup/", views.signup, name="signup"),
    path("me/", views.dashboard, name="dashboard"),
    path("beast/<int:beast_id>/catch", views.catch, name="catch"),
    path("sprite/<int:beast_id>.png", views.sprite, name="sprite"),

    path("nodes/", views.nodes, name="nodes"),
    path("nodes/new", views.node_create, name="node_create"),
    path("nodes/<int:node_id>/boost", views.node_boost, name="node_boost"),
    path("nodes/<int:node_id>/delete", views.node_delete, name="node_delete"),

    path("trade/", views.trade, name="trade"),
    path("trade/list", views.trade_list_beast, name="trade_list_beast"),
    path("trade/<int:listing_id>/unlist", views.trade_unlist, name="trade_unlist"),
    path("trade/<int:listing_id>/offer", views.trade_offer, name="trade_offer"),
    path("trade/offer/<int:offer_id>/accept", views.trade_accept, name="trade_accept"),
    path("trade/offer/<int:offer_id>/decline", views.trade_decline, name="trade_decline"),

    path("battle/", views.battle, name="battle"),
    path("battle/team", views.set_team, name="set_team"),
    path("battle/fight", views.battle_fight, name="battle_fight"),

    path("api/snapshot", views.api_snapshot, name="api_snapshot"),
]
