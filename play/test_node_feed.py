from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Node, Snapshot, Wallet

class NodeFeedTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('feed')
        self.wallet=Wallet.objects.create(user=self.user,subscribed=True)
        self.nodes=[Node.objects.create(user=self.user,name=f'Node {i}') for i in range(2)]
        self.rows=[Snapshot.objects.create(node=self.nodes[i%2],outcome='beast',detail=f'Beast {i}') for i in range(25)]
        other=get_user_model().objects.create_user('other-feed')
        node=Node.objects.create(user=other,name='Private node')
        Snapshot.objects.create(node=node,outcome='resource',detail='Private reward')

    def fetch(self):
        return self.client.get('/api/account',HTTP_X_WB_NODE_TOKEN=self.nodes[0].token)

    def test_recent_twenty_across_owned_nodes_only(self):
        response=self.fetch()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Cache-Control'],'private, no-store')
        rows=response.json()['recent_snapshots']
        self.assertEqual([r['id'] for r in rows],[r.id for r in reversed(self.rows[-20:])])
        self.assertEqual({r['node_name'] for r in rows},{'Node 0','Node 1'})
        self.assertNotIn('Private reward',response.content.decode())
        self.assertTrue(all(r['at'] for r in rows))

    def test_free_account_has_no_feed(self):
        self.wallet.subscribed=False;self.wallet.save()
        self.assertEqual(self.fetch().json()['recent_snapshots'],[])

    def test_requires_node_auth(self):
        self.assertEqual(self.client.get('/api/account').status_code,403)
