import json
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import Client, TestCase
from .models import Wallet, Node

CODE = {'kind':'code','strength':1,'value':{'symbology':'manual','data':'WB:TEST'}}
IMAGE = {'kind':'image_features','strength':.9,'value':{'phash':'0123456789abcdef','palette':[[12,34,56]],'dims':[640,480]}}

class BrowserScannerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('scanner')
        self.wallet = Wallet.objects.create(user=self.user, subscribed=True)
        self.client.force_login(self.user)
    def scan(self, signals):
        return self.client.post('/api/browser/scan',json.dumps({'signals':signals}),content_type='application/json')
    def test_premium_gate_and_csrf(self):
        self.wallet.subscribed=False;self.wallet.save()
        self.assertEqual(self.scan([CODE]).status_code,402)
        self.assertContains(self.client.get('/scan/'),'Get Premium')
        self.assertNotContains(self.client.get('/scan/'),'browser-scanner.js')
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.user)
        self.assertEqual(strict.post('/api/browser/scan',json.dumps({'signals':[CODE]}),content_type='application/json').status_code,403)
        self.assertEqual(Node.objects.count(),0)
    @patch('play.views.resolver.generate',return_value={'outcome':'resource','reward_kind':'currency','reward_id':'shards','reward_amount':7,'reward_label':'7 shards'})
    def test_hashes_only_and_shared_cooldown(self,generate):
        a=self.scan([CODE,IMAGE]);self.assertEqual(a.status_code,200)
        self.assertEqual(a.json()['wallet']['shards'],57)
        bundle=generate.call_args.args[0]
        self.assertEqual(bundle['signals'],[CODE,IMAGE])
        self.assertNotIn('image',bundle)
        another=Client();another.force_login(self.user)
        b=another.post('/api/browser/scan',json.dumps({'signals':[CODE]}),content_type='application/json')
        self.assertEqual(b.status_code,429)
        self.assertEqual(Node.objects.filter(user=self.user,kind='browser').count(),1)
        self.assertEqual(generate.call_count,1)
    @patch('play.views.resolver.generate')
    def test_images_unknown_fields_duplicate_camera_and_empty_scans_rejected(self,generate):
        for signals in [[],[CODE,CODE],[IMAGE,IMAGE],[{'kind':'image','strength':1,'value':{'data':'base64'}}],[{**IMAGE,'value':{**IMAGE['value'],'data':'raw pixels'}}],[{'kind':'scalar','strength':.5,'value':{'metric':'orientation_alpha','n':10}}]]:
            self.assertEqual(self.scan(signals).status_code,400)
        self.assertEqual(self.client.post('/api/browser/scan',b'raw image',content_type='image/jpeg').status_code,400)
        generate.assert_not_called()
        self.assertEqual(Node.objects.count(),0)
    @patch('play.views.resolver.generate',side_effect=RuntimeError('offline'))
    def test_resolver_failure_does_not_spend_or_start_cooldown(self,_):
        self.assertEqual(self.scan([CODE]).status_code,502)
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.shards,50)
        self.assertIsNone(Node.objects.get(user=self.user,kind='browser').last_snapshot_at)
