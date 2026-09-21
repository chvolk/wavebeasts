"""Paid-feature workflows and regressions. All accounts and balances are isolated test data."""
import hashlib
import hmac
import json
import time
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from . import billing, ladder
from .models import AsyncBattle, BattleRecord, Buddy, InventoryItem, LadderTeam, Node, TradeListing, TradeOffer, Wallet
from .tests import _beast


@override_settings(ALLOWED_HOSTS=['testserver'], CLERK_SECRET_KEY='')
class PremiumWorkflowTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user('alice', email='alice@example.test')
        self.b = User.objects.create_user('bob', email='bob@example.test')
        self.wa = Wallet.objects.create(user=self.a, subscribed=True, shards=100, cores=5)
        self.wb = Wallet.objects.create(user=self.b, subscribed=True, shards=100, cores=5)
        self.na = Node.objects.create(user=self.a, name='Alice phone')
        self.nb = Node.objects.create(user=self.b, name='Bob phone')
        self.ba, self.bb = _beast(self.a), _beast(self.b)
        self.client.force_login(self.a)

    def api(self, path, data=None, node=None):
        headers = {'HTTP_X_WB_NODE_TOKEN': (node or self.na).token}
        if data is None:
            return self.client.get(path, **headers)
        return self.client.post(path, json.dumps(data), content_type='application/json', **headers)

    def offer(self):
        listing = TradeListing.objects.create(user=self.a, beast=self.ba)
        self.client.force_login(self.b)
        self.client.post(f'/trade/{listing.id}/offer', {'beast_id': self.bb.id, 'shards': 20, 'cores': 1})
        self.client.force_login(self.a)
        return listing, TradeOffer.objects.get(listing=listing)

    def test_account_is_private_and_matches_token_owner(self):
        self.assertEqual(self.client.get('/api/account').status_code, 403)
        response = self.api('/api/account', node=self.nb)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['account']['email'], 'bob@example.test')
        self.assertEqual(response.json()['account']['plan'], 'Premium')
        self.assertEqual(response.json()['account']['node_limit'], 12)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertNotIn(self.nb.token, response.content.decode())
        self.assertNotIn('alice@example.test', response.content.decode())
        self.assertEqual(self.api('/api/account', {}).status_code, 405)

    def test_free_account_can_see_identity(self):
        self.wa.subscribed = False; self.wa.save()
        data = self.api('/api/account').json()['account']
        self.assertEqual((data['plan'], data['node_limit']), ('Free', 3))

    @patch('play.clerkauth.account_profile', return_value={'name': 'New name', 'email': 'primary@example.test'})
    def test_existing_clerk_account_email_backfilled(self, profile):
        self.a.username = 'user_existing'; self.a.email = ''; self.a.save(); cache.clear()
        data = self.api('/api/account').json()['account']
        self.assertEqual(data['email'], 'primary@example.test')
        self.assertEqual(data['name'], 'New name')
        self.api('/api/account'); profile.assert_called_once()

    def test_boost_cost_cadence_and_expiry(self):
        self.client.post(f'/nodes/{self.na.id}/boost')
        self.wa.refresh_from_db(); self.na.refresh_from_db()
        self.assertEqual(self.wa.cores, 4); self.assertEqual(self.na.min_interval(), 100)
        self.assertGreater(self.na.boosted_until, timezone.now())
        self.na.boosted_until = timezone.now() - timedelta(seconds=1)
        self.assertEqual(self.na.min_interval(), 300)
        self.assertEqual(self.client.post(f'/nodes/{self.nb.id}/boost').status_code, 404)

    def test_boost_without_funds_or_subscription_does_not_charge(self):
        self.wa.cores = 0; self.wa.save(); self.client.post(f'/nodes/{self.na.id}/boost')
        self.na.refresh_from_db(); self.assertIsNone(self.na.boosted_until)
        self.wa.cores = 5; self.wa.subscribed = False; self.wa.save()
        self.client.post(f'/nodes/{self.na.id}/boost'); self.wa.refresh_from_db()
        self.assertEqual(self.wa.cores, 5)

    def test_unlist_refunds_and_can_relist(self):
        listing, offer = self.offer()
        self.client.post(f'/trade/{listing.id}/unlist')
        self.wb.refresh_from_db(); offer.refresh_from_db()
        self.assertEqual((self.wb.shards, self.wb.cores), (100, 5))
        self.assertEqual(offer.status, 'declined')
        self.client.post('/trade/list', {'beast_id': self.ba.id})
        self.assertTrue(TradeListing.objects.get(beast=self.ba).is_open)

    def test_offered_beast_cannot_be_listed_or_released(self):
        listing, offer = self.offer()
        self.client.force_login(self.b)
        self.client.post('/trade/list', {'beast_id': self.bb.id})
        self.assertFalse(TradeListing.objects.filter(beast=self.bb, is_open=True).exists())
        self.assertEqual(self.api('/api/release', {'beast_id': self.bb.id}, self.nb).status_code, 409)
        self.assertEqual(self.api('/api/release', {'beast_id': self.ba.id}).status_code, 409)

    def test_accept_clears_old_companion_team_and_ladder(self):
        listing, offer = self.offer()
        Buddy.objects.create(user=self.a, beast=self.ba, carrier=self.na)
        self.wa.team_ids = [str(self.ba.id)]; self.wa.save()
        LadderTeam.objects.create(user=self.a, fighters=[{'species': {}, 'individual': {}}])
        self.client.post(f'/trade/offer/{offer.id}/accept')
        self.ba.refresh_from_db(); self.assertEqual(self.ba.user_id, self.b.id)
        self.assertIsNone(Buddy.objects.get(user=self.a).beast_id)
        self.wa.refresh_from_db(); self.assertEqual(self.wa.team_ids, [])
        self.assertEqual(LadderTeam.objects.get(user=self.a).fighters, [])

    def test_buddy_all_actions_cooldowns_transfer_and_unslot(self):
        self.assertEqual(self.api('/api/buddy/slot', {'beast_id': self.bb.id}).status_code, 404)
        self.assertEqual(self.api('/api/buddy/slot', {'beast_id': self.ba.id}).status_code, 200)
        for action in ['feed', 'play', 'rest', 'clean', 'train']:
            with self.subTest(action=action):
                self.assertEqual(self.api('/api/buddy/care', {'action': action}).status_code, 200)
                self.assertEqual(self.api('/api/buddy/care', {'action': action}).status_code, 429)
        self.ba.refresh_from_db(); self.assertGreater(self.ba.level, 1)
        carrier = Node.objects.create(user=self.a, name='Second phone')
        self.api('/api/buddy/slot', {'beast_id': self.ba.id}, carrier)
        self.assertEqual(Buddy.objects.get(user=self.a).carrier_id, carrier.id)
        self.assertEqual(self.api('/api/buddy/care', {'action':'feed'}, carrier).status_code, 429)
        self.assertEqual(self.api('/api/buddy/slot', {'beast_id': None}).status_code, 200)
        self.assertIsNone(Buddy.objects.get(user=self.a).beast_id)
        self.assertEqual(self.api('/api/buddy').json()['events'], [])

    @patch('play.buddy.random.random', return_value=0.1)
    def test_buddy_away_rewards_are_paid_once(self, roll):
        b = Buddy.objects.create(user=self.a, beast=self.ba, relationship=100,
                                 last_event_at=timezone.now()-timedelta(minutes=21))
        result = self.api('/api/buddy').json()
        self.assertEqual(len(result['events']), 2)
        self.wa.refresh_from_db(); self.assertGreater(self.wa.shards, 100)
        self.assertEqual(self.api('/api/buddy').json()['events'], [])

    def test_paid_import_dedupes_and_stays_unverified(self):
        data = {'beasts':[{'species': {'species_id': 'imported', 'name':'Imported'}, 'individual': {'id':'local-1','level':5,'ivs':{'hp':999}}}]}
        result = self.api('/api/import', data).json()
        self.assertEqual(result['imported'], 1)
        self.assertEqual(self.api('/api/import', data).json()['skipped'], 1)
        imported = self.a.beasts.get(source_id='local-1')
        self.assertFalse(imported.verified); self.assertEqual(imported.individual_json['ivs']['hp'],31)
        self.client.post('/battle/team', {'beast_ids':[imported.id]})
        self.wa.refresh_from_db(); self.assertEqual(self.wa.team_ids, [])
        self.client.post('/trade/list', {'beast_id':imported.id})
        self.assertFalse(TradeListing.objects.filter(beast=imported).exists())
        self.wa.subscribed=False;self.wa.save()
        self.assertEqual(self.api('/api/import', data).status_code,402)

    @patch('play.resolver.battle_auto', return_value={'winner':'a','turns':4,'log':[]})
    def test_paid_battle_ladder_rewards_and_passive_matches(self, resolve):
        for user, beast in [(self.a,self.ba),(self.b,self.bb)]:
            self.client.force_login(user)
            self.client.post('/battle/team',{'beast_ids':[beast.id]})
            self.client.post('/ladder/enter')
        self.client.force_login(self.a)
        self.client.post('/battle/fight');self.assertEqual(BattleRecord.objects.count(),1)
        self.client.post('/ladder/run');self.assertEqual(AsyncBattle.objects.count(),2)
        self.assertEqual(LadderTeam.objects.get(user=self.a).mmr,1012)
        self.assertEqual(ladder.run_round(),1)
        self.assertEqual(AsyncBattle.objects.count(),4)
        self.wa.refresh_from_db(); self.assertGreaterEqual(self.wa.shards,135)

    @patch('play.resolver.battle_auto')
    def test_expired_subscription_removed_from_matchmaking(self, resolve):
        for user in [self.a,self.b]:LadderTeam.objects.create(user=user,fighters=[{'species':{},'individual':{}}])
        self.wb.subscribed=False;self.wb.save()
        self.assertEqual(ladder.run_round(),0)
        resolve.assert_not_called()

    def test_paid_mutations_reject_get(self):
        listing,offer=self.offer()
        for path in [f'/nodes/{self.na.id}/boost',f'/trade/{listing.id}/unlist',f'/trade/offer/{offer.id}/accept','/ladder/enter','/ladder/run','/battle/fight','/billing/checkout']:
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,405)


@override_settings(ALLOWED_HOSTS=['testserver'], STRIPE_WEBHOOK_SECRET='whsec_unit_only')
class SubscriptionWebhookTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('payer')
        self.wallet=Wallet.objects.create(user=self.user,stripe_customer_id='cus_test',subscribed=False)

    def send(self,etype,status,**extra):
        payload=json.dumps({'type':etype,'data':{'object':{'customer':'cus_test','status':status,**extra}}}).encode()
        now=str(int(time.time()))
        sig=hmac.new(b'whsec_unit_only',now.encode()+b'.'+payload,hashlib.sha256).hexdigest()
        return self.client.post('/webhooks/stripe',payload,content_type='application/json',HTTP_STRIPE_SIGNATURE=f't={now},v1={sig}')

    def test_signed_lifecycle_and_cancel_at_period_end(self):
        for status,enabled in [('trialing',True),('active',True),('past_due',False),('unpaid',False),('canceled',False)]:
            with self.subTest(status=status):
                self.assertEqual(self.send('customer.subscription.updated',status).status_code,200)
                self.wallet.refresh_from_db();self.assertEqual(self.wallet.subscribed,enabled)
        self.send('customer.subscription.updated','active',cancel_at_period_end=True)
        self.wallet.refresh_from_db();self.assertTrue(self.wallet.subscribed)
        self.send('customer.subscription.deleted','canceled')
        self.wallet.refresh_from_db();self.assertFalse(self.wallet.subscribed)

    def test_invalid_signature_rejected(self):
        self.assertEqual(self.client.post('/webhooks/stripe','{}',content_type='application/json').status_code,400)
        self.wallet.refresh_from_db();self.assertFalse(self.wallet.subscribed)

    @override_settings(DEBUG=False,STRIPE_WEBHOOK_SECRET='')
    def test_missing_signing_secret_fails_closed_in_production(self):
        result=self.send('customer.subscription.updated','active')
        self.assertEqual(result.status_code,503)
        self.wallet.refresh_from_db();self.assertFalse(self.wallet.subscribed)

@override_settings(CLERK_SECRET_KEY='fixture-secret')
class ClerkProfileTests(TestCase):
    @patch('play.clerkauth.requests.get')
    def test_profile_selects_primary_email(self, get):
        from . import clerkauth
        get.return_value.json.return_value = {
            'first_name':'Signal', 'last_name':'Hunter',
            'primary_email_address_id':'primary',
            'email_addresses':[{'id':'secondary','email_address':'old@example.test'},
                               {'id':'primary','email_address':'current@example.test'}]}
        profile=clerkauth.account_profile('user_fixture')
        self.assertEqual(profile,{'name':'Signal Hunter','email':'current@example.test'})

    @patch('play.clerkauth.account_profile', return_value=None)
    def test_failed_lookup_preserves_cached_identity(self, profile):
        from . import clerkauth
        user=User.objects.create_user('user_cached',email='cached@example.test',first_name='Cached')
        clerkauth.sync_profile(user)
        user.refresh_from_db()
        self.assertEqual(user.email,'cached@example.test')
        self.assertEqual(user.first_name,'Cached')
