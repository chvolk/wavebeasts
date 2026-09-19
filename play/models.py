import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def gen_token():
    return secrets.token_urlsafe(24)


class Wallet(models.Model):
    """Per-account soft/hard currency."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet")
    shards = models.IntegerField(default=50)
    cores = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user} wallet"


class InventoryItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="items")
    item_id = models.CharField(max_length=64)
    qty = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "item_id")


class Node(models.Model):
    """A listener node the player signs in: it uploads rate-limited sensor SNAPSHOTS to this account.
    It need not run the full engine — just sensors -> ScanBundle -> POST /api/snapshot with its token."""
    KIND = [("phone", "phone"), ("edi", "edi"), ("bishop", "bishop"), ("pi", "pi"), ("pc", "pc")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="nodes")
    name = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=KIND, default="pc")
    token = models.CharField(max_length=64, unique=True, default=gen_token)
    rate_limit_sec = models.IntegerField(default=300)  # base snapshot cadence (anti-spam)
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
    species_id = models.CharField(max_length=32)
    id_version = models.IntegerField(default=1)
    name = models.CharField(max_length=64)
    rarity = models.CharField(max_length=16)
    shiny = models.BooleanField(default=False)
    level = models.IntegerField(default=1)
    status = models.CharField(max_length=8, choices=STATUS, default="wild")
    species_json = models.JSONField()
    individual_json = models.JSONField()
    caught_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-caught_at"]
