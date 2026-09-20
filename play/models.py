import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def gen_token():
    return secrets.token_urlsafe(24)


class Wallet(models.Model):
    """Per-account soft/hard currency + the chosen battle team (up to 3 owned beast ids)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet")
    shards = models.IntegerField(default=50)
    cores = models.IntegerField(default=0)
    team_ids = models.JSONField(default=list)
    subscribed = models.BooleanField(default=True)  # faked-on for now; gates worldwide upload/features

    def __str__(self):
        return f"{self.user} wallet"


class InventoryItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="items")
    item_id = models.CharField(max_length=64)
    qty = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "item_id")


class Buddy(models.Model):
    """The one slotted companion on an account (paid feature). You carry it in a registered app (Omnitool
    is one). Care raises its vitals, mood and relationship; while carried it occasionally reports
    away-events (resources / XP from off-screen scraps). All state is server-authoritative — the client
    only ever calls actions and displays what the site returns — so none of it is cheatable."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="buddy")
    beast = models.ForeignKey("OwnedBeast", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    mood = models.IntegerField(default=60)          # 0-100
    relationship = models.IntegerField(default=0)   # 0-100; 100 = "loves you"
    hunger = models.IntegerField(default=60)        # vitals; higher is better, decay over time
    energy = models.IntegerField(default=70)
    cleanliness = models.IntegerField(default=80)
    last_care = models.JSONField(default=dict)      # {action: iso8601} for per-action cooldowns
    last_event_at = models.DateTimeField(null=True, blank=True)
    refreshed_at = models.DateTimeField(default=timezone.now)  # anchor for vital decay
    slotted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user} buddy"


class Node(models.Model):
    """A listener node the player signs in: it uploads rate-limited sensor SNAPSHOTS to this account.
    It need not run the full engine — just sensors -> ScanBundle -> POST /api/snapshot with its token."""
    KIND = [("phone", "phone"), ("edi", "edi"), ("bishop", "bishop"), ("pi", "pi"), ("pc", "pc")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="nodes")
    name = models.CharField(max_length=256)  # free text, emoji allowed
    kind = models.CharField(max_length=16, default="node")
    token = models.CharField(max_length=64, unique=True, default=gen_token)
    rate_limit_sec = models.IntegerField(default=60)  # base snapshot cadence (anti-spam); ~once a minute
    boost_interval_sec = models.IntegerField(default=20)  # cadence while boosted
    boosted_until = models.DateTimeField(null=True, blank=True)
    last_snapshot_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    def min_interval(self):
        if self.boosted_until and self.boosted_until > timezone.now():
            return self.boost_interval_sec
        return self.rate_limit_sec

    def seconds_until_ready(self):
        if not self.last_snapshot_at:
            return 0
        elapsed = (timezone.now() - self.last_snapshot_at).total_seconds()
        return max(0, int(self.min_interval() - elapsed))

    def __str__(self):
        return f"{self.name} ({self.kind})"


class Snapshot(models.Model):
    """Audit log of accepted snapshots."""
    node = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="snapshots")
    at = models.DateTimeField(auto_now_add=True)
    outcome = models.CharField(max_length=16)
    entropy = models.FloatField(default=0)
    detail = models.CharField(max_length=200, blank=True)


class OwnedBeast(models.Model):
    """A beast on the account. status 'wild' = seen via a node, not yet caught; 'owned' = caught."""
    STATUS = [("wild", "wild"), ("owned", "owned")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="beasts")
    node = models.ForeignKey(Node, null=True, blank=True, on_delete=models.SET_NULL)
    source_id = models.CharField(max_length=64, blank=True, default="")  # local individual id, for dedupe on upload
    species_id = models.CharField(max_length=32)
    id_version = models.IntegerField(default=1)
    name = models.CharField(max_length=64)
    rarity = models.CharField(max_length=16)
    shiny = models.BooleanField(default=False)
    level = models.IntegerField(default=1)
    status = models.CharField(max_length=8, choices=STATUS, default="wild")
    # verified = the site generated this beast itself (server-authoritative roll) from a submitted scan.
    # Only verified beasts can be traded or laddered; imported (claimed-stats) beasts are collection-only.
    verified = models.BooleanField(default=False)
    species_json = models.JSONField()
    individual_json = models.JSONField()
    caught_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-caught_at"]

    @property
    def types_display(self):
        return " / ".join((self.species_json or {}).get("types", []))

    @property
    def tribe(self):
        return (self.species_json or {}).get("tribe", "")


class TradeListing(models.Model):
    """An owned beast a player has put up for trade on the market."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listings")
    beast = models.OneToOneField(OwnedBeast, on_delete=models.CASCADE, related_name="listing")
    note = models.CharField(max_length=200, blank=True)
    is_open = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]


class TradeOffer(models.Model):
    """Another player's offer of one of their beasts for a listing."""
    STATUS = [("pending", "pending"), ("accepted", "accepted"), ("declined", "declined")]
    listing = models.ForeignKey(TradeListing, on_delete=models.CASCADE, related_name="offers")
    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offers")
    offered_beast = models.ForeignKey(OwnedBeast, on_delete=models.CASCADE, related_name="offered_in")
    status = models.CharField(max_length=10, choices=STATUS, default="pending")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]


class LadderTeam(models.Model):
    """A player's submitted async-PvP team: a frozen snapshot of up to 3 fighters + their rating, so it
    can be battled by others even while the player is offline (Super Auto Pets style)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ladder")
    fighters = models.JSONField(default=list)  # [{species, individual}, ...]
    mmr = models.IntegerField(default=1000)
    wins = models.IntegerField(default=0)
    losses = models.IntegerField(default=0)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-mmr"]


class AsyncBattle(models.Model):
    """A resolved ladder match from one player's perspective (both sides get a row)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ladder_battles")
    opponent = models.CharField(max_length=64)
    result = models.CharField(max_length=8)  # win|loss|draw
    mmr_delta = models.IntegerField(default=0)
    turns = models.IntegerField(default=0)
    seen = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]


class BattleRecord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="battles")
    opponent = models.CharField(max_length=64)
    result = models.CharField(max_length=8)  # win|loss|draw
    turns = models.IntegerField(default=0)
    reward = models.IntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]
