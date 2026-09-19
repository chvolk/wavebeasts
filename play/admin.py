from django.contrib import admin

from .models import InventoryItem, Node, OwnedBeast, Snapshot, Wallet

admin.site.register([Wallet, InventoryItem, Node, Snapshot, OwnedBeast])
