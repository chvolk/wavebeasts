from django.contrib import admin

from .models import (BattleRecord, InventoryItem, Node, OwnedBeast, Snapshot,
                     TradeListing, TradeOffer, Wallet)

admin.site.register([Wallet, InventoryItem, Node, Snapshot, OwnedBeast,
                     TradeListing, TradeOffer, BattleRecord])
