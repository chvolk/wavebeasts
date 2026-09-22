from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth.models import User
from .models import InventoryItem, Node
from .tests import _beast

@override_settings(ALLOWED_HOSTS=['testserver'], CLERK_SECRET_KEY='')
class SightingTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('sightings')
        self.node=Node.objects.create(user=self.user)
        self.beast=_beast(self.user)
        self.beast.status='wild';self.beast.expires_at=timezone.now()+timedelta(hours=12);self.beast.save()
        self.client.force_login(self.user)

    def test_page_and_api_expose_same_expiry(self):
        page=self.client.get('/scan/')
        self.assertContains(page,'data-expires-in=')
        self.assertContains(page,'data-expiry-duration=')
        self.assertContains(page,'brand/sightings.js')
        r=self.client.get('/api/beasts',HTTP_X_WB_NODE_TOKEN=self.node.token).json()['wild'][0]
        self.assertEqual(r['expires_at'],self.beast.expires_at.isoformat())
        self.assertAlmostEqual(r['expires_in'],43200,delta=3)
        self.assertEqual(r['expiry_duration'],self.beast.expiry_duration)

    def test_expired_web_catch_does_not_consume_drive(self):
        self.beast.expires_at=timezone.now()-timedelta(seconds=1);self.beast.save()
        item=InventoryItem.objects.create(user=self.user,item_id='spark_drive',qty=3)
        self.client.post(f'/beast/{self.beast.id}/catch',{'drive':'spark_drive'})
        item.refresh_from_db();self.assertEqual(item.qty,3)
        self.assertFalse(self.user.beasts.filter(pk=self.beast.pk).exists())

    def test_legacy_sighting_receives_original_day_deadline(self):
        self.beast.expires_at=None;self.beast.save()
        self.client.get('/scan/')
        self.beast.refresh_from_db()
        self.assertEqual(self.beast.expires_at,self.beast.caught_at+timedelta(days=1))

    def test_only_owned_capture_drives_are_offered(self):
        InventoryItem.objects.create(user=self.user,item_id='pulse_drive',qty=2)
        InventoryItem.objects.create(user=self.user,item_id='nova_drive',qty=0)
        InventoryItem.objects.create(user=self.user,item_id='potion',qty=4)
        page=self.client.get('/scan/')
        self.assertContains(page,'<option value="pulse_drive">Pulse Drive ×2</option>',html=True)
        self.assertNotContains(page,'<option value="spark_drive">')
        self.assertNotContains(page,'<option value="nova_drive">')
        self.assertNotContains(page,'<option value="potion">')
        row=self.client.get('/api/beasts',HTTP_X_WB_NODE_TOKEN=self.node.token).json()
        self.assertEqual(row['catch_drives'],[{'item_id':'pulse_drive','name':'Pulse Drive','qty':2}])

    def test_no_drives_keeps_dismiss_available(self):
        page=self.client.get('/scan/')
        self.assertContains(page,'No capture drives in your inventory.')
        self.assertContains(page,f'/beast/{self.beast.id}/dismiss')
        self.assertNotContains(page,'data-catch-form')

    def test_dismiss_only_own_wild_sightings(self):
        import json
        other=User.objects.create_user('other-hunter')
        foreign=_beast(other);foreign.status='wild';foreign.save()
        owned=_beast(self.user)
        for target in [foreign,owned]:
            response=self.client.post('/api/sightings/dismiss',json.dumps({'beast_id':target.id}),content_type='application/json',HTTP_X_WB_NODE_TOKEN=self.node.token)
            self.assertEqual(response.status_code,404)
            self.assertTrue(type(target).objects.filter(pk=target.pk).exists())
        response=self.client.post('/api/sightings/dismiss',json.dumps({'beast_id':self.beast.id}),content_type='application/json',HTTP_X_WB_NODE_TOKEN=self.node.token)
        self.assertEqual(response.status_code,200)
        self.assertFalse(self.user.beasts.filter(pk=self.beast.pk).exists())
        self.assertEqual(self.client.get('/api/sightings/dismiss').status_code,405)
        self.assertEqual(self.client.get(f'/beast/{owned.id}/dismiss').status_code,405)

    def test_web_dismiss_preserves_inventory(self):
        item=InventoryItem.objects.create(user=self.user,item_id='pulse_drive',qty=2)
        self.client.post(f'/beast/{self.beast.id}/dismiss')
        self.assertFalse(self.user.beasts.filter(pk=self.beast.pk).exists())
        item.refresh_from_db();self.assertEqual(item.qty,2)

    def test_non_drive_items_cannot_be_spent_on_catches(self):
        import json
        item=InventoryItem.objects.create(user=self.user,item_id='potion',qty=2)
        response=self.client.post('/api/catch',json.dumps({'beast_id':self.beast.id,'drive':'potion'}),content_type='application/json',HTTP_X_WB_NODE_TOKEN=self.node.token)
        self.assertEqual(response.status_code,400)
        self.client.post(f'/beast/{self.beast.id}/catch',{'drive':'potion'})
        item.refresh_from_db();self.assertEqual(item.qty,2)

    def test_spent_last_drive_disappears_and_caught_beast_cannot_be_dismissed(self):
        from unittest.mock import patch
        import json
        InventoryItem.objects.create(user=self.user,item_id='pulse_drive',qty=1)
        with patch('play.views.random.random',return_value=0):
            response=self.client.post('/api/catch',json.dumps({'beast_id':self.beast.id,'drive':'pulse_drive'}),content_type='application/json',HTTP_X_WB_NODE_TOKEN=self.node.token)
        self.assertTrue(response.json()['caught'])
        self.beast.refresh_from_db();self.assertIsNone(self.beast.expires_at)
        self.assertEqual(self.client.get('/api/beasts',HTTP_X_WB_NODE_TOKEN=self.node.token).json()['catch_drives'],[])
        response=self.client.post('/api/sightings/dismiss',json.dumps({'beast_id':self.beast.id}),content_type='application/json',HTTP_X_WB_NODE_TOKEN=self.node.token)
        self.assertEqual(response.status_code,404)
