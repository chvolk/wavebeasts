"""Google Play Billing: purchase verification, offers policy, RTDN webhook, reconcile and provider
exclusivity. Google is never called: fetch_subscription/acknowledge/verify_oauth2_token are patched."""
import base64
import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from . import billing, playbilling
from .models import Node, Wallet

PLAY = dict(PLAY_SERVICE_ACCOUNT_JSON="e30=", STRIPE_SECRET_KEY="", CLERK_SECRET_KEY="", PLAY_RTDN_SERVICE_ACCOUNT="")


def _iso(delta):
    return (timezone.now() + delta).isoformat().replace("+00:00", "Z")


def sub(state="SUBSCRIPTION_STATE_ACTIVE", expires=timedelta(days=30), ack="ACKNOWLEDGEMENT_STATE_PENDING",
        oid=None, plan="monthly", renew=True):
    s = {"subscriptionState": state, "acknowledgementState": ack,
         "lineItems": [{"productId": "premium", "expiryTime": _iso(expires),
                        "offerDetails": {"basePlanId": plan}, "autoRenewingPlan": {"autoRenewEnabled": renew}}]}
    if oid:
        s["externalAccountIdentifiers"] = {"obfuscatedExternalAccountId": oid}
    return s


@override_settings(**PLAY)
class VerifyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("user_play", password="x")
        self.wallet = Wallet.objects.get_or_create(user=self.user)[0]
        self.node = Node.objects.create(user=self.user, name="Pixel", kind="app")

    def post(self, body, token=None):
        return self.client.post("/api/billing/play/verify", json.dumps(body), content_type="application/json",
                                HTTP_X_WB_NODE_TOKEN=token or self.node.token)

    def test_success_activates_acknowledges_and_binds(self):
        oid = playbilling.obfuscated_id(self.user)
        with patch.object(playbilling, "fetch_subscription", return_value=sub(oid=oid)) as fetch, \
             patch.object(playbilling, "acknowledge", return_value=True) as ack:
            r = self.post({"purchase_token": "tok-1", "product_id": "premium"})
        self.assertEqual(r.status_code, 200, r.content)
        fetch.assert_called_once_with("tok-1")
        ack.assert_called_once_with("tok-1", "premium")
        self.assertEqual(r["Cache-Control"], "private, no-store")
        a = r.json()["account"]
        self.assertTrue(a["subscribed"])
        self.assertEqual((a["plan"], a["billing_provider"], a["subscription_status"]), ("Premium", "play", "active"))
        self.assertTrue(a["renews_at"])
        self.assertIn("play.google.com/store/account/subscriptions", a["manage_url"])
        self.wallet.refresh_from_db()
        self.assertEqual((self.wallet.play_purchase_token, self.wallet.play_base_plan, self.wallet.play_obfuscated_id),
                         ("tok-1", "monthly", oid))
        self.assertTrue(self.wallet.play_auto_renewing and self.wallet.play_linked_at and self.wallet.play_expires_at)

    def test_no_ack_when_already_acknowledged(self):
        with patch.object(playbilling, "fetch_subscription", return_value=sub(ack="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED")), \
             patch.object(playbilling, "acknowledge") as ack:
            self.assertEqual(self.post({"purchase_token": "tok-2"}).status_code, 200)
        ack.assert_not_called()

    def test_account_mismatch(self):
        with patch.object(playbilling, "fetch_subscription", return_value=sub(oid="someone-else")):
            r = self.post({"purchase_token": "tok-3"})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "account_mismatch"))
        self.wallet.refresh_from_db()
        self.assertFalse(self.wallet.subscribed)

    def test_token_in_use(self):
        other = User.objects.create_user("user_other", password="x")
        Wallet.objects.create(user=other, play_purchase_token="tok-4")
        with patch.object(playbilling, "fetch_subscription", return_value=sub()):
            r = self.post({"purchase_token": "tok-4"})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "token_in_use"))

    def test_stripe_active_refused(self):
        Wallet.objects.filter(pk=self.wallet.pk).update(subscribed=True, billing_provider="stripe")
        with patch.object(playbilling, "fetch_subscription", return_value=sub()):
            r = self.post({"purchase_token": "tok-5"})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "stripe_active"))

    def test_non_app_node_and_bad_token(self):
        pi = Node.objects.create(user=self.user, name="Pi", kind="pi")
        self.assertEqual(self.post({"purchase_token": "x"}, token=pi.token).json()["error"], "app_node_required")
        self.assertEqual(self.post({"purchase_token": "x"}, token="nope").status_code, 403)
        self.assertEqual(self.post({}).status_code, 400)

    def test_invalid_token_from_google(self):
        with patch.object(playbilling, "fetch_subscription", side_effect=playbilling.PlayError("invalid_token", 400)):
            r = self.post({"purchase_token": "garbage"})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "invalid_token"))

    def test_rate_limited(self):
        with patch.object(playbilling, "fetch_subscription", side_effect=playbilling.PlayError("invalid_token", 400)):
            for _ in range(30):
                self.post({"purchase_token": "x"})
            self.assertEqual(self.post({"purchase_token": "x"}).status_code, 429)

    def test_unconfigured_returns_503(self):
        with override_settings(PLAY_SERVICE_ACCOUNT_JSON=""):
            r = self.post({"purchase_token": "tok"})
        self.assertEqual((r.status_code, r.json()["error"]), (503, "play_not_configured"))


@override_settings(**PLAY)
class StateMappingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("user_state", password="x")
        self.wallet = Wallet.objects.get_or_create(user=self.user)[0]

    def apply(self, s):
        with patch.object(playbilling, "fetch_subscription", return_value=s), patch.object(playbilling, "acknowledge"):
            ok, payload, status = playbilling.verify_and_apply(self.wallet, "tok", refresh=True)
        self.assertTrue(ok, payload)
        self.wallet.refresh_from_db()
        return self.wallet

    def test_grace_period_keeps_access_as_past_due(self):
        w = self.apply(sub("SUBSCRIPTION_STATE_IN_GRACE_PERIOD"))
        self.assertEqual((w.subscribed, w.subscription_status, w.billing_provider), (True, "past_due", "play"))

    def test_on_hold_and_paused_lose_access(self):
        self.assertFalse(self.apply(sub("SUBSCRIPTION_STATE_ON_HOLD")).subscribed)
        w = self.apply(sub("SUBSCRIPTION_STATE_PAUSED"))
        self.assertEqual((w.subscribed, w.subscription_status), (False, "paused"))

    def test_canceled_keeps_access_until_expiry(self):
        w = self.apply(sub("SUBSCRIPTION_STATE_CANCELED", renew=False))
        self.assertEqual((w.subscribed, w.subscription_status, w.play_auto_renewing), (True, "canceled", False))
        w = self.apply(sub("SUBSCRIPTION_STATE_CANCELED", expires=timedelta(days=-1)))
        self.assertEqual((w.subscribed, w.subscription_status, w.billing_provider), (False, "expired", ""))

    def test_expired_clears_provider_but_keeps_token_for_audit(self):
        self.apply(sub())
        w = self.apply(sub("SUBSCRIPTION_STATE_EXPIRED", expires=timedelta(days=-2)))
        self.assertEqual((w.subscribed, w.subscription_status, w.billing_provider, w.play_purchase_token),
                         (False, "expired", "", "tok"))

    def test_active_but_past_expiry_is_expired(self):
        w = self.apply(sub("SUBSCRIPTION_STATE_ACTIVE", expires=timedelta(hours=-1)))
        self.assertFalse(w.subscribed)


@override_settings(**PLAY)
class OffersTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("user_offers", password="x")
        self.wallet = Wallet.objects.get_or_create(user=self.user)[0]
        self.node = Node.objects.create(user=self.user, name="Pixel", kind="app")

    def get(self, channel=""):
        return self.client.get("/api/billing/offers", {"channel": channel} if channel else {},
                               HTTP_X_WB_NODE_TOKEN=self.node.token)

    def test_play_channel_hides_web_paths(self):
        r = self.get("play")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertNotIn("web", d)
        self.assertEqual(d["play"]["base_plans"], ["monthly", "annual"])
        self.assertEqual(d["play"]["obfuscated_account_id"], playbilling.obfuscated_id(self.user))
        self.assertEqual(d["obfuscated_id"], playbilling.obfuscated_id(self.user))
        self.assertEqual(r["Cache-Control"], "private, no-store")

    def test_other_channels_see_web_and_stripe_is_flagged(self):
        d = self.get("sideload").json()
        self.assertEqual(d["obfuscated_id"], playbilling.obfuscated_id(self.user))
        self.assertTrue(d["web"]["billing_url"].endswith("/billing/"))
        self.assertFalse(d["web"]["portal_available"])
        self.assertNotIn("managed_elsewhere", d)
        Wallet.objects.filter(pk=self.wallet.pk).update(subscribed=True, billing_provider="stripe", stripe_customer_id="cus_1")
        d = self.get("play").json()
        self.assertTrue(d["managed_elsewhere"])
        self.assertNotIn("web", d)
        self.assertEqual(d["provider"], "stripe")

    def test_requires_token(self):
        self.assertEqual(self.client.get("/api/billing/offers").status_code, 403)


def push(note, message_id="1"):
    data = base64.b64encode(json.dumps(note).encode()).decode()
    return json.dumps({"message": {"data": data, "messageId": message_id}, "subscription": "s"})


@override_settings(**PLAY)
class WebhookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("user_hook", password="x")
        self.wallet = Wallet.objects.get_or_create(user=self.user)[0]

    def post(self, body, **headers):
        # Play is configured in these tests, so pushes must carry a valid token; patch the verifier and
        # send a bearer header unless a test supplies its own.
        headers.setdefault("HTTP_AUTHORIZATION", "Bearer jwt")
        with override_settings(PLAY_RTDN_SERVICE_ACCOUNT="push@p.iam.gserviceaccount.com"), \
             patch("google.oauth2.id_token.verify_oauth2_token",
                   return_value={"email": "push@p.iam.gserviceaccount.com", "email_verified": True}):
            return self.client.post("/webhooks/play", body, content_type="application/json", **headers)

    def test_fails_closed_when_play_configured_but_push_account_missing(self):
        r = self.client.post("/webhooks/play", push({"testNotification": {}}), content_type="application/json")
        self.assertEqual(r.status_code, 401)
        with override_settings(PLAY_SERVICE_ACCOUNT_JSON=""):  # nothing configured at all: dev stays open
            r = self.client.post("/webhooks/play", push({"testNotification": {}}), content_type="application/json")
            self.assertEqual(r.status_code, 200)

    def test_auth_required_when_configured(self):
        with override_settings(PLAY_RTDN_SERVICE_ACCOUNT="push@p.iam.gserviceaccount.com"):
            raw = lambda **h: self.client.post("/webhooks/play", push({"testNotification": {"version": "1"}}),
                                               content_type="application/json", **h)
            self.assertEqual(raw().status_code, 401)
            with patch("google.oauth2.id_token.verify_oauth2_token",
                       return_value={"email": "push@p.iam.gserviceaccount.com", "email_verified": True}) as v:
                r = raw(HTTP_AUTHORIZATION="Bearer jwt")
            self.assertEqual((r.status_code, r.json()["outcome"]), (200, "test"))
            self.assertEqual(v.call_args.kwargs["audience"], "https://wavebeasts.com/webhooks/play")
            with patch("google.oauth2.id_token.verify_oauth2_token",
                       return_value={"email": "evil@x", "email_verified": True}):
                self.assertEqual(raw(HTTP_AUTHORIZATION="Bearer jwt").status_code, 401)

    def test_unparseable_is_204(self):
        self.assertEqual(self.post("not json").status_code, 204)
        self.assertEqual(self.post(json.dumps({"message": {"data": "!!!"}})).status_code, 204)

    def test_wrong_package_ignored(self):
        r = self.post(push({"packageName": "com.other", "subscriptionNotification": {"purchaseToken": "t"}}))
        self.assertEqual(r.json()["outcome"], "wrong_package")

    def test_expiry_notification_unsubscribes(self):
        Wallet.objects.filter(pk=self.wallet.pk).update(subscribed=True, billing_provider="play", play_purchase_token="tok-e",
                                                        play_expires_at=timezone.now())
        with patch.object(playbilling, "fetch_subscription", return_value=sub("SUBSCRIPTION_STATE_EXPIRED", timedelta(days=-1))):
            r = self.post(push({"packageName": "net.wavebeasts.app",
                                "subscriptionNotification": {"purchaseToken": "tok-e", "notificationType": 13}}))
        self.assertEqual(r.json()["outcome"], "applied")
        self.wallet.refresh_from_db()
        self.assertEqual((self.wallet.subscribed, self.wallet.billing_provider), (False, ""))

    def test_refresh_bypasses_stripe_refusal_for_known_token(self):
        Wallet.objects.filter(pk=self.wallet.pk).update(subscribed=True, billing_provider="stripe", play_purchase_token="tok-r")
        with patch.object(playbilling, "fetch_subscription", return_value=sub("SUBSCRIPTION_STATE_EXPIRED", timedelta(days=-1))):
            self.assertEqual(self.post(push({"subscriptionNotification": {"purchaseToken": "tok-r"}})).json()["outcome"], "applied")

    def test_unknown_token_found_by_obfuscated_id(self):
        oid = playbilling.obfuscated_id(self.user)
        Wallet.objects.filter(pk=self.wallet.pk).update(play_obfuscated_id=oid)
        with patch.object(playbilling, "fetch_subscription", return_value=sub(oid=oid)), \
             patch.object(playbilling, "acknowledge", return_value=True):
            r = self.post(push({"subscriptionNotification": {"purchaseToken": "tok-new", "notificationType": 4}}))
        self.assertEqual(r.json()["outcome"], "applied")
        self.wallet.refresh_from_db()
        self.assertEqual((self.wallet.subscribed, self.wallet.play_purchase_token), (True, "tok-new"))

    def test_unknown_token_without_wallet_is_logged_not_retried(self):
        with patch.object(playbilling, "fetch_subscription", return_value=sub(oid="nobody")):
            r = self.post(push({"subscriptionNotification": {"purchaseToken": "tok-x"}}))
        self.assertEqual((r.status_code, r.json()["outcome"]), (200, "no_wallet"))

    def test_handler_exception_is_200(self):
        with patch.object(playbilling, "handle_notification", side_effect=RuntimeError("boom")):
            self.assertEqual(self.post(push({"testNotification": {}})).json()["outcome"], "error")


@override_settings(**PLAY)
class ReconcileAndExclusivityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("user_rec", password="x")
        self.wallet = Wallet.objects.get_or_create(user=self.user)[0]

    def test_reconcile_reverifies_due_wallets(self):
        Wallet.objects.filter(pk=self.wallet.pk).update(subscribed=True, billing_provider="play", play_purchase_token="tok-d",
                                                        play_expires_at=timezone.now() - timedelta(days=1))
        far = User.objects.create_user("user_far", password="x")
        Wallet.objects.create(user=far, subscribed=True, billing_provider="play", play_purchase_token="tok-far",
                              play_expires_at=timezone.now() + timedelta(days=20))
        out = StringIO()
        with patch.object(playbilling, "fetch_subscription", return_value=sub("SUBSCRIPTION_STATE_EXPIRED", timedelta(days=-1))) as f:
            call_command("play_reconcile", stdout=out)
        f.assert_called_once_with("tok-d")
        self.assertIn("checked 1", out.getvalue())
        self.assertIn("1 changed", out.getvalue())
        self.wallet.refresh_from_db()
        self.assertFalse(self.wallet.subscribed)

    def test_reconcile_noop_when_unconfigured(self):
        out = StringIO()
        with override_settings(PLAY_SERVICE_ACCOUNT_JSON=""), patch.object(playbilling, "fetch_subscription") as f:
            call_command("play_reconcile", stdout=out)
        f.assert_not_called()
        self.assertIn("not set", out.getvalue())

    def test_stripe_event_refused_while_play_active(self):
        Wallet.objects.filter(pk=self.wallet.pk).update(subscribed=True, billing_provider="play", stripe_customer_id="cus_p")
        ok = billing.apply_event({"type": "checkout.session.completed", "data": {"object": {"customer": "cus_p"}}})
        self.assertFalse(ok)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.billing_provider, "play")

    def test_stripe_event_sets_provider_when_free(self):
        Wallet.objects.filter(pk=self.wallet.pk).update(stripe_customer_id="cus_f")
        self.assertTrue(billing.apply_event({"type": "customer.subscription.updated",
                                             "data": {"object": {"customer": "cus_f", "status": "active"}}}))
        self.wallet.refresh_from_db()
        self.assertEqual((self.wallet.subscribed, self.wallet.billing_provider), (True, "stripe"))

    def test_api_account_renews_and_manage_url(self):
        node = Node.objects.create(user=self.user, name="Pixel", kind="app")
        exp = timezone.now() + timedelta(days=10)
        Wallet.objects.filter(pk=self.wallet.pk).update(subscribed=True, billing_provider="play", play_expires_at=exp)
        a = self.client.get("/api/account", HTTP_X_WB_NODE_TOKEN=node.token).json()["account"]
        self.assertEqual(a["renews_at"], exp.isoformat())
        self.assertIn("sku=premium&package=net.wavebeasts.app", a["manage_url"])
        Wallet.objects.filter(pk=self.wallet.pk).update(billing_provider="stripe")
        a = self.client.get("/api/account", HTTP_X_WB_NODE_TOKEN=node.token).json()["account"]
        self.assertEqual((a["renews_at"], a["manage_url"], a["billing_provider"]), (None, None, "stripe"))

    def test_web_checkout_refused_while_play_active(self):
        Wallet.objects.filter(pk=self.wallet.pk).update(subscribed=True, billing_provider="play")
        self.client.force_login(self.user)
        r = self.client.post("/billing/checkout", {"plan": "monthly"})
        self.assertEqual(r.status_code, 302)
        page = self.client.get("/billing/")
        self.assertContains(page, "managed through Google Play")
        self.assertContains(page, "Manage on Google Play")
        self.assertNotContains(page, "/billing/portal")
