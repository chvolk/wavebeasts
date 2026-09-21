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
        page=self.client.get('/me/')
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
        self.client.get('/me/')
        self.beast.refresh_from_db()
        self.assertEqual(self.beast.expires_at,self.beast.caught_at+timedelta(days=1))
