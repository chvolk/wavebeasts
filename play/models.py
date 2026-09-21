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
    # Free tier by default. Paid unlocks the web-service layer: multi-node, trading, battles, async
    # ladder, and the Buddy system. (Existing accounts were grandfathered to paid - see migration 0009.)
    subscribed = models.BooleanField(default=False)  # driven by the Stripe subscription status below
    stripe_customer_id = models.CharField(max_length=64, blank=True, default="")
    subscription_status = models.CharField(max_length=32, blank=True, default="")  # active/trialing/past_due/canceled/...
    onboarded = models.BooleanField(default=False)
    last_sync = models.DateTimeField(null=True, blank=True)  # once-per-day standardize-old-beasts run

    def __str__(self):
        return f"{self.user} wallet"


class InventoryItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="items")
    item_id = models.CharField(max_length=64)
    qty = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "item_id")


class Buddy(models.Model):
    """The one slotted companion on an account (paid feature). You carry it in a registered app. Care
    raises its vitals, mood and relationship; while carried it occasionally reports
    away-events (resources / XP from off-screen scraps). All state is server-authoritative - the client
    only ever calls actions and displays what the site returns - so none of it is cheatable."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="buddy")
    beast = models.ForeignKey("OwnedBeast", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    carrier = models.ForeignKey("Node", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")  # which device carries it now (UX/anchor)
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
    It need not run the full engine - just sensors -> ScanBundle -> POST /api/snapshot with its token."""
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
    """Another player's offer for a listing: up to 3 of their beasts PLUS a sweetener of shards/cores.
    Offered currency is escrowed (deducted from the offerer's wallet) when the offer is made and refunded
    if it's declined or withdrawn, so it can't be double-spent while the offer sits pending."""
    STATUS = [("pending", "pending"), ("accepted", "accepted"), ("declined", "declined")]
    MAX_BEASTS = 3
    listing = models.ForeignKey(TradeListing, on_delete=models.CASCADE, related_name="offers")
    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offers")
    # legacy single-beast pointer kept nullable for old rows; new offers use offered_beasts (M2M, up to 3).
    offered_beast = models.ForeignKey(OwnedBeast, null=True, blank=True, on_delete=models.CASCADE, related_name="offered_in")
    offered_beasts = models.ManyToManyField(OwnedBeast, blank=True, related_name="offered_in_set")
    offered_shards = models.IntegerField(default=0)
    offered_cores = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS, default="pending")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def beasts(self):
        """All beasts in this offer (new M2M, falling back to the legacy single pointer)."""
        rows = list(self.offered_beasts.all())
        if not rows and self.offered_beast_id:
            rows = [self.offered_beast]
        return rows


class LadderTeam(models.Model):
    """A player's submitted async-PvP team: a frozen snapshot of up to 3 fighters + their rating, so it
    can be battled by others even while the player is offline."""
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
