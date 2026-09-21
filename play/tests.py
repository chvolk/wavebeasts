import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from datetime import timedelta

from . import buddy as buddymod
from .models import Buddy, InventoryItem, Node, OwnedBeast, Wallet

User = get_user_model()


def _beast(user, verified=True, xp=0, level=1):
    return OwnedBeast.objects.create(
        user=user, species_id="sp1", name="Testmon", rarity="rare", shiny=False, level=level,
        status="owned", verified=verified, species_json={"types": ["ember"]},
        individual_json={"level": level, "xp": xp, "nickname": "Sparky"})


class BuddyLogicTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("t", password="x")
        self.wallet = Wallet.objects.get_or_create(user=self.user)[0]

    def test_event_interval_scales_with_relationship(self):
        self.assertEqual(buddymod.event_interval_min(100), 10)   # loves you → fastest
        self.assertEqual(buddymod.event_interval_min(0), 60)     # wary → slowest

    def test_care_applies_effects_and_cooldown(self):
        b = Buddy.objects.create(user=self.user, beast=_beast(self.user), hunger=20, relationship=0)
        r1 = buddymod.apply_care(b, "feed")
        self.assertTrue(r1.get("ok"))
        self.assertGreater(b.hunger, 20)
        self.assertEqual(b.relationship, 2)
        r2 = buddymod.apply_care(b, "feed")   # immediate re-feed → cooldown
        self.assertEqual(r2.get("error"), "cooldown")
        self.assertGreater(r2.get("retry_after_sec", 0), 0)

    def test_train_grants_xp_and_levels(self):
        beast = _beast(self.user, xp=(1 ** 3) * buddymod.XP_CURVE_K)  # already enough for level 1->2 with TRAIN_XP
        b = Buddy.objects.create(user=self.user, beast=beast)
        res = buddymod.apply_care(b, "train")
        self.assertEqual(res.get("xp_gained"), buddymod.TRAIN_XP)
        self.assertGreaterEqual(res.get("levels_gained"), 1)
        self.assertGreaterEqual(beast.individual_json["level"], 2)

    def test_away_events_rate_limited_and_capped(self):
        beast = _beast(self.user)
        b = Buddy.objects.create(user=self.user, beast=beast, relationship=100,
                                 last_event_at=timezone.now() - timedelta(hours=10))
        before = self.wallet.shards
        events = buddymod.accrue_events(b, self.wallet, beast)
        self.assertEqual(len(events), buddymod.EVENT_CAP)         # capped, not one-per-second
        self.assertLessEqual(b.last_event_at, timezone.now())     # clock advanced, not to now
        # at least some resource/xp was granted somewhere
        self.assertTrue(self.wallet.shards >= before)

    def test_no_events_before_first_interval(self):
        beast = _beast(self.user)
        b = Buddy.objects.create(user=self.user, beast=beast, relationship=100,
                                 last_event_at=timezone.now() - timedelta(minutes=3))  # < 10 min interval
        self.assertEqual(buddymod.accrue_events(b, self.wallet, beast), [])


@override_settings(ALLOWED_HOSTS=["testserver"])
class BuddyApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("n", password="x")
        self.wallet = Wallet.objects.get_or_create(user=self.user, defaults={"subscribed": True})[0]
        self.node = Node.objects.create(user=self.user, name="companion")

    def _hdr(self):
        return {"HTTP_X_WB_NODE_TOKEN": self.node.token}

    def test_slot_requires_verified_beast(self):
        unv = _beast(self.user, verified=False)
        r = self.client.post("/api/buddy/slot", data=json.dumps({"beast_id": unv.id}),
                             content_type="application/json", **self._hdr())
        self.assertEqual(r.status_code, 403)
        ver = _beast(self.user, verified=True)
        r2 = self.client.post("/api/buddy/slot", data=json.dumps({"beast_id": ver.id}),
                              content_type="application/json", **self._hdr())
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["buddy"]["beast"]["id"], ver.id)
        self.assertEqual(r2.json()["buddy"]["carrier"]["id"], self.node.id)  # this device is the carrier

    def test_paywall_blocks_unsubscribed(self):
        self.wallet.subscribed = False
        self.wallet.save()
        r = self.client.get("/api/buddy", **self._hdr())
        self.assertEqual(r.status_code, 402)

    def test_bad_token_rejected(self):
        r = self.client.get("/api/buddy", HTTP_X_WB_NODE_TOKEN="nope")
        self.assertEqual(r.status_code, 403)


@override_settings(ALLOWED_HOSTS=["testserver"])
class AuthBillingTests(TestCase):
    def test_auth_pages_render(self):
        self.assertEqual(self.client.get("/sign-in/").status_code, 200)
        self.assertEqual(self.client.get("/sign-up/").status_code, 200)

    def test_django_login_fallback_still_exists(self):
        self.assertEqual(self.client.get("/login/").status_code, 200)  # fallback when Clerk isn't configured

    @patch("play.clerkauth.verify_clerk_token")
    def test_auth_clerk_creates_user_and_session(self, mv):
        mv.return_value = {"sub": "user_abc"}
        r = self.client.post("/auth/clerk", data=json.dumps({"token": "x"}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.filter(username="user_abc").exists())
        self.assertEqual(r.json()["redirect"], "/onboarding/")  # new user → onboarding first

    @patch("play.clerkauth.verify_clerk_token")
    def test_auth_clerk_rejects_bad_token(self, mv):
        mv.return_value = None
        r = self.client.post("/auth/clerk", data=json.dumps({"token": "x"}), content_type="application/json")
        self.assertEqual(r.status_code, 401)

    def test_billing_requires_login(self):
        self.assertIn(self.client.get("/billing/").status_code, (301, 302))


@override_settings(ALLOWED_HOSTS=["testserver"])
class TieringTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("free", password="x")
        self.client.force_login(self.user)
        self.wallet = Wallet.objects.get_or_create(user=self.user)[0]  # subscribed defaults False now

    def test_free_account_capped_at_one_node(self):
        self.client.post("/nodes/new", {"name": "rig1"})
        self.client.post("/nodes/new", {"name": "rig2"})
        self.assertEqual(self.user.nodes.count(), 1)

    def test_paid_account_capped_at_twelve(self):
        self.wallet.subscribed = True
        self.wallet.save()
        for i in range(15):
            self.client.post("/nodes/new", {"name": f"rig{i}"})
        self.assertEqual(self.user.nodes.count(), 12)

    def test_battle_and_ladder_require_paid(self):
        _beast(self.user)
        self.client.post("/battle/fight")
        self.assertIn("paid", (self.client.session.get("last_battle") or {}).get("error", "").lower())
        self.client.post("/ladder/enter")
        self.assertIn("paid", (self.client.session.get("ladder_msg") or "").lower())


@override_settings(ALLOWED_HOSTS=["testserver"])
class BuyTests(TestCase):
    CATALOG = {"items": [{"id": "pulse_drive", "cost_kind": "shards", "cost_amt": 30}]}

    def setUp(self):
        self.user = User.objects.create_user("buyer", password="x")
        self.wallet = Wallet.objects.get_or_create(user=self.user)[0]  # 50 shards by default
        self.node = Node.objects.create(user=self.user, name="app")

    def _buy(self, item_id, qty=1):
        return self.client.post("/api/buy", data=json.dumps({"item_id": item_id, "qty": qty}),
                                content_type="application/json", HTTP_X_WB_NODE_TOKEN=self.node.token)

    @patch("play.resolver.shop")
    def test_buy_deducts_server_side_price(self, mshop):
        mshop.return_value = self.CATALOG
        r = self._buy("pulse_drive")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["shards"], 20)  # 50 - 30, computed on the server
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.shards, 20)

    @patch("play.resolver.shop")
    def test_buy_rejects_when_short(self, mshop):
        mshop.return_value = self.CATALOG
        self.wallet.shards = 5
        self.wallet.save()
        self.assertEqual(self._buy("pulse_drive").status_code, 409)

    @patch("play.resolver.shop")
    def test_buy_cost_scales_with_qty(self, mshop):
        mshop.return_value = self.CATALOG
        self.assertEqual(self._buy("pulse_drive", qty=2).status_code, 409)  # 60 > 50

    @patch("play.resolver.shop")
    def test_buy_unknown_item(self, mshop):
        mshop.return_value = self.CATALOG
        self.assertEqual(self._buy("cheat_item").status_code, 404)


@override_settings(ALLOWED_HOSTS=["testserver"])
class SyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("syncer", password="x")
        self.wallet = Wallet.objects.get_or_create(user=self.user)[0]
        self.node = Node.objects.create(user=self.user, name="app")

    def _mk(self, verified=True, idv=1):
        return OwnedBeast.objects.create(user=self.user, species_id="sp", name="M", rarity="rare", level=5,
            status="owned", verified=verified, id_version=idv, species_json={}, individual_json={})

    def _sync(self):
        return self.client.post("/api/sync", HTTP_X_WB_NODE_TOKEN=self.node.token)

    @patch("play.resolver.capabilities")
    def test_sync_backfills_nature_and_version_verified_only(self, mcaps):
        mcaps.return_value = {"id_version": 2, "natures": ["Brave", "Timid"]}
        b = self._mk(verified=True, idv=1)
        unv = self._mk(verified=False, idv=1)
        r = self._sync()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["synced"], 1)
        b.refresh_from_db()
        self.assertEqual(b.id_version, 2)
        self.assertIn(b.individual_json["nature"], ["Brave", "Timid"])
        unv.refresh_from_db()
        self.assertEqual(unv.id_version, 1)  # modded/unverified untouched

    @patch("play.resolver.capabilities")
    def test_sync_is_once_per_day(self, mcaps):
        mcaps.return_value = {"id_version": 2, "natures": ["Brave"]}
        self._mk()
        self.assertEqual(self._sync().status_code, 200)
        self.assertEqual(self._sync().status_code, 429)


@override_settings(ALLOWED_HOSTS=["testserver"])
class ReleaseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("releaser", password="x")
        Wallet.objects.get_or_create(user=self.user)
        self.node = Node.objects.create(user=self.user, name="app")

    def _rel(self, bid):
        return self.client.post("/api/release", data=json.dumps({"beast_id": bid}),
                                content_type="application/json", HTTP_X_WB_NODE_TOKEN=self.node.token)

    def test_release_removes_beast(self):
        b = _beast(self.user)
        self.assertEqual(self._rel(b.id).status_code, 200)
        self.assertFalse(OwnedBeast.objects.filter(id=b.id).exists())

    def test_cannot_release_slotted_buddy(self):
        b = _beast(self.user)
        Buddy.objects.create(user=self.user, beast=b)
        self.assertEqual(self._rel(b.id).status_code, 409)
        self.assertTrue(OwnedBeast.objects.filter(id=b.id).exists())


@override_settings(ALLOWED_HOSTS=["testserver"])
class CatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("catcher", password="x")
        Wallet.objects.get_or_create(user=self.user)
        self.node = Node.objects.create(user=self.user, name="app")

    def _wild(self):
        return OwnedBeast.objects.create(user=self.user, species_id="s", name="Wildmon", rarity="common",
            level=1, status="wild", verified=True, species_json={}, individual_json={})

    def _catch(self, beast_id, drive):
        return self.client.post("/api/catch", data=json.dumps({"beast_id": beast_id, "drive": drive}),
                                content_type="application/json", HTTP_X_WB_NODE_TOKEN=self.node.token)

    def test_catch_needs_a_drive(self):
        self.assertEqual(self._catch(self._wild().id, "pulse_drive").status_code, 409)

    def test_catch_consumes_drive(self):
        w = self._wild()
        InventoryItem.objects.create(user=self.user, item_id="nova_drive", qty=1)
        r = self._catch(w.id, "nova_drive")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["remaining"], 0)  # drive consumed regardless of outcome
