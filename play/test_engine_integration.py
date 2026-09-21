"""Opt-in end-to-end gameplay with a real local Go resolver and Django's isolated test DB.
WB_INTEGRATION_RESOLVER=http://127.0.0.1:18779 python manage.py test play.test_engine_integration
"""
import copy
import json
import os
from unittest import skipUnless
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from . import resolver, ladder
from .models import Wallet, Node, OwnedBeast, BattleRecord, AsyncBattle, TradeListing, TradeOffer

@skipUnless(os.environ.get('WB_INTEGRATION_RESOLVER'), 'Set WB_INTEGRATION_RESOLVER for real-engine integration')
@override_settings(ALLOWED_HOSTS=['testserver'],CLERK_SECRET_KEY='')
class EngineIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config=patch('play.resolver.RESOLVER',os.environ['WB_INTEGRATION_RESOLVER']);cls.config.start()
        cls.addClassCleanup(cls.config.stop)

    def setUp(self):
        self.a=User.objects.create_user('integration-a');self.b=User.objects.create_user('integration-b')
        for user in [self.a,self.b]:
            Wallet.objects.create(user=user,subscribed=True,shards=300,cores=5)
            Node.objects.create(user=user,name='Test device')
            for n in range(3):
                bundle={'schema':'wavebeast.scanbundle','v':1,'signals':[{'kind':'code','strength':1,'value':{'data':f'{user.username}-{n}'}}]}
                for _ in range(100):
                    result=resolver.generate(bundle,roll_nonce='integration-fixture')
                    if result.get('outcome')=='beast':break
                else:self.fail('Engine did not produce a beast')
                sp,ind=result['species'],result['individual']
                OwnedBeast.objects.create(user=user,species_id=sp['species_id'],id_version=sp['id_version'],name=sp['name'],rarity=ind['rarity'],level=ind['level'],species_json=sp,individual_json=ind,status='owned',verified=True)
        self.client.force_login(self.a)

    def test_real_battles_ladder_and_sprite(self):
        for user in [self.a,self.b]:
            self.client.force_login(user)
            self.client.post('/battle/team',{'beast_ids':list(user.beasts.values_list('id',flat=True))})
            self.client.post('/ladder/enter')
        self.client.force_login(self.a)
        self.client.post('/battle/fight')
        self.assertEqual(BattleRecord.objects.count(),1)
        self.assertGreater(BattleRecord.objects.get().turns,0)
        self.client.post('/ladder/run')
        self.assertEqual(AsyncBattle.objects.count(),2)
        self.assertEqual(ladder.run_round(),1)
        sprite=self.client.get(f'/sprite/{self.a.beasts.first().id}.png')
        self.assertEqual(sprite.status_code,200);self.assertTrue(sprite.content.startswith(b'\x89PNG'))

    def test_real_catalog_purchase_and_import(self):
        node=self.a.nodes.first();hdr={'HTTP_X_WB_NODE_TOKEN':node.token}
        r=self.client.post('/api/buy',json.dumps({'item_id':'pulse_drive','qty':2}),content_type='application/json',**hdr)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['spent'],60)
        b=self.a.beasts.first();data={'beasts':[{'species':b.species_json,'individual':b.individual_json}]}
        r=self.client.post('/api/import',json.dumps(data),content_type='application/json',**hdr)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['imported'],1)
        self.assertEqual(self.a.beasts.filter(verified=False).count(),1)
        sync=self.client.post('/api/sync','{}',content_type='application/json',**hdr)
        self.assertEqual(sync.status_code,200)

    def test_real_beast_trade_round_trip_and_relisting(self):
        prize=self.a.beasts.first();offered=self.b.beasts.first()
        self.client.post('/trade/list',{'beast_id':prize.id})
        listing=TradeListing.objects.get(beast=prize)
        self.client.force_login(self.b)
        self.client.post(f'/trade/{listing.id}/offer',{'beast_id':offered.id,'shards':20})
        offer=TradeOffer.objects.get(listing=listing)
        self.client.force_login(self.a);self.client.post(f'/trade/offer/{offer.id}/accept')
        prize.refresh_from_db();offered.refresh_from_db()
        self.assertEqual(prize.user_id,self.b.id);self.assertEqual(offered.user_id,self.a.id)
        self.client.force_login(self.b);self.client.post('/trade/list',{'beast_id':prize.id})
        listing.refresh_from_db();self.assertEqual(listing.user_id,self.b.id);self.assertTrue(listing.is_open)
