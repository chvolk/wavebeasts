"""Comp (or revoke) Premium for an account by username or email, without a payment provider.

    manage.py grant_premium cvolk            # Premium on, provider "" (comped)
    manage.py grant_premium cvolk --revoke   # back to Free

Accounts billed through Stripe or Google Play are refused so a comp never masks a real subscription.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from play.models import Wallet


class Command(BaseCommand):
    help = "Grant or revoke comped Premium for a user (by username or email)."

    def add_arguments(self, parser):
        parser.add_argument("who", help="username or email")
        parser.add_argument("--revoke", action="store_true", help="remove comped Premium instead")

    def handle(self, who, revoke, **options):
        User = get_user_model()
        user = User.objects.filter(Q(username__iexact=who) | Q(email__iexact=who)).first()
        if user is None:
            raise CommandError(f"no user matching {who!r}")
        wallet, _ = Wallet.objects.get_or_create(user=user)
        if wallet.billing_provider in ("stripe", "play"):
            raise CommandError(f"{user.username} is billed via {wallet.billing_provider}; manage it there instead")
        wallet.subscribed = not revoke
        wallet.subscription_status = "" if revoke else "active"
        wallet.billing_provider = ""
        wallet.save(update_fields=["subscribed", "subscription_status", "billing_provider"])
        self.stdout.write(f"{user.username}: Premium {'revoked' if revoke else 'granted'} (comped)")
