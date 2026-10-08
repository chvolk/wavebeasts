import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from . import applink, appversion
from .models import InventoryItem, LinkCode, Node, OwnedBeast, TradeListing, TradeOffer, Wallet

STATE = "abcDEF123_-xyz"


def _beast(user, name="Testmon"):
    return OwnedBeast.objects.create(user=user, species_id="sp1", name=name, rarity="rare", level=1, status="owned",
                                     verified=True, species_json={"types": ["ember"]}, individual_json={"level": 1})


class ConnectTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("user_abc", password="x", first_name="Trainer")
        Wallet.objects.get_or_create(user=self.user)

    def test_login_required_preserves_next(self):
        r = self.client.get(f"/app/connect?state={STATE}&device=Pixel")
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=/app/connect%3Fstate%3D", r["Location"])

    def test_bad_state_rejected(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/app/connect").status_code, 400)
        self.assertEqual(self.client.get("/app/connect?state=short").status_code, 400)
        self.assertEqual(self.client.get("/app/connect?state=has space!!!").status_code, 400)

    def test_get_shows_device_and_account(self):
        self.client.force_login(self.user)
        r = self.client.get(f"/app/connect?state={STATE}&device=Pixel%209")
        self.assertContains(r, "Pixel 9")
        self.assertContains(r, "Trainer")
        self.assertEqual(Node.objects.count(), 0)

    def test_node_limit_blocks_connect(self):
        self.client.force_login(self.user)
        for i in range(3):
            Node.objects.create(user=self.user, name=f"n{i}")
        r = self.client.post(f"/app/connect?state={STATE}")
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, "Node limit reached", status_code=409)
        self.assertEqual(Node.objects.count(), 3)
        self.assertEqual(LinkCode.objects.count(), 0)

    @override_settings(SITE_URL="https://wavebeasts.com")
    def test_post_creates_app_node_code_and_redirects(self):
        self.client.force_login(self.user)
        r = self.client.post(f"/app/connect?state={STATE}&device=Pixel")
        self.assertEqual(r.status_code, 302)
        node = Node.objects.get()
        self.assertEqual((node.kind, node.name), ("app", "Pixel"))
        code = LinkCode.objects.get()
        self.assertEqual(code.node, node)
        self.assertEqual(code.state, STATE)
        self.assertTrue(code.is_valid())
        self.assertEqual(r["Location"], f"https://wavebeasts.com/app/callback?code={code.code}&state={STATE}")
        self.assertTrue(Wallet.objects.get(user=self.user).onboarded)
        self.assertNotIn(node.token, r["Location"])

    def test_default_device_name(self):
        self.client.force_login(self.user)
        self.client.post(f"/app/connect?state={STATE}")
        self.assertEqual(Node.objects.get().name, applink.DEVICE_DEFAULT)


class CallbackTests(TestCase):
    def test_renders_deep_link_and_play_url(self):
        r = self.client.get(f"/app/callback?code=abc123&state={STATE}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f"wavebeast://link?code=abc123&amp;state={STATE}")
        self.assertContains(r, applink.PLAY_URL)
        self.assertContains(r, "expires in 5 minutes")
        self.assertEqual(r["Cache-Control"], "private, no-store")

    def test_invalid_params(self):
        self.assertEqual(self.client.get("/app/callback").status_code, 400)
        self.assertEqual(self.client.get("/app/callback?code=<x>&state=bad").status_code, 400)


class ExchangeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("user_x", password="x")
        self.node = Node.objects.create(user=self.user, name="Pixel", kind="app")
        self.code = LinkCode.objects.create(node=self.node, state=STATE, expires_at=timezone.now() + timedelta(minutes=5))

    def post(self, body, **extra):
        return self.client.post("/api/app/link/exchange", json.dumps(body), content_type="application/json", **extra)

    @override_settings(SITE_URL="https://wavebeasts.com/")
    def test_success_is_single_use(self):
        r = self.post({"code": self.code.code, "state": STATE})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["token"], self.node.token)
        self.assertEqual(data["site"], "https://wavebeasts.com")
        self.assertEqual(data["node"], {"id": self.node.id, "name": "Pixel", "kind": "app"})
        self.assertEqual(r["Cache-Control"], "private, no-store")
        self.code.refresh_from_db()
        self.assertIsNotNone(self.code.used_at)
        r2 = self.post({"code": self.code.code, "state": STATE})
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(r2.json()["error"], "invalid_code")

    def test_state_mismatch_unknown_and_bad_json(self):
        self.assertEqual(self.post({"code": self.code.code, "state": "wrongstate1"}).status_code, 400)
        self.assertEqual(self.post({"code": "nope", "state": STATE}).status_code, 400)
        self.assertEqual(self.post({}).status_code, 400)
        r = self.client.post("/api/app/link/exchange", "not json", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/api/app/link/exchange").status_code, 405)
        self.code.refresh_from_db()
        self.assertIsNone(self.code.used_at)

    def test_expired(self):
        LinkCode.objects.filter(pk=self.code.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        r = self.post({"code": self.code.code, "state": STATE})
        self.assertEqual(r.status_code, 410)
        self.assertEqual(r.json()["error"], "expired")

    def test_rate_limited_per_ip(self):
        for _ in range(applink.EXCHANGE_RATE_LIMIT):
            self.assertEqual(self.post({"code": "x", "state": STATE}, REMOTE_ADDR="10.0.0.9").status_code, 400)
        self.assertEqual(self.post({"code": "x", "state": STATE}, REMOTE_ADDR="10.0.0.9").status_code, 429)
        self.assertEqual(self.post({"code": "x", "state": STATE}, REMOTE_ADDR="10.0.0.8").status_code, 400)


@override_settings(ANDROID_CERT_SHA256="AA:BB, cc:dd")
class AssetLinksTests(TestCase):
    def test_statement(self):
        r = self.client.get("/.well-known/assetlinks.json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/json")
        self.assertIn("max-age=3600", r["Cache-Control"])
        data = json.loads(r.content)
        self.assertEqual(data[0]["relation"], ["delegate_permission/common.handle_all_urls"])
        self.assertEqual(data[0]["target"]["package_name"], "net.wavebeasts.app")
        self.assertEqual(data[0]["target"]["sha256_cert_fingerprints"], ["AA:BB", "CC:DD"])


@override_settings(CLERK_PUBLISHABLE_KEY="pk_test_" + "d2F2ZWJlYXN0cy5leGFtcGxlLmNvbSQ=")
class ClerkNextTests(TestCase):
    def exchange(self, nxt):
        with patch("play.views.clerkauth.verify_clerk_token", return_value={"sub": "user_new1"}), \
                patch("play.views.clerkauth.sync_profile", return_value=None):
            body = {"token": "t"}
            if nxt is not None:
                body["next"] = nxt
            return self.client.post("/auth/clerk", json.dumps(body), content_type="application/json")

    def test_safe_next_is_honoured(self):
        r = self.exchange(f"/app/connect?state={STATE}")
        self.assertEqual(r.json()["redirect"], f"/app/connect?state={STATE}")
        self.assertTrue(User.objects.filter(username="user_new1").exists())

    def test_unsafe_next_falls_back(self):
        for bad in ["https://evil.example/", "//evil.example/x", "javascript:alert(1)"]:
            self.assertEqual(self.exchange(bad).json()["redirect"], "/onboarding/")
        self.assertEqual(self.exchange(None).json()["redirect"], "/onboarding/")

    def test_sign_in_page_embeds_next(self):
        r = self.client.get(f"/sign-in/?next=/app/connect%3Fstate%3D{STATE}")
        self.assertContains(r, "var NEXT='/app/connect?state\\u003DabcDEF123_\\u002Dxyz'")  # escapejs output
        r = self.client.get("/sign-in/?next=https://evil.example/")
        self.assertContains(r, "var NEXT=''")


@override_settings(STRIPE_SECRET_KEY="", CLERK_SECRET_KEY="")  # never reach the live providers from tests
class AccountDeleteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("user_del", password="x")
        self.wallet = Wallet.objects.get_or_create(user=self.user)[0]
        self.wallet.stripe_customer_id = "cus_123"
        self.wallet.save()
        self.node = Node.objects.create(user=self.user, name="Pixel", kind="app")
        InventoryItem.objects.create(user=self.user, item_id="spark_drive", qty=2)
        self.other = User.objects.create_user("user_other", password="x")
        self.other_wallet = Wallet.objects.get_or_create(user=self.other)[0]
        self.other_wallet.shards = 10
        self.other_wallet.save()
        # the other player's open offer on this user's listing holds 25 shards in escrow
        listing = TradeListing.objects.create(user=self.user, beast=_beast(self.user))
        self.offer = TradeOffer.objects.create(listing=listing, from_user=self.other, offered_shards=25, offered_cores=1)
        # this user's own open offer on the other player's listing is just closed
        other_listing = TradeListing.objects.create(user=self.other, beast=_beast(self.other, "Othermon"))
        self.own_offer = TradeOffer.objects.create(listing=other_listing, from_user=self.user, offered_shards=5)

    def api(self, body, token=None):
        return self.client.post("/api/account/delete", json.dumps(body), content_type="application/json",
                                HTTP_X_WB_NODE_TOKEN=token or self.node.token)

    def test_requires_token_and_confirmation(self):
        self.assertEqual(self.api({"confirm": "DELETE"}, token="bad").status_code, 403)
        self.assertEqual(self.api({"confirm": "yes"}).status_code, 400)
        self.assertEqual(self.api({}).status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_api_delete_rejects_non_app_nodes(self):
        listener = Node.objects.create(user=self.user, name="Pi", kind="pi")
        r = self.client.post("/api/account/delete", json.dumps({"confirm": "DELETE"}), content_type="application/json",
                             HTTP_X_WB_NODE_TOKEN=listener.token)
        self.assertEqual(r.status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    @override_settings(STRIPE_SECRET_KEY="sk_test_x", CLERK_SECRET_KEY="sk_clerk")
    def test_api_delete_cascades_refunds_and_calls_providers(self):
        with patch("play.applink._cancel_stripe") as cancel, patch("play.applink.requests.delete") as clerk_delete:
            r = self.api({"confirm": "DELETE"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        cancel.assert_called_once()
        clerk_delete.assert_called_once()
        self.assertIn("/v1/users/user_del", clerk_delete.call_args[0][0])
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Node.objects.filter(pk=self.node.pk).exists())
        self.assertFalse(OwnedBeast.objects.filter(user_id=self.user.pk).exists())
        self.assertFalse(Wallet.objects.filter(user_id=self.user.pk).exists())
        self.other_wallet.refresh_from_db()
        self.assertEqual((self.other_wallet.shards, self.other_wallet.cores), (35, 1))
        self.assertFalse(TradeOffer.objects.filter(pk=self.offer.pk).exists())  # cascaded with the listing
        self.assertFalse(TradeOffer.objects.filter(pk=self.own_offer.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.other.pk).exists())

    def test_stripe_failure_does_not_block(self):
        with override_settings(STRIPE_SECRET_KEY="sk_test_x"), \
                patch("play.billing.stripe.Subscription.list", side_effect=Exception("boom")):
            r = self.api({"confirm": "DELETE"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_web_delete_requires_confirmation_then_deletes_and_logs_out(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get("/me/delete"), "Type DELETE to confirm")
        self.assertEqual(self.client.post("/me/delete", {"confirm": "nope"}).status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        r = self.client.post("/me/delete", {"confirm": "DELETE"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/")
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_web_delete_requires_login(self):
        self.assertEqual(self.client.get("/me/delete").status_code, 302)


class AccountApiAndVersionTests(TestCase):
    def test_api_account_new_fields(self):
        user = User.objects.create_user("user_acc", password="x")
        Wallet.objects.get_or_create(user=user)
        node = Node.objects.create(user=user, name="Pixel", kind="app")
        a = self.client.get("/api/account", HTTP_X_WB_NODE_TOKEN=node.token).json()["account"]
        self.assertEqual(a["billing_provider"], "")
        self.assertIsNone(a["renews_at"])
        self.assertIsNone(a["manage_url"])

    def test_stripe_activation_sets_provider(self):
        from . import billing
        user = User.objects.create_user("user_stripe", password="x")
        w = Wallet.objects.get_or_create(user=user)[0]
        w.stripe_customer_id = "cus_1"
        w.save()
        self.assertTrue(billing.apply_event({"type": "checkout.session.completed", "data": {"object": {"customer": "cus_1"}}}))
        w.refresh_from_db()
        self.assertEqual((w.subscribed, w.billing_provider), (True, "stripe"))

    def test_version_manifest(self):
        data = self.client.get("/api/app/version").json()
        self.assertEqual((data["version_code"], data["version_name"]), (38, "0.13.0"))
        self.assertEqual(data["play_url"], appversion.PLAY_URL)
        self.assertIn("uninstall", data["notes"].lower())

    def test_download_page_has_no_ios(self):
        r = self.client.get("/download/")
        self.assertNotContains(r, "IPA")
        self.assertNotContains(r, "iOS")
        self.assertContains(r, "Google Play")
        self.assertEqual(self.client.get("/docs/local-play/").status_code, 200)
        self.assertNotContains(self.client.get("/docs/local-play/"), "iPhone")
