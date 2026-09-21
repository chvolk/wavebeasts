from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("download/", views.download, name="download"),
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
    path("docs/", views.docs, name="docs"),
    path("download/wavebeast-node.py", views.node_client, name="node_client"),
    path("download/app.apk", views.app_apk, name="app_apk"),
    path("api/app/version", views.app_version, name="app_version"),
    path("signup/", views.signup, name="signup"),
    path("sign-in/", views.sign_in, name="sign_in"),
    path("sign-up/", views.sign_up, name="sign_up"),
    path("auth/clerk", views.auth_clerk, name="auth_clerk"),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("billing/", views.billing, name="billing"),
    path("billing/checkout", views.checkout, name="checkout"),
    path("billing/portal", views.billing_portal, name="billing_portal"),
    path("webhooks/stripe", views.stripe_webhook, name="stripe_webhook"),
    path("me/", views.dashboard, name="dashboard"),
    path("beast/<int:beast_id>/catch", views.catch, name="catch"),
    path("sprite/<int:beast_id>.png", views.sprite, name="sprite"),

    path("nodes/", views.nodes, name="nodes"),
    path("nodes/new", views.node_create, name="node_create"),
    path("nodes/app-token", views.node_app_token, name="node_app_token"),
    path("nodes/<int:node_id>/boost", views.node_boost, name="node_boost"),
    path("nodes/<int:node_id>/delete", views.node_delete, name="node_delete"),

    path("trade/", views.trade, name="trade"),
    path("trade/list", views.trade_list_beast, name="trade_list_beast"),
    path("trade/<int:listing_id>/unlist", views.trade_unlist, name="trade_unlist"),
    path("trade/<int:listing_id>/offer", views.trade_offer, name="trade_offer"),
    path("trade/offer/<int:offer_id>/accept", views.trade_accept, name="trade_accept"),
    path("trade/offer/<int:offer_id>/decline", views.trade_decline, name="trade_decline"),
    path("trade/offer/<int:offer_id>/withdraw", views.trade_withdraw, name="trade_withdraw"),

    path("battle/", views.battle, name="battle"),
    path("battle/team", views.set_team, name="set_team"),
    path("battle/fight", views.battle_fight, name="battle_fight"),
    path("ladder/enter", views.ladder_enter, name="ladder_enter"),
    path("ladder/run", views.ladder_run, name="ladder_run"),

    path("api/snapshot", views.api_snapshot, name="api_snapshot"),
    path("api/import", views.api_import, name="api_import"),

    path("api/beasts", views.api_beasts, name="api_beasts"),
    path("api/catch", views.api_catch, name="api_catch"),
    path("api/shop", views.api_shop, name="api_shop"),
    path("api/buy", views.api_buy, name="api_buy"),
    path("api/sync", views.api_sync, name="api_sync"),
    path("api/release", views.api_release, name="api_release"),
    path("api/buddy", views.api_buddy, name="api_buddy"),
    path("api/buddy/slot", views.api_buddy_slot, name="api_buddy_slot"),
    path("api/buddy/care", views.api_buddy_care, name="api_buddy_care"),
]
