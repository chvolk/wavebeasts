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

    def test_scanner_lists_all_device_kinds_privately_and_caps_feed(self):
        self.client.force_login(self.user)
        self.nodes[0].kind='phone';self.nodes[0].save()
        response=self.client.get('/scan/')
        self.assertEqual(response['Cache-Control'],'private, no-store')
        self.assertEqual(len(response.context['snapshots']),25)
        self.assertContains(response,'Beast 24')
        self.assertNotContains(response,'Private reward')
        self.wallet.subscribed=False;self.wallet.save()
        response=self.client.get('/scan/')
        self.assertEqual(response.context['snapshots'],[])
        self.assertNotContains(response,'Beast 24')

    def test_scanner_discoveries_include_rarity_type_and_source(self):
        from .models import OwnedBeast
        beast=OwnedBeast.objects.create(user=self.user,node=self.nodes[0],name='Radio Drake',species_id='scan-find',
            rarity='epic',status='owned',species_json={'types':['spark','gale']},individual_json={})
        self.client.force_login(self.user)
        response=self.client.get('/scan/')
        self.assertEqual([b.id for b in response.context['finds']],[beast.id])
        self.assertContains(response,'Radio Drake')
        self.assertContains(response,'rt-epic')
        self.assertContains(response,'spark / gale')
        self.assertContains(response,'data-beast=')
        self.assertContains(self.client.get('/me/'),'data-beast=')
