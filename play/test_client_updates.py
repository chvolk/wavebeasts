import json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Node, Snapshot
from .client_updates import status

class ClientUpdateTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('versions')
        self.node=Node.objects.create(user=self.user,name='Bishop')
    def post(self,path,body):
        return self.client.post(path,json.dumps(body),content_type='application/json',HTTP_X_WB_NODE_TOKEN=self.node.token)
    def test_check_in_reports_versions_without_scan_or_reward(self):
        response=self.post('/api/node/check-in',{'client':{'id':'wavebeast-node','app_v':'1.0.0'}})
        self.assertTrue(response.json()['update_available'])
        self.node.refresh_from_db();self.assertIsNone(self.node.last_snapshot_at)
        self.assertEqual(Snapshot.objects.count(),0)
        self.assertFalse(self.post('/api/node/check-in',{'client':{'id':'wavebeast-node','app_v':'1.2.0'}}).json()['update_available'])
        self.assertEqual(self.client.post('/api/node/check-in',data='{}',content_type='application/json').status_code,403)
    def test_legacy_listener_cannot_use_manual_five_minute_cooldown(self):
        self.node.last_snapshot_at=timezone.now()-timedelta(minutes=6);self.node.save()
        response=self.post('/api/snapshot',{'client':{'id':'wavebeast-node','app_v':'1.1.0'},'signals':[]})
        self.assertEqual(response.status_code,429)
        self.assertGreater(response.json()['retry_after'],1400)
        self.node.refresh_from_db();self.assertTrue(status(self.node)['update_available']);self.assertFalse(status(self.node)['update_required'])
    @patch('play.views.resolver.generate',return_value={'outcome':'nothing'})
    def test_auto_thirty_minutes_and_manual_five_minutes(self,generate):
        self.node.last_snapshot_at=timezone.now()-timedelta(minutes=6);self.node.save()
        auto={'client':{'id':'wavebeast-engine','app_v':'0.12.15'},'scan_mode':'auto','signals':[]}
        self.assertEqual(self.post('/api/snapshot',auto).status_code,429)
        self.assertEqual(self.post('/api/snapshot',{'signals':[]}).status_code,200)
        self.node.last_snapshot_at=timezone.now()-timedelta(minutes=31);self.node.save()
        response=self.post('/api/snapshot',auto)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['next_snapshot_in'],1800)
    def test_unknown_custom_and_old_version_notices(self):
        self.assertTrue(status(self.node)['unknown'])
        self.node.client_app='custom-game';self.node.client_version='v42'
        self.assertTrue(status(self.node)['custom']);self.assertFalse(status(self.node)['update_available'])
        self.node.client_app='wavebeast-engine';self.node.client_version='0.1.0'
        self.node.save();self.client.force_login(self.user)
        self.assertContains(self.client.get('/nodes/'),'data-node-health')
        self.assertTrue(self.client.get('/api/nodes/status').json()['nodes'][0]['update']['update_required'])

    @patch('play.views.resolver.generate')
    def test_required_updates_block_scan_without_resolving_or_spending(self,generate):
        for client in [{'id':'wavebeast-engine','app_v':42}, {'id':'app','app':'wavebeast-app'}, {'id':'wavebeast-node'}, {'id':'wavebeast-node','app_v':'1.0.0'}, {'id':'wavebeast-engine','app_v':'0.12.14'}]:
            response=self.post('/api/snapshot',{'client':client,'signals':[]})
            self.assertEqual(response.status_code,426)
            self.assertTrue(response.json()['update_required'])
            self.assertEqual(response.json()['error'],'update_required')
        generate.assert_not_called()
        self.node.refresh_from_db();self.assertIsNone(self.node.last_snapshot_at)
        self.assertEqual(Snapshot.objects.count(),0)
        self.assertEqual(self.post('/api/snapshot',{'client':{},'signals':[]}).status_code,426)
        self.client.force_login(self.user)
        self.assertContains(self.client.get('/me/'),'Client update required')
        self.assertEqual(self.client.get('/api/beasts',HTTP_X_WB_NODE_TOKEN=self.node.token).status_code,200)

    @patch('play.views.resolver.generate',return_value={'outcome':'nothing'})
    def test_custom_integrations_keep_their_own_version_policy(self,generate):
        response=self.post('/api/snapshot',{'client':{'id':'my-custom-game','app_v':'0.0.1'},'signals':[]})
        self.assertEqual(response.status_code,200)

    def test_manifest_advertises_supported_minimums(self):
        from .client_updates import MIN_ENGINE_CODE, MIN_ENGINE_VERSION, MIN_LISTENER_VERSION, parts
        manifest=self.client.get('/api/app/version').json()
        self.assertEqual(manifest['minimum_engine_code'],MIN_ENGINE_CODE)
        self.assertLessEqual(parts(MIN_ENGINE_VERSION),parts(manifest['version_name']))
        self.assertLessEqual(parts(MIN_LISTENER_VERSION),parts(manifest['listener_version']))
