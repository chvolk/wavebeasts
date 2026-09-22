"""Account state consumed by the engine and independent API clients."""
import json
from django.contrib.auth.models import User
from django.test import TestCase
from .models import InventoryItem, Node, Wallet
from .tests import _beast

class HostStateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('host-account')
        Wallet.objects.create(user=self.user, shards=100, cores=4)
        self.a = Node.objects.create(user=self.user, name='phone')
        self.b = Node.objects.create(user=self.user, name='desktop')
        self.beast = _beast(self.user)
        InventoryItem.objects.create(user=self.user, item_id='kibble', qty=1)

    def api(self, node, path, data=None):
        args = {'HTTP_X_WB_NODE_TOKEN': node.token}
        return self.client.get(path, **args) if data is None else self.client.post(path, json.dumps(data), content_type='application/json', **args)

    def test_nodes_share_food_beasts_and_wallet(self):
        r = self.api(self.a, '/api/train', {'beast_id': self.beast.id, 'item_id': 'kibble'})
        self.assertEqual(r.status_code, 200)
        a = self.api(self.a, '/api/beasts')
        b = self.api(self.b, '/api/beasts')
        self.assertEqual(a['Cache-Control'], 'private, no-store')
        for key in ('shards', 'cores', 'inventory', 'beasts'):
            self.assertEqual(a.json()[key], b.json()[key])
        self.assertNotIn('kibble', b.json()['inventory'])
        self.assertGreater(b.json()['beasts'][0]['level'], 1)
        self.assertEqual(self.api(self.b, '/api/train', {'beast_id': self.beast.id, 'item_id': 'kibble'}).status_code, 409)

    def test_details_and_training_are_owner_scoped(self):
        other = User.objects.create_user('other')
        Wallet.objects.create(user=other)
        node = Node.objects.create(user=other, name='other phone')
        detail = f'/api/beast/{self.beast.id}'
        self.assertEqual(self.api(node, detail).status_code, 404)
        self.assertEqual(self.api(node, '/api/train', {'beast_id': self.beast.id, 'item_id': 'kibble'}).status_code, 404)
        r = self.api(self.a, detail)
        self.assertEqual(r.json()['individual']['id'], str(self.beast.id))
        self.assertEqual(r['Cache-Control'], 'private, no-store')
        self.assertEqual(self.api(self.a, '/api/train', {'beast_id': self.beast.id, 'item_id': 'spark_drive'}).status_code, 400)
        self.assertEqual(self.api(self.a, '/api/train').status_code, 405)
        self.assertEqual(InventoryItem.objects.get(user=self.user, item_id='kibble').qty, 1)
