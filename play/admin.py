from django.contrib import admin

from .models import (AsyncBattle, BattleRecord, InventoryItem, LadderTeam, Node,
                     OwnedBeast, Snapshot, TradeListing, TradeOffer, Wallet)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    """Find a player by name/email and flip Premium. Leave billing_provider empty for a comp; Stripe
    and Play set it themselves and the exclusivity checks key off it."""
    list_display = ("user", "subscribed", "subscription_status", "billing_provider", "shards", "cores")
    list_filter = ("subscribed", "billing_provider", "subscription_status")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("stripe_customer_id", "play_purchase_token", "play_product_id", "play_base_plan",
                       "play_expires_at", "play_auto_renewing", "play_linked_at", "play_obfuscated_id")
    raw_id_fields = ("user",)


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "kind", "last_seen_at", "heartbeat_sec")
    search_fields = ("name", "user__username", "user__email")
    list_filter = ("kind",)
    raw_id_fields = ("user",)


admin.site.register([InventoryItem, Snapshot, OwnedBeast, TradeListing, TradeOffer, BattleRecord,
                     LadderTeam, AsyncBattle])
