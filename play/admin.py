from django.contrib import admin

from .models import (AsyncBattle, BattleRecord, InventoryItem, LadderTeam, Node,
                     OwnedBeast, Snapshot, TradeListing, TradeOffer, Wallet)

admin.site.register([Wallet, InventoryItem, Node, Snapshot, OwnedBeast,
                     TradeListing, TradeOffer, BattleRecord, LadderTeam, AsyncBattle])
