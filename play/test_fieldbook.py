import json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Node, Wallet, InventoryItem, ActivityEntry, Snapshot
from .tests import _beast
from . import journals, node_health
from .activity import audit


class FieldbookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("fieldtester")
        self.other = User.objects.create_user("other")
        self.wallet = Wallet.objects.create(user=self.user, shards=100)
        self.node = Node.objects.create(user=self.user, name="Desk node")
        self.beast = _beast(self.user)
        self.headers = {"HTTP_X_WB_NODE_TOKEN": self.node.token}

    def post(self, url, data):
        return self.client.post(
            url, json.dumps(data), content_type="application/json", **self.headers
        )

    def test_profile_private_stable_and_release_protected(self):
        before = journals.traits(self.beast)
        response = self.post(
            "/api/beast/profile",
            {
                "beast_id": self.beast.pk,
                "favorite": True,
                "notes": "Private <note>",
                "nickname": "Wave friend",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.beast.refresh_from_db()
        self.assertEqual(before, journals.traits(self.beast))
        self.assertTrue(self.beast.favorite)
        self.assertEqual(
            self.post("/api/release", {"beast_id": self.beast.pk}).status_code, 409
        )
        node2 = Node.objects.create(user=self.other, name="Other")
        r = self.client.post(
            "/api/beast/profile",
            json.dumps({"beast_id": self.beast.pk, "notes": "oops"}),
            content_type="application/json",
            HTTP_X_WB_NODE_TOKEN=node2.token,
        )
        self.assertEqual(r.status_code, 404)
        r = self.client.get("/api/beast/" + str(self.beast.pk), **self.headers)
        self.assertEqual(r.json()["journal"]["notes"], "Private <note>")
        self.assertEqual(
            self.post(
                "/api/beast/profile", {"beast_id": self.beast.pk, "favorite": "false"}
            ).status_code,
            400,
        )

    def test_health_checkin_no_rewards_or_scans_and_offline(self):
        body = {
            "client": {"id": "custom-client", "app_v": "1"},
            "health": {
                "mode": "auto",
                "heartbeat_sec": 120,
                "next_attempt_at": (timezone.now() + timedelta(minutes=30)).isoformat(),
                "sensors": [{"name": "wifi", "status": "available", "raw": "SECRET"}],
                "error": {},
            },
        }
        for _ in range(2):
            self.assertEqual(self.post("/api/node/check-in", body).status_code, 200)
        self.assertEqual(Snapshot.objects.count(), 0)
        self.assertEqual(ActivityEntry.objects.count(), 0)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.shards, 100)
        self.node.refresh_from_db()
        self.assertEqual(node_health.row(self.node)["state"], "waiting for next scan")
        self.node.last_seen_at = timezone.now() - timedelta(minutes=7)
        self.assertEqual(node_health.row(self.node)["state"], "offline")
        response = self.client.get("/api/nodes/status", **self.headers)
        self.assertNotIn("SECRET", response.content.decode())
        self.assertNotIn(self.node.token, response.content.decode())
        self.assertEqual(self.client.get("/api/nodes/status").status_code, 403)

    @patch(
        "play.views.resolver.shop",
        return_value={
            "items": [
                {
                    "id": "kibble",
                    "price": {"shards": 10},
                    "cost": {"kind": "shards", "amount": 10},
                }
            ]
        },
    )
    def test_purchase_receipt(self, mock):
        # Catalog shape mirrors resolver protocol.
        mock.return_value = {
            "items": [
                {
                    "id": "kibble",
                    "name": "Kibble",
                    "cost_kind": "shards",
                    "cost_amt": 10,
                }
            ]
        }
        from .views import _buy_item

        status, payload = _buy_item(self.user, "kibble", 2)
        self.assertEqual(status, 200, payload)
        entry = self.user.activity_entries.get()
        self.assertEqual(entry.changes, {"shards": -20, "item:kibble": 2})
        self.assertEqual(entry.balances["shards"], 80)
        count = ActivityEntry.objects.count()
        status, _ = _buy_item(self.user, "kibble", 99)
        self.assertEqual(status, 409)
        self.assertEqual(ActivityEntry.objects.count(), count)

    def test_rollback_and_pagination_isolation(self):
        @audit("test", "test mutation")
        def mutate(user):
            wallet = Wallet.objects.get(user=user)
            wallet.shards = 1
            wallet.save()
            raise RuntimeError("rollback")

        with self.assertRaises(RuntimeError):
            mutate(self.user)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.shards, 100)
        self.assertEqual(ActivityEntry.objects.count(), 0)
        for i in range(23):
            ActivityEntry.objects.create(user=self.user, kind="scan", summary=str(i))
        ActivityEntry.objects.create(user=self.other, kind="scan", summary="PRIVATE")
        first = self.client.get("/api/activity", **self.headers).json()
        self.assertEqual(len(first["entries"]), 20)
        second = self.client.get(
            "/api/activity", {"before": first["next_before"]}, **self.headers
        ).json()
        self.assertEqual(len(second["entries"]), 3)
        self.assertFalse(
            set(e["id"] for e in first["entries"])
            & set(e["id"] for e in second["entries"])
        )
        self.assertNotIn("PRIVATE", str(first) + str(second))

    def test_journal_memory_bound_and_legacy_honesty(self):
        self.assertTrue(journals.profile(self.beast)["origin"]["legacy"])
        for i in range(103):
            journals.remember(self.beast, "battle", str(i), win=i % 2 == 0)
        data = journals.profile(self.beast)
        self.assertEqual(len(data["events"]), 100)
        self.assertEqual(data["battles"], 103)
        self.assertEqual(data["wins"], 52)

    @patch("play.views.random.random", return_value=0)
    def test_catch_receipt_and_memory(self, mock):
        self.beast.status = "wild"
        self.beast.expires_at = timezone.now() + timedelta(minutes=5)
        self.beast.save()
        InventoryItem.objects.create(user=self.user, item_id="spark_drive", qty=1)
        r = self.post("/api/catch", {"beast_id": self.beast.pk, "drive": "spark_drive"})
        self.assertEqual(r.status_code, 200)
        entry = self.user.activity_entries.get()
        self.assertEqual(entry.changes["item:spark_drive"], -1)
        self.assertEqual(entry.changes["beasts"], 1)
        self.beast.refresh_from_db()
        self.assertEqual(journals.profile(self.beast)["events"][0]["kind"], "catch")
        self.post("/api/catch", {"beast_id": self.beast.pk, "drive": "spark_drive"})
        self.assertEqual(self.user.activity_entries.count(), 1)

    def test_journal_page_notes_escaped_and_favorites_filter(self):
        self.beast.field_notes = "<script>bad()</script>"
        self.beast.favorite = True
        self.beast.save()
        self.client.force_login(self.user)
        r = self.client.get("/me/" + str(self.beast.pk) + "/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "<script>bad()</script>")
        self.assertContains(self.client.get("/me/"), "Field journal")

    def test_trade_preserves_memories_but_clears_private_annotations(self):
        from .models import TradeListing, TradeOffer

        self.wallet.subscribed = True
        self.wallet.save()
        Wallet.objects.create(user=self.other, subscribed=True)
        theirs = _beast(self.other)
        for beast in (self.beast, theirs):
            beast.favorite = True
            beast.field_notes = "Owner-only note"
            beast.save()
            journals.remember(beast, "discovery", "A shared origin")
        listing = TradeListing.objects.create(user=self.user, beast=self.beast)
        offer = TradeOffer.objects.create(
            listing=listing, from_user=self.other, offered_beast=theirs
        )
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.post(f"/trade/offer/{offer.pk}/accept").status_code, 302
        )
        self.beast.refresh_from_db()
        theirs.refresh_from_db()
        self.assertEqual(self.beast.user_id, self.other.pk)
        self.assertEqual(theirs.user_id, self.user.pk)
        for beast in (self.beast, theirs):
            self.assertFalse(beast.favorite)
            self.assertEqual(beast.field_notes, "")
            self.assertIn("A shared origin", str(journals.profile(beast)["events"]))
        self.assertEqual(self.user.activity_entries.count(), 1)
        self.assertEqual(self.other.activity_entries.count(), 1)


class ListenerHeartbeatTests(TestCase):
    def test_waiting_sends_heartbeats_without_collecting_or_scanning(self):
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "listener_test", Path(__file__).parent / "files/wavebeast-node.py"
        )
        listener = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(listener)
        now = [1000.0]
        health = {"mode": "auto"}
        with patch.object(
            listener.time, "time", side_effect=lambda: now[0]
        ), patch.object(
            listener.time,
            "sleep",
            side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds),
        ) as sleep, patch.object(
            listener, "heartbeat"
        ) as heartbeat, patch.object(
            listener, "build_bundle"
        ) as collect:
            listener.wait_with_heartbeats(1300, health)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [120, 120, 60])
        self.assertEqual(heartbeat.call_count, 3)
        collect.assert_not_called()
        self.assertGreaterEqual(listener.INTERVAL, 1800)
