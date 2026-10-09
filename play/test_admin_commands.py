"""Admin bootstrap (ensure_admin) and comped Premium (grant_premium) commands."""
import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import TestCase

from .models import Wallet


class EnsureAdminTests(TestCase):
    def test_skips_without_env(self):
        with patch.dict(os.environ, {"ADMIN_USERNAME": "", "ADMIN_PASSWORD": ""}):
            out = StringIO()
            call_command("ensure_admin", stdout=out)
        self.assertIn("skipping", out.getvalue())
        self.assertFalse(User.objects.filter(is_superuser=True).exists())

    def test_creates_then_rekeys_superuser(self):
        with patch.dict(os.environ, {"ADMIN_USERNAME": "ops", "ADMIN_PASSWORD": "first-pass-123", "ADMIN_EMAIL": "ops@example.test"}):
            call_command("ensure_admin", stdout=StringIO())
        u = User.objects.get(username="ops")
        self.assertTrue(u.is_staff and u.is_superuser and u.check_password("first-pass-123"))
        self.assertEqual(u.email, "ops@example.test")
        with patch.dict(os.environ, {"ADMIN_USERNAME": "ops", "ADMIN_PASSWORD": "second-pass-456"}):
            call_command("ensure_admin", stdout=StringIO())
        u.refresh_from_db()
        self.assertTrue(u.check_password("second-pass-456"))
        self.assertEqual(User.objects.filter(username="ops").count(), 1)

    def test_admin_login_page_served(self):
        with patch.dict(os.environ, {"ADMIN_USERNAME": "ops", "ADMIN_PASSWORD": "pw-for-admin-1"}):
            call_command("ensure_admin", stdout=StringIO())
        self.assertTrue(self.client.login(username="ops", password="pw-for-admin-1"))
        r = self.client.get("/admin/play/wallet/")
        self.assertEqual(r.status_code, 200)


class GrantPremiumTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("cvolk", email="c@example.test", password="x")

    def test_grant_and_revoke_by_username_or_email(self):
        out = StringIO()
        call_command("grant_premium", "CVOLK", stdout=out)
        w = Wallet.objects.get(user=self.user)
        self.assertEqual((w.subscribed, w.subscription_status, w.billing_provider), (True, "active", ""))
        self.assertIn("granted", out.getvalue())
        call_command("grant_premium", "c@example.test", "--revoke", stdout=StringIO())
        w.refresh_from_db()
        self.assertEqual((w.subscribed, w.subscription_status), (False, ""))

    def test_refuses_provider_billed_and_unknown(self):
        Wallet.objects.create(user=self.user, subscribed=True, billing_provider="stripe")
        with self.assertRaises(CommandError):
            call_command("grant_premium", "cvolk", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("grant_premium", "nobody", stdout=StringIO())


class WalletAdminFormTests(TestCase):
    def test_wallet_admin_saves_premium_without_team_ids(self):
        from django.contrib.auth.models import User
        from django.test import Client
        admin = User.objects.create_superuser("root", "root@example.com", "pw")
        user = User.objects.create_user("player", "p@example.com", "pw")
        Wallet.objects.get_or_create(user=user)
        w = Wallet.objects.get(user=user)
        c = Client()
        c.force_login(admin)
        r = c.post(f"/admin/play/wallet/{w.pk}/change/", {
            "user": user.pk, "shards": 50, "cores": 0, "subscribed": "on", "subscription_status": "active",
            "billing_provider": "", "play_auto_renewing": "", "onboarded": "", "_save": "Save",
        })
        self.assertEqual(r.status_code, 302, getattr(r, "content", b"")[:2000])
        w.refresh_from_db()
        self.assertTrue(w.subscribed)
        self.assertEqual(w.team_ids, [])
